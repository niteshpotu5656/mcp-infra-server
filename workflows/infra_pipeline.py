from config import config


def run_infra_pipeline(
    issue_number: int,
    account_id: str,
    account_name: str,
    environment: str,
    vpc_cidr: str,
    github_tools: dict,
    jenkins_tools: dict,
    checkov_tools: dict,
) -> dict:
    """
    Phase 2 — Infra Creation: Orchestrates all pipelines in strict order.

    Order enforced:
    1. Log Account Pipeline
    2. Checkov account file
    3. TGW Pipeline
    4. Network Infra Pipeline
    5. Application Infra Pipeline

    Each step has a pre-check — if already done for this account it is skipped.
    Pipeline is blocked immediately on any failure; logs are posted to GitHub Issue.
    """

    def _post(comment: str):
        github_tools["github_update_issue"](issue_number=issue_number, comment=comment)

    def _trigger_and_wait(pipeline_name: str, parameters: dict, step_label: str) -> dict:
        """Trigger a pipeline, get its build number, wait for completion."""
        trigger = jenkins_tools["jenkins_trigger_pipeline"](
            pipeline_name=pipeline_name,
            parameters=parameters,
        )
        import time; time.sleep(5)  # brief pause for Jenkins to queue the build
        build_info = jenkins_tools["jenkins_get_last_build_number"](pipeline_name=pipeline_name)
        build_number = build_info["last_build_number"]
        _post(f"**[MCP]** {step_label} triggered — build `#{build_number}`. Waiting for completion...")
        result = jenkins_tools["jenkins_wait_for_pipeline"](
            pipeline_name=pipeline_name,
            build_number=build_number,
        )
        return result

    def _handle_failure(result: dict, step_label: str, build_number: int, pipeline_name: str) -> dict:
        """Fetch logs and post failure to GitHub Issue, then stop the workflow."""
        logs = jenkins_tools["jenkins_get_pipeline_logs"](
            pipeline_name=pipeline_name,
            build_number=build_number,
        )
        _post(
            f"**[MCP] FAILED — {step_label}**\n\n"
            f"Build `#{build_number}` result: `{result['result']}`\n\n"
            f"**Last logs:**\n```\n{logs['logs']}\n```\n\n"
            "Workflow stopped. Please fix the issue and re-trigger."
        )
        return {"phase": "infra-pipeline", "status": "failed", "step": step_label}

    # ── STEP 1: Log Account Pipeline ──────────────────────────────────────
    _post(f"**[MCP]** Starting infra pipeline for account `{account_id}` ({account_name}).")

    pre_check = jenkins_tools["jenkins_check_pipeline_ran"](
        pipeline_name=config.JENKINS_LOG_PIPELINE,
        account_id=account_id,
    )
    if pre_check["already_ran"]:
        _post("**[MCP]** Log account pipeline already ran for this account — skipping.")
    else:
        result = _trigger_and_wait(
            pipeline_name=config.JENKINS_LOG_PIPELINE,
            parameters={"ACCOUNT_ID": account_id},
            step_label="Log Account Pipeline",
        )
        if not result["success"]:
            return _handle_failure(result, "Log Account Pipeline", result["build_number"], config.JENKINS_LOG_PIPELINE)
        _post("**[MCP]** Log Account Pipeline completed. VPC flow logs will route to Log Account S3.")

    # ── STEP 2: Checkov Account File ──────────────────────────────────────
    file_check = checkov_tools["checkov_check_account_file"](account_id=account_id)
    if file_check["file_exists"]:
        _post("**[MCP]** Checkov account file already exists — skipping.")
    else:
        checkov_tools["checkov_create_account_file"](
            account_id=account_id,
            account_name=account_name,
            environment=environment,
            app_id="",  # populated by caller if available
            manager="",
        )
        _post(f"**[MCP]** Checkov account file created for `{account_id}`.")

    # ── STEP 3: TGW Pipeline ──────────────────────────────────────────────
    pre_check = jenkins_tools["jenkins_check_pipeline_ran"](
        pipeline_name=config.JENKINS_TGW_PIPELINE,
        account_id=account_id,
    )
    if pre_check["already_ran"]:
        _post("**[MCP]** TGW pipeline already ran for this account — skipping.")
    else:
        result = _trigger_and_wait(
            pipeline_name=config.JENKINS_TGW_PIPELINE,
            parameters={"ACCOUNT_ID": account_id},
            step_label="TGW Pipeline",
        )
        if not result["success"]:
            return _handle_failure(result, "TGW Pipeline", result["build_number"], config.JENKINS_TGW_PIPELINE)
        _post(
            "**[MCP]** TGW Pipeline completed.\n"
            "- TGW created in Shared Services account\n"
            "- Re-shared to new account\n"
            "- Static routes and propagation configured"
        )

    # ── STEP 4: Network Infra Pipeline ────────────────────────────────────
    pre_check = jenkins_tools["jenkins_check_pipeline_ran"](
        pipeline_name=config.JENKINS_NETWORK_PIPELINE,
        account_id=account_id,
    )
    if pre_check["already_ran"]:
        _post("**[MCP]** Network infra pipeline already ran for this account — skipping.")
    else:
        # Commit network Terraform config to GitHub and raise PR
        branch_name = f"network-infra/{account_id}"
        github_tools["github_create_branch"](
            repo_name=config.GITHUB_NETWORK_REPO,
            branch_name=branch_name,
        )
        network_tf_content = _generate_network_tf(account_id, account_name, environment, vpc_cidr)
        github_tools["github_create_file"](
            repo_name=config.GITHUB_NETWORK_REPO,
            file_path=f"accounts/{environment}/{account_id}/main.tf",
            content=network_tf_content,
            commit_message=f"feat: add network infra for account {account_id} ({account_name})",
            branch=branch_name,
        )
        pr = github_tools["github_create_pr"](
            repo_name=config.GITHUB_NETWORK_REPO,
            title=f"Network Infra: {account_name} ({account_id})",
            body=f"Automated network infra config for account `{account_id}` in `{environment}`.\n\nVPC CIDR: `{vpc_cidr}`",
            head_branch=branch_name,
        )
        _post(
            f"**[MCP]** Network Terraform config committed and PR raised.\n"
            f"- PR: {pr['pr_url']}\n"
            "Waiting for PR approval before merging and triggering pipeline..."
        )
        return {
            "phase": "infra-pipeline",
            "status": "awaiting_pr_approval",
            "step": "network-infra",
            "pr_number": pr["pr_number"],
            "pr_url": pr["pr_url"],
            "account_id": account_id,
            "message": "Approve and merge the PR, then re-trigger the workflow to continue.",
        }

    # ── STEP 5: Application Infra Pipeline ────────────────────────────────
    pre_check = jenkins_tools["jenkins_check_pipeline_ran"](
        pipeline_name=config.JENKINS_APP_PIPELINE,
        account_id=account_id,
    )
    if pre_check["already_ran"]:
        _post("**[MCP]** Application infra pipeline already ran for this account — skipping.")
    else:
        result = _trigger_and_wait(
            pipeline_name=config.JENKINS_APP_PIPELINE,
            parameters={"ACCOUNT_ID": account_id, "ENVIRONMENT": environment},
            step_label="Application Infra Pipeline",
        )
        if not result["success"]:
            return _handle_failure(result, "Application Infra Pipeline", result["build_number"], config.JENKINS_APP_PIPELINE)
        _post("**[MCP]** Application Infra Pipeline completed successfully.")

    _post("**[MCP] All infra pipelines complete.** Moving to post-infra steps.")
    return {"phase": "infra-pipeline", "status": "complete", "account_id": account_id}


def _generate_network_tf(account_id: str, account_name: str, environment: str, vpc_cidr: str) -> str:
    """Generate a Terraform wrapper config for network infra from the standard template."""
    return f'''# Auto-generated by MCP Infra Server
# Account: {account_name} ({account_id}) | Environment: {environment}

module "network" {{
  source = "git::https://github.com/{"{config.GITHUB_ORG}"}/{"{config.GITHUB_MODULES_REPO}"}//network?ref=latest"

  account_id   = "{account_id}"
  account_name = "{account_name}"
  environment  = "{environment}"
  vpc_cidr     = "{vpc_cidr}"

  # All 24 mandatory tags are injected from tags.tfvars
}}
'''
