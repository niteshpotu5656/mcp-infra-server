import json
import subprocess
from pathlib import Path
from mcp.server.fastmcp import FastMCP
from config import config


def register_checkov_tools(mcp: FastMCP):

    @mcp.tool()
    def checkov_check_account_file(account_id: str) -> dict:
        """Check whether a Checkov account config file already exists for this account."""
        account_file = Path(config.CHECKOV_REPO_PATH) / f"{account_id}.json"
        exists = account_file.exists()
        return {"account_id": account_id, "file_exists": exists, "path": str(account_file)}

    @mcp.tool()
    def checkov_create_account_file(
        account_id: str,
        account_name: str,
        environment: str,
        app_id: str,
        manager: str,
    ) -> dict:
        """
        Create a new Checkov account config file for the given account.
        This file is required before any pipeline runs — it registers the account
        for compliance scanning and tag validation.
        """
        account_file = Path(config.CHECKOV_REPO_PATH) / f"{account_id}.json"
        account_config = {
            "account_id": account_id,
            "account_name": account_name,
            "environment": environment,
            "app_id": app_id,
            "manager": manager,
            "enabled": True,
        }
        account_file.write_text(json.dumps(account_config, indent=2))
        return {
            "account_id": account_id,
            "file_path": str(account_file),
            "status": "created",
        }

    @mcp.tool()
    def checkov_run_scan(terraform_dir: str, account_id: str) -> dict:
        """
        Run a Checkov scan against a Terraform directory.
        Validates resource compliance and checks all 24 mandatory tags are present.
        Blocks pipeline if any check fails.
        """
        result = subprocess.run(
            [
                "checkov",
                "-d", terraform_dir,
                "--output", "json",
                "--compact",
                "--quiet",
            ],
            capture_output=True,
            text=True,
        )
        try:
            scan_output = json.loads(result.stdout)
        except json.JSONDecodeError:
            return {
                "account_id": account_id,
                "passed": False,
                "error": "Could not parse Checkov output",
                "raw": result.stdout[-2000:],
            }

        summary = scan_output.get("summary", {})
        passed_checks = summary.get("passed", 0)
        failed_checks = summary.get("failed", 0)
        passed = failed_checks == 0

        failed_details = []
        for check_type in scan_output.get("results", {}).get("failed_checks", []):
            failed_details.append({
                "check_id": check_type.get("check_id"),
                "check_name": check_type.get("check_id"),
                "resource": check_type.get("resource"),
                "file": check_type.get("file_path"),
            })

        return {
            "account_id": account_id,
            "passed": passed,
            "passed_checks": passed_checks,
            "failed_checks": failed_checks,
            "failures": failed_details,
        }

    @mcp.tool()
    def checkov_validate_tags(terraform_dir: str, required_tag_count: int = 24) -> dict:
        """
        Validate that all resources in a Terraform directory have the required number of tags.
        Every resource must have all 24 mandatory tags before a pipeline is allowed to run.
        """
        result = subprocess.run(
            [
                "checkov",
                "-d", terraform_dir,
                "--check", "CKV_AWS_RESOURCE_TAGS",
                "--output", "json",
                "--compact",
            ],
            capture_output=True,
            text=True,
        )
        try:
            scan_output = json.loads(result.stdout)
        except json.JSONDecodeError:
            return {"valid": False, "error": "Could not parse Checkov tag validation output"}

        summary = scan_output.get("summary", {})
        failed = summary.get("failed", 0)
        return {
            "valid": failed == 0,
            "required_tags": required_tag_count,
            "resources_missing_tags": failed,
            "passed": summary.get("passed", 0),
        }
