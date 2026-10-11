from __future__ import annotations
import argparse
import os
import sys
import tarfile
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import aws.env_loader
import boto3
from botocore.exceptions import BotoCoreError, ClientError
import pandas as pd

from data.generators.indian_load_profile import IndianMicrogridSimulator
from models.lgbm_forecaster import QuantileEnergyForecaster


def run_training_pipeline(
    start_date: str = "2024-01-01",
    end_date: str = "2024-03-25",
    val_days: int = 7,
    s3_bucket: str = None,
    s3_prefix: str = "p2p-models",
    output_dir: str = "models/saved",
):
    print(f"=== Starting Microgrid Training Pipeline [{start_date} to {end_date}] ===")
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    simulator = IndianMicrogridSimulator()
    print("1. Generating multi-node synthetic Indian microgrid profile...")
    full_df = simulator.generate_microgrid_dataset(start_date=start_date, end_date=end_date)

    split_date = full_df["datetime"].max() - pd.Timedelta(days=val_days)
    train_df = full_df[full_df["datetime"] <= split_date].copy()
    val_df = full_df[full_df["datetime"] > split_date].copy()
    print(f"   Train samples: {len(train_df)}, Val samples: {len(val_df)}")

    forecaster = QuantileEnergyForecaster(models_dir=out_path)
    print("2. Training LightGBM Quantile Models (p10, p50, p90)...")
    metrics = forecaster.train(train_df=train_df, val_df=val_df, num_boost_round=200)

    print("   Validation Metrics Summary:")
    print("   Load Metrics:", metrics["load"])
    print("   Solar Metrics:", metrics["solar"])

    model_file = out_path / "lgbm_forecaster.joblib"
    tar_file = out_path / "model.tar.gz"

    print(f"3. Packaging model archive to {tar_file}...")
    with tarfile.open(tar_file, "w:gz") as tar:
        tar.add(model_file, arcname="lgbm_forecaster.joblib")

    if s3_bucket:
        print(f"4. Uploading model archive to s3://{s3_bucket}/{s3_prefix}/model.tar.gz...")
        try:
            s3_client = boto3.client("s3")
            s3_client.upload_file(str(tar_file), s3_bucket, f"{s3_prefix}/model.tar.gz")
            print("   Successfully uploaded model to Amazon S3!")
        except (BotoCoreError, ClientError) as e:
            print(f"   Warning: Could not upload to S3 ({e}). Local model artifact is preserved.")

    print("=== Training Pipeline Complete ===")
    return metrics


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="P2P Energy Forecaster Trainer")
    parser.add_argument("--start-date", default="2024-01-01")
    parser.add_argument("--end-date", default="2024-02-28")
    parser.add_argument("--s3-bucket", default=os.environ.get("S3_BUCKET_NAME", None))
    args = parser.parse_args()

    run_training_pipeline(
        start_date=args.start_date,
        end_date=args.end_date,
        s3_bucket=args.s3_bucket,
    )
