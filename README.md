# MCP Infrastructure Automation Server

An MCP (Model Context Protocol) server that connects to Claude and automates the full end-to-end AWS infrastructure creation workflow — from account creation through pipeline orchestration to live inventory sync.

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
Claude + MCP Server
   │
   ├── GitHub Tools       → issues, PRs, file commits, version tags
   ├── AWS Tools          → account creation via AFT (Organizations API)
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
| Code & Terraform Modules | GitHub |
| CI/CD Pipelines | Jenkins |
| Compliance & Tag Scanning | Checkov |
| Secrets Management | HashiCorp Vault |
| Live Inventory / CMDB | AWS Config + Netbox |
| Terraform Provider Cache | `TF_PLUGIN_CACHE_DIR` on Jenkins agent |

---

## AWS Account Structure

| Account | Role |
|---|---|
| OU (Master) | Manages all 131 child accounts, enforces SCPs, Identity Center |
| AFT | All Terraform operations run from here; holds all S3 state files |
| Shared Services | Firewall, proxy, Route 53, Transit Gateway |
| Prod Shared Services | Custom AMIs, private repos — auto-shared to new accounts |
| Security | Guardduty, antivirus, ServiceNow |
| Log Account | Centralised VPC flow logs from all accounts |

---

## Project Structure

```
mcp-infra-server/
├── server.py                               # MCP server entry point — registers all tools
├── config.py                               # All credentials loaded from env vars
├── requirements.txt                        # Python dependencies
├── claude_mcp_config.json                  # Claude Code MCP connection config
├── .env.example                            # Environment variable template — copy to .env
│
├── tools/                                  # 33 MCP tools across 6 categories
│   ├── github_tools.py                     # 9 tools — issue, PR, file, branch, tag
│   ├── jenkins_tools.py                    # 6 tools — trigger, poll, pre-check, logs
│   ├── aws_tools.py                        # 4 tools — account creation via AFT
│   ├── checkov_tools.py                    # 4 tools — compliance scan + 24-tag validation
│   ├── netbox_tools.py                     # 4 tools — CMDB registration and query
│   └── vault_tools.py                      # 4 tools — secret fetch, store, list
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
│   ├── Jenkinsfile.warm-cache              # Run ONCE first — pre-warms provider cache
│   ├── Jenkinsfile.log-account             # Pipeline 1 — log account registration
│   ├── Jenkinsfile.tgw                     # Pipeline 2 — Transit Gateway
│   ├── Jenkinsfile.network-infra           # Pipeline 3 — VPC, subnets, NAT, KMS, SGs
│   ├── Jenkinsfile.app-infra               # Pipeline 4 — EC2, EKS, RDS, ALB, SQS, ECR
│   └── Jenkinsfile.module-version-checker  # Weekly cron — Monday 08:00
│
├── lambda/
│   └── netbox_sync.py                      # Lambda — AWS Config → EventBridge → Netbox
│
├── setup/                                  # One-time setup scripts
│   ├── vault/vault_setup.py                # Initialise all Vault secrets
│   ├── netbox/netbox_setup.py              # Create Netbox custom fields
│   ├── aws/main.tf                         # Terraform — EventBridge + Lambda + AWS Config
│   └── terraform/
│       ├── versions.tf                     # Minimal config declaring all providers
│       └── warm_provider_cache.sh          # Downloads AWS provider into cache once
│
├── templates/
│   └── tags.json                           # All 24 mandatory tags defined
│
└── tests/
    └── test_e2e.py                         # Full test suite — all 3 phases + cache + tags
```

> The architecture diagram is saved at `../architecture.png` (root of the repo).
> To regenerate it run `python ../generate_architecture.py`.

---

## Prerequisites

Before running the MCP server, the following must be set up manually:

