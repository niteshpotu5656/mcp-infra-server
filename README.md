# MCP Infrastructure Automation Server

An MCP (Model Context Protocol) server that connects to Claude Desktop and automates the full end-to-end AWS infrastructure creation workflow — from account creation through pipeline orchestration to live inventory sync.

> **Status:** Live and connected. 35 tools running. All services verified.

---

## Architecture Diagram

![MCP Infrastructure Automation Architecture](../architecture.png)

---

## What It Does

When an application team needs new AWS infrastructure, this MCP handles everything automatically:

1. **Pre-Infra** — reads the GitHub Issue, waits for manager approval, creates the AWS account, registers it in Netbox
2. **Infra Creation** — runs all Jenkins pipelines in the correct enforced order with pre-checks at every step
3. **Post-Infra** — syncs live resource inventory into Netbox via AWS Config and closes the GitHub Issue with a full summary

Claude acts as the orchestrator — it calls each MCP tool in order, checks results, handles failures, and keeps the app team updated via GitHub Issue comments throughout.

---

## Architecture Overview

```
App Team
   │
   ▼
GitHub Issue (infra request)
   │
   ▼
Claude Desktop + MCP Server (35 tools)
   │
   ├── GitHub Tools       → issues, PRs, file commits, version tags
   ├── AWS Tools          → account creation (POC: single account / Prod: AFT Organizations)
   ├── Jenkins Tools      → trigger & monitor all pipelines
   ├── Checkov Tools      → compliance scanning + 24-tag validation
   ├── Netbox Tools       → live CMDB inventory
   └── Vault Tools        → secrets & credentials
         │
         ▼
   Jenkins Pipelines (enforced order)
   ┌─────────────────────────────────┐
   │ 1. Log Account Pipeline         │
   │ 2. Checkov Account File         │
   │ 3. TGW Pipeline                 │
   │ 4. Network Infra Pipeline       │
   │ 5. Application Infra Pipeline   │
   └─────────────────────────────────┘
         │
         ▼
   AWS Config → EventBridge → Lambda → Netbox (live sync)
         │
         ▼
   GitHub Issue closed with full resource summary
```

---

## Tool Stack

| Purpose | Tool |
|---|---|
| Ticketing / Requests | GitHub Issues |
| Code & Terraform Modules | GitHub (personal account or org) |
| CI/CD Pipelines | Jenkins (Docker container) |
| Compliance & Tag Scanning | Checkov |
| Secrets Management | HashiCorp Vault (Docker container) |
| Live Inventory / CMDB | Netbox (Docker container) |
| Terraform Provider Cache | Shared `TF_PLUGIN_CACHE_DIR` on Jenkins agent |
| MCP Runtime | Python 3.13 + FastMCP |

---

## AWS Account Structure

### Production (full multi-account)

| Account | Role |
|---|---|
| OU (Master) | Manages all child accounts, enforces SCPs, Identity Center |
| AFT | All Terraform operations; holds all S3 state files |
| Shared Services | Firewall, proxy, Route 53, Transit Gateway |
| Prod Shared Services | Custom AMIs, private repos — auto-shared to new accounts |
| Security | Guardduty, antivirus |
| Log Account | Centralised VPC flow logs from all accounts |

### POC Mode (single account)

Set `POC_MODE=true` in your `.env` to bypass AFT account creation and use a single existing AWS account with static access keys. All other tools (GitHub, Jenkins, Netbox, Vault, Checkov) run fully in POC mode.

---

## Project Structure

