import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # GitHub
    GITHUB_TOKEN: str = os.environ["GITHUB_TOKEN"]
    GITHUB_ORG: str = os.environ["GITHUB_ORG"]
    GITHUB_MODULES_REPO: str = os.getenv("GITHUB_MODULES_REPO", "modules")
    GITHUB_NETWORK_REPO: str = os.getenv("GITHUB_NETWORK_REPO", "network-infra")
    GITHUB_INFRA_REPO: str = os.getenv("GITHUB_INFRA_REPO", "infra-requests")

    # Jenkins
    JENKINS_URL: str = os.environ["JENKINS_URL"]
    JENKINS_USER: str = os.environ["JENKINS_USER"]
    JENKINS_TOKEN: str = os.environ["JENKINS_TOKEN"]

    # Jenkins pipeline names (must match exactly what is configured in Jenkins)
    JENKINS_LOG_PIPELINE: str = os.getenv("JENKINS_LOG_PIPELINE", "log-account-pipeline")
    JENKINS_TGW_PIPELINE: str = os.getenv("JENKINS_TGW_PIPELINE", "tgw-pipeline")
    JENKINS_NETWORK_PIPELINE: str = os.getenv("JENKINS_NETWORK_PIPELINE", "network-infra-pipeline")
    JENKINS_APP_PIPELINE: str = os.getenv("JENKINS_APP_PIPELINE", "app-infra-pipeline")

    # Terraform provider cache — fix for provider re-download issue
    TF_PLUGIN_CACHE_DIR: str = os.getenv("TF_PLUGIN_CACHE_DIR", "/var/jenkins_home/terraform-plugin-cache")

    # AWS
    AWS_REGION: str = os.getenv("AWS_REGION", "us-east-1")
    AWS_AFT_ACCOUNT_ID: str = os.environ["AWS_AFT_ACCOUNT_ID"]
    AWS_LOG_ACCOUNT_ID: str = os.environ["AWS_LOG_ACCOUNT_ID"]
    AWS_SHARED_SERVICES_ACCOUNT_ID: str = os.environ["AWS_SHARED_SERVICES_ACCOUNT_ID"]

    # Netbox
    NETBOX_URL: str = os.environ["NETBOX_URL"]
    NETBOX_TOKEN: str = os.environ["NETBOX_TOKEN"]

    # HashiCorp Vault
    VAULT_URL: str = os.environ["VAULT_URL"]
    VAULT_TOKEN: str = os.environ["VAULT_TOKEN"]
    VAULT_SECRET_PATH: str = os.getenv("VAULT_SECRET_PATH", "secret/infra")

    # Checkov
    CHECKOV_REPO_PATH: str = os.getenv("CHECKOV_REPO_PATH", "/checkov/configs")

    # Module version checker schedule
    MODULE_CHECK_SCHEDULE: str = os.getenv("MODULE_CHECK_SCHEDULE", "weekly")


config = Config()
