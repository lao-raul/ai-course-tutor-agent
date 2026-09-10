"""MinIO / S3-compatible object store for ingestion artifacts.

The object store holds the original source files and extraction artifacts. It is never the
system of record — that is PostgreSQL — and is not the vector store.
"""

from __future__ import annotations

from pathlib import Path

import boto3
import botocore.exceptions
import structlog

logger = structlog.get_logger(__name__)

#: Key prefix for ingestion artifacts within the bucket.
ARTIFACT_PREFIX = "artifacts/"


class ObjectStoreError(RuntimeError):
    """Raised when object store operations fail."""


class MinioObjectStore:
    """Stores and retrieves ingestion artifacts from MinIO / S3-compatible storage.

    Files are stored under ``artifacts/{tenant_id}/{course_id}/{source_document_id}/{filename}``.
    The caller is responsible for computing the key.
    """

    def __init__(
        self,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        *,
        region: str = "us-east-1",
        public: bool = False,
    ) -> None:
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
            config=boto3.session.Config(
                signature_version=botocore.session.UNSIGNED if public else "s3v4"
            ),
        )
        self._bucket = bucket

    def ensure_bucket(self) -> None:
        """Create the configured private bucket once; tolerate concurrent creators."""
        try:
            self._client.head_bucket(Bucket=self._bucket)
            return
        except botocore.exceptions.ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            if code not in {"404", "NoSuchBucket", "NotFound"}:
                raise ObjectStoreError(f"bucket {self._bucket!r} is not accessible: {exc}") from exc
        try:
            self._client.create_bucket(Bucket=self._bucket)
        except botocore.exceptions.ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            if code not in {"BucketAlreadyExists", "BucketAlreadyOwnedByYou"}:
                raise ObjectStoreError(f"could not create bucket {self._bucket!r}: {exc}") from exc

    async def put(self, key: str, data: bytes, *, content_type: str) -> str:
        """Store *data* under *key* and return the key."""
        try:
            self._client.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=data,
                ContentType=content_type,
            )
            logger.debug("object_store_put", key=key, size_bytes=len(data))
            return key
        except botocore.exceptions.ClientError as exc:
            raise ObjectStoreError(f"put failed for key {key!r}: {exc}") from exc

    async def get(self, key: str) -> bytes:
        """Return the bytes stored under *key*."""
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=key)
            body: bytes = response["Body"].read()
            return body
        except botocore.exceptions.ClientError as exc:
            raise ObjectStoreError(f"get failed for key {key!r}: {exc}") from exc

    async def health(self) -> None:
        """Raise ObjectStoreError if the bucket is not accessible."""
        try:
            self._client.head_bucket(Bucket=self._bucket)
        except botocore.exceptions.ClientError as exc:
            raise ObjectStoreError(f"bucket {self._bucket!r} is not accessible: {exc}") from exc

    def artifact_key(self, tenant_id: str, course_id: str, source_id: str, filename: str) -> str:
        """Build a canonical artifact key."""
        return f"{ARTIFACT_PREFIX}{tenant_id}/{course_id}/{source_id}/{filename}"

    def upload_path(self, source_path: Path, tenant_id: str, course_id: str, source_id: str) -> str:
        """Upload a local file and return its artifact key."""
        key = self.artifact_key(tenant_id, course_id, source_id, source_path.name)
        with open(source_path, "rb") as f:
            data = f.read()
        content_type = "application/octet-stream"
        # Infer from extension.
        suffix = source_path.suffix.lower()
        MIME_MAP = {
            ".pdf": "application/pdf",
            ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".md": "text/markdown; charset=utf-8",
            ".txt": "text/plain; charset=utf-8",
        }
        content_type = MIME_MAP.get(suffix, "application/octet-stream")
        return self._sync_put(key, data, content_type)

    def _sync_put(self, key: str, data: bytes, content_type: str) -> str:
        """Synchronous put (boto3 is sync-only; run in a thread pool)."""
        try:
            self._client.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=data,
                ContentType=content_type,
            )
            return key
        except botocore.exceptions.ClientError as exc:
            raise ObjectStoreError(f"put failed for key {key!r}: {exc}") from exc