| Requirement | Notes |
|---|---|
| GitHub Organisation & PAT | PAT needs `repo`, `issues`, `admin:org` scopes |
| Jenkins server running | All 5 Jenkinsfiles added as pipeline jobs |
| Jenkins agent with Terraform + Checkov installed | `TF_PLUGIN_CACHE_DIR` directory must exist and be writable |
| HashiCorp Vault instance | KV v2 secrets engine enabled at `secret/infra` |
| Netbox instance | Custom fields created via `setup/netbox/netbox_setup.py` |
| AWS AFT account | `MCPAutomationRole` IAM role with Organizations + STS permissions |
| AWS Config enabled | Across all child accounts — deploy via `setup/aws/main.tf` |
| AWS RAM sharing enabled | In Shared Services account for TGW re-sharing |
| Python 3.12+ | On the machine running the MCP server |

---

## Setup

### 1. Clone and install dependencies

```bash
git clone https://github.com/your-org/mcp-infra-server.git
cd mcp-infra-server
pip install -r requirements.txt
```

### 2. Configure environment variables

```bash
cp .env.example .env
# Fill in all values — GitHub, Jenkins, AWS, Netbox, Vault
```

### 3. Initialise Vault secrets

```bash
python setup/vault/vault_setup.py
```

This reads values from your `.env` and stores them all in Vault under `secret/infra/`.

### 4. Initialise Netbox custom fields

```bash
python setup/netbox/netbox_setup.py
```

Creates the 6 custom fields required by the MCP (account_id, app_id, manager, application_type, environment, account_name).

### 5. Deploy AWS Config + EventBridge + Lambda (live sync)

```bash
cd setup/aws

# Package the Lambda function
zip netbox_sync.zip ../../lambda/netbox_sync.py

terraform init
terraform apply \
  -var="netbox_url=http://your-netbox-url:8000" \
  -var="netbox_token=your_netbox_token"
```

This deploys:
- **AWS Config recorder** — detects every resource change across child accounts
- **EventBridge rule** — fires on every Config change event
- **Lambda function** (`netbox_sync.py`) — syncs the change into Netbox automatically

### 6. Configure Jenkins pipelines

Create the following pipeline jobs in Jenkins using the Jenkinsfiles in the `jenkins/` folder:

| Jenkins Job Name | Jenkinsfile | Run Order |
|---|---|---|
| `terraform-warm-cache` | `Jenkinsfile.warm-cache` | **Run once first** — pre-warms provider cache |
| `log-account-pipeline` | `Jenkinsfile.log-account` | Pipeline 1 |
| `tgw-pipeline` | `Jenkinsfile.tgw` | Pipeline 2 |
| `network-infra-pipeline` | `Jenkinsfile.network-infra` | Pipeline 3 |
| `app-infra-pipeline` | `Jenkinsfile.app-infra` | Pipeline 4 |
| `module-version-checker` | `Jenkinsfile.module-version-checker` | Weekly cron |

Additional Jenkins setup:
- Set module version checker cron trigger to `0 8 * * 1` (every Monday 08:00)
- Add Jenkins credentials:
  - `github-token` — GitHub PAT
  - `vault-token` — HashiCorp Vault token

### 7. Pre-warm the Terraform provider cache

**Run the `terraform-warm-cache` Jenkins job once** before triggering any real pipeline.

This downloads the AWS provider into the shared cache directory on the Jenkins agent so all pipelines reuse it instead of downloading it fresh every run.

```bash
# Or run manually on the Jenkins agent:
bash setup/terraform/warm_provider_cache.sh
```

You only need to re-run this if:
- The Jenkins agent is rebuilt and the cache directory is wiped
- You upgrade to a new major AWS provider version

> Without this step, the first pipeline run for every account will still download the provider. After the first run the cache kicks in. Running the warm-up job means **zero downloads** from the very first pipeline.

### 8. Connect to Claude Code

Copy `claude_mcp_config.json` into your Claude Code MCP settings (usually `~/.claude/claude_desktop_config.json`), filling in all placeholder values:

