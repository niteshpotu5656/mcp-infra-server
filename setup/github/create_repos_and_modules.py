"""
GitHub Setup Script — creates all repos, Terraform modules, tags and Checkov structure.
Run once after filling in .env.

Usage:
    python setup/github/create_repos_and_modules.py
"""

import os
import sys
import time
import base64
from dotenv import load_dotenv
from github import Github, GithubException

# ── Load env ──────────────────────────────────────────────────────────────────
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "../../.env.example"))

TOKEN = os.environ["GITHUB_TOKEN"]
ORG   = os.environ["GITHUB_ORG"]

gh   = Github(TOKEN)
user = gh.get_user()
print(f"Authenticated as: {user.login}")

# Always create repos under the authenticated personal account
owner  = user
is_org = False
print(f"Creating repos under personal account: {user.login}\n")

# ── Helpers ───────────────────────────────────────────────────────────────────

def create_repo(name: str, description: str, private: bool = False):
    """Create a GitHub repo, skip if already exists."""
    try:
        if is_org:
            repo = owner.create_repo(
                name=name,
                description=description,
                private=private,
                auto_init=True,
            )
        else:
            repo = gh.get_user().create_repo(
                name=name,
                description=description,
                private=private,
                auto_init=True,
            )
        print(f"  [CREATED] {ORG}/{name}")
        time.sleep(2)  # avoid secondary rate limit
        return repo
    except GithubException as e:
        if e.status == 422:
            print(f"  [EXISTS]  {ORG}/{name} — skipping")
            return owner.get_repo(name) if is_org else gh.get_user().get_repo(name)
        raise


def push_file(repo, path: str, content: str, message: str = None):
    """Create or update a file in a repo."""
    msg = message or f"feat: add {path}"
    try:
        existing = repo.get_contents(path)
        repo.update_file(path, msg, content, existing.sha)
    except GithubException:
        repo.create_file(path, msg, content)
    time.sleep(0.3)


def create_tag(repo, tag: str, message: str):
    """Create an annotated Git tag on HEAD of main/master."""
    try:
        ref = repo.get_git_ref("heads/main")
    except Exception:
        ref = repo.get_git_ref("heads/master")
    sha = ref.object.sha
    tag_obj = repo.create_git_tag(tag=tag, message=message, object=sha, type="commit")
    try:
        repo.create_git_ref(ref=f"refs/tags/{tag}", sha=tag_obj.sha)
        print(f"  [TAG]     {tag} created on {repo.name}")
    except GithubException:
        print(f"  [TAG]     {tag} already exists on {repo.name}")


# ══════════════════════════════════════════════════════════════════════════════
# STEP 1 — Create all repos
# ══════════════════════════════════════════════════════════════════════════════
print("=" * 60)
print("STEP 1 — Creating GitHub repositories")
print("=" * 60)

repos = {}
repo_defs = [
    ("modules",          "Terraform modules for all AWS infra — versioned with tags"),
    ("network-infra",    "Network infrastructure per account — VPC, subnets, TGW, NAT"),
    ("checkov-configs",  "Checkov account config files for compliance scanning"),
    ("infra-requests",   "Infrastructure requests — app teams raise GitHub Issues here"),
    ("mcp-infra-server", "MCP server that automates end-to-end AWS infra creation"),
]
for name, desc in repo_defs:
    repos[name] = create_repo(name, desc, private=False)

# ══════════════════════════════════════════════════════════════════════════════
# STEP 2 — Build Terraform modules in the modules repo
# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("STEP 2 — Creating Terraform modules")
print("=" * 60)

repo_mod = repos["modules"]

# ── Shared tags variable (used by every module) ───────────────────────────────
TAGS_VARIABLE = '''
variable "tags" {
  description = "All 24 mandatory tags that must be applied to every resource."
  type        = map(string)
  validation {
    condition = alltrue([
      for tag in [
        "AccountId", "AccountName", "AppId", "ApplicationType",
        "Environment", "Manager", "CostCenter", "BusinessUnit",
        "Department", "Project", "Owner", "CreatedBy", "CreatedDate",
        "LastModifiedBy", "LastModifiedDate", "Compliance",
        "DataClassification", "BackupPolicy", "MonitoringLevel",
        "PatchGroup", "SupportTeam", "Region", "Terraform",
        "TerraformModuleVersion"
      ] : contains(keys(var.tags), tag)
    ])
    error_message = "All 24 mandatory tags must be provided."
  }
}
'''

# ── Module definitions ────────────────────────────────────────────────────────
# Each entry: (folder_path, variables_tf, main_tf, outputs_tf)

