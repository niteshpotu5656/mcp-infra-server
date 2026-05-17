import re
from github import Github
from mcp.server.fastmcp import FastMCP
from config import config

_gh = Github(config.GITHUB_TOKEN)
_org = _gh.get_user(config.GITHUB_ORG)


def register_scheduler_tools(mcp: FastMCP):

    @mcp.tool()
    def module_check_versions() -> dict:
        """
        Scan the modules repo for the latest tag and compare against the previous tag.
        Returns whether a new version is available and what changed.
        Run weekly via Jenkins cron.
        """
        repo = _org.get_repo(config.GITHUB_MODULES_REPO)
        tags = sorted(repo.get_tags(), key=lambda t: t.name, reverse=True)

        if len(tags) < 2:
            return {
                "repo": config.GITHUB_MODULES_REPO,
                "new_version_available": False,
                "reason": "Not enough tags to compare",
            }

        latest = tags[0]
        previous = tags[1]

        # Get commit diff between the two tags
        comparison = repo.compare(previous.commit.sha, latest.commit.sha)
        changed_files = [f.filename for f in comparison.files]
        commit_messages = [c.commit.message.split("\n")[0] for c in comparison.commits]

        return {
            "repo": config.GITHUB_MODULES_REPO,
            "latest_tag": latest.name,
            "previous_tag": previous.name,
            "new_version_available": latest.name != previous.name,
            "changed_files": changed_files,
            "commits": commit_messages,
        }

    @mcp.tool()
    def module_create_next_tag(bump: str = "patch") -> dict:
        """
        Create the next semantic version tag on the modules repo.
        bump: 'major', 'minor', or 'patch' (default: patch).
        Example: v1.2.3 → patch → v1.2.4
        """
        repo = _org.get_repo(config.GITHUB_MODULES_REPO)
        tags = sorted(repo.get_tags(), key=lambda t: t.name, reverse=True)
        latest_tag = tags[0].name if tags else "v0.0.0"

        # Parse semver
        match = re.match(r"v?(\d+)\.(\d+)\.(\d+)", latest_tag)
        if not match:
            return {"status": "failed", "reason": f"Latest tag '{latest_tag}' is not semver"}

        major, minor, patch = int(match.group(1)), int(match.group(2)), int(match.group(3))
        if bump == "major":
            major += 1; minor = 0; patch = 0
        elif bump == "minor":
            minor += 1; patch = 0
        else:
            patch += 1

        new_tag = f"v{major}.{minor}.{patch}"
        branch = repo.get_branch("main")
        tag_obj = repo.create_git_tag(
            tag=new_tag,
            message=f"Release {new_tag} — auto-tagged by MCP module version checker",
            object=branch.commit.sha,
            type="commit",
        )
        repo.create_git_ref(ref=f"refs/tags/{new_tag}", sha=tag_obj.sha)

        return {
            "repo": config.GITHUB_MODULES_REPO,
            "previous_tag": latest_tag,
            "new_tag": new_tag,
            "status": "created",
        }

    @mcp.tool()
    def module_notify_update(
        latest_tag: str,
        previous_tag: str,
        changed_files: list,
        commits: list,
    ) -> dict:
        """
        Raise a GitHub Issue notifying the team that a new module version is available.
        Includes changelog, changed files, and which pipelines are on the old version.
        """
        infra_repo = _org.get_repo(config.GITHUB_INFRA_REPO)

        changed_files_list = "\n".join([f"- `{f}`" for f in changed_files]) or "- No files listed"
        commits_list = "\n".join([f"- {c}" for c in commits]) or "- No commits listed"

        body = f"""## New Module Version Available

| Field | Value |
|---|---|
| Previous Version | `{previous_tag}` |
| New Version | `{latest_tag}` |
| Detected By | MCP Module Version Checker (weekly run) |

### Changed Files
{changed_files_list}

### Commits
{commits_list}

### Action Required
Review the changes above and update pipeline references from `{previous_tag}` to `{latest_tag}` in:
- `network-infra` repo pipelines
- All application repo pipelines currently referencing `{previous_tag}`

> This issue was auto-created by the MCP module version checker.
"""
        issue = infra_repo.create_issue(
            title=f"Module Update Available: {previous_tag} → {latest_tag}",
            body=body,
            labels=["module-update"],
        )
        return {
            "issue_number": issue.number,
            "issue_url": issue.html_url,
            "latest_tag": latest_tag,
            "previous_tag": previous_tag,
            "status": "notified",
        }
