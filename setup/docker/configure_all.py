#!/usr/bin/env python3
"""
configure_all.py
────────────────
Configures Jenkins, Netbox, and Vault after docker-compose up,
then writes all generated credentials into ../../.env

Run ONCE after the containers are healthy:
    python setup/docker/configure_all.py
"""

import json
import os
import sys
import time
import urllib.request
import urllib.parse
import urllib.error
import base64
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]   # mcp-infra-server/
ENV_FILE = ROOT / ".env"

# ── Endpoints ────────────────────────────────────────────────────────────────
JENKINS_URL   = "http://localhost:8080"
NETBOX_URL    = "http://localhost:8000"
VAULT_URL     = "http://localhost:8200"

JENKINS_USER  = "admin"
JENKINS_PASS  = "admin"      # set during first-run init below
NETBOX_TOKEN  = "netbox-mcp-api-token-000001"   # set via env in compose
VAULT_TOKEN   = "root"       # dev mode root token

# ─────────────────────────────────────────────────────────────────────────────

def log(msg): print(f"  {msg}", flush=True)
def header(msg): print(f"\n{'='*60}\n {msg}\n{'='*60}", flush=True)
def ok(msg): print(f"  ✅  {msg}", flush=True)
def warn(msg): print(f"  ⚠️   {msg}", flush=True)

# ── HTTP helpers ──────────────────────────────────────────────────────────────

def http(method, url, data=None, headers=None, user=None, password=None, timeout=15):
    headers = headers or {}
    if user and password:
        creds = base64.b64encode(f"{user}:{password}".encode()).decode()
        headers["Authorization"] = f"Basic {creds}"
    if isinstance(data, dict):
        data = json.dumps(data).encode()
        headers.setdefault("Content-Type", "application/json")
    elif isinstance(data, str):
        data = data.encode()
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
            return r.status, body.decode(errors="replace"), dict(r.headers)
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        return e.code, body, {}
    except Exception as e:
        return 0, str(e), {}


def wait_for(url, label, token_header=None, timeout=180):
    """Poll until service returns 200 or 401."""
    headers = {}
    if token_header:
        headers["Authorization"] = token_header
    deadline = time.time() + timeout
    attempt = 0
    while time.time() < deadline:
        attempt += 1
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=5) as r:
                if r.status in (200, 201, 301, 302):
                    ok(f"{label} is up")
                    return True
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                ok(f"{label} is up (auth required)")
                return True
        except Exception:
            pass
        if attempt % 6 == 0:
            log(f"  Still waiting for {label}... ({int(time.time()-deadline+timeout)}s left)")
        time.sleep(5)
    return False

# ══════════════════════════════════════════════════════════════════════════════
# JENKINS
# ══════════════════════════════════════════════════════════════════════════════

def setup_jenkins():
    header("JENKINS")

    if not wait_for(f"{JENKINS_URL}/login", "Jenkins"):
        warn("Jenkins did not start in time — skipping")
        return None

    # ── Get initial admin password ────────────────────────────────────────────
    log("Reading initial admin password from container...")
    exit_code = os.system(
        'docker exec mcp-jenkins cat /var/jenkins_home/secrets/initialAdminPassword > '
        '.jenkins_pass.tmp 2>&1'
    )
    init_pass = None
    if os.path.exists(".jenkins_pass.tmp"):
        with open(".jenkins_pass.tmp") as f:
            init_pass = f.read().strip()
        os.remove(".jenkins_pass.tmp")

    if not init_pass:
        warn("Could not read initialAdminPassword — Jenkins may already be configured")
        init_pass = JENKINS_PASS

    log(f"Initial password found: {init_pass[:8]}...")

    # ── Create admin user via Jenkins script console ──────────────────────────
    groovy_create_user = f"""
import jenkins.model.*
import hudson.security.*

def instance = Jenkins.getInstance()
def hudsonRealm = new HudsonPrivateSecurityRealm(false)
hudsonRealm.createAccount("{JENKINS_USER}", "{JENKINS_PASS}")
instance.setSecurityRealm(hudsonRealm)
def strategy = new FullControlOnceLoggedInAuthorizationStrategy()
strategy.setAllowAnonymousRead(false)
instance.setAuthorizationStrategy(strategy)
instance.save()
println "User created: {JENKINS_USER}"
"""
    status, body, _ = http(
        "POST",
        f"{JENKINS_URL}/scriptText",
        data=urllib.parse.urlencode({"script": groovy_create_user}),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        user=JENKINS_USER,
        password=init_pass
    )
    if "User created" in body or status in (200, 201):
        ok("Admin user configured")
    else:
        log(f"User setup response ({status}): {body[:200]}")

    # ── Generate API token ────────────────────────────────────────────────────
    # Step 1: get crumb
    status, body, _ = http(
        "GET",
        f"{JENKINS_URL}/crumbIssuer/api/json",
        user=JENKINS_USER,
        password=JENKINS_PASS
    )
    crumb_field, crumb_value = "Jenkins-Crumb", ""
    if status == 200:
        try:
            d = json.loads(body)
            crumb_field = d.get("crumbRequestField", "Jenkins-Crumb")
            crumb_value = d.get("crumb", "")
        except Exception:
            pass

    # Step 2: generate token
    status, body, _ = http(
        "POST",
        f"{JENKINS_URL}/me/descriptorByName/jenkins.security.ApiTokenProperty/generateNewToken",
        data=urllib.parse.urlencode({"newTokenName": "mcp-token"}),
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            crumb_field: crumb_value
        },
        user=JENKINS_USER,
        password=JENKINS_PASS
    )
    token = None
    if status == 200:
        try:
            d = json.loads(body)
            token = d["data"]["tokenValue"]
            ok(f"API token generated: {token[:12]}...")
        except Exception:
            pass

    if not token:
        warn("Could not auto-generate Jenkins token. After Jenkins starts:")
        warn(f"  → Go to {JENKINS_URL} → admin → Configure → API Token → Add new Token")
        token = "PASTE_YOUR_JENKINS_TOKEN_HERE"

    return token