MODULES = {

  # ── NETWORK ────────────────────────────────────────────────────────────────

  "network/vpc": {
    "variables.tf": f'''variable "vpc_cidr"     {{ description = "CIDR block for the VPC" }}
variable "account_name"  {{ description = "AWS account name" }}
variable "environment"   {{ description = "Environment: nonprod | prod | dr" }}
{TAGS_VARIABLE}''',
    "main.tf": '''resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags = merge(var.tags, {
    Name = "${{var.account_name}}-${{var.environment}}-vpc"
  })
}''',
    "outputs.tf": '''output "vpc_id"   { value = aws_vpc.main.id }
output "vpc_cidr" { value = aws_vpc.main.cidr_block }''',
  },

  "network/subnets": {
    "variables.tf": f'''variable "vpc_id"              {{ description = "VPC ID" }}
variable "public_cidrs"        {{ type = list(string); description = "Public subnet CIDRs" }}
variable "private_cidrs"       {{ type = list(string); description = "Private subnet CIDRs" }}
variable "db_cidrs"            {{ type = list(string); description = "DB subnet CIDRs" }}
variable "availability_zones"  {{ type = list(string); description = "AZs to deploy subnets" }}
variable "account_name"        {{ description = "AWS account name" }}
variable "environment"         {{ description = "Environment" }}
{TAGS_VARIABLE}''',
    "main.tf": '''resource "aws_subnet" "public" {
  count             = length(var.public_cidrs)
  vpc_id            = var.vpc_id
  cidr_block        = var.public_cidrs[count.index]
  availability_zone = var.availability_zones[count.index]
  map_public_ip_on_launch = true
  tags = merge(var.tags, {
    Name = "${{var.account_name}}-${{var.environment}}-public-${{count.index + 1}}"
    Tier = "public"
  })
}

resource "aws_subnet" "private" {
  count             = length(var.private_cidrs)
  vpc_id            = var.vpc_id
  cidr_block        = var.private_cidrs[count.index]
  availability_zone = var.availability_zones[count.index]
  tags = merge(var.tags, {
    Name = "${{var.account_name}}-${{var.environment}}-private-${{count.index + 1}}"
    Tier = "private"
  })
}

resource "aws_subnet" "db" {
  count             = length(var.db_cidrs)
  vpc_id            = var.vpc_id
  cidr_block        = var.db_cidrs[count.index]
  availability_zone = var.availability_zones[count.index]
  tags = merge(var.tags, {
    Name = "${{var.account_name}}-${{var.environment}}-db-${{count.index + 1}}"
    Tier = "db"
  })
}

resource "aws_internet_gateway" "main" {
  vpc_id = var.vpc_id
  tags   = merge(var.tags, { Name = "${{var.account_name}}-${{var.environment}}-igw" })
}

resource "aws_route_table" "public" {
  vpc_id = var.vpc_id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }
  tags = merge(var.tags, { Name = "${{var.account_name}}-${{var.environment}}-public-rt" })
}

resource "aws_route_table_association" "public" {
  count          = length(aws_subnet.public)
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}''',
    "outputs.tf": '''output "public_subnet_ids"  { value = aws_subnet.public[*].id }
output "private_subnet_ids" { value = aws_subnet.private[*].id }
output "db_subnet_ids"      { value = aws_subnet.db[*].id }
output "igw_id"             { value = aws_internet_gateway.main.id }''',
  },

  "network/nat": {
    "variables.tf": f'''variable "public_subnet_id" {{ description = "Public subnet for NAT gateway" }}
variable "private_route_table_ids" {{ type = list(string); description = "Private route table IDs" }}
variable "account_name" {{ description = "AWS account name" }}
variable "environment"  {{ description = "Environment" }}
{TAGS_VARIABLE}''',
    "main.tf": '''resource "aws_eip" "nat" {
  domain = "vpc"
  tags   = merge(var.tags, { Name = "${{var.account_name}}-${{var.environment}}-nat-eip" })
}

resource "aws_nat_gateway" "main" {
  allocation_id = aws_eip.nat.id
  subnet_id     = var.public_subnet_id
  tags          = merge(var.tags, { Name = "${{var.account_name}}-${{var.environment}}-nat" })
  depends_on    = [aws_eip.nat]
}

resource "aws_route" "private_nat" {
  count                  = length(var.private_route_table_ids)
  route_table_id         = var.private_route_table_ids[count.index]
  destination_cidr_block = "0.0.0.0/0"
  nat_gateway_id         = aws_nat_gateway.main.id
}''',
    "outputs.tf": '''output "nat_gateway_id" { value = aws_nat_gateway.main.id }
output "nat_eip"        { value = aws_eip.nat.public_ip }''',
  },

  "network/kms": {
    "variables.tf": f'''variable "account_name"      {{ description = "AWS account name" }}
variable "environment"        {{ description = "Environment" }}
variable "deletion_window"    {{ default = 30; description = "Key deletion window in days" }}
variable "key_administrators" {{ type = list(string); description = "IAM ARNs for key admins" }}
{TAGS_VARIABLE}''',
    "main.tf": '''data "aws_caller_identity" "current" {{}}

resource "aws_kms_key" "main" {
  description             = "${{var.account_name}}-${{var.environment}} KMS key"
  deletion_window_in_days = var.deletion_window
  enable_key_rotation     = true
  tags                    = var.tags
  policy = jsonencode({{
    Version = "2012-10-17"
    Statement = [
      {{
        Sid    = "Enable IAM User Permissions"
        Effect = "Allow"
        Principal = {{ AWS = "arn:aws:iam::${{data.aws_caller_identity.current.account_id}}:root" }}
        Action   = "kms:*"
        Resource = "*"
      }},
      {{
        Sid    = "Allow Key Administrators"
        Effect = "Allow"
        Principal = {{ AWS = var.key_administrators }}
        Action   = ["kms:Create*","kms:Describe*","kms:Enable*","kms:List*","kms:Put*","kms:Update*","kms:Revoke*","kms:Disable*","kms:Get*","kms:Delete*","kms:ScheduleKeyDeletion","kms:CancelKeyDeletion"]
        Resource = "*"
      }}
    ]
  }})
}

resource "aws_kms_alias" "main" {
  name          = "alias/${{var.account_name}}-${{var.environment}}"
  target_key_id = aws_kms_key.main.key_id
}''',
    "outputs.tf": '''output "kms_key_id"  { value = aws_kms_key.main.key_id }
output "kms_key_arn" { value = aws_kms_key.main.arn }
output "kms_alias"   { value = aws_kms_alias.main.name }''',
  },

  "network/security-group": {
    "variables.tf": f'''variable "vpc_id"       {{ description = "VPC ID" }}
variable "name"         {{ description = "Security group name" }}
variable "description"  {{ description = "Security group description" }}
variable "ingress_rules" {{
  type = list(object({{ from_port = number, to_port = number, protocol = string, cidr_blocks = list(string), description = string }}))
  default = []
}}
variable "egress_rules" {{
  type = list(object({{ from_port = number, to_port = number, protocol = string, cidr_blocks = list(string), description = string }}))
  default = [{{ from_port = 0, to_port = 0, protocol = "-1", cidr_blocks = ["0.0.0.0/0"], description = "Allow all outbound" }}]
}}
{TAGS_VARIABLE}''',
    "main.tf": '''resource "aws_security_group" "main" {
  name        = var.name
  description = var.description
  vpc_id      = var.vpc_id
  tags        = merge(var.tags, {{ Name = var.name }})

  dynamic "ingress" {{
    for_each = var.ingress_rules
    content {{
      from_port   = ingress.value.from_port
      to_port     = ingress.value.to_port
      protocol    = ingress.value.protocol
      cidr_blocks = ingress.value.cidr_blocks
      description = ingress.value.description
    }}
  }}

  dynamic "egress" {{
    for_each = var.egress_rules
    content {{
      from_port   = egress.value.from_port
      to_port     = egress.value.to_port
      protocol    = egress.value.protocol
      cidr_blocks = egress.value.cidr_blocks
      description = egress.value.description
    }}
  }}
}''',
    "outputs.tf": '''output "sg_id"  { value = aws_security_group.main.id }
output "sg_arn" { value = aws_security_group.main.arn }''',
  },

  "network/tgw": {
    "variables.tf": f'''variable "vpc_id"           {{ description = "VPC ID to attach to TGW" }}
variable "subnet_ids"       {{ type = list(string); description = "Subnet IDs for TGW attachment" }}
variable "tgw_id"           {{ description = "Transit Gateway ID from Shared Services" }}
variable "static_routes"    {{ type = list(string); default = []; description = "Static CIDR routes to propagate" }}
variable "account_name"     {{ description = "AWS account name" }}
variable "environment"      {{ description = "Environment" }}
{TAGS_VARIABLE}''',
    "main.tf": '''resource "aws_ec2_transit_gateway_vpc_attachment" "main" {
  transit_gateway_id = var.tgw_id
  vpc_id             = var.vpc_id
  subnet_ids         = var.subnet_ids
  tags               = merge(var.tags, {{
    Name = "${{var.account_name}}-${{var.environment}}-tgw-attachment"
  }})
}

resource "aws_ec2_transit_gateway_route" "static" {
  count                          = length(var.static_routes)
  transit_gateway_route_table_id = data.aws_ec2_transit_gateway_route_table.main.id
  destination_cidr_block         = var.static_routes[count.index]
  transit_gateway_attachment_id  = aws_ec2_transit_gateway_vpc_attachment.main.id
}

data "aws_ec2_transit_gateway_route_table" "main" {{
  filter {{
    name   = "transit-gateway-id"
    values = [var.tgw_id]
  }}
  filter {{
    name   = "default-association-route-table"
    values = ["true"]
  }}
}}''',
    "outputs.tf": '''output "tgw_attachment_id" { value = aws_ec2_transit_gateway_vpc_attachment.main.id }''',
  },

  "network/ssm": {
    "variables.tf": f'''variable "vpc_id"       {{ description = "VPC ID" }}
variable "subnet_ids"   {{ type = list(string); description = "Subnet IDs for SSM endpoints" }}
variable "sg_id"        {{ description = "Security group for SSM endpoints" }}
variable "account_name" {{ description = "AWS account name" }}
variable "environment"  {{ description = "Environment" }}
{TAGS_VARIABLE}''',
    "main.tf": '''resource "aws_vpc_endpoint" "ssm" {
  vpc_id              = var.vpc_id
  service_name        = "com.amazonaws.${{data.aws_region.current.name}}.ssm"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = var.subnet_ids
  security_group_ids  = [var.sg_id]
  private_dns_enabled = true
  tags = merge(var.tags, {{ Name = "${{var.account_name}}-${{var.environment}}-ssm-endpoint" }})
}

resource "aws_vpc_endpoint" "ssmmessages" {
  vpc_id              = var.vpc_id
  service_name        = "com.amazonaws.${{data.aws_region.current.name}}.ssmmessages"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = var.subnet_ids
  security_group_ids  = [var.sg_id]
  private_dns_enabled = true
  tags = merge(var.tags, {{ Name = "${{var.account_name}}-${{var.environment}}-ssmmessages-endpoint" }})
}

resource "aws_vpc_endpoint" "ec2messages" {
  vpc_id              = var.vpc_id
  service_name        = "com.amazonaws.${{data.aws_region.current.name}}.ec2messages"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = var.subnet_ids
  security_group_ids  = [var.sg_id]
  private_dns_enabled = true
  tags = merge(var.tags, {{ Name = "${{var.account_name}}-${{var.environment}}-ec2messages-endpoint" }})
}

data "aws_region" "current" {{}}''',
    "outputs.tf": '''output "ssm_endpoint_id"         { value = aws_vpc_endpoint.ssm.id }
output "ssmmessages_endpoint_id" { value = aws_vpc_endpoint.ssmmessages.id }
output "ec2messages_endpoint_id" { value = aws_vpc_endpoint.ec2messages.id }''',
  },

  "network/vpce": {
    "variables.tf": f'''variable "vpc_id"       {{ description = "VPC ID" }}
variable "subnet_ids"   {{ type = list(string); description = "Subnet IDs" }}
variable "sg_id"        {{ description = "Security group ID" }}
variable "route_table_ids" {{ type = list(string); description = "Route table IDs for gateway endpoints" }}
variable "account_name" {{ description = "AWS account name" }}
variable "environment"  {{ description = "Environment" }}
{TAGS_VARIABLE}''',
    "main.tf": '''data "aws_region" "current" {{}}

resource "aws_vpc_endpoint" "s3" {
  vpc_id            = var.vpc_id
  service_name      = "com.amazonaws.${{data.aws_region.current.name}}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = var.route_table_ids
  tags              = merge(var.tags, {{ Name = "${{var.account_name}}-${{var.environment}}-s3-vpce" }})
}

resource "aws_vpc_endpoint" "ecr_api" {
  vpc_id              = var.vpc_id
  service_name        = "com.amazonaws.${{data.aws_region.current.name}}.ecr.api"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = var.subnet_ids
  security_group_ids  = [var.sg_id]
  private_dns_enabled = true
  tags                = merge(var.tags, {{ Name = "${{var.account_name}}-${{var.environment}}-ecr-api-vpce" }})
}

resource "aws_vpc_endpoint" "ecr_dkr" {
  vpc_id              = var.vpc_id
  service_name        = "com.amazonaws.${{data.aws_region.current.name}}.ecr.dkr"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = var.subnet_ids
  security_group_ids  = [var.sg_id]
  private_dns_enabled = true
  tags                = merge(var.tags, {{ Name = "${{var.account_name}}-${{var.environment}}-ecr-dkr-vpce" }})
}

resource "aws_vpc_endpoint" "secretsmanager" {
  vpc_id              = var.vpc_id
  service_name        = "com.amazonaws.${{data.aws_region.current.name}}.secretsmanager"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = var.subnet_ids
  security_group_ids  = [var.sg_id]
  private_dns_enabled = true
  tags                = merge(var.tags, {{ Name = "${{var.account_name}}-${{var.environment}}-secretsmanager-vpce" }})
}''',
    "outputs.tf": '''output "s3_vpce_id"             { value = aws_vpc_endpoint.s3.id }
output "ecr_api_vpce_id"        { value = aws_vpc_endpoint.ecr_api.id }
output "ecr_dkr_vpce_id"        { value = aws_vpc_endpoint.ecr_dkr.id }
output "secretsmanager_vpce_id" { value = aws_vpc_endpoint.secretsmanager.id }''',
  },

  "network/vpc-flow-logs": {
    "variables.tf": f'''variable "vpc_id"          {{ description = "VPC ID" }}
variable "log_bucket_arn"  {{ description = "S3 ARN of centralised Log Account bucket" }}
variable "account_name"    {{ description = "AWS account name" }}
variable "environment"     {{ description = "Environment" }}
{TAGS_VARIABLE}''',
    "main.tf": '''resource "aws_iam_role" "flow_log" {
  name = "${{var.account_name}}-${{var.environment}}-flow-log-role"
  assume_role_policy = jsonencode({{
    Version = "2012-10-17"
    Statement = [{{
      Effect    = "Allow"
      Principal = {{ Service = "vpc-flow-logs.amazonaws.com" }}
      Action    = "sts:AssumeRole"
    }}]
  }})
  tags = var.tags
}

resource "aws_iam_role_policy" "flow_log" {
  name   = "flow-log-s3-policy"
  role   = aws_iam_role.flow_log.id
  policy = jsonencode({{
    Version = "2012-10-17"
    Statement = [{{
      Effect   = "Allow"
      Action   = ["s3:PutObject"]
      Resource = "${{var.log_bucket_arn}}/vpc-flow-logs/*"
    }}]
  }})
}

resource "aws_flow_log" "main" {
  vpc_id               = var.vpc_id
  traffic_type         = "ALL"
  log_destination_type = "s3"
  log_destination      = "${{var.log_bucket_arn}}/vpc-flow-logs/"
  iam_role_arn         = aws_iam_role.flow_log.arn
  tags                 = merge(var.tags, {{ Name = "${{var.account_name}}-${{var.environment}}-flow-log" }})
}''',
    "outputs.tf": '''output "flow_log_id"      { value = aws_flow_log.main.id }
output "flow_log_role_arn" { value = aws_iam_role.flow_log.arn }''',
  },

  # ── APP INFRA ──────────────────────────────────────────────────────────────

  "app/ec2": {
    "variables.tf": f'''variable "name"            {{ description = "EC2 instance name" }}
variable "ami_id"          {{ description = "AMI ID (shared from Prod Shared Services)" }}
variable "instance_type"   {{ default = "t3.medium" }}
variable "subnet_id"       {{ description = "Subnet to launch instance in" }}
variable "sg_ids"          {{ type = list(string); description = "Security group IDs" }}
variable "kms_key_arn"     {{ description = "KMS key ARN for EBS encryption" }}
variable "iam_role_name"   {{ description = "IAM role name for EC2 instance profile" }}
variable "user_data"       {{ default = "" }}
variable "account_name"    {{ description = "AWS account name" }}
variable "environment"     {{ description = "Environment" }}
{TAGS_VARIABLE}''',
    "main.tf": '''resource "aws_iam_instance_profile" "main" {
  name = "${{var.name}}-profile"
  role = var.iam_role_name
  tags = var.tags
}

resource "aws_instance" "main" {
  ami                    = var.ami_id
  instance_type          = var.instance_type
  subnet_id              = var.subnet_id
  vpc_security_group_ids = var.sg_ids
  iam_instance_profile   = aws_iam_instance_profile.main.name
  user_data              = var.user_data
  monitoring             = true

  root_block_device {{
    encrypted   = true
    kms_key_id  = var.kms_key_arn
    volume_type = "gp3"
  }}

  metadata_options {{
    http_tokens = "required"
  }}

  tags = merge(var.tags, {{ Name = var.name }})
}''',
    "outputs.tf": '''output "instance_id"         { value = aws_instance.main.id }
output "private_ip"          { value = aws_instance.main.private_ip }
output "instance_profile_arn"{ value = aws_iam_instance_profile.main.arn }''',
  },

  "app/eks": {
    "variables.tf": f'''variable "cluster_name"    {{ description = "EKS cluster name" }}
variable "k8s_version"     {{ default = "1.29" }}
variable "subnet_ids"      {{ type = list(string) }}
variable "sg_id"           {{ description = "Control plane security group" }}
variable "kms_key_arn"     {{ description = "KMS key for secrets encryption" }}
variable "node_instance_type" {{ default = "t3.medium" }}
variable "node_desired"    {{ default = 2 }}
variable "node_min"        {{ default = 1 }}
variable "node_max"        {{ default = 4 }}
variable "account_name"    {{ description = "AWS account name" }}
variable "environment"     {{ description = "Environment" }}
{TAGS_VARIABLE}''',
    "main.tf": '''resource "aws_iam_role" "cluster" {{
  name = "${{var.cluster_name}}-cluster-role"
  assume_role_policy = jsonencode({{
    Version = "2012-10-17"
    Statement = [{{
      Effect    = "Allow"
      Principal = {{ Service = "eks.amazonaws.com" }}
      Action    = "sts:AssumeRole"
    }}]
  }})
  tags = var.tags
}}

resource "aws_iam_role_policy_attachment" "cluster_policy" {{
  role       = aws_iam_role.cluster.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSClusterPolicy"
}}

resource "aws_eks_cluster" "main" {{
  name     = var.cluster_name
  version  = var.k8s_version
  role_arn = aws_iam_role.cluster.arn

  vpc_config {{
    subnet_ids              = var.subnet_ids
    security_group_ids      = [var.sg_id]
    endpoint_private_access = true
    endpoint_public_access  = false
  }}

  encryption_config {{
    resources = ["secrets"]
    provider {{ key_arn = var.kms_key_arn }}
  }}

  tags = merge(var.tags, {{ Name = var.cluster_name }})
  depends_on = [aws_iam_role_policy_attachment.cluster_policy]
}}

resource "aws_iam_role" "node" {{
  name = "${{var.cluster_name}}-node-role"
  assume_role_policy = jsonencode({{
    Version = "2012-10-17"
    Statement = [{{
      Effect    = "Allow"
      Principal = {{ Service = "ec2.amazonaws.com" }}
      Action    = "sts:AssumeRole"
    }}]
  }})
  tags = var.tags
}}

resource "aws_eks_node_group" "main" {{
  cluster_name    = aws_eks_cluster.main.name
  node_group_name = "${{var.cluster_name}}-node-group"
  node_role_arn   = aws_iam_role.node.arn
  subnet_ids      = var.subnet_ids
  instance_types  = [var.node_instance_type]

  scaling_config {{
    desired_size = var.node_desired
    min_size     = var.node_min
    max_size     = var.node_max
  }}

  tags = merge(var.tags, {{ Name = "${{var.cluster_name}}-node-group" }})
}}''',
    "outputs.tf": '''output "cluster_name"     { value = aws_eks_cluster.main.name }
output "cluster_endpoint" { value = aws_eks_cluster.main.endpoint }
output "cluster_arn"      { value = aws_eks_cluster.main.arn }''',
  },

  "app/rds": {
    "variables.tf": f'''variable "identifier"      {{ description = "RDS instance identifier" }}
variable "engine"          {{ default = "mysql" }}
variable "engine_version"  {{ default = "8.0" }}
variable "instance_class"  {{ default = "db.t3.medium" }}
variable "allocated_storage" {{ default = 20 }}
variable "db_name"         {{ description = "Initial database name" }}
variable "username"        {{ description = "Master username" }}
variable "password"        {{ description = "Master password (store in Vault)" }}
variable "subnet_ids"      {{ type = list(string) }}
variable "sg_ids"          {{ type = list(string) }}
variable "kms_key_arn"     {{ description = "KMS key for storage encryption" }}
variable "account_name"    {{ description = "AWS account name" }}
variable "environment"     {{ description = "Environment" }}
{TAGS_VARIABLE}''',
    "main.tf": '''resource "aws_db_subnet_group" "main" {{
  name       = "${{var.identifier}}-subnet-group"
  subnet_ids = var.subnet_ids
  tags       = merge(var.tags, {{ Name = "${{var.identifier}}-subnet-group" }})
}}

resource "aws_db_instance" "main" {{
  identifier              = var.identifier
  engine                  = var.engine
  engine_version          = var.engine_version
  instance_class          = var.instance_class
  allocated_storage       = var.allocated_storage
  storage_type            = "gp3"
  storage_encrypted       = true
  kms_key_id              = var.kms_key_arn
  db_name                 = var.db_name
  username                = var.username
  password                = var.password
  db_subnet_group_name    = aws_db_subnet_group.main.name
  vpc_security_group_ids  = var.sg_ids
  multi_az                = var.environment == "prod" ? true : false
  backup_retention_period = var.environment == "prod" ? 7 : 1
  deletion_protection     = var.environment == "prod" ? true : false
  skip_final_snapshot     = var.environment == "prod" ? false : true
  tags                    = merge(var.tags, {{ Name = var.identifier }})
}}''',
    "outputs.tf": '''output "db_endpoint" { value = aws_db_instance.main.endpoint }
output "db_id"       { value = aws_db_instance.main.id }
output "db_arn"      { value = aws_db_instance.main.arn }''',
  },

  "app/alb": {
    "variables.tf": f'''variable "name"        {{ description = "ALB name" }}
variable "internal"    {{ default = false }}
variable "subnet_ids"  {{ type = list(string) }}
variable "sg_ids"      {{ type = list(string) }}
variable "vpc_id"      {{ description = "VPC ID for target group" }}
variable "target_port" {{ default = 80 }}
variable "account_name" {{ description = "AWS account name" }}
variable "environment"  {{ description = "Environment" }}
{TAGS_VARIABLE}''',
    "main.tf": '''resource "aws_lb" "main" {{
  name               = var.name
  load_balancer_type = "application"
  internal           = var.internal
  subnets            = var.subnet_ids
  security_groups    = var.sg_ids
  tags               = merge(var.tags, {{ Name = var.name }})
}}

resource "aws_lb_target_group" "main" {{
  name     = "${{var.name}}-tg"
  port     = var.target_port
  protocol = "HTTP"
  vpc_id   = var.vpc_id
  health_check {{
    enabled             = true
    healthy_threshold   = 2
    unhealthy_threshold = 3
    interval            = 30
  }}
  tags = merge(var.tags, {{ Name = "${{var.name}}-tg" }})
}}

resource "aws_lb_listener" "main" {{
  load_balancer_arn = aws_lb.main.arn
  port              = 80
  protocol          = "HTTP"
  default_action {{
    type             = "forward"
    target_group_arn = aws_lb_target_group.main.arn
  }}
}}''',
    "outputs.tf": '''output "alb_arn"            { value = aws_lb.main.arn }
output "alb_dns_name"       { value = aws_lb.main.dns_name }
output "target_group_arn"   { value = aws_lb_target_group.main.arn }''',
  },

  "app/nlb": {
    "variables.tf": f'''variable "name"        {{ description = "NLB name" }}
variable "internal"    {{ default = true }}
variable "subnet_ids"  {{ type = list(string) }}
variable "vpc_id"      {{ description = "VPC ID" }}
variable "target_port" {{ default = 443 }}
variable "account_name" {{ description = "AWS account name" }}
variable "environment"  {{ description = "Environment" }}
{TAGS_VARIABLE}''',
    "main.tf": '''resource "aws_lb" "main" {{
  name               = var.name
  load_balancer_type = "network"
  internal           = var.internal
  subnets            = var.subnet_ids
  tags               = merge(var.tags, {{ Name = var.name }})
}}

resource "aws_lb_target_group" "main" {{
  name     = "${{var.name}}-tg"
  port     = var.target_port
  protocol = "TCP"
  vpc_id   = var.vpc_id
  tags     = merge(var.tags, {{ Name = "${{var.name}}-tg" }})
}}

resource "aws_lb_listener" "main" {{
  load_balancer_arn = aws_lb.main.arn
  port              = var.target_port
  protocol          = "TCP"
  default_action {{
    type             = "forward"
    target_group_arn = aws_lb_target_group.main.arn
  }}
}}''',
    "outputs.tf": '''output "nlb_arn"          { value = aws_lb.main.arn }
output "nlb_dns_name"     { value = aws_lb.main.dns_name }
output "target_group_arn" { value = aws_lb_target_group.main.arn }''',
  },

  "app/sqs": {
    "variables.tf": f'''variable "name"           {{ description = "SQS queue name" }}
variable "fifo"           {{ default = false }}
variable "kms_key_arn"    {{ description = "KMS key for encryption" }}
variable "dlq_enabled"    {{ default = true }}
variable "max_receive_count" {{ default = 3 }}
variable "account_name"   {{ description = "AWS account name" }}
variable "environment"    {{ description = "Environment" }}
{TAGS_VARIABLE}''',
    "main.tf": '''resource "aws_sqs_queue" "dlq" {{
  count                     = var.dlq_enabled ? 1 : 0
  name                      = "${{var.name}}-dlq${{var.fifo ? ".fifo" : ""}}"
  fifo_queue                = var.fifo
  kms_master_key_id         = var.kms_key_arn
  tags                      = merge(var.tags, {{ Name = "${{var.name}}-dlq" }})
}}

resource "aws_sqs_queue" "main" {{
  name                      = "${{var.name}}${{var.fifo ? ".fifo" : ""}}"
  fifo_queue                = var.fifo
  kms_master_key_id         = var.kms_key_arn
  redrive_policy            = var.dlq_enabled ? jsonencode({{
    deadLetterTargetArn = aws_sqs_queue.dlq[0].arn
    maxReceiveCount     = var.max_receive_count
  }}) : null
  tags = merge(var.tags, {{ Name = var.name }})
}}''',
    "outputs.tf": '''output "queue_url" { value = aws_sqs_queue.main.url }
output "queue_arn" { value = aws_sqs_queue.main.arn }
output "dlq_arn"   { value = var.dlq_enabled ? aws_sqs_queue.dlq[0].arn : "" }''',
  },

  "app/sns": {
    "variables.tf": f'''variable "name"        {{ description = "SNS topic name" }}
variable "kms_key_arn" {{ description = "KMS key for encryption" }}
variable "account_name" {{ description = "AWS account name" }}
variable "environment"  {{ description = "Environment" }}
{TAGS_VARIABLE}''',
    "main.tf": '''resource "aws_sns_topic" "main" {{
  name              = var.name
  kms_master_key_id = var.kms_key_arn
  tags              = merge(var.tags, {{ Name = var.name }})
}}''',
    "outputs.tf": '''output "topic_arn"  { value = aws_sns_topic.main.arn }
output "topic_name" { value = aws_sns_topic.main.name }''',
  },

  "app/eventbridge": {
    "variables.tf": f'''variable "bus_name"     {{ description = "EventBridge bus name" }}
variable "rule_name"    {{ description = "EventBridge rule name" }}
variable "event_pattern" {{ description = "JSON event pattern" }}
variable "target_arn"   {{ description = "Target resource ARN (Lambda, SQS, etc.)" }}
variable "account_name" {{ description = "AWS account name" }}
variable "environment"  {{ description = "Environment" }}
{TAGS_VARIABLE}''',
    "main.tf": '''resource "aws_cloudwatch_event_bus" "main" {{
  name = var.bus_name
  tags = merge(var.tags, {{ Name = var.bus_name }})
}}

resource "aws_cloudwatch_event_rule" "main" {{
  name           = var.rule_name
  event_bus_name = aws_cloudwatch_event_bus.main.name
  event_pattern  = var.event_pattern
  tags           = merge(var.tags, {{ Name = var.rule_name }})
}}

resource "aws_cloudwatch_event_target" "main" {{
  rule           = aws_cloudwatch_event_rule.main.name
  event_bus_name = aws_cloudwatch_event_bus.main.name
  target_id      = "main-target"
  arn            = var.target_arn
}}''',
    "outputs.tf": '''output "bus_arn"  { value = aws_cloudwatch_event_bus.main.arn }
output "rule_arn" { value = aws_cloudwatch_event_rule.main.arn }''',
  },

  "app/ecr": {
    "variables.tf": f'''variable "name"           {{ description = "ECR repository name" }}
variable "kms_key_arn"    {{ description = "KMS key for encryption" }}
variable "image_count_limit" {{ default = 30; description = "Max images to keep per repo" }}
variable "account_name"   {{ description = "AWS account name" }}
variable "environment"    {{ description = "Environment" }}
{TAGS_VARIABLE}''',
    "main.tf": '''resource "aws_ecr_repository" "main" {{
  name                 = var.name
  image_tag_mutability = "IMMUTABLE"
  image_scanning_configuration {{
    scan_on_push = true
  }}
  encryption_configuration {{
    encryption_type = "KMS"
    kms_key         = var.kms_key_arn
  }}
  tags = merge(var.tags, {{ Name = var.name }})
}}

resource "aws_ecr_lifecycle_policy" "main" {{
  repository = aws_ecr_repository.main.name
  policy = jsonencode({{
    rules = [{{
      rulePriority = 1
      description  = "Keep last ${{var.image_count_limit}} images"
      selection = {{
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = var.image_count_limit
      }}
      action = {{ type = "expire" }}
    }}]
  }})
}}''',
    "outputs.tf": '''output "repository_url" { value = aws_ecr_repository.main.repository_url }
output "repository_arn" { value = aws_ecr_repository.main.arn }''',
  },

  "app/secrets-manager": {
    "variables.tf": f'''variable "name"        {{ description = "Secret name" }}
variable "description" {{ description = "Secret description" }}
variable "secret_value" {{ description = "Secret value (JSON string)" }}
variable "kms_key_arn" {{ description = "KMS key for encryption" }}
variable "rotation_days" {{ default = 90 }}
variable "account_name" {{ description = "AWS account name" }}
variable "environment"  {{ description = "Environment" }}
{TAGS_VARIABLE}''',
    "main.tf": '''resource "aws_secretsmanager_secret" "main" {{
  name                    = "${{var.account_name}}/${{var.environment}}/${{var.name}}"
  description             = var.description
  kms_key_id              = var.kms_key_arn
  recovery_window_in_days = var.environment == "prod" ? 30 : 7
  tags                    = merge(var.tags, {{ Name = var.name }})
}}

resource "aws_secretsmanager_secret_version" "main" {{
  secret_id     = aws_secretsmanager_secret.main.id
  secret_string = var.secret_value
}}''',
    "outputs.tf": '''output "secret_arn"  { value = aws_secretsmanager_secret.main.arn }
output "secret_name" { value = aws_secretsmanager_secret.main.name }''',
  },
}

