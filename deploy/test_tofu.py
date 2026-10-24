"""Offline deployment checks; cloud and OpenTofu commands are always mocked."""

from pathlib import Path
import subprocess
import json
import os
import shutil
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent
TF = "\n".join(p.read_text() for p in sorted((ROOT / "tofu").glob("*.tf")))


class OpenTofuDeploymentTests(unittest.TestCase):
    def test_saved_plans_are_ignored(self):
        patterns = (ROOT.parent / ".gitignore").read_text().splitlines()
        for suffix in ("plan", "tfplan"):
            with self.subTest(suffix=suffix):
                self.assertIn(f"deploy/tofu/*.{suffix}", patterns)
                result = subprocess.run(
                    ["git", "check-ignore", "--", f"deploy/tofu/bootstrap.{suffix}"],
                    cwd=ROOT.parent,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_deployment_never_handles_secret_values(self):
        # Inspect source, excluding downloaded provider binaries and local state.
        for path in ROOT.rglob("*"):
            if not path.is_file() or any(
                part in {".terraform", "__pycache__"} for part in path.parts
            ):
                continue
            if "tfstate" in path.name:
                continue
            with self.subTest(path=path.relative_to(ROOT)):
                source = path.read_text()
                self.assertNotRegex(source, r"\." + r"env\b")
                self.assertNotRegex(
                    source,
                    r'resource\s+"google_secret_manager_secret(?:_version)?"',
                )
                self.assertNotRegex(
                    source, r'data\s+"google_secret_manager_secret_version"'
                )
                for forbidden in ("versions " + "access", "versions " + "add", "secrets " + "create"):
                    self.assertNotIn(forbidden, source)
        self.assertIn('data "google_secret_manager_secret" "existing"', TF)
        self.assertIn('role      = "roles/secretmanager.secretAccessor"', TF)
        for name in (
            "GEMINI_API_KEY", "MONGODB_URI", "EPC_API_TOKEN", "ACCESS_CODE_HASH", "SESSION_SECRET"
        ):
            self.assertIn('"' + name + '"', TF)
        # The retired plaintext code must not be mapped or granted.
        self.assertNotIn('"ACCESS_CODE"', TF)
        self.assertIn('version = "latest"', TF)

    def test_static_direct_egress(self):
        for setting in (
            'auto_create_subnetworks = false',
            'ip_cidr_range = "10.42.0.0/24"',
            'nat_ip_allocate_option             = "MANUAL_ONLY"',
            'nat_ips                            = [google_compute_address.egress.self_link]',
            'source_subnetwork_ip_ranges_to_nat = "LIST_OF_SUBNETWORKS"',
            'egress = "ALL_TRAFFIC"',
            'network    = google_compute_network.egress.name',
            'subnetwork = google_compute_subnetwork.egress.name',
        ):
            # Ignore alignment whitespace changed by tofu fmt.
            self.assertIn(" ".join(setting.split()), " ".join(TF.split()))

    def test_service_limits_and_defaults(self):
        for setting in (
            'min_instance_count = 0', 'max_instance_count = 2',
            'timeout = "900s"', 'max_instance_request_concurrency = 8',
            'cpu = "1"', 'memory = "2Gi"',
            'value = tostring(var.gemini_requests_per_ip)',
            'value = tostring(var.gemini_limit_window_seconds)',
        ):
            self.assertIn(" ".join(setting.split()), " ".join(TF.split()))
        for name, default in (
            ("gemini_requests_per_ip", 300), ("gemini_limit_window_seconds", 3600)
        ):
            self.assertRegex(TF, rf'variable "{name}" \{{[^}}]*default\s*=\s*{default}\b')
        self.assertIn('count               = var.image == null ? 0 : 1', TF)

    def test_request_exclusion_precedes_service(self):
        self.assertIn('resource "google_logging_project_exclusion" "requests"', TF)
        self.assertIn('disabled    = false', TF)
        self.assertIn('resource.type=\\"cloud_run_revision\\"', TF)
        self.assertIn('resource.labels.service_name=\\"${var.service_name}\\"', TF)
        self.assertIn('log_id(\\"run.googleapis.com/requests\\")', TF)
        dependencies = TF.split("# Establish privacy", 1)[1]
        for resource in (
            "google_logging_project_exclusion.requests",
            "google_secret_manager_secret_iam_member.runtime",
            "google_compute_router_nat.egress",
        ):
            self.assertIn(resource, dependencies)

    def test_build_uses_dedicated_account_and_commit_tag(self):
        build = (ROOT / "build.sh").read_text()
        self.assertIn('rev-parse HEAD', build)
        self.assertIn('gae-build@$PROJECT.iam.gserviceaccount.com', build)
        self.assertIn('go-all-electric:$SHA', build)
        self.assertIn('gcloud builds submit', build)
        self.assertIn('logging: CLOUD_LOGGING_ONLY', (ROOT / "cloudbuild.yaml").read_text())
        for ignore in (".gcloudignore", ".dockerignore"):
            self.assertIn("deploy/tofu/", (ROOT.parent / ignore).read_text())


class RedeployTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "deploy/tofu").mkdir(parents=True)
        for name in ("deploy.sh", "build.sh"):
            shutil.copy2(ROOT / name, self.root / "deploy" / name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.log = self.root / "calls.jsonl"
        self.image = "europe-west2-docker.pkg.dev/go-all-electric-demo/go-all-electric/go-all-electric:" + "a" * 40
        self.saved = self.root / "deploy/tofu/image.auto.tfvars"
        self.private = self.root / "deploy/tofu/terraform.tfvars"
        self.private.write_text('image = "older-image"\n')
        stub = "#!" + sys.executable + "\n" + r'''import json, os, pathlib, sys
name = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
with open(os.environ["TEST_LOG"], "a") as log:
    log.write(json.dumps([name, *args]) + "\n")
if name == "git":
    if args[-1] == "--show-toplevel":
        print(os.environ["TEST_ROOT"])
    elif args[-1] == "--porcelain":
        print(os.environ.get("TEST_DIRTY", ""), end="")
    elif args[-1] == "HEAD":
        print("a" * 40)
    else:
        sys.exit(90)
elif name == "gcloud":
    if args[:4] == ["artifacts", "docker", "images", "describe"]:
        sys.exit(int(os.environ.get("TEST_LOOKUP", "1")))
    if args[:2] == ["builds", "submit"]:
        sys.exit(int(os.environ.get("TEST_BUILD", "0")))
    sys.exit(91)
elif name == "tofu":
    command = args[1]
    if command == "plan":
        saved = pathlib.Path(os.environ["TEST_ROOT"]) / "deploy/tofu/image.auto.tfvars"
        assert saved.read_text().startswith('image = "europe-west2-docker.pkg.dev/')
        assert "-detailed-exitcode" in args and "-out=deploy.plan" in args
        print("Plan for review")
        sys.exit(int(os.environ.get("TEST_PLAN", "2")))
    if command == "show":
        assert args[2:] == ["deploy.plan"]
        print("Saved plan for review")
    elif command == "apply":
        assert args[2:] == ["deploy.plan"]
        sys.exit(int(os.environ.get("TEST_APPLY", "0")))
    elif command == "output":
        assert args[2:] == ["-raw", "service_url"]
        print("https://example.run.app", end="")
    else:
        sys.exit(92)
'''
        for name in ("git", "gcloud", "tofu"):
            path = self.bin / name
            path.write_text(stub)
            path.chmod(0o755)

    def run_deploy(self, *args, answer="", **settings):
        env = {key: value for key, value in os.environ.items()
               if key not in {"GOOGLE_CLOUD_PROJECT", "GOOGLE_CLOUD_REGION"}}
        env.update(PATH=str(self.bin) + os.pathsep + env["PATH"],
                   TEST_ROOT=str(self.root), TEST_LOG=str(self.log), **settings)
        result = subprocess.run([str(self.root / "deploy/deploy.sh"), *args],
                                cwd=self.root, env=env, input=answer,
                                text=True, capture_output=True)
        self.calls = [json.loads(line) for line in self.log.read_text().splitlines()]
        self.assertEqual(self.private.read_text(), 'image = "older-image"\n')
        return result

    def commands(self, tool):
        return [call[1:] for call in self.calls if call[0] == tool]

    def assert_saved(self):
        self.assertEqual(self.saved.read_text(), f'image = "{self.image}"\n')
        self.assertEqual(list(self.saved.parent.glob("image.auto.tfvars.*")), [])

    def test_dirty_tree_refused_before_cloud_calls(self):
        result = self.run_deploy("--yes", TEST_DIRTY=" M README.md\n")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("clean tree", result.stderr)
        self.assertFalse(self.saved.exists())
        self.assertEqual(self.commands("gcloud"), [])
        self.assertEqual(self.commands("tofu"), [])

    def test_build_persist_and_unattended_apply(self):
        result = self.run_deploy("--yes")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_saved()
        self.assertEqual([c[:2] for c in self.commands("gcloud")],
                         [["artifacts", "docker"], ["builds", "submit"]])
        self.assertEqual([c[1] for c in self.commands("tofu")],
                         ["plan", "show", "apply", "output"])
        self.assertIn("https://example.run.app", result.stdout)
        self.assertNotIn("Type yes", result.stdout)

    def test_existing_image_skips_build(self):
        result = self.run_deploy("--yes", TEST_LOOKUP="0")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_saved()
        self.assertEqual(len(self.commands("gcloud")), 1)
        self.assertEqual(self.commands("gcloud")[0],
                         ["artifacts", "docker", "images", "describe", self.image, "--quiet"])

    def test_typed_yes_required(self):
        for answer, applied in (("yes\n", True), ("y\n", False), ("YES\n", False), ("", False)):
            with self.subTest(answer=answer):
                self.log.write_text("")
                result = self.run_deploy(answer=answer)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assert_saved()
                commands = [c[1] for c in self.commands("tofu")]
                self.assertEqual("apply" in commands, applied)
                self.assertIn("Saved plan for review", result.stdout)

    def test_no_changes_never_applies(self):
        result = self.run_deploy("--yes", TEST_PLAN="0")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_saved()
        self.assertIn("No infrastructure changes", result.stdout)
        self.assertEqual([c[1] for c in self.commands("tofu")], ["plan", "output"])

    def test_failures_preserve_image(self):
        for phase in ("BUILD", "PLAN", "APPLY"):
            with self.subTest(phase=phase):
                self.log.write_text("")
                self.saved.write_text('image = "previous"\n')
                result = self.run_deploy("--yes", **{f"TEST_{phase}": "1"})
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(phase.lower() + " failed", result.stderr)
                if phase == "BUILD":
                    self.assertEqual(self.saved.read_text(), 'image = "previous"\n')
                    self.assertEqual(self.commands("tofu"), [])
                else:
                    self.assert_saved()
                if phase == "PLAN":
                    self.assertEqual([c[1] for c in self.commands("tofu")], ["plan"])

    def test_script_does_not_read_or_print_secrets(self):
        for name in ("build.sh", "deploy.sh"):
            source = (ROOT / name).read_text()
            self.assertNotIn("gcloud " + "secrets", source)
            self.assertNotIn("." + "env", source)
            self.assertNotRegex(source, r"(?m)^\s*(?:env|printenv|set)\s*$")
            self.assertNotIn("set -" + "x", source)
        self.assertIn("deploy/tofu/image.auto.tfvars",
                      (ROOT.parent / ".gitignore").read_text().splitlines())


if __name__ == "__main__":
    unittest.main()
