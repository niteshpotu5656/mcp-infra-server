"""
AWS Lambda — triggered by EventBridge when AWS Config records a resource change.
Syncs the change into Netbox so the inventory stays live across all 131 accounts.

EventBridge rule pattern:
{
  "source": ["aws.config"],
  "detail-type": ["Config Configuration Item Change"]
}
"""
import os
import json
import urllib.request

NETBOX_URL   = os.environ["NETBOX_URL"]
NETBOX_TOKEN = os.environ["NETBOX_TOKEN"]


def _netbox_request(method: str, path: str, body: dict = None):
    url  = f"{NETBOX_URL}/api/{path}"
    data = json.dumps(body).encode() if body else None
    req  = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Token {NETBOX_TOKEN}",
            "Content-Type":  "application/json",
        },
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def _get_account_record(account_id: str):
    resp = _netbox_request("GET", f"extras/config-contexts/?name=aws-account-{account_id}")
    results = resp.get("results", [])
    return results[0] if results else None


def _build_resource_entry(config_item: dict) -> dict:
    return {
        "type":   config_item.get("resourceType", "unknown"),
        "id":     config_item.get("resourceId", ""),
        "name":   config_item.get("resourceName", ""),
        "state":  config_item.get("configurationItemStatus", "unknown"),
        "region": config_item.get("awsRegion", ""),
    }


def lambda_handler(event, context):
    detail       = event.get("detail", {})
    config_item  = detail.get("configurationItem", {})
    account_id   = config_item.get("awsAccountId", "")
    resource     = _build_resource_entry(config_item)

    if not account_id:
        print("No account ID in event — skipping.")
        return {"status": "skipped"}

    record = _get_account_record(account_id)
    if not record:
        print(f"Account {account_id} not found in Netbox — skipping.")
        return {"status": "account_not_found", "account_id": account_id}

    # Merge resource into existing list (upsert by resource ID)
    existing_resources = record["data"].get("resources", [])
    updated = {r["id"]: r for r in existing_resources}
    updated[resource["id"]] = resource
    record["data"]["resources"] = list(updated.values())

    _netbox_request("PATCH", f"extras/config-contexts/{record['id']}/", {"data": record["data"]})

    print(f"Synced resource {resource['id']} ({resource['type']}) for account {account_id}")
    return {"status": "synced", "account_id": account_id, "resource_id": resource["id"]}