# ── Push all modules ──────────────────────────────────────────────────────────
total = len(MODULES)
for i, (module_path, files) in enumerate(MODULES.items(), 1):
    print(f"  [{i}/{total}] modules/{module_path}")
    for filename, content in files.items():
        push_file(repo_mod, f"{module_path}/{filename}", content,
                  f"feat: add {module_path}/{filename}")

# Root README for modules repo
modules_readme = """# Terraform Modules

Reusable Terraform modules for all AWS infrastructure.
Versioned with Git tags (e.g. v1.0.0).

## Network Modules
| Module | Resources |
|---|---|
| `network/vpc` | aws_vpc |
| `network/subnets` | aws_subnet (public/private/db), IGW, route tables |
| `network/nat` | aws_nat_gateway, aws_eip |
| `network/kms` | aws_kms_key, aws_kms_alias |
| `network/security-group` | aws_security_group |
| `network/tgw` | TGW VPC attachment, static routes |
| `network/ssm` | SSM, SSMMessages, EC2Messages VPC endpoints |
| `network/vpce` | S3, ECR API/DKR, Secrets Manager VPC endpoints |
| `network/vpc-flow-logs` | aws_flow_log → centralised Log Account S3 |

## App Infra Modules
| Module | Resources |
|---|---|
| `app/ec2` | aws_instance, IAM instance profile |
| `app/eks` | aws_eks_cluster, aws_eks_node_group |
| `app/rds` | aws_db_instance, aws_db_subnet_group |
| `app/alb` | Application Load Balancer, target group, listener |
| `app/nlb` | Network Load Balancer, target group, listener |
| `app/sqs` | aws_sqs_queue + DLQ |
| `app/sns` | aws_sns_topic |
| `app/eventbridge` | Event bus, rule, target |
| `app/ecr` | aws_ecr_repository + lifecycle policy |
| `app/secrets-manager` | aws_secretsmanager_secret + version |

## Versioning
All modules are referenced by Git tag in pipelines:
```hcl
source = "git::https://github.com/AI-with-Nitesh/modules//network/vpc?ref=v1.0.0"
```

## Mandatory Tags
Every module enforces all 24 mandatory tags via input validation.
"""
push_file(repo_mod, "README.md", modules_readme, "docs: add modules README")