```
mcp-infra-server/
├── server.py                               # MCP entry point — registers all 35 tools
├── config.py                               # Credentials loaded from env vars + POC_MODE flag
├── requirements.txt                        # Python dependencies
├── claude_mcp_config.json                  # Template for Claude Desktop MCP config
├── .env.example                            # Environment variable template
├── .env                                    # Your real credentials — never committed
│
├── tools/                                  # 35 MCP tools across 6 categories
│   ├── github_tools.py                     # 10 tools — issue, PR, file, branch, tag
│   ├── jenkins_tools.py                    #  6 tools — trigger, poll, pre-check, logs
│   ├── aws_tools.py                        #  4 tools — account creation (POC + prod)
│   ├── checkov_tools.py                    #  4 tools — compliance scan + 24-tag validation
│   ├── netbox_tools.py                     #  4 tools — CMDB registration and query
│   └── vault_tools.py                      #  4 tools — secret fetch, store, list, check
│
├── workflows/                              # Phase orchestration logic
│   ├── pre_infra.py                        # Phase 1 — account creation orchestration
│   ├── infra_pipeline.py                   # Phase 2 — 5-step enforced pipeline order
│   └── post_infra.py                       # Phase 3 — inventory sync + issue close
│
├── scheduler/
│   └── module_version_checker.py           # 3 tools — weekly version scan + auto-tag + notify
│
├── jenkins/                                # Jenkinsfile for every pipeline
│   ├── Jenkinsfile.warm-cache              # Run ONCE — pre-warms Terraform provider cache
│   ├── Jenkinsfile.log-account             # Pipeline 1 — log account registration
│   ├── Jenkinsfile.tgw                     # Pipeline 2 — Transit Gateway
│   ├── Jenkinsfile.network-infra           # Pipeline 3 — VPC, subnets, NAT, KMS, SGs
│   ├── Jenkinsfile.app-infra               # Pipeline 4 — EC2, EKS, RDS, ALB, SQS, ECR
│   └── Jenkinsfile.module-version-checker  # Weekly cron — Monday 08:00
│
├── lambda/
│   └── netbox_sync.py                      # Lambda — AWS Config → EventBridge → Netbox
│
├── setup/
│   ├── docker/
│   │   ├── docker-compose.yml              # Spins up Jenkins + Netbox + Vault
│   │   ├── configure_all.py                # Auto-configures all 3 services + writes .env
│   │   └── netbox-config/
│   │       └── extra.py                    # Netbox 4.6 API_TOKEN_PEPPERS config
│   ├── vault/vault_setup.py                # Seeds all secrets into Vault
│   ├── netbox/netbox_setup.py              # Creates Netbox custom fields
│   ├── aws/main.tf                         # Terraform — EventBridge + Lambda + AWS Config
│   └── terraform/
│       ├── versions.tf                     # Minimal config for provider cache warm-up
│       └── warm_provider_cache.sh          # Downloads AWS provider into cache once
│
├── templates/
│   └── tags.json                           # All 24 mandatory tags defined
│
└── tests/
    └── test_e2e.py                         # Full test suite — all 3 phases + cache + tags
```

---

## GitHub Repositories

All repos live under your GitHub account. Created automatically by `setup/github/create_repos_and_modules.py`.

| Repo | Contents | Tag |
|---|---|---|
| `modules` | 19 Terraform modules (9 network + 10 app) | `v1.0.0` |
| `network-infra` | Network Terraform configs per account/env | — |
| `checkov-configs` | Per-account Checkov compliance files | — |
| `infra-requests` | GitHub Issues for infra requests | — |
| `mcp-infra-server` | This repo — MCP server code | — |

---

## Prerequisites

| Requirement | Notes |
|---|---|
| Docker Desktop | For running Jenkins, Netbox, and Vault locally |
| Python 3.12+ | For the MCP server process |
| Claude Desktop | App that connects to the MCP server |
| GitHub account + PAT | Classic PAT with `repo` scope |
| AWS account + IAM user | Access key + secret key (POC: any account; Prod: AFT account with MCPAutomationRole) |

---

## Quick Start

### 1. Clone and install dependencies

```bash
git clone https://github.com/niteshpotu5656/mcp-infra-server.git
cd mcp-infra-server
pip install -r requirements.txt
```

### 2. Start all services with Docker