```json
{
  "mcpServers": {
    "mcp-infra-server": {
      "command": "python",
      "args": ["server.py"],
      "cwd": "/path/to/mcp-infra-server",
      "env": {
        "GITHUB_TOKEN":                   "your_github_pat",
        "GITHUB_ORG":                     "your_org",
        "JENKINS_URL":                    "http://your-jenkins:8080",
        "JENKINS_USER":                   "your_user",
        "JENKINS_TOKEN":                  "your_token",
        "AWS_AFT_ACCOUNT_ID":             "123456789012",
        "AWS_LOG_ACCOUNT_ID":             "123456789013",
        "AWS_SHARED_SERVICES_ACCOUNT_ID": "123456789014",
        "NETBOX_URL":                     "http://your-netbox:8000",
        "NETBOX_TOKEN":                   "your_netbox_token",
        "VAULT_URL":                      "http://your-vault:8200",
        "VAULT_TOKEN":                    "your_vault_token"
      }
    }
  }
}
```

Once saved, restart Claude Code — it will discover all 33 MCP tools automatically.

---

## How the Workflow Runs

### Step 1 — App team raises a GitHub Issue

The issue must include all of the following fields:

| Field | Description |
|---|---|
| Account Name | Name for the new AWS account |
| App ID | Application identifier |
| Manager | Approving manager's name |
| Application Type | Type of application (microservice, data platform, etc.) |
| Environment | `nonprod`, `prod`, or `dr` |
| VPC CIDR | Required IP range e.g. `10.0.0.0/16` |
| Budget Approval Link | Link to approved budget document |
| Architecture Doc Link | Link to approved architecture document |

### Step 2 — Manager approves

Manager adds the `approved` label to the GitHub Issue. Claude polls for this via `github_check_approval` before doing anything else.

### Step 3 — Claude runs pre-infra

```
Approval confirmed
    → AWS account created via AFT (AWS Organizations API)
    → Account placed in correct OU (nonprod / prod / DR)
    → Account registered in Netbox with all metadata
    → Account ID and Netbox record ID posted back to GitHub Issue
```

### Step 4 — Claude runs infra pipelines in strict order

Each step has a pre-check. If a step already ran for this account it is skipped automatically — safe to re-run at any time.

```
1. Log Account Pipeline     → registers account ARN so VPC flow logs route to Log Account S3
        ↓
2. Checkov Account File     → creates compliance config, validates 24 mandatory tags
        ↓
3. TGW Pipeline             → creates TGW in Shared Services, re-shares to new account
                              configures static routes + propagation
        ↓
4. Network Infra Pipeline   → VPC · subnets · NAT · KMS · SGs · SSM · VPCE · flow logs
                              (Terraform config committed to GitHub, PR raised, merged, then applied)
        ↓
5. App Infra Pipeline       → EC2 · EKS · RDS · ALB · NLB · SQS · SNS · ECR · Secrets Manager
                              (same GitHub PR flow as network infra)
```

If any pipeline fails, Claude fetches the console logs, posts them directly to the GitHub Issue, and stops. No further steps run until the issue is resolved and the workflow is re-triggered.

### Step 5 — Post-infra

AWS Config continuously detects all resource changes and syncs them to Netbox via Lambda — no manual step needed. Claude reads the Netbox record, posts a full resource summary to the GitHub Issue, and closes it.

---

## Terraform Provider Cache

All Jenkinsfiles set `TF_PLUGIN_CACHE_DIR` to a shared persistent directory on the Jenkins agent:

```groovy
environment {
    TF_PLUGIN_CACHE_DIR = '/var/jenkins_home/terraform-plugin-cache'
}
```

This means the AWS provider is downloaded **once** and reused across all 131 account pipelines. Without this, every pipeline re-downloads the provider from scratch.

---

## 24 Mandatory Tags

Every resource must have all 24 tags at creation time. Checkov validates this before every pipeline run and blocks if any tag is missing. The full tag list is defined in `templates/tags.json`:

```
AccountId, AccountName, AppId, ApplicationType, Environment, Manager,
CostCenter, BusinessUnit, Department, Project, Owner, CreatedBy,
CreatedDate, LastModifiedBy, LastModifiedDate, Compliance, DataClassification,
BackupPolicy, MonitoringLevel, PatchGroup, SupportTeam, Region,
Terraform, TerraformModuleVersion
```

---

## Module Version Management

A Jenkins cron job runs every Monday at 08:00 and:

