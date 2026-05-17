import base64
from github import Github, GithubException
from mcp.server.fastmcp import FastMCP
from config import config

_gh = Github(config.GITHUB_TOKEN)
# Use personal account (get_user()) — works for both personal accounts and orgs
_user = _gh.get_user(config.GITHUB_ORG)


def _get_repo(repo_name: str):
    return _user.get_repo(repo_name)


def register_github_tools(mcp: FastMCP):

    @mcp.tool()
    def github_create_issue(
        title: str,
        account_name: str,
        app_id: str,
        manager: str,
        application_type: str,
        environment: str,
        vpc_cidr: str,
        budget_approval_link: str,
        architecture_doc_link: str,
    ) -> dict:
        """Create a new infrastructure request issue in the infra-requests repo."""
        repo = _get_repo(config.GITHUB_INFRA_REPO)
        body = f"""## Infrastructure Request

| Field | Value |
|---|---|
| Account Name | {account_name} |
| App ID | {app_id} |
| Manager | {manager} |
| Application Type | {application_type} |
| Environment | {environment} |
| VPC CIDR Requirement | {vpc_cidr} |
| Budget Approval | {budget_approval_link} |
| Architecture Doc | {architecture_doc_link} |

---
**Status:** Pending manager approval

> Add label `approved` to this issue to trigger automated account creation.
"""
        issue = repo.create_issue(title=title, body=body, labels=["infra-request"])
        return {"issue_number": issue.number, "issue_url": issue.html_url, "status": "created"}

    @mcp.tool()
    def github_check_approval(issue_number: int) -> dict:
        """Check if the manager has added the 'approved' label to the issue."""
        repo = _get_repo(config.GITHUB_INFRA_REPO)
        issue = repo.get_issue(issue_number)
        labels = [label.name for label in issue.labels]
        approved = "approved" in labels
        return {"issue_number": issue_number, "approved": approved, "labels": labels}

    @mcp.tool()
    def github_update_issue(issue_number: int, comment: str) -> dict:
        """Post a status update comment on an existing issue."""
        repo = _get_repo(config.GITHUB_INFRA_REPO)
        issue = repo.get_issue(issue_number)
        issue_comment = issue.create_comment(comment)
        return {"issue_number": issue_number, "comment_id": issue_comment.id, "status": "updated"}

    @mcp.tool()
    def github_close_issue(issue_number: int, summary: str) -> dict:
        """Close a completed infra request issue with a final summary comment."""
        repo = _get_repo(config.GITHUB_INFRA_REPO)
        issue = repo.get_issue(issue_number)
        issue.create_comment(f"## Infra Request Complete\n\n{summary}")
        issue.edit(state="closed")
        return {"issue_number": issue_number, "status": "closed"}

    @mcp.tool()
    def github_create_file(
        repo_name: str,
        file_path: str,
        content: str,
        commit_message: str,
        branch: str = "main",
    ) -> dict:
        """Commit a new file (e.g. Terraform config) to a GitHub repo on a given branch."""
        repo = _get_repo(repo_name)
        try:
            existing = repo.get_contents(file_path, ref=branch)
            repo.update_file(
                path=file_path,
                message=commit_message,
                content=content,
                sha=existing.sha,
                branch=branch,
            )
            action = "updated"
        except GithubException:
            repo.create_file(
                path=file_path,
                message=commit_message,
                content=content,
                branch=branch,
            )
            action = "created"
        return {"repo": repo_name, "file_path": file_path, "branch": branch, "action": action}

    @mcp.tool()
    def github_create_branch(repo_name: str, branch_name: str, from_branch: str = "main") -> dict:
        """Create a new branch in a repo from an existing base branch."""
        repo = _get_repo(repo_name)
        source = repo.get_branch(from_branch)
        repo.create_git_ref(ref=f"refs/heads/{branch_name}", sha=source.commit.sha)
        return {"repo": repo_name, "branch": branch_name, "from": from_branch, "status": "created"}

    @mcp.tool()
    def github_create_pr(
        repo_name: str,
        title: str,
        body: str,
        head_branch: str,
        base_branch: str = "main",
    ) -> dict:
        """Raise a pull request in a GitHub repo for review."""
        repo = _get_repo(repo_name)
        pr = repo.create_pull(title=title, body=body, head=head_branch, base=base_branch)
        return {"repo": repo_name, "pr_number": pr.number, "pr_url": pr.html_url, "status": "open"}

    @mcp.tool()
    def github_merge_pr(repo_name: str, pr_number: int) -> dict:
        """Merge an approved pull request."""
        repo = _get_repo(repo_name)
        pr = repo.get_pull(pr_number)
        if pr.mergeable:
            result = pr.merge(merge_method="squash")
            return {"repo": repo_name, "pr_number": pr_number, "merged": result.merged, "sha": result.sha}
        return {"repo": repo_name, "pr_number": pr_number, "merged": False, "reason": "PR is not mergeable — pending reviews or conflicts"}

    @mcp.tool()
    def github_create_tag(repo_name: str, tag_name: str, message: str, ref: str = "main") -> dict:
        """Create a new Git tag on a repo — used for module versioning."""
        repo = _get_repo(repo_name)
        branch = repo.get_branch(ref)
        tag = repo.create_git_tag(
            tag=tag_name,
            message=message,
            object=branch.commit.sha,
            type="commit",
        )
        repo.create_git_ref(ref=f"refs/tags/{tag_name}", sha=tag.sha)
        return {"repo": repo_name, "tag": tag_name, "sha": branch.commit.sha, "status": "created"}

    @mcp.tool()
    def github_get_latest_tag(repo_name: str) -> dict:
        """Get the latest Git tag from a repo — used to detect current module version."""
        repo = _get_repo(repo_name)
        tags = sorted(repo.get_tags(), key=lambda t: t.name, reverse=True)
        if not tags:
            return {"repo": repo_name, "latest_tag": None}
        latest = tags[0]
        return {"repo": repo_name, "latest_tag": latest.name, "sha": latest.commit.sha}