```bash
cd setup/docker
docker compose up -d
```

This starts:
- **Jenkins** at `http://localhost:8080`
- **Netbox** at `http://localhost:8000`
- **Vault** at `http://localhost:8200` (dev mode, token: `root`)

### 3. Configure all services automatically

```bash
python setup/docker/configure_all.py
```

This script:
- Creates Jenkins admin user and generates an API token
- Verifies the Netbox API token
- Enables Vault KV v2 and seeds all secret paths
- Writes all generated credentials into `.env`

### 4. Fill in the remaining `.env` values

```bash
# Open .env and fill in the AWS section:
AWS_ACCESS_KEY_ID=your_access_key
AWS_SECRET_ACCESS_KEY=your_secret_key
AWS_ACCOUNT_ID=your_12_digit_account_id

# For production (multi-account), also fill in:
AWS_AFT_ACCOUNT_ID=...
AWS_LOG_ACCOUNT_ID=...
AWS_SHARED_SERVICES_ACCOUNT_ID=...
```

### 5. Create GitHub repos and push all Terraform modules

```bash
python setup/github/create_repos_and_modules.py
```

Creates all 5 repos and pushes 19 Terraform modules tagged at `v1.0.0`.

### 6. Install Terraform on Jenkins and warm the provider cache

```bash
# Install Terraform inside the Jenkins container
docker exec -u root mcp-jenkins bash -c "
  apt-get update -qq && apt-get install -y -qq wget unzip && \
  wget -q https://releases.hashicorp.com/terraform/1.7.5/terraform_1.7.5_linux_amd64.zip && \
  unzip -q terraform_1.7.5_linux_amd64.zip && mv terraform /usr/local/bin/ && \
  rm terraform_1.7.5_linux_amd64.zip
"

# Warm the provider cache (downloads AWS provider ~675MB — once only)
docker cp setup/terraform/versions.tf mcp-jenkins:/tmp/versions.tf
docker exec -u root mcp-jenkins bash -c "
  mkdir -p /tmp/tf-warm && cp /tmp/versions.tf /tmp/tf-warm/ && \
  cd /tmp/tf-warm && \
  TF_PLUGIN_CACHE_DIR=/var/jenkins_home/terraform-plugin-cache \
  terraform init -backend=false -input=false -no-color
"
```

After this, all pipelines reuse the cached provider — **zero downloads** per run.

> **Already done?** The provider cache persists in a Docker volume (`jenkins_cache`). It survives container restarts. Only re-run if you rebuild the volume or upgrade the provider version.

### 7. Configure Jenkins pipeline jobs

Create the following pipeline jobs in Jenkins (`http://localhost:8080`):

| Jenkins Job Name | Jenkinsfile | Purpose |
|---|---|---|
| `terraform-warm-cache` | `Jenkinsfile.warm-cache` | One-time provider cache warm-up |
| `log-account-pipeline` | `Jenkinsfile.log-account` | Pipeline 1 |
| `tgw-pipeline` | `Jenkinsfile.tgw` | Pipeline 2 |
| `network-infra-pipeline` | `Jenkinsfile.network-infra` | Pipeline 3 |
| `app-infra-pipeline` | `Jenkinsfile.app-infra` | Pipeline 4 |
| `module-version-checker` | `Jenkinsfile.module-version-checker` | Weekly cron (Mon 08:00) |

Add Jenkins credentials:
- `github-token` — GitHub PAT
- `vault-token` — Vault root token (`root` in dev mode)

### 8. Connect to Claude Desktop

