def run_post_infra(
    issue_number: int,
    account_id: str,
    account_name: str,
    environment: str,
    github_tools: dict,
    netbox_tools: dict,
) -> dict:
    """
    Phase 3 — Post-Infra: Inventory sync and issue closure.

    Steps:
    1. Confirm Netbox has the account registered
    2. Fetch current resources from Netbox (populated by AWS Config → Lambda sync)
    3. Post final resource summary to GitHub Issue
    4. Close the GitHub Issue

    Note: The live AWS Config → EventBridge → Lambda → Netbox sync runs continuously
    in the background and does not need to be triggered here. This workflow just
    reads the current Netbox state and closes the issue.
    """

    def _post(comment: str):
        github_tools["github_update_issue"](issue_number=issue_number, comment=comment)

    _post("**[MCP]** Starting post-infra steps...")

    # Step 1: Confirm Netbox record exists
    netbox_record = netbox_tools["netbox_get_account"](account_id=account_id)
    if not netbox_record["found"]:
        _post(
            f"**[MCP]** Warning: Account `{account_id}` not found in Netbox inventory. "
            "Please check the Netbox sync is running correctly."
        )
        return {
            "phase": "post-infra",
            "status": "warning",
            "reason": "Account not found in Netbox",
            "account_id": account_id,
        }

    # Step 2: Build resource summary from Netbox
    resources = netbox_record["data"].get("resources", [])
    resource_table = "\n".join(
        [f"| {r.get('type', '-')} | {r.get('name', '-')} | {r.get('id', '-')} | {r.get('state', '-')} |"
         for r in resources]
    ) if resources else "| — | No resources recorded yet | — | — |"

    summary = (
        f"## Infra Complete — {account_name} (`{account_id}`)\n\n"
        f"| Field | Value |\n|---|---|\n"
        f"| Account ID | `{account_id}` |\n"
        f"| Account Name | {account_name} |\n"
        f"| Environment | {environment} |\n"
        f"| Netbox Record ID | `{netbox_record['netbox_id']}` |\n\n"
        f"### Resources (live from Netbox)\n\n"
        f"| Type | Name | ID | State |\n|---|---|---|---|\n"
        f"{resource_table}\n\n"
        "_Resource list is kept live by AWS Config → EventBridge → Lambda → Netbox sync._"
    )

    # Step 3 & 4: Post summary and close issue
    github_tools["github_close_issue"](issue_number=issue_number, summary=summary)

    return {
        "phase": "post-infra",
        "status": "complete",
        "account_id": account_id,
        "resources_recorded": len(resources),
        "issue_closed": True,
    }
