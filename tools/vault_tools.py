import hvac
from mcp.server.fastmcp import FastMCP
from config import config

_client = hvac.Client(url=config.VAULT_URL, token=config.VAULT_TOKEN)


def register_vault_tools(mcp: FastMCP):

    @mcp.tool()
    def vault_get_secret(secret_path: str) -> dict:
        """
        Fetch a secret from HashiCorp Vault by path.
        Used by pipelines to retrieve credentials (GitHub token, Jenkins token, AWS keys, etc.)
        without hardcoding them anywhere.
        """
        full_path = f"{config.VAULT_SECRET_PATH}/{secret_path}"
        response = _client.secrets.kv.v2.read_secret_version(path=full_path)
        data = response["data"]["data"]
        return {"path": full_path, "data": data}

    @mcp.tool()
    def vault_store_secret(secret_path: str, secret_data: dict) -> dict:
        """Store or update a secret in HashiCorp Vault at the given path."""
        full_path = f"{config.VAULT_SECRET_PATH}/{secret_path}"
        _client.secrets.kv.v2.create_or_update_secret(path=full_path, secret=secret_data)
        return {"path": full_path, "status": "stored"}

    @mcp.tool()
    def vault_list_secrets(path: str = "") -> dict:
        """List all secret keys at a given Vault path."""
        full_path = f"{config.VAULT_SECRET_PATH}/{path}" if path else config.VAULT_SECRET_PATH
        try:
            response = _client.secrets.kv.v2.list_secrets(path=full_path)
            keys = response["data"]["keys"]
        except Exception:
            keys = []
        return {"path": full_path, "keys": keys}

    @mcp.tool()
    def vault_check_connection() -> dict:
        """Verify the MCP server can reach HashiCorp Vault and authenticate successfully."""
        authenticated = _client.is_authenticated()
        return {"vault_url": config.VAULT_URL, "authenticated": authenticated}