print(f"\n  All {total} modules pushed.")

# ── Tag the modules repo v1.0.0 ───────────────────────────────────────────────
print("\n  Tagging modules repo as v1.0.0...")
create_tag(repo_mod, "v1.0.0", "Initial release — all network and app infra modules")


# ══════════════════════════════════════════════════════════════════════════════
# STEP 3 — Set up checkov-configs repo
# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("STEP 3 — Setting up checkov-configs repo")
print("=" * 60)

repo_chk = repos["checkov-configs"]

checkov_readme = """# Checkov Account Configs

One JSON file per AWS account.
The MCP server checks for this file before running any pipeline.
If it does not exist the MCP creates it automatically.

## File naming
`{account_id}.json`

## Required fields
- account_id
- account_name
- environment
- app_id
- manager
- enabled
"""

checkov_template = """{
  "account_id": "ACCOUNT_ID_HERE",
  "account_name": "ACCOUNT_NAME_HERE",
  "environment": "nonprod",
  "app_id": "APP_ID_HERE",
  "manager": "MANAGER_NAME_HERE",
  "enabled": true
}
"""

checkov_config = """# .checkov.yaml — applied to all Terraform in all pipelines
framework:
  - terraform
check:
  - CKV_AWS_RESOURCE_TAGS
  - CKV2_AWS_*
skip_check:
  - CKV_AWS_18   # S3 access logging optional for non-prod
output:
  - json
compact: true
quiet: true
"""

