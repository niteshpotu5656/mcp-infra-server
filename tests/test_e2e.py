"""
End-to-end test suite — Chunk 13.
Tests each phase of the workflow with mocked external services so no real AWS/Jenkins
calls are made during CI. Set USE_REAL_SERVICES=true to run against live systems.
"""
import json
import os
import unittest
from unittest.mock import MagicMock, patch

USE_REAL = os.getenv("USE_REAL_SERVICES", "false").lower() == "true"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _mock_github_tools(approved=True, pr_mergeable=True):
    return {
        "github_create_issue":    MagicMock(return_value={"issue_number": 1, "issue_url": "https://github.com/org/repo/issues/1", "status": "created"}),
        "github_check_approval":  MagicMock(return_value={"approved": approved, "labels": ["approved"] if approved else []}),
        "github_update_issue":    MagicMock(return_value={"status": "updated"}),
        "github_close_issue":     MagicMock(return_value={"status": "closed"}),
        "github_create_branch":   MagicMock(return_value={"status": "created"}),
        "github_create_file":     MagicMock(return_value={"action": "created"}),
        "github_create_pr":       MagicMock(return_value={"pr_number": 42, "pr_url": "https://github.com/org/repo/pull/42", "status": "open"}),
        "github_merge_pr":        MagicMock(return_value={"merged": pr_mergeable}),
    }

def _mock_aws_tools(create_status="created"):
    return {
        "aws_create_account":      MagicMock(return_value={"account_id": "123456789099", "account_name": "test-account", "environment": "nonprod", "ou": "nonprod", "status": create_status}),
        "aws_check_account_active":MagicMock(return_value={"account_id": "123456789099", "active": True, "status": "ACTIVE"}),
        "aws_get_account_arn":     MagicMock(return_value={"account_id": "123456789099", "arn": "arn:aws:organizations::123456789099:account/o-xxx/123456789099"}),
    }

def _mock_netbox_tools(found=True):
    return {
        "netbox_create_account": MagicMock(return_value={"account_id": "123456789099", "netbox_id": 7, "status": "registered"}),
        "netbox_get_account":    MagicMock(return_value={"account_id": "123456789099", "found": found, "netbox_id": 7, "data": {"resources": [{"type": "VPC", "id": "vpc-abc123", "name": "main-vpc", "state": "ResourceDiscovered", "region": "us-east-1"}]}}),
        "netbox_update_resources": MagicMock(return_value={"updated": True, "resource_count": 1}),
    }

def _mock_jenkins_tools(pipeline_result="SUCCESS", already_ran=False):
    return {
        "jenkins_trigger_pipeline":    MagicMock(return_value={"queue_id": 1, "status": "triggered"}),
        "jenkins_get_last_build_number":MagicMock(return_value={"last_build_number": 5}),
        "jenkins_wait_for_pipeline":   MagicMock(return_value={"result": pipeline_result, "success": pipeline_result == "SUCCESS", "build_number": 5}),
        "jenkins_check_pipeline_ran":  MagicMock(return_value={"already_ran": already_ran}),
        "jenkins_get_pipeline_logs":   MagicMock(return_value={"logs": "BUILD FAILED: some error", "truncated": False}),
    }

def _mock_checkov_tools(file_exists=False, scan_passed=True):
    return {
        "checkov_check_account_file":  MagicMock(return_value={"file_exists": file_exists}),
        "checkov_create_account_file": MagicMock(return_value={"status": "created"}),
        "checkov_run_scan":            MagicMock(return_value={"passed": scan_passed, "failed_checks": 0 if scan_passed else 3}),
        "checkov_validate_tags":       MagicMock(return_value={"valid": scan_passed, "resources_missing_tags": 0 if scan_passed else 2}),
    }


# ── Phase 1: Pre-Infra Tests ──────────────────────────────────────────────────

class TestPreInfra(unittest.TestCase):

    def _run(self, github_tools, aws_tools, netbox_tools):
        from workflows.pre_infra import run_pre_infra
        return run_pre_infra(
            issue_number=1,
            account_name="test-account",
            app_id="APP001",
            manager="john.doe",
            application_type="microservice",
            environment="nonprod",
            email="test-account@company.com",
            organizational_unit="nonprod",
            github_tools=github_tools,
            aws_tools=aws_tools,
            netbox_tools=netbox_tools,
        )

    def test_blocked_when_not_approved(self):
        result = self._run(_mock_github_tools(approved=False), _mock_aws_tools(), _mock_netbox_tools())
        self.assertEqual(result["status"], "blocked")
        self.assertIn("Manager has not yet", result["reason"])

    def test_happy_path(self):
        result = self._run(_mock_github_tools(approved=True), _mock_aws_tools(), _mock_netbox_tools())
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["account_id"], "123456789099")
        self.assertEqual(result["netbox_id"], 7)

    def test_account_creation_failure(self):
        result = self._run(_mock_github_tools(), _mock_aws_tools(create_status="failed"), _mock_netbox_tools())
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["step"], "account_creation")


# ── Phase 2: Infra Pipeline Tests ─────────────────────────────────────────────