1. Open Claude Desktop → **Settings → Developer → Edit Config**
2. Add the `mcpServers` block to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "mcp-infra-server": {
      "command": "C:\\Python313\\python.exe",
      "args": ["H:\\path\\to\\mcp-infra-server\\server.py"],
      "env": {
        "POC_MODE":                        "true",
        "GITHUB_TOKEN":                    "your_github_pat",
        "GITHUB_ORG":                      "your_github_username",
        "GITHUB_MODULES_REPO":             "modules",
        "GITHUB_NETWORK_REPO":             "network-infra",
        "GITHUB_INFRA_REPO":               "infra-requests",
        "JENKINS_URL":                     "http://localhost:8080",
        "JENKINS_USER":                    "admin",
        "JENKINS_TOKEN":                   "your_jenkins_token",
        "AWS_REGION":                      "us-east-1",
        "AWS_ACCESS_KEY_ID":               "your_access_key",
        "AWS_SECRET_ACCESS_KEY":           "your_secret_key",
        "AWS_ACCOUNT_ID":                  "123456789012",
        "AWS_AFT_ACCOUNT_ID":              "123456789012",
        "AWS_LOG_ACCOUNT_ID":              "123456789012",
        "AWS_SHARED_SERVICES_ACCOUNT_ID":  "123456789012",
        "NETBOX_URL":                      "http://localhost:8000",
        "NETBOX_TOKEN":                    "your_netbox_token",
        "VAULT_URL":                       "http://localhost:8200",
        "VAULT_TOKEN":                     "root",
        "VAULT_SECRET_PATH":               "secret/infra",
        "CHECKOV_REPO_PATH":               "H:\\path\\to\\checkov\\configs",
        "PYTHONPATH":                      "H:\\path\\to\\mcp-infra-server"
      }
    }
  }
}
```

> **Important:** Use the **full path** to `python.exe` and `server.py` — relative paths don't work because Claude Desktop launches from `system32`.

3. **Fully quit Claude Desktop** (system tray → Quit) and reopen it
4. Go to **Settings → Developer** — you should see `mcp-infra-server` with a blue **running** badge

---

## Terraform Provider Cache

All Jenkinsfiles set `TF_PLUGIN_CACHE_DIR` to the same shared persistent directory:

```groovy
environment {
    TF_PLUGIN_CACHE_DIR = '/var/jenkins_home/terraform-plugin-cache'
}
```

```
/var/jenkins_home/terraform-plugin-cache/
  └── registry.terraform.io/hashicorp/aws/5.100.0/linux_amd64/
        └── terraform-provider-aws_v5.100.0_x5   (675 MB)
```

**How it's shared:**

```
One cached binary (675 MB, downloaded once)
         │
         ├── log-account-pipeline  → Account A
         ├── tgw-pipeline          → Account A, B, C...
         ├── network-infra-pipeline → All accounts
         └── app-infra-pipeline    → All accounts, all apps
```

No pipeline ever re-downloads the provider. The cache persists in the `jenkins_cache` Docker volume and survives container restarts.

---

## POC Mode

Set `POC_MODE=true` to run against a single existing AWS account instead of the full AFT multi-account setup:

| Behaviour | POC Mode | Production Mode |
|---|---|---|
| `aws_create_account` | Returns existing account ID immediately | Creates real account via Organizations API |
| `aws_check_account_active` | Verifies credentials via STS | Checks Organizations account status |
| `aws_get_account_details` | Returns STS caller identity | Queries Organizations API |
| AWS authentication | Static access key + secret key | `assume_role` to `MCPAutomationRole` in AFT account |
| All other tools | Run fully (GitHub, Jenkins, Netbox, Vault, Checkov) | Run fully |

To switch to production mode: set `POC_MODE=false` and fill in the real AFT/Log/Shared Services account IDs.

---

## How the Workflow Runs

### Step 1 — App team raises a GitHub Issue

The issue must include:

| Field | Description |
|---|---|
| Account Name | Name for the new AWS account |
| App ID | Application identifier |
| Manager | Approving manager's name |
| Application Type | Type (microservice, data platform, etc.) |
| Environment | `nonprod`, `prod`, or `dr` |
| VPC CIDR | Required IP range e.g. `10.0.0.0/16` |
| Budget Approval Link | Link to approved budget document |
| Architecture Doc Link | Link to approved architecture document |

### Step 2 — Manager approves

Manager adds the `approved` label to the GitHub Issue. Claude polls via `github_check_approval` before proceeding.

### Step 3 — Claude runs pre-infra

```
Approval confirmed
    → AWS account created (or bypassed in POC mode)
    → Account registered in Netbox with all metadata
    → Account ID and Netbox record posted back to GitHub Issue