# ══════════════════════════════════════════════════════════════════════════════
# NETBOX
# ══════════════════════════════════════════════════════════════════════════════

def setup_netbox():
    header("NETBOX")

    if not wait_for(f"{NETBOX_URL}/api/", "Netbox", timeout=240):
        warn("Netbox did not start in time — skipping")
        return None

    # Verify token works
    status, body, _ = http(
        "GET",
        f"{NETBOX_URL}/api/users/tokens/",
        headers={"Authorization": f"Token {NETBOX_TOKEN}"}
    )
    if status == 200:
        ok(f"Netbox API token verified: {NETBOX_TOKEN[:20]}...")
    else:
        warn(f"Netbox token check returned {status} — it may still be initialising")

    # ── Create custom fields ──────────────────────────────────────────────────
    custom_fields = [
        {
            "name": "app_id",
            "label": "App ID",
            "type": "text",
            "object_types": ["extras.configcontext"],
            "required": False,
            "description": "Application identifier"
        },
        {
            "name": "manager",
            "label": "Manager",
            "type": "text",
            "object_types": ["extras.configcontext"],
            "required": False,
            "description": "Responsible manager"
        },
        {
            "name": "application_type",
            "label": "Application Type",
            "type": "text",
            "object_types": ["extras.configcontext"],
            "required": False,
            "description": "Type of application (web, data, batch, etc.)"
        },
        {
            "name": "environment",
            "label": "Environment",
            "type": "text",
            "object_types": ["extras.configcontext"],
            "required": False,
            "description": "Deployment environment (prod, staging, dev, etc.)"
        },
        {
            "name": "aws_account_id",
            "label": "AWS Account ID",
            "type": "text",
            "object_types": ["extras.configcontext"],
            "required": False,
            "description": "12-digit AWS account ID"
        },
    ]
    created = 0
    for cf in custom_fields:
        status, body, _ = http(
            "POST",
            f"{NETBOX_URL}/api/extras/custom-fields/",
            data=cf,
            headers={"Authorization": f"Token {NETBOX_TOKEN}"}
        )
        if status in (200, 201):
            created += 1
        elif status == 400 and "already exists" in body.lower():
            pass   # already there
        else:
            log(f"  Custom field '{cf['name']}' → {status}: {body[:100]}")

    ok(f"Custom fields: {created} created (others already existed)")
    return NETBOX_TOKEN

# ══════════════════════════════════════════════════════════════════════════════
# VAULT
# ══════════════════════════════════════════════════════════════════════════════

