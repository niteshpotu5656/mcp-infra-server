from mcp.server.fastmcp import FastMCP
from tools.github_tools import register_github_tools
from tools.jenkins_tools import register_jenkins_tools
from tools.aws_tools import register_aws_tools
from tools.checkov_tools import register_checkov_tools
from tools.netbox_tools import register_netbox_tools
from tools.vault_tools import register_vault_tools
from scheduler.module_version_checker import register_scheduler_tools

mcp = FastMCP(
    name="mcp-infra-server",
    instructions="Automates end-to-end AWS infrastructure creation: account creation, pipeline orchestration, and live inventory sync.",
)

register_github_tools(mcp)
register_jenkins_tools(mcp)
register_aws_tools(mcp)
register_checkov_tools(mcp)
register_netbox_tools(mcp)
register_vault_tools(mcp)
register_scheduler_tools(mcp)

if __name__ == "__main__":
    mcp.run()
