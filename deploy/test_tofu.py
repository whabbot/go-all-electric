"""Offline deployment checks; never call a cloud API or execute the build helper."""

from pathlib import Path
import subprocess
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
                self.assertNotIn("." + "env", source)
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
        for name in ("GEMINI_API_KEY", "MONGODB_URI", "EPC_API_TOKEN", "ACCESS_CODE"):
            self.assertIn('"' + name + '"', TF)
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


if __name__ == "__main__":
    unittest.main()
