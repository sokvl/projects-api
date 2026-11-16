import uuid
from collections.abc import Callable
from functools import partial
from typing import BinaryIO
from urllib.parse import quote

import boto3
from anyio import CapacityLimiter, to_thread
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import Settings, settings

s3_limiter = CapacityLimiter(10)


def project_prefix(project_id: uuid.UUID) -> str:
    return f"projects/{project_id}/"


class StorageError(Exception):
    """S3 call failed. General error for S3 storage operations."""


class S3Storage:
    def __init__(self, settings: Settings) -> None:
        self.bucket = settings.s3_bucket_name
        config = Config(
            s3={"addressing_style": "path"},
            connect_timeout=5,
            read_timeout=5,
            retries={"max_attempts": 3},
        )
        self.s3_regular_client = boto3.client(
            "s3", region_name=settings.s3_region, endpoint_url=settings.s3_api_url, config=config
        )
        self.s3_signer_client = boto3.client(
            "s3", region_name=settings.s3_region, endpoint_url=settings.s3_public_url, config=config
        )

    def generate_presigned_download_url(self, key: str, filename: str, inline: bool = False) -> str:
        kind = "inline" if inline else "attachment"
        disposition = f"{kind}; filename*=UTF-8''{quote(filename, safe='')}"
        return self.s3_signer_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key, "ResponseContentDisposition": disposition},
            ExpiresIn=300,
        )

    async def upload_file(self, key: str, data: BinaryIO, content_type: str) -> None:
        await self._run(
            partial(
                self.s3_regular_client.put_object,
                Bucket=self.bucket,
                Key=key,
                Body=data,
                ContentType=content_type,
            )
        )

    async def delete_file(self, key: str) -> None:
        await self._run(partial(self.s3_regular_client.delete_object, Bucket=self.bucket, Key=key))

    async def delete_prefix(self, prefix: str) -> None:
        await self._run(partial(self._delete_prefix_sync, prefix))

    def _delete_prefix_sync(self, prefix: str) -> None:
        paginator = self.s3_regular_client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            contents = page.get("Contents", [])
            if not contents:
                continue
            response = self.s3_regular_client.delete_objects(
                Bucket=self.bucket,
                Delete={"Objects": [{"Key": obj["Key"]} for obj in contents], "Quiet": True},
            )
            if errors := response.get("Errors"):
                raise StorageError(f"Failed to delete {len(errors)} objects under {prefix!r}")

    async def _run[T](self, call: Callable[[], T]) -> T:
        try:
            return await to_thread.run_sync(call, limiter=s3_limiter)
        except (BotoCoreError, ClientError) as e:
            raise StorageError(str(e)) from e


storage = S3Storage(settings)


def get_storage() -> S3Storage:
    return storage
