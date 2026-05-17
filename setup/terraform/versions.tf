# Minimal Terraform config used ONLY to pre-warm the plugin cache.
# Declares every provider used across all pipelines so they are all
# downloaded into TF_PLUGIN_CACHE_DIR in one single init run.
# This file is never used for actual infra creation.

terraform {
  required_version = ">= 1.6.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

# No real provider configuration needed — cache warm only.
provider "aws" {
  region = "us-east-1"
  # Credentials intentionally not set here.
  # This block just needs to exist for terraform init to download the provider.
  skip_credentials_validation = true
  skip_requesting_account_id  = true
  skip_metadata_api_check     = true
  access_key                  = "mock"
  secret_key                  = "mock"
}
