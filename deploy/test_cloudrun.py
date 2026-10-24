"""Offline regression checks: no Google Cloud commands are executed."""

import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).with_name("cloudrun.sh").read_text()


class CloudRunDeploymentTests(unittest.TestCase):
    def test_script_never_handles_secret_values(self):
        for forbidden in (".env", "versions add", "versions access", "secrets create"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, SCRIPT)

    def test_secret_preflight_precedes_project_changes(self):
        preflight = SCRIPT.index('gcloud secrets describe "$NAME"')
        self.assertLess(preflight, SCRIPT.index("gcloud services enable"))
        self.assertIn("SECRETS=(GEMINI_API_KEY MONGODB_URI EPC_API_TOKEN ACCESS_CODE)", SCRIPT)
        self.assertIn('"${MISSING_SECRETS[*]}"', SCRIPT)
        self.assertIn("https://console.cloud.google.com/security/secret-manager?project=%s", SCRIPT)
        self.assertLess(SCRIPT.index("  exit 1"), SCRIPT.index("gcloud services enable"))
        self.assertIn("roles/secretmanager.secretAccessor", SCRIPT)
        self.assertIn("--set-secrets", SCRIPT)

    def test_request_exclusion_stays_enabled_on_create_and_update(self):
        block = next(
            block.split("\nPYCODE", 1)[0]
            for block in SCRIPT.split("python3 - <<'PYCODE'\n")[1:]
            if "log_filter =" in block
        )
        for exists in (False, True):
            with self.subTest(exists=exists):
                sink = {"exclusions": [{"name": "demo-requests"}]} if exists else {}
                with (
                    patch.dict(os.environ, PROJECT="test-project", SERVICE="demo"),
                    patch("subprocess.check_output", return_value=json.dumps(sink).encode()),
                    patch("subprocess.run") as run,
                ):
                    exec(compile(block, "cloudrun-exclusion", "exec"), {})
                args = run.call_args.args[0]
                flag = "--update-exclusion" if exists else "--add-exclusion"
                self.assertIn(flag, args)
                exclusion = args[args.index(flag) + 1]
                self.assertNotIn("disabled", exclusion)
                self.assertEqual(
                    exclusion,
                    'name=demo-requests,filter=resource.type="cloud_run_revision" '
                    'AND resource.labels.service_name="demo" '
                    'AND log_id("run.googleapis.com/requests")',
                )

    def test_deploy_limit_accepts_environment_overrides(self):
        # Evaluate only the shell argument, never the deployment command.
        import subprocess

        line = next(line for line in SCRIPT.splitlines() if "--set-env-vars " in line)
        argument = line.split("--set-env-vars ", 1)[1].rsplit(" --quiet", 1)[0]
        for allowance, window, expected in (
            ("", "", "GEMINI_REQUESTS_PER_IP=300,GEMINI_LIMIT_WINDOW_SECONDS=3600"),
            ("600", "1800", "GEMINI_REQUESTS_PER_IP=600,GEMINI_LIMIT_WINDOW_SECONDS=1800"),
            ("0", "60", "GEMINI_REQUESTS_PER_IP=0,GEMINI_LIMIT_WINDOW_SECONDS=60"),
        ):
            env = dict(os.environ, GEMINI_REQUESTS_PER_IP=allowance,
                       GEMINI_LIMIT_WINDOW_SECONDS=window)
            result = subprocess.check_output(
                ["bash", "-c", "printf '%s' " + argument], env=env, text=True
            )
            self.assertEqual(result, expected)


if __name__ == "__main__":
    unittest.main()