def setup_vault():
    header("VAULT")

    if not wait_for(f"{VAULT_URL}/v1/sys/health", "Vault"):
        warn("Vault did not start in time — skipping")
        return None

    # dev mode is already unsealed with root token
    ok(f"Vault running in dev mode — root token: {VAULT_TOKEN}")

    # Enable KV v2 at secret/
    status, body, _ = http(
        "POST",
        f"{VAULT_URL}/v1/sys/mounts/secret",
        data={"type": "kv", "options": {"version": "2"}},
        headers={"X-Vault-Token": VAULT_TOKEN}
    )
    if status in (200, 204):
        ok("KV v2 secrets engine enabled at secret/")
    elif status == 400 and "already" in body.lower():
        ok("KV v2 already enabled at secret/")
    else:
        log(f"Mount response ({status}): {body[:200]}")

    # Seed initial secrets structure
    seeds = {
        "secret/data/infra/github": {
            "data": {
                "token": "FILL_IN_AFTER_SETUP",
                "org": "niteshpotu5656"
            }
        },
        "secret/data/infra/jenkins": {
            "data": {
                "url": f"{JENKINS_URL}",
                "user": JENKINS_USER,
                "token": "FILL_AFTER_JENKINS_TOKEN_GENERATED"
            }
        },
        "secret/data/infra/aws": {
            "data": {
                "region": "us-east-1",
                "aft_account_id": "FILL_IN",
                "log_account_id": "FILL_IN",
                "shared_services_account_id": "FILL_IN"
            }
        },
        "secret/data/infra/netbox": {
            "data": {
                "url": NETBOX_URL,
                "token": NETBOX_TOKEN
            }
        },
    }

    seeded = 0
    for path, payload in seeds.items():
        status, body, _ = http(
            "POST",
            f"{VAULT_URL}/v1/{path}",
            data=payload,
            headers={"X-Vault-Token": VAULT_TOKEN}
        )
        if status in (200, 204):
            seeded += 1

    ok(f"Vault secrets seeded: {seeded}/{len(seeds)} paths")
    return VAULT_TOKEN

# ══════════════════════════════════════════════════════════════════════════════
# .env writer
# ══════════════════════════════════════════════════════════════════════════════

def update_env(updates: dict):
    """Read current .env, replace matching keys, write back."""
    if not ENV_FILE.exists():
        warn(f".env not found at {ENV_FILE}")
        return

    lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
    new_lines = []
    updated_keys = set()

    for line in lines:
        matched = False
        for key, val in updates.items():
            if line.startswith(f"{key}=") or line.startswith(f"# {key}="):
                new_lines.append(f"{key}={val}")
                updated_keys.add(key)
                matched = True
                break
        if not matched:
            new_lines.append(line)

    # Append any keys not already in file
    for key, val in updates.items():
        if key not in updated_keys:
            new_lines.append(f"{key}={val}")

    ENV_FILE.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    log(f"Updated .env: {', '.join(updates.keys())}")

# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    print("\n" + "="*60)
    print(" MCP Infrastructure — Service Configuration")
    print("="*60)
    print(f"\n  Config target: {ENV_FILE}\n")

    jenkins_token = setup_jenkins()
    netbox_token  = setup_netbox()
    vault_token   = setup_vault()

    header("UPDATING .env")

    env_updates = {
        "JENKINS_URL":   JENKINS_URL,
        "JENKINS_USER":  JENKINS_USER,
        "JENKINS_TOKEN": jenkins_token or "PASTE_YOUR_JENKINS_TOKEN_HERE",
        "NETBOX_URL":    NETBOX_URL,
        "NETBOX_TOKEN":  netbox_token or NETBOX_TOKEN,
        "VAULT_URL":     VAULT_URL,
        "VAULT_TOKEN":   vault_token or VAULT_TOKEN,
        "VAULT_SECRET_PATH": "secret/infra",
    }
    update_env(env_updates)
    ok(".env updated with all service credentials")

    print("""
╔══════════════════════════════════════════════════════════╗
║           ALL SERVICES CONFIGURED ✅                     ║
╠══════════════════════════════════════════════════════════╣
║  Jenkins  →  http://localhost:8080                       ║
║             user: admin / pass: admin                    ║
║  Netbox   →  http://localhost:8000                       ║
║             user: admin / pass: admin123                 ║
║  Vault    →  http://localhost:8200                       ║
║             token: root  (dev mode)                      ║
╠══════════════════════════════════════════════════════════╣
║  ⚠️  Still needed — fill manually in .env:               ║
║     AWS_AFT_ACCOUNT_ID          (12-digit AWS ID)        ║
║     AWS_LOG_ACCOUNT_ID          (12-digit AWS ID)        ║
║     AWS_SHARED_SERVICES_ACCOUNT_ID  (12-digit AWS ID)   ║
╚══════════════════════════════════════════════════════════╝
""")

if __name__ == "__main__":
    main()
