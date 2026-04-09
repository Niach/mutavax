import os
from pathlib import Path
from typing import BinaryIO, Optional

import boto3
from botocore.config import Config


class S3Storage:
    def __init__(self) -> None:
        bucket = os.getenv("S3_BUCKET")
        if not bucket:
            raise RuntimeError("S3_BUCKET is required for workspace file storage")

        endpoint_url = os.getenv("S3_ENDPOINT_URL")
        region_name = os.getenv("AWS_REGION") or "us-east-1"
        access_key = os.getenv("AWS_ACCESS_KEY_ID")
        secret_key = os.getenv("AWS_SECRET_ACCESS_KEY")
        force_path_style = os.getenv("S3_FORCE_PATH_STYLE", "true").lower() == "true"
        config = Config(s3={"addressing_style": "path" if force_path_style else "virtual"})

        self.bucket = bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            region_name=region_name,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=config,
        )

    def upload_fileobj(self, fileobj: BinaryIO, key: str, content_type: Optional[str] = None) -> None:
        extra_args = {"ContentType": content_type} if content_type else None
        self.client.upload_fileobj(fileobj, self.bucket, key, ExtraArgs=extra_args or {})

    def upload_path(self, path: Path, key: str, content_type: Optional[str] = None) -> None:
        extra_args = {"ContentType": content_type} if content_type else None
        self.client.upload_file(str(path), self.bucket, key, ExtraArgs=extra_args or {})

    def copy_object(self, source_key: str, destination_key: str) -> None:
        self.client.copy(
            {"Bucket": self.bucket, "Key": source_key},
            self.bucket,
            destination_key,
        )

    def download_path(self, key: str, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        self.client.download_file(self.bucket, key, str(destination))


_storage: Optional[S3Storage] = None


def get_storage() -> S3Storage:
    global _storage
    if _storage is None:
        _storage = S3Storage()
    return _storage
