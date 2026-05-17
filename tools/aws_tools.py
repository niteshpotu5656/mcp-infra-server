import boto3
import time
from mcp.server.fastmcp import FastMCP
from config import config


def _get_session():
    """
    Return a boto3 session.
    - POC mode: use static Access Key + Secret from .env directly.
    - Production: assume MCPAutomationRole in the AFT account via STS.
    """
    if config.POC_MODE:
        return boto3.Session(
            aws_access_key_id=config.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=config.AWS_SECRET_ACCESS_KEY,
            region_name=config.AWS_REGION,
        )
    # Production: assume role in AFT account
    sts = boto3.client("sts", region_name=config.AWS_REGION)
    role_arn = f"arn:aws:iam::{config.AWS_AFT_ACCOUNT_ID}:role/MCPAutomationRole"
    creds = sts.assume_role(RoleArn=role_arn, RoleSessionName="mcp-infra-session")["Credentials"]
    return boto3.Session(
        aws_access_key_id=creds["AccessKeyId"],
        aws_secret_access_key=creds["SecretAccessKey"],
        aws_session_token=creds["SessionToken"],
        region_name=config.AWS_REGION,
    )


def register_aws_tools(mcp: FastMCP):

    @mcp.tool()
    def aws_create_account(
        account_name: str,
        email: str,
        organizational_unit: str,
        environment: str,
    ) -> dict:
        """
        Create a new AWS account via Organizations.
        In POC mode: skips real account creation and returns the existing
        POC account ID so the rest of the workflow can continue.
        In production: triggers AFT account creation and waits for completion.
        """
        if config.POC_MODE:
            return {
                "account_id": config.AWS_ACCOUNT_ID,
                "account_name": account_name,
                "environment": environment,
                "ou": organizational_unit,
                "status": "poc_bypass",
                "note": "POC mode — using existing account instead of creating a new one",
            }

        session = _get_session()
        orgs = session.client("organizations")

        response = orgs.create_account(
            AccountName=account_name,
            Email=email,
            IamUserAccessToBilling="DENY",
        )
        request_id = response["CreateAccountStatus"]["Id"]

        for _ in range(30):
            status = orgs.describe_create_account_status(CreateAccountRequestId=request_id)
            state = status["CreateAccountStatus"]["State"]
            if state == "SUCCEEDED":
                account_id = status["CreateAccountStatus"]["AccountId"]
                _move_account_to_ou(orgs, account_id, organizational_unit)
                return {
                    "account_id": account_id,
                    "account_name": account_name,
                    "environment": environment,
                    "ou": organizational_unit,
                    "status": "created",
                }
            if state == "FAILED":
                return {
                    "status": "failed",
                    "reason": status["CreateAccountStatus"].get("FailureReason"),
                }
            time.sleep(10)

        return {"status": "timeout", "request_id": request_id}

    def _move_account_to_ou(orgs_client, account_id: str, target_ou_name: str):
        """Move a newly created account from root to the target OU."""
        roots = orgs_client.list_roots()["Roots"]
        root_id = roots[0]["Id"]
        parents = orgs_client.list_parents(ChildId=account_id)["Parents"]
        current_parent_id = parents[0]["Id"]
        ous = orgs_client.list_organizational_units_for_parent(ParentId=root_id)["OrganizationalUnits"]
        target_ou = next((ou for ou in ous if ou["Name"].lower() == target_ou_name.lower()), None)
        if not target_ou:
            raise ValueError(f"OU '{target_ou_name}' not found under root")
        orgs_client.move_account(
            AccountId=account_id,
            SourceParentId=current_parent_id,
            DestinationParentId=target_ou["Id"],
        )

    @mcp.tool()
    def aws_get_account_details(account_id: str) -> dict:
        """
        Get details of an AWS account.
        In POC mode: returns details of the POC account directly via STS.
        """
        if config.POC_MODE:
            session = _get_session()
            sts = session.client("sts")
            identity = sts.get_caller_identity()
            return {
                "account_id": identity["Account"],
                "account_name": "POC Account",
                "arn": identity["Arn"],
                "status": "ACTIVE",
                "note": "POC mode — returning caller identity",
            }

        session = _get_session()
        orgs = session.client("organizations")
        account = orgs.describe_account(AccountId=account_id)["Account"]
        return {
            "account_id": account["Id"],
            "account_name": account["Name"],
            "email": account["Email"],
            "status": account["Status"],
            "arn": account["Arn"],
        }

    @mcp.tool()
    def aws_check_account_active(account_id: str) -> dict:
        """
        Check whether an AWS account is active and accessible.
        In POC mode: verifies the POC account credentials work via STS.
        """
        if config.POC_MODE:
            try:
                session = _get_session()
                sts = session.client("sts")
                identity = sts.get_caller_identity()
                return {
                    "account_id": identity["Account"],
                    "active": True,
                    "status": "ACTIVE",
                    "note": "POC mode — credentials verified via STS",
                }
            except Exception as e:
                return {"account_id": account_id, "active": False, "status": "ERROR", "error": str(e)}

        session = _get_session()
        orgs = session.client("organizations")
        account = orgs.describe_account(AccountId=account_id)["Account"]
        active = account["Status"] == "ACTIVE"
        return {"account_id": account_id, "active": active, "status": account["Status"]}

    @mcp.tool()
    def aws_get_account_arn(account_id: str) -> dict:
        """
        Get the ARN for an AWS account.
        In POC mode: returns the caller ARN from STS.
        """
        if config.POC_MODE:
            session = _get_session()
            sts = session.client("sts")
            identity = sts.get_caller_identity()
            return {
                "account_id": identity["Account"],
                "arn": identity["Arn"],
                "note": "POC mode — returning caller ARN",
            }

        session = _get_session()
        orgs = session.client("organizations")
        account = orgs.describe_account(AccountId=account_id)["Account"]
        return {"account_id": account_id, "arn": account["Arn"]}