class TestInfraPipeline(unittest.TestCase):

    def _run(self, jenkins_tools, checkov_tools, already_ran=False):
        from workflows.infra_pipeline import run_infra_pipeline
        jt = jenkins_tools or _mock_jenkins_tools(already_ran=already_ran)
        return run_infra_pipeline(
            issue_number=1,
            account_id="123456789099",
            account_name="test-account",
            environment="nonprod",
            vpc_cidr="10.0.0.0/16",
            github_tools=_mock_github_tools(),
            jenkins_tools=jt,
            checkov_tools=checkov_tools or _mock_checkov_tools(),
        )

    def test_pipeline_order_enforced_skip_already_ran(self):
        # All pipelines already ran — should reach network-infra PR step
        result = self._run(
            jenkins_tools=_mock_jenkins_tools(already_ran=True),
            checkov_tools=_mock_checkov_tools(file_exists=True),
            already_ran=True,
        )
        # Network PR is raised (awaiting approval) since network pipeline not yet ran
        self.assertIn(result["status"], ["awaiting_pr_approval", "complete"])

    def test_pipeline_failure_stops_workflow(self):
        jt = _mock_jenkins_tools(pipeline_result="FAILURE")
        # Override pre-check to say pipeline hasn't run
        jt["jenkins_check_pipeline_ran"] = MagicMock(return_value={"already_ran": False})
        result = self._run(jenkins_tools=jt, checkov_tools=_mock_checkov_tools())
        self.assertEqual(result["status"], "failed")

    def test_network_pr_raised_when_pipeline_not_run(self):
        jt = _mock_jenkins_tools(pipeline_result="SUCCESS")
        jt["jenkins_check_pipeline_ran"] = MagicMock(return_value={"already_ran": True})
        result = self._run(jenkins_tools=jt, checkov_tools=_mock_checkov_tools(file_exists=True))
        # Should stop at network PR step waiting for approval
        self.assertEqual(result["status"], "awaiting_pr_approval")


# ── Phase 3: Post-Infra Tests ─────────────────────────────────────────────────

class TestPostInfra(unittest.TestCase):

    def _run(self, netbox_tools):
        from workflows.post_infra import run_post_infra
        return run_post_infra(
            issue_number=1,
            account_id="123456789099",
            account_name="test-account",
            environment="nonprod",
            github_tools=_mock_github_tools(),
            netbox_tools=netbox_tools,
        )

    def test_happy_path_closes_issue(self):
        result = self._run(_mock_netbox_tools(found=True))
        self.assertEqual(result["status"], "complete")
        self.assertTrue(result["issue_closed"])

    def test_warning_when_account_not_in_netbox(self):
        result = self._run(_mock_netbox_tools(found=False))
        self.assertEqual(result["status"], "warning")


# ── Terraform Provider Cache Test ─────────────────────────────────────────────

class TestProviderCache(unittest.TestCase):

    def test_tf_plugin_cache_dir_set_in_config(self):
        from config import config
        self.assertTrue(
            config.TF_PLUGIN_CACHE_DIR,
            "TF_PLUGIN_CACHE_DIR must be set to prevent provider re-download on every pipeline run",
        )

    def test_all_jenkinsfiles_reference_cache_dir(self):
        import pathlib
        jenkins_dir = pathlib.Path(__file__).parent.parent / "jenkins"
        for jf in jenkins_dir.glob("Jenkinsfile.*"):
            content = jf.read_text()
            self.assertIn(
                "TF_PLUGIN_CACHE_DIR",
                content,
                f"{jf.name} is missing TF_PLUGIN_CACHE_DIR — provider will re-download on every run",
            )


# ── Tag Validation Tests ───────────────────────────────────────────────────────

class TestTagValidation(unittest.TestCase):

    def test_24_tags_defined(self):
        import json, pathlib
        tags_file = pathlib.Path(__file__).parent.parent / "templates" / "tags.json"
        tags = json.loads(tags_file.read_text())
        self.assertEqual(tags["count"], 24)
        self.assertEqual(len(tags["required_tags"]), 24)


# ── Module Version Checker Tests ──────────────────────────────────────────────

class TestModuleVersionChecker(unittest.TestCase):

    @patch("scheduler.module_version_checker._org")
    def test_detects_new_version(self, mock_org):
        from scheduler.module_version_checker import register_scheduler_tools
        from mcp.server.fastmcp import FastMCP

        mock_repo  = MagicMock()
        mock_org.get_repo.return_value = mock_repo

        t1 = MagicMock(); t1.name = "v1.1.0"; t1.commit.sha = "abc"
        t2 = MagicMock(); t2.name = "v1.0.0"; t2.commit.sha = "def"
        mock_repo.get_tags.return_value = [t1, t2]

        comparison      = MagicMock()
        comparison.files   = [MagicMock(filename="modules/vpc/main.tf")]
        comparison.commits = [MagicMock(**{"commit.message": "feat: update VPC module"})]
        mock_repo.compare.return_value = comparison

        mcp = FastMCP("test")
        register_scheduler_tools(mcp)
        result = mcp._tool_map["module_check_versions"]()

        self.assertTrue(result["new_version_available"])
        self.assertEqual(result["latest_tag"], "v1.1.0")
        self.assertEqual(result["previous_tag"], "v1.0.0")

    def test_semver_bump_patch(self):
        # Verify semver bump logic independently
        import re
        tag = "v1.2.3"
        match = re.match(r"v?(\d+)\.(\d+)\.(\d+)", tag)
        major, minor, patch = int(match.group(1)), int(match.group(2)), int(match.group(3))
        patch += 1
        self.assertEqual(f"v{major}.{minor}.{patch}", "v1.2.4")


if __name__ == "__main__":
    unittest.main(verbosity=2)