```

### Step 4 — Claude runs infra pipelines in strict order

Each step has a pre-check — if it already ran for this account it is skipped automatically.

```
1. Log Account Pipeline     → registers account ARN for centralised VPC flow logs
        ↓
2. Checkov Account File     → creates compliance config, validates 24 mandatory tags
        ↓
3. TGW Pipeline             → Transit Gateway in Shared Services, re-shared to new account
        ↓
4. Network Infra Pipeline   → VPC · subnets · NAT · KMS · SGs · SSM · VPCE · flow logs
                              (Terraform committed to GitHub → PR raised → merged → applied)
        ↓
5. App Infra Pipeline       → EC2 · EKS · RDS · ALB · NLB · SQS · SNS · ECR · Secrets Manager
                              (same GitHub PR flow)
```

If any pipeline fails, Claude fetches the console logs, posts them to the GitHub Issue, and stops.

### Step 5 — Post-infra

AWS Config syncs all resources to Netbox via Lambda automatically. Claude reads the Netbox record, posts a full resource summary, and closes the GitHub Issue.

---

## 24 Mandatory Tags

Every resource must have all 24 tags. Checkov validates this before every pipeline and blocks if any tag is missing:

```
AccountId, AccountName, AppId, ApplicationType, Environment, Manager,
CostCenter, BusinessUnit, Department, Project, Owner, CreatedBy,
CreatedDate, LastModifiedBy, LastModifiedDate, Compliance, DataClassification,
BackupPolicy, MonitoringLevel, PatchGroup, SupportTeam, Region,
Terraform, TerraformModuleVersion
```

Full definition in `templates/tags.json`.

---

## Module Version Management

A Jenkins cron runs every Monday at 08:00 and:

1. Scans the `modules` repo for changes since the last Git tag
2. If changes detected — auto-creates the next semver tag (`v1.2.3` → `v1.2.4`)
3. Raises a GitHub Issue listing what changed and which pipelines need updating

---

## Live Inventory Sync

```
Resource created / modified / deleted in AWS
    → AWS Config detects the change
    → EventBridge rule fires
    → Lambda (lambda/netbox_sync.py) calls Netbox API
    → Netbox record updated in real time
