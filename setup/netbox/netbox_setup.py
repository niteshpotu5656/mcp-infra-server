"""
Run this once to configure Netbox custom fields required by the MCP server.
Usage:
    python setup/netbox/netbox_setup.py
"""
import os
import pynetbox

nb = pynetbox.api(os.environ["NETBOX_URL"], token=os.environ["NETBOX_TOKEN"])

CUSTOM_FIELDS = [
    {"name": "account_id",       "label": "AWS Account ID",      "type": "text",   "required": True},
    {"name": "account_name",     "label": "AWS Account Name",    "type": "text",   "required": True},
    {"name": "app_id",           "label": "Application ID",      "type": "text",   "required": True},
    {"name": "manager",          "label": "Manager",             "type": "text",   "required": True},
    {"name": "application_type", "label": "Application Type",    "type": "text",   "required": True},
    {"name": "environment",      "label": "Environment",         "type": "select", "required": True,
     "choices": ["nonprod", "prod", "dr"]},
]

print("Creating Netbox custom fields...")
for field in CUSTOM_FIELDS:
    try:
        nb.extras.custom_fields.create(
            name=field["name"],
            label=field["label"],
            type=field["type"],
            required=field["required"],
            content_types=["extras.configcontext"],
        )
        print(f"  created → {field['name']}")
    except Exception as e:
        print(f"  skipped → {field['name']} ({e})")

print("\nNetbox setup complete.")