1. Scans the `modules` repo for changes since the last Git tag
2. If changes are detected — creates the next semantic version tag automatically (e.g. `v1.2.3` → `v1.2.4`)
3. Raises a GitHub Issue listing what changed, which files were modified, and which pipelines are still on the old version

The team reviews the issue and updates pipeline tag references accordingly.

---

## Live Inventory Sync

Netbox is kept live automatically — no manual updates needed:

```
Resource created / modified / deleted in any of the 131 AWS accounts
    → AWS Config detects the change
    → EventBridge rule fires
    → Lambda (lambda/netbox_sync.py) calls Netbox API
    → Netbox record updated in real time
```

Netbox tracks per account: AWS Account ID, Account Name, App ID, Manager, Application Type, Environment, and all resources with their current state.

---

## Running Tests

```bash
# Unit tests — mocked services, no real AWS/Jenkins calls
python -m pytest tests/test_e2e.py -v

# Integration tests — runs against real services
USE_REAL_SERVICES=true python -m pytest tests/test_e2e.py -v
```

Test coverage:
- Pre-infra: approval check, account creation, Netbox registration
- Infra pipeline: order enforcement, skip-if-already-ran, failure handling, PR flow
- Post-infra: Netbox sync, issue closure
- Provider cache: all Jenkinsfiles checked for `TF_PLUGIN_CACHE_DIR`
- Tag validation: 24 tags verified in `tags.json`
- Module version checker: semver bump logic, new version detection

---

## MCP Tools Reference

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
| `aws_create_account` | Pre | Create AWS account via AFT |
| `aws_get_account_details` | Pre | Fetch account info |
| `aws_check_account_active` | Pre | Verify account is active |
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

## Access Rules

- App teams have **read-only** access to their own application repo
- App teams have **no access** to the `network-infra` repo, even for their own account
- All Terraform state files are stored in the **AFT account S3 bucket**
- The MCP server assumes `MCPAutomationRole` in the AFT account for all AWS operations
- Vault holds all credentials — no secrets are stored in code or environment files in production

---

## Troubleshooting

| Problem | Cause | Fix |
|---|---|---|
| Provider re-downloading every pipeline run | Cache not pre-warmed or directory missing | Run the `terraform-warm-cache` Jenkins job once, or run `bash setup/terraform/warm_provider_cache.sh` on the agent manually |
| Pipeline blocked at Checkov step | Account file missing in `CHECKOV_REPO_PATH` | Run `checkov_create_account_file` tool first, then re-trigger |
| TGW pipeline fails | RAM sharing not enabled in Shared Services account | Enable AWS RAM in Shared Services and confirm new account is in the same AWS Organisation |
| Netbox not updating after resource change | EventBridge not routing to Lambda | Check CloudWatch logs for the Lambda — verify EventBridge rule ARN matches Lambda ARN |
| Claude cannot discover MCP tools | Wrong `cwd` or missing env vars in MCP config | Check `claude_mcp_config.json` — all env vars must be filled in, `cwd` must be the absolute path to `mcp-infra-server/` |
| Vault authentication error | Token expired or wrong | Re-run `setup/vault/vault_setup.py` with a fresh `VAULT_TOKEN` |
| Account creation stuck in SUCCEEDED but inactive | AWS account activation delay | Wait 2–3 minutes and call `aws_check_account_active` again — new accounts take time to become fully active |
| Network PR not auto-merging | PR has unresolved review requests | Approve the PR manually, then re-trigger the infra pipeline workflow |

---

## Related Documents

| Document | Location | Description |
|---|---|---|
| Full Plan | `../MCP_PLAN.md` | Complete architecture plan — all phases, tools, and design decisions |
| Task Tracking | `../MCP_TRACKING.md` | 87 tasks across 13 chunks — tracks build progress |
| Architecture Diagram | `../architecture.png` | Visual diagram of the full workflow |
| Diagram Generator | `../generate_architecture.py` | Run to regenerate `architecture.png` after changes |
| Original Workflow Notes | `../OU_level.txt` | Original company workflow documentation used to design this MCP |