push_file(repo_chk, "README.md",              checkov_readme,    "docs: add README")
push_file(repo_chk, "_template.json",         checkov_template,  "feat: add account config template")
push_file(repo_chk, ".checkov.yaml",          checkov_config,    "feat: add checkov config")
push_file(repo_chk, "accounts/.gitkeep",      "",                "feat: add accounts directory")

print("  checkov-configs repo set up.")


# ══════════════════════════════════════════════════════════════════════════════
# STEP 4 — Set up network-infra repo
# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("STEP 4 — Setting up network-infra repo")
print("=" * 60)

repo_net = repos["network-infra"]

network_readme = """# Network Infrastructure

Per-account network infra — VPC, subnets, TGW, NAT, KMS, SGs, SSM, VPCE, flow logs.

## Structure
```
accounts/
├── nonprod/
│   └── {account_id}/
│       ├── main.tf
│       ├── variables.tf
│       └── tags.tfvars
├── prod/
└── dr/
```

## Pipeline order
1. Log Account Pipeline
2. Checkov Account File
3. TGW Pipeline
4. **Network Infra Pipeline** ← this repo

## Tags
All 24 mandatory tags must be set in `tags.tfvars` before pipeline runs.
"""

tags_tfvars_example = """# tags.tfvars — all 24 mandatory tags
# Copy this file to accounts/{env}/{account_id}/tags.tfvars and fill in values

AccountId            = "ACCOUNT_ID"
AccountName          = "ACCOUNT_NAME"
AppId                = "APP_ID"
ApplicationType      = "APPLICATION_TYPE"
Environment          = "nonprod"
Manager              = "MANAGER_NAME"
CostCenter           = "COST_CENTER"
BusinessUnit         = "BUSINESS_UNIT"
Department           = "DEPARTMENT"
Project              = "PROJECT_NAME"
Owner                = "OWNER"
CreatedBy            = "terraform"
CreatedDate          = "2026-01-01"
LastModifiedBy       = "terraform"
LastModifiedDate     = "2026-01-01"
Compliance           = "internal"
DataClassification   = "internal"
BackupPolicy         = "daily"
MonitoringLevel      = "standard"
PatchGroup           = "standard"
SupportTeam          = "infra-team"
Region               = "us-east-1"
Terraform            = "true"
TerraformModuleVersion = "v1.0.0"
"""

