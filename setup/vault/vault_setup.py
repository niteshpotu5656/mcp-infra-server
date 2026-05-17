"""
Run this once to initialise HashiCorp Vault with all secrets the MCP server needs.
Usage:
    python setup/vault/vault_setup.py
Requires VAULT_URL and VAULT_TOKEN to already be set in your environment.
"""
import os
import hvac

VAULT_URL   = os.environ["VAULT_URL"]
VAULT_TOKEN = os.environ["VAULT_TOKEN"]
BASE_PATH   = os.getenv("VAULT_SECRET_PATH", "secret/infra")

client = hvac.Client(url=VAULT_URL, token=VAULT_TOKEN)
assert client.is_authenticated(), "Vault authentication failed — check VAULT_TOKEN"


def store(path: str, data: dict):
    client.secrets.kv.v2.create_or_update_secret(path=f"{BASE_PATH}/{path}", secret=data)
    print(f"  stored → {BASE_PATH}/{path}")


print("Setting up Vault secrets...")

store("github", {
    "token": os.environ["GITHUB_TOKEN"],
    "org":   os.environ["GITHUB_ORG"],
})

store("jenkins", {
    "url":   os.environ["JENKINS_URL"],
    "user":  os.environ["JENKINS_USER"],
    "token": os.environ["JENKINS_TOKEN"],
})

store("aws", {
    "aft_account_id":             os.environ["AWS_AFT_ACCOUNT_ID"],
    "log_account_id":             os.environ["AWS_LOG_ACCOUNT_ID"],
    "shared_services_account_id": os.environ["AWS_SHARED_SERVICES_ACCOUNT_ID"],
    "region":                     os.getenv("AWS_REGION", "us-east-1"),
})

store("netbox", {
    "url":   os.environ["NETBOX_URL"],
    "token": os.environ["NETBOX_TOKEN"],
})

print("\nVault setup complete. All secrets stored under:", BASE_PATH)
