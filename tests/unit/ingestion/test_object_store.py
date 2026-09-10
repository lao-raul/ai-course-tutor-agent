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

    def put_object(self, *, Bucket: str, Key: str, Body: bytes, ContentType: str) -> None:
        self.objects[(Bucket, Key)] = Body

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
    key = store.upload_path(source, "tenant-a", "course-b", "source-c")

    assert key == "artifacts/tenant-a/course-b/source-c/lecture.md"
    assert await store.get(key) == b"course material"
