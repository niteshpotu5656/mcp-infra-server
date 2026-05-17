terraform {
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
  }
  backend "s3" {
    bucket = "aft-terraform-state"
    key    = "mcp-infra/setup/terraform.tfstate"
    region = "us-east-1"
  }
}

provider "aws" {
  region = var.region
}

variable "region"         { default = "us-east-1" }
variable "netbox_url"     {}
variable "netbox_token"   {}
variable "lambda_zip"     { default = "netbox_sync.zip" }

# ── Lambda execution role ────────────────────────────────────────────────────
resource "aws_iam_role" "lambda_exec" {
  name = "mcp-netbox-sync-lambda-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_basic" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "lambda_config_read" {
  name = "mcp-lambda-config-read"
  role = aws_iam_role.lambda_exec.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["config:GetResourceConfigHistory", "config:DescribeConfigurationRecorders"]
      Resource = "*"
    }]
  })
}

# ── Lambda function ──────────────────────────────────────────────────────────
resource "aws_lambda_function" "netbox_sync" {
  function_name    = "mcp-netbox-sync"
  filename         = var.lambda_zip
  source_code_hash = filebase64sha256(var.lambda_zip)
  handler          = "netbox_sync.lambda_handler"
  runtime          = "python3.12"
  role             = aws_iam_role.lambda_exec.arn
  timeout          = 30

  environment {
    variables = {
      NETBOX_URL   = var.netbox_url
      NETBOX_TOKEN = var.netbox_token
    }
  }
}

# ── EventBridge rule — fires on every AWS Config resource change ─────────────
resource "aws_cloudwatch_event_rule" "config_changes" {
  name        = "mcp-aws-config-changes"
  description = "Fires when AWS Config records any resource change — triggers Netbox sync"
  event_pattern = jsonencode({
    source        = ["aws.config"]
    "detail-type" = ["Config Configuration Item Change"]
  })
}

resource "aws_cloudwatch_event_target" "netbox_sync" {
  rule = aws_cloudwatch_event_rule.config_changes.name
  arn  = aws_lambda_function.netbox_sync.arn
}

resource "aws_lambda_permission" "allow_eventbridge" {
  statement_id  = "AllowEventBridgeInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.netbox_sync.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.config_changes.arn
}

# ── AWS Config recorder (deploy to each child account via org stack sets) ────
resource "aws_config_configuration_recorder" "main" {
  name     = "mcp-config-recorder"
  role_arn = aws_iam_role.lambda_exec.arn
  recording_group {
    all_supported                 = true
    include_global_resource_types = true
  }
}

resource "aws_config_delivery_channel" "main" {
  name           = "mcp-config-delivery"
  s3_bucket_name = "aft-terraform-state"
  depends_on     = [aws_config_configuration_recorder.main]
}

resource "aws_config_configuration_recorder_status" "main" {
  name       = aws_config_configuration_recorder.main.name
  is_enabled = true
  depends_on = [aws_config_delivery_channel.main]
}

output "lambda_arn"      { value = aws_lambda_function.netbox_sync.arn }
output "eventbridge_rule"{ value = aws_cloudwatch_event_rule.config_changes.arn }
