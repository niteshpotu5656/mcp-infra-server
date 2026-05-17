import pynetbox
from mcp.server.fastmcp import FastMCP
from config import config

_nb = pynetbox.api(config.NETBOX_URL, token=config.NETBOX_TOKEN)


def register_netbox_tools(mcp: FastMCP):

    @mcp.tool()
    def netbox_create_account(
        account_id: str,
        account_name: str,
        app_id: str,
        manager: str,
        application_type: str,
        environment: str,
    ) -> dict:
        """
        Register a new AWS account in Netbox with all required metadata.
        Custom fields: app_id, manager, application_type, environment.
        """
        record = _nb.extras.config_contexts.create({
            "name": f"aws-account-{account_id}",
            "data": {
                "account_id": account_id,
                "account_name": account_name,
                "app_id": app_id,
                "manager": manager,
                "application_type": application_type,
                "environment": environment,
                "resources": [],
            },
        })
        return {
            "account_id": account_id,
            "netbox_id": record.id,
            "status": "registered",
        }

    @mcp.tool()
    def netbox_get_account(account_id: str) -> dict:
        """Fetch a Netbox account record by AWS account ID."""
        results = list(_nb.extras.config_contexts.filter(name=f"aws-account-{account_id}"))
        if not results:
            return {"account_id": account_id, "found": False}
        record = results[0]
        return {
            "account_id": account_id,
            "found": True,
            "netbox_id": record.id,
            "data": dict(record.data),
        }

    @mcp.tool()
    def netbox_update_resources(account_id: str, resources: list) -> dict:
        """
        Update the resource list for an account in Netbox.
        Called automatically by the AWS Config → Lambda sync when resources change.
        resources: list of dicts with keys: type, id, name, state, region.
        """
        results = list(_nb.extras.config_contexts.filter(name=f"aws-account-{account_id}"))
        if not results:
            return {"account_id": account_id, "updated": False, "reason": "Account not found in Netbox"}
        record = results[0]
        data = dict(record.data)
        data["resources"] = resources
        _nb.extras.config_contexts.update([{"id": record.id, "data": data}])
        return {
            "account_id": account_id,
            "updated": True,
            "resource_count": len(resources),
        }

    @mcp.tool()
    def netbox_list_accounts(environment: str = "") -> dict:
        """List all registered accounts in Netbox. Optionally filter by environment."""
        all_records = list(_nb.extras.config_contexts.filter(name__startswith="aws-account-"))
        accounts = []
        for record in all_records:
            data = dict(record.data)
            if environment and data.get("environment") != environment:
                continue
            accounts.append({
                "account_id": data.get("account_id"),
                "account_name": data.get("account_name"),
                "app_id": data.get("app_id"),
                "manager": data.get("manager"),
                "environment": data.get("environment"),
                "application_type": data.get("application_type"),
            })
        return {"accounts": accounts, "total": len(accounts)}
