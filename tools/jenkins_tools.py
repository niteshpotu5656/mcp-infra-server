import time
import jenkins
from mcp.server.fastmcp import FastMCP
from config import config

_server = jenkins.Jenkins(
    config.JENKINS_URL,
    username=config.JENKINS_USER,
    password=config.JENKINS_TOKEN,
)

# How long to wait between status polls (seconds)
_POLL_INTERVAL = 15
# Max wait time per pipeline (seconds) — 45 minutes
_MAX_WAIT = 2700


def register_jenkins_tools(mcp: FastMCP):

    @mcp.tool()
    def jenkins_trigger_pipeline(pipeline_name: str, parameters: dict = {}) -> dict:
        """Trigger a Jenkins pipeline by name with optional parameters. Returns queue item number."""
        queue_id = _server.build_job(pipeline_name, parameters=parameters)
        return {
            "pipeline": pipeline_name,
            "queue_id": queue_id,
            "status": "triggered",
            "message": f"Pipeline '{pipeline_name}' queued. Use jenkins_get_pipeline_status to poll.",
        }

    @mcp.tool()
    def jenkins_get_pipeline_status(pipeline_name: str, build_number: int) -> dict:
        """Get the current status of a specific Jenkins pipeline build."""
        build_info = _server.get_build_info(pipeline_name, build_number)
        result = build_info.get("result")  # SUCCESS, FAILURE, ABORTED, or None if still running
        building = build_info.get("building", False)
        return {
            "pipeline": pipeline_name,
            "build_number": build_number,
            "building": building,
            "result": result,
            "url": build_info.get("url"),
            "duration_ms": build_info.get("duration"),
        }

    @mcp.tool()
    def jenkins_wait_for_pipeline(pipeline_name: str, build_number: int) -> dict:
        """Poll a Jenkins pipeline until it completes. Returns final result (SUCCESS or FAILURE)."""
        elapsed = 0
        while elapsed < _MAX_WAIT:
            build_info = _server.get_build_info(pipeline_name, build_number)
            if not build_info.get("building", True):
                result = build_info.get("result")
                return {
                    "pipeline": pipeline_name,
                    "build_number": build_number,
                    "result": result,
                    "success": result == "SUCCESS",
                    "url": build_info.get("url"),
                }
            time.sleep(_POLL_INTERVAL)
            elapsed += _POLL_INTERVAL
        return {
            "pipeline": pipeline_name,
            "build_number": build_number,
            "result": "TIMEOUT",
            "success": False,
            "message": f"Pipeline did not complete within {_MAX_WAIT}s",
        }

    @mcp.tool()
    def jenkins_check_pipeline_ran(pipeline_name: str, account_id: str) -> dict:
        """
        Check if a pipeline has already successfully run for a given account.
        Looks at the last successful build description for the account ID.
        Returns True if already ran so the workflow can skip this step.
        """
        try:
            job_info = _server.get_job_info(pipeline_name)
            last_successful = job_info.get("lastSuccessfulBuild")
            if not last_successful:
                return {"pipeline": pipeline_name, "account_id": account_id, "already_ran": False}
            build_number = last_successful["number"]
            build_info = _server.get_build_info(pipeline_name, build_number)
            description = build_info.get("description", "") or ""
            already_ran = account_id in description
            return {
                "pipeline": pipeline_name,
                "account_id": account_id,
                "already_ran": already_ran,
                "last_successful_build": build_number,
            }
        except Exception as e:
            return {"pipeline": pipeline_name, "account_id": account_id, "already_ran": False, "error": str(e)}

    @mcp.tool()
    def jenkins_get_pipeline_logs(pipeline_name: str, build_number: int) -> dict:
        """Fetch the console output of a Jenkins pipeline build — used to report failures to Claude."""
        logs = _server.get_build_console_output(pipeline_name, build_number)
        # Return last 3000 chars to avoid overwhelming context
        trimmed = logs[-3000:] if len(logs) > 3000 else logs
        return {
            "pipeline": pipeline_name,
            "build_number": build_number,
            "logs": trimmed,
            "truncated": len(logs) > 3000,
        }

    @mcp.tool()
    def jenkins_get_last_build_number(pipeline_name: str) -> dict:
        """Get the last build number for a pipeline — needed to poll status after triggering."""
        job_info = _server.get_job_info(pipeline_name)
        last_build = job_info.get("lastBuild")
        if not last_build:
            return {"pipeline": pipeline_name, "last_build_number": None}
        return {"pipeline": pipeline_name, "last_build_number": last_build["number"]}