push_file(repo_net, "README.md",                  network_readme,       "docs: add README")
push_file(repo_net, "tags.tfvars.example",         tags_tfvars_example,  "feat: add tags example")
push_file(repo_net, "accounts/nonprod/.gitkeep",  "",                   "feat: add nonprod folder")
push_file(repo_net, "accounts/prod/.gitkeep",     "",                   "feat: add prod folder")
push_file(repo_net, "accounts/dr/.gitkeep",       "",                   "feat: add dr folder")

print("  network-infra repo set up.")


# ══════════════════════════════════════════════════════════════════════════════
# STEP 5 — Set up infra-requests repo (GitHub Issues)
# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("STEP 5 — Setting up infra-requests repo")
print("=" * 60)

repo_req = repos["infra-requests"]

issue_template = """---
name: Infrastructure Request
about: Request new AWS infrastructure
title: "[INFRA] "
labels: infra-request
assignees: ''
---

## Infrastructure Request

| Field | Value |
|---|---|
| Account Name | <!-- e.g. myapp-nonprod --> |
| App ID | <!-- e.g. APP001 --> |
| Manager | <!-- Manager name --> |
| Application Type | <!-- microservice / data-platform / etc. --> |
| Environment | <!-- nonprod / prod / dr --> |
| VPC CIDR | <!-- e.g. 10.0.0.0/16 --> |
| Budget Approval Link | <!-- Link to approved budget doc --> |
| Architecture Doc Link | <!-- Link to approved architecture doc --> |

## Additional Notes
<!-- Any extra context the infra team needs -->

---
> After manager approval, add the `approved` label to trigger automated account creation.
"""