```

Deploy the Lambda + EventBridge + AWS Config via `setup/aws/main.tf`.

---

## MCP Tools Reference (35 tools)

| Tool | Phase | Description |
|---|---|---|
| `github_create_issue` | Pre | Create infra request issue |
| `github_check_approval` | Pre | Check manager approved label |
| `github_update_issue` | All | Post status comment to issue |
| `github_close_issue` | Post | Close issue with final summary |
| `github_create_file` | Infra | Commit Terraform config to repo |
| `github_create_branch` | Infra | Create feature branch |
| `github_create_pr` | Infra | Raise PR for review |
| `github_merge_pr` | Infra | Merge approved PR |
| `github_create_tag` | Scheduler | Create new module version tag |
| `github_get_latest_tag` | Scheduler | Get current module version |
| `aws_create_account` | Pre | Create AWS account (POC: returns existing) |
| `aws_get_account_details` | Pre | Fetch account info |
| `aws_check_account_active` | Pre | Verify account is accessible |
| `aws_get_account_arn` | Pre | Get account ARN for log pipeline |
| `jenkins_trigger_pipeline` | Infra | Trigger a Jenkins pipeline |
| `jenkins_get_pipeline_status` | Infra | Get build status |
| `jenkins_wait_for_pipeline` | Infra | Poll until pipeline completes |
| `jenkins_check_pipeline_ran` | Infra | Pre-check — skip if already ran |
| `jenkins_get_pipeline_logs` | Infra | Fetch logs on failure |
| `jenkins_get_last_build_number` | Infra | Get build number after trigger |
| `checkov_check_account_file` | Infra | Check if account file exists |
| `checkov_create_account_file` | Infra | Create compliance account file |
| `checkov_run_scan` | Infra | Run full compliance scan |
| `checkov_validate_tags` | Infra | Validate all 24 tags present |
| `netbox_create_account` | Pre | Register account in CMDB |
| `netbox_get_account` | Any | Query account and resources |
| `netbox_update_resources` | Post | Update resource inventory |
| `netbox_list_accounts` | Any | List accounts by environment |
| `vault_get_secret` | Infra | Fetch secret by path |
| `vault_store_secret` | Setup | Store secret in Vault |
| `vault_list_secrets` | Setup | List keys at a Vault path |
| `vault_check_connection` | Setup | Verify Vault connectivity |
| `module_check_versions` | Scheduler | Scan for new module version |
| `module_create_next_tag` | Scheduler | Auto-create next semver tag |
| `module_notify_update` | Scheduler | Raise GitHub Issue for new version |

---

## Running Tests

```bash
# Unit tests — all services mocked
python -m pytest tests/test_e2e.py -v

# Integration tests — runs against real services
USE_REAL_SERVICES=true python -m pytest tests/test_e2e.py -v
```

---

## Troubleshooting

| Problem | Cause | Fix |
|---|---|---|
| `Server disconnected` in Claude Desktop | `server.py` path wrong | Use full absolute path in `args`, not just `"server.py"` |
| `Could not load app settings` — invalid JSON | BOM in config file | Re-save `claude_desktop_config.json` using UTF-8 without BOM |
| Provider re-downloading every pipeline run | Cache empty or Terraform not installed on Jenkins | Re-run the provider cache warm-up steps in Setup §6 |
| Pipeline blocked at Checkov step | Account file missing | Run `checkov_create_account_file` tool first |
| Netbox API returns `Invalid v1 token` | Netbox 4.6 requires `API_TOKEN_PEPPERS` | Ensure `setup/docker/netbox-config/extra.py` is mounted and container restarted |
| Vault authentication error | Token expired | Vault dev mode resets on restart — token is always `root` in dev mode |
| Jenkins `403 No valid crumb` | CSRF protection | Use a web session when calling Jenkins API — crumb and cookies must come from the same session |
| Claude shows `No servers added` | Config not saved or preferences-only file | Ensure `mcpServers` key exists at root level in `claude_desktop_config.json` |
| `ModuleNotFoundError` in server | `PYTHONPATH` not set | Add `"PYTHONPATH": "/full/path/to/mcp-infra-server"` to the MCP env config |
| AWS `InvalidClientTokenId` | Wrong access key | Verify `AWS_ACCESS_KEY_ID` in `.env` matches what AWS Console shows |

---

## Service Credentials (Docker / Local)

| Service | URL | Default Login |
|---|---|---|
| Jenkins | http://localhost:8080 | admin / admin |
| Netbox | http://localhost:8000 | admin / admin123 |
| Vault | http://localhost:8200 | token: `root` (dev mode) |

> Vault dev mode resets on container restart. For production, use a properly initialised and unsealed Vault instance.

---

## Related Documents

| Document | Location | Description |
|---|---|---|
| Full Plan | `../MCP_PLAN.md` | Complete architecture plan — all phases, tools, design decisions |
| Task Tracking | `../MCP_TRACKING.md` | 87 tasks across 13 chunks |
| Architecture Diagram | `../architecture.png` | Visual diagram of the full workflow |
| Diagram Generator | `../generate_architecture.py` | Run to regenerate after changes |
