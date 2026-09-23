from __future__ import annotations

from io import BytesIO
from pathlib import Path

import botocore.exceptions
from course_tutor_ingestion.object_store import MinioObjectStore


class _S3:
    def __init__(self) -> None:
        self.bucket_exists = False
        self.objects: dict[tuple[str, str], bytes] = {}

    def head_bucket(self, *, Bucket: str) -> None:
        if not self.bucket_exists:
            raise botocore.exceptions.ClientError(
                {"Error": {"Code": "404", "Message": "missing"}}, "HeadBucket"
            )

    def create_bucket(self, *, Bucket: str) -> None:
        self.bucket_exists = True

    def put_object(self, *, Bucket: str, Key: str, Body: object, ContentType: str) -> None:
        data = Body.read() if hasattr(Body, "read") else Body
        assert isinstance(data, bytes)
        self.objects[(Bucket, Key)] = data

    def head_object(self, *, Bucket: str, Key: str) -> None:
        if (Bucket, Key) not in self.objects:
            raise botocore.exceptions.ClientError(
                {"Error": {"Code": "404", "Message": "missing"}}, "HeadObject"
            )

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, BytesIO]:
        return {"Body": BytesIO(self.objects[(Bucket, Key)])}


async def test_bucket_creation_and_canonical_artifact_round_trip(tmp_path: Path) -> None:
    client = _S3()
    store = MinioObjectStore.__new__(MinioObjectStore)
    store._client = client  # type: ignore[attr-defined]
    store._bucket = "test-artifacts"  # type: ignore[attr-defined]
    store.ensure_bucket()

    source = tmp_path / "lecture.md"
    source.write_bytes(b"course material")
    checksum = "a" * 64
    key = store.upload_path(source, checksum)

    assert key == f"artifacts/sha256/aa/{checksum}"
    assert await store.get(key) == b"course material"
    renamed_source = tmp_path / "renamed-course-material.pdf"
    renamed_source.write_bytes(b"course material")
    assert store.upload_path(renamed_source, checksum) == key
    assert len(client.objects) == 1
