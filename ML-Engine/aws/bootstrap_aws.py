from __future__ import annotations
import os
import sys
import json
from pathlib import Path
from typing import Optional

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import aws.env_loader
import boto3
from botocore.exceptions import BotoCoreError, ClientError

from aws.bedrock_agent import BedrockEnergyAgent


def check_aws_identity(session: boto3.Session):
    try:
        sts = session.client("sts")
        identity = sts.get_caller_identity()
        print("[OK] AWS Credentials Active:")
        print(f"   Account: {identity.get('Account')}")
        print(f"   ARN:     {identity.get('Arn')}")
        print(f"   Region:  {session.region_name or 'us-east-1'}")
        return identity
    except (BotoCoreError, ClientError, Exception) as e:
        print(f"[WARNING] Could not authenticate with AWS STS: {e}")
        print("   Please ensure AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY are set.")
        return None


def sync_artifacts_to_s3(session: boto3.Session, bucket_name: str, prefix: str = "p2p-models"):
    s3 = session.client("s3")
    region = session.region_name or "us-east-1"

    print(f"\nStep 1: Syncing Model Artifacts to S3 [s3://{bucket_name}/{prefix}/]...")

    try:
        s3.head_bucket(Bucket=bucket_name)
        print(f"   Bucket '{bucket_name}' verified.")
    except ClientError as e:
        error_code = str(e.response.get("Error", {}).get("Code", ""))
        if error_code in ("404", "NoSuchBucket"):
            print(f"   Bucket '{bucket_name}' not found. Creating it in {region}...")
            if region == "us-east-1":
                s3.create_bucket(Bucket=bucket_name)
            else:
                s3.create_bucket(
                    Bucket=bucket_name,
                    CreateBucketConfiguration={"LocationConstraint": region},
                )
            print(f"   Bucket '{bucket_name}' created successfully.")
        elif error_code in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
            print(f"   Bucket '{bucket_name}' already exists.")
        else:
            print(f"   [NOTICE] Bucket access check notice: {e}")

    saved_dir = ROOT_DIR / "models" / "saved"
    model_tar = saved_dir / "model.tar.gz"
    model_joblib = saved_dir / "lgbm_forecaster.joblib"
    nodes_cfg = ROOT_DIR / "data" / "archetypes" / "nodes_config.yaml"

    files_to_upload = [
        (model_tar, f"{prefix}/model.tar.gz"),
        (model_joblib, f"{prefix}/lgbm_forecaster.joblib"),
        (nodes_cfg, f"{prefix}/nodes_config.yaml"),
    ]

    for local_path, s3_key in files_to_upload:
        if local_path.exists():
            print(f"   Uploading {local_path.name} -> s3://{bucket_name}/{s3_key}...")
            s3.upload_file(str(local_path), bucket_name, s3_key)
            print(f"   [UPLOADED] s3://{bucket_name}/{s3_key}")
        else:
            print(f"   [WARNING] Local file not found: {local_path}")

    return f"s3://{bucket_name}/{prefix}/model.tar.gz"


def verify_bedrock(session: boto3.Session, model_id: Optional[str] = None):
    region = session.region_name or "us-east-1"
    agent = BedrockEnergyAgent(model_id=model_id, region_name=region)
    print(f"\nStep 2: Testing Amazon Bedrock [Primary: {agent.active_model_id}]...")

    print("   Invoking sample prosumer advisory...")
    advisory = agent.generate_advisory(
        node_name="Aarav Sharma",
        node_type="Solar Champion Prosumer",
        peak_surplus_slot="13:00–15:00",
        peak_surplus_kwh=3.8,
        p10_surplus=2.9,
        p90_surplus=4.4,
        matched_peer="Iyengar Bakery & Vikram Mehta",
        estimated_earnings_inr=19.95,
        grid_comparison_inr=9.31,
    )
    print(f"   Result: \"{advisory}\"")

    print("\n   Invoking sample SHAP attribution explanation...")
    sample_shap = {
        "solar_drivers": [
            {"feature": "ghi_w_m2", "shap_impact": 2.85},
            {"feature": "solar_potential_theoretical", "shap_impact": 0.45},
        ],
        "load_drivers": [
            {"feature": "temp_over_30", "shap_impact": 0.72},
            {"feature": "ac_units", "shap_impact": 0.35},
        ],
    }
    explanation = agent.generate_shap_explanation(
        node_name="Aarav Sharma",
        shap_explanation=sample_shap,
        surplus_kwh=3.8,
        slot_time="14:00",
    )
    print(f"   Result: \"{explanation}\"")

    print(f"\n   Execution Engine: {agent.last_invocation_source.upper()}")
    if agent.last_invocation_source == "aws_bedrock":
        print("   Engine Status:    [LIVE] Amazon Bedrock returned live LLM inference.")
        print(f"   Active Model:     {agent.active_model_id}")
    else:
        print("   Engine Status:    [FALLBACK] Local rule-based template generation was used.")
        if agent.last_error:
            print(f"   Fallback Reason:  {agent.last_error}")
        print("\n   Note: AWS Bedrock serverless models auto-enable on first invocation.")
        print("   If 'Operation not allowed' appears on a new account:")
        print("   1. Open AWS Console -> Amazon Bedrock -> Playgrounds -> Chat.")
        print("   2. Select a model (Amazon Nova Lite or Titan Text Express) and run one test prompt.")
        print("   3. If your AWS account is brand new, AWS may take up to 24-48h for account verification.")


def main():
    region = (
        os.environ.get("AWS_DEFAULT_REGION")
        or os.environ.get("AWS_REGION")
        or "us-east-1"
    )
    session = boto3.Session(
        region_name=region,
        aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
        aws_session_token=os.environ.get("AWS_SESSION_TOKEN"),
    )

    print("==================================================")
    print("      P2P-ES AWS Infrastructure Bootstrap         ")
    print("==================================================")

    identity = check_aws_identity(session)
    account_id = identity.get("Account", "demo") if identity else "demo"

    default_bucket = os.environ.get("S3_BUCKET_NAME", f"p2p-energy-models-{account_id}")

    if identity is not None:
        sync_artifacts_to_s3(session, bucket_name=default_bucket)
        verify_bedrock(session)
        print("\nAll AI components staged and verified.")
    else:
        print("\n[WARNING] AWS credentials not detected in environment.")
        print("   To run this with your AWS account, configure credentials in ML-Engine/.env:")
        print("     AWS_ACCESS_KEY_ID=your-key")
        print("     AWS_SECRET_ACCESS_KEY=your-secret")
        print("     AWS_DEFAULT_REGION=us-east-1")
        print("   Then re-run: python aws/bootstrap_aws.py")


if __name__ == "__main__":
    main()