infra_readme = """# Infrastructure Requests

App teams raise GitHub Issues here to request new AWS infrastructure.

## How to raise a request
1. Click **New Issue** and select the **Infrastructure Request** template
2. Fill in all fields in the table
3. Submit the issue — your manager will review and add the `approved` label
4. Once approved, the MCP server automates the rest

## What happens after approval
1. AWS account created in the correct OU
2. Account registered in Netbox
3. Log account pipeline runs
4. TGW pipeline runs
5. Network infra pipeline runs (VPC, subnets, NAT, KMS, SGs)
6. App infra pipeline runs
7. Issue closed with full resource summary

## Labels
| Label | Meaning |
|---|---|
| `infra-request` | New request raised by app team |
| `approved` | Manager approved — triggers automation |
| `in-progress` | MCP is actively building the infra |
| `module-update` | New Terraform module version available |
"""

push_file(repo_req, "README.md",                                    infra_readme,   "docs: add README")
push_file(repo_req, ".github/ISSUE_TEMPLATE/infra_request.md",     issue_template, "feat: add issue template")

print("  infra-requests repo set up.")


# ══════════════════════════════════════════════════════════════════════════════
# STEP 6 — Push MCP server code
# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("STEP 6 — mcp-infra-server repo")
print("=" * 60)
print("  Push your local mcp-infra-server/ code to this repo:")
print(f"  https://github.com/{ORG}/mcp-infra-server")
print("  Use: git remote add origin <url> && git push -u origin main")


# ══════════════════════════════════════════════════════════════════════════════
# DONE
# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("ALL DONE")
print("=" * 60)
print(f"""
Repos created:
  https://github.com/{user.login}/modules          (tagged v1.0.0)
  https://github.com/{user.login}/network-infra
  https://github.com/{user.login}/checkov-configs
  https://github.com/{user.login}/infra-requests
  https://github.com/{user.login}/mcp-infra-server

Next steps:
  1. Push mcp-infra-server code (see Step 6 above)
  2. Fill in remaining .env values (Jenkins, AWS IDs, Netbox, Vault)
  3. Run setup/vault/vault_setup.py
  4. Run setup/netbox/netbox_setup.py
  5. Deploy setup/aws/main.tf
  6. Configure Jenkins pipeline jobs
  7. Run terraform-warm-cache Jenkins job
""")
