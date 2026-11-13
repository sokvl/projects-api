from collections.abc import Iterator
from typing import Final
from unittest.mock import MagicMock
from urllib.parse import parse_qs, urlparse

import boto3
import pytest
from botocore.exceptions import ClientError, EndpointConnectionError
from moto import mock_aws
from mypy_boto3_s3 import S3Client

from app.core.config import Settings, settings
from app.storage.s3 import S3Storage, StorageError

REGION: Final = "eu-central-1"
BUCKET = "documents"


@pytest.fixture(autouse=True)
def fake_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")


@pytest.fixture
def s3_settings() -> Settings:
    return settings.model_copy(
        update={
            "s3_region": REGION,
            "s3_bucket_name": BUCKET,
            "s3_api_url": None,
            "s3_public_url": None,
        }
    )


@pytest.fixture
def s3() -> Iterator[S3Client]:
    with mock_aws():
        client = boto3.client("s3", region_name=REGION)
        client.create_bucket(
            Bucket=BUCKET, CreateBucketConfiguration={"LocationConstraint": REGION}
        )
        yield client


@pytest.fixture
def storage(s3: S3Client, s3_settings: Settings) -> S3Storage:
    return S3Storage(s3_settings)


@pytest.fixture
def emulator_storage(s3_settings: Settings) -> S3Storage:
    return S3Storage(
        s3_settings.model_copy(
            update={"s3_api_url": "http://s3:4566", "s3_public_url": "http://localhost:4566"}
        )
    )


def keys(s3: S3Client) -> list[str]:
    return [obj["Key"] for obj in s3.list_objects_v2(Bucket=BUCKET).get("Contents", [])]


async def test_upload_file_stores_body_and_content_type(storage: S3Storage, s3: S3Client) -> None:
    await storage.upload_file("projects/a/doc", b"%PDF-1.7", "application/pdf")

    obj = s3.get_object(Bucket=BUCKET, Key="projects/a/doc")
    assert obj["Body"].read() == b"%PDF-1.7"
    assert obj["ContentType"] == "application/pdf"


async def test_upload_file_overwrites_existing_key(storage: S3Storage, s3: S3Client) -> None:
    await storage.upload_file("projects/a/doc", b"old", "application/pdf")

    await storage.upload_file("projects/a/doc", b"new", "application/pdf")

    assert s3.get_object(Bucket=BUCKET, Key="projects/a/doc")["Body"].read() == b"new"


async def test_upload_file_to_missing_bucket_raises_storage_error(
    s3: S3Client, s3_settings: Settings
) -> None:
    storage = S3Storage(s3_settings.model_copy(update={"s3_bucket_name": "missing"}))

    with pytest.raises(StorageError) as exc_info:
        await storage.upload_file("projects/a/doc", b"%PDF", "application/pdf")

    assert isinstance(exc_info.value.__cause__, ClientError)


async def test_delete_file_removes_only_that_object(storage: S3Storage, s3: S3Client) -> None:
    s3.put_object(Bucket=BUCKET, Key="projects/a/one", Body=b"1")
    s3.put_object(Bucket=BUCKET, Key="projects/a/two", Body=b"2")

    await storage.delete_file("projects/a/one")

    assert keys(s3) == ["projects/a/two"]


async def test_delete_file_missing_key_does_not_raise(storage: S3Storage, s3: S3Client) -> None:
    await storage.delete_file("projects/a/missing")

    assert keys(s3) == []


async def test_delete_prefix_removes_objects_across_pages(storage: S3Storage, s3: S3Client) -> None:
    for i in range(1001):
        s3.put_object(Bucket=BUCKET, Key=f"projects/a/{i}", Body=b"x")

    await storage.delete_prefix("projects/a/")

    assert keys(s3) == []


async def test_delete_prefix_keeps_objects_outside_prefix(storage: S3Storage, s3: S3Client) -> None:
    s3.put_object(Bucket=BUCKET, Key="projects/1/doc", Body=b"x")
    s3.put_object(Bucket=BUCKET, Key="projects/12/doc", Body=b"x")
    s3.put_object(Bucket=BUCKET, Key="other/doc", Body=b"x")

    await storage.delete_prefix("projects/1/")

    assert keys(s3) == ["other/doc", "projects/12/doc"]


async def test_delete_prefix_with_no_objects_does_nothing(storage: S3Storage, s3: S3Client) -> None:
    await storage.delete_prefix("projects/a/")

    assert keys(s3) == []


async def test_delete_prefix_raises_when_s3_reports_errors(emulator_storage: S3Storage) -> None:
    client = MagicMock()
    client.get_paginator.return_value.paginate.return_value = [
        {"Contents": [{"Key": "projects/a/doc"}]}
    ]
    client.delete_objects.return_value = {
        "Errors": [{"Key": "projects/a/doc", "Code": "AccessDenied"}]
    }
    emulator_storage.s3_regular_client = client

    with pytest.raises(StorageError):
        await emulator_storage.delete_prefix("projects/a/")


async def test_run_wraps_connection_errors(emulator_storage: S3Storage) -> None:
    def call() -> None:
        raise EndpointConnectionError(endpoint_url="http://s3:4566")

    with pytest.raises(StorageError) as exc_info:
        await emulator_storage._run(call)

    assert isinstance(exc_info.value.__cause__, EndpointConnectionError)


async def test_run_does_not_wrap_unrelated_errors(emulator_storage: S3Storage) -> None:
    def call() -> None:
        raise ValueError("bug")

    with pytest.raises(ValueError):
        await emulator_storage._run(call)


def test_presigned_url_uses_public_endpoint(emulator_storage: S3Storage) -> None:
    url = urlparse(emulator_storage.generate_presigned_download_url("projects/a/doc", "a.pdf"))

    assert url.netloc == "localhost:4566"


def test_presigned_url_points_to_bucket_and_key(emulator_storage: S3Storage) -> None:
    url = urlparse(emulator_storage.generate_presigned_download_url("projects/a/doc", "a.pdf"))

    assert url.path == f"/{BUCKET}/projects/a/doc"


def test_presigned_url_expires_in_five_minutes(emulator_storage: S3Storage) -> None:
    url = urlparse(emulator_storage.generate_presigned_download_url("projects/a/doc", "a.pdf"))

    assert parse_qs(url.query)["X-Amz-Expires"] == ["300"]


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("raport.pdf", "attachment; filename*=UTF-8''raport.pdf"),
        ("Zażółć.pdf", "attachment; filename*=UTF-8''Za%C5%BC%C3%B3%C5%82%C4%87.pdf"),
        ('a b"c/d.pdf', "attachment; filename*=UTF-8''a%20b%22c%2Fd.pdf"),
    ],
    ids=["ascii", "polish", "special_chars"],
)
def test_presigned_url_encodes_filename(
    emulator_storage: S3Storage, filename: str, expected: str
) -> None:
    url = urlparse(emulator_storage.generate_presigned_download_url("projects/a/doc", filename))

    assert parse_qs(url.query)["response-content-disposition"] == [expected]
