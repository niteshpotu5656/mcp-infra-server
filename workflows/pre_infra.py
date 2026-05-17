from tools.github_tools import register_github_tools
from tools.aws_tools import register_aws_tools
from tools.netbox_tools import register_netbox_tools


def run_pre_infra(
    issue_number: int,
    account_name: str,
    app_id: str,
    manager: str,
    application_type: str,
    environment: str,
    email: str,
    organizational_unit: str,
    github_tools: dict,
    aws_tools: dict,
    netbox_tools: dict,
) -> dict:
    """
    Phase 1 — Pre-Infra: Full account creation workflow.

    Steps:
    1. Verify manager approval on GitHub Issue
    2. Create AWS account via AFT
    3. Wait for account to become active
    4. Register account in Netbox
    5. Update GitHub Issue with account details

    Claude calls this after confirming all required fields are present in the issue.
    """

    # Step 1: Check manager approval
    approval = github_tools["github_check_approval"](issue_number=issue_number)
    if not approval["approved"]:
        return {
            "phase": "pre-infra",
            "status": "blocked",
            "reason": "Manager has not yet added the 'approved' label to the GitHub Issue.",
            "issue_number": issue_number,
        }

    github_tools["github_update_issue"](
        issue_number=issue_number,
        comment="**[MCP]** Manager approval confirmed. Starting AWS account creation...",
    )

    # Step 2: Create AWS account
    account_result = aws_tools["aws_create_account"](
        account_name=account_name,
        email=email,
        organizational_unit=organizational_unit,
        environment=environment,
    )

    if account_result.get("status") != "created":
        github_tools["github_update_issue"](
            issue_number=issue_number,
            comment=f"**[MCP]** Account creation failed: {account_result.get('reason', 'Unknown error')}",
        )
        return {"phase": "pre-infra", "status": "failed", "step": "account_creation", "detail": account_result}

    account_id = account_result["account_id"]

    github_tools["github_update_issue"](
        issue_number=issue_number,
        comment=f"**[MCP]** AWS account created successfully.\n- **Account ID:** `{account_id}`\n- **Environment:** {environment}\n- **OU:** {organizational_unit}",
    )

    # Step 3: Verify account is active
    active_check = aws_tools["aws_check_account_active"](account_id=account_id)
    if not active_check["active"]:
        return {
            "phase": "pre-infra",
            "status": "failed",
            "step": "account_activation",
            "detail": active_check,
        }

    # Step 4: Register in Netbox
    netbox_result = netbox_tools["netbox_create_account"](
        account_id=account_id,
        account_name=account_name,
        app_id=app_id,
        manager=manager,
        application_type=application_type,
        environment=environment,
    )

    github_tools["github_update_issue"](
        issue_number=issue_number,
        comment=f"**[MCP]** Account registered in Netbox inventory.\n- **Netbox ID:** `{netbox_result['netbox_id']}`",
    )

    # Step 5: Final update
    github_tools["github_update_issue"](
        issue_number=issue_number,
        comment=(
            "**[MCP] Pre-Infra Complete**\n\n"
            f"| Field | Value |\n|---|---|\n"
            f"| Account ID | `{account_id}` |\n"
            f"| Account Name | {account_name} |\n"
            f"| Environment | {environment} |\n"
            f"| Netbox Record | ID `{netbox_result['netbox_id']}` |\n\n"
            "Next step: Infra pipeline will now be triggered automatically."
        ),
    )

    return {
        "phase": "pre-infra",
        "status": "complete",
        "account_id": account_id,
        "account_name": account_name,
        "environment": environment,
        "netbox_id": netbox_result["netbox_id"],
    }
