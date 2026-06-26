"""Vault object storage — presigned S3 URLs for document upload/download (V3).

Two impls behind one ``VaultStorage`` Protocol, selected by the FastAPI lifespan
(``app/main.py``) exactly like the AgentCore runtime client:

  * ``S3VaultStorage`` — real boto3 S3 presigner. Client construction is **lazy**
    (boto3 imported + built on first use) so unit/integration tests never touch
    AWS. Bytes never flow through the API: the browser PUTs straight to S3 using
    a presigned URL, and downloads via a presigned GET.
  * ``MockVaultStorage`` — deterministic fake URLs (no AWS), wired when
    ``vault_bucket_name`` is unset in local dev so pytest runs offline.

Objects are encrypted at rest by the bucket's **default SSE-KMS** (the aws/s3
managed key, set in CDK), so the presigned PUT does not carry an SSE header —
keeping the browser request simple and the signature stable.

Discipline (R / D-VAULT): the S3 key and the presigned URLs are sensitive. They
are returned only to the authorized caller and must NEVER be logged.
"""

from __future__ import annotations

from typing import Any, Protocol, cast, runtime_checkable

from fastapi import HTTPException, Request

from app.config import Settings, get_settings


@runtime_checkable
class VaultStorage(Protocol):
    """The presigned-URL surface the document router depends on."""

    def upload_url(self, *, key: str, content_type: str) -> str:
        """A short-TTL presigned PUT URL for the browser to upload ``key`` to."""
        ...

    def download_url(self, *, key: str, file_name: str) -> str:
        """A short-TTL presigned GET URL that downloads as ``file_name``."""
        ...


class S3VaultStorage:
    """Real presigner backed by ``boto3.client('s3')`` (lazy)."""

    def __init__(self, *, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._client: Any | None = None

    def _build_client(self) -> Any:
        # Lazy import so boto3 is only loaded when the real client is built;
        # mock-backed tests never pay the cost or need AWS credentials.
        import boto3
        from botocore.config import Config

        # SigV4 is required for SSE-KMS objects; pin it explicitly.
        return boto3.client(
            "s3",
            region_name=self._settings.aws_region,
            config=Config(signature_version="s3v4"),
        )

    def _ensure_client(self) -> Any:
        if self._client is None:
            self._client = self._build_client()
        return self._client

    def upload_url(self, *, key: str, content_type: str) -> str:
        client = self._ensure_client()
        url = client.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": self._settings.vault_bucket_name,
                "Key": key,
                "ContentType": content_type,
            },
            ExpiresIn=self._settings.vault_presigned_ttl_seconds,
        )
        return str(url)

    def download_url(self, *, key: str, file_name: str) -> str:
        client = self._ensure_client()
        # quote the filename for the Content-Disposition header.
        from urllib.parse import quote

        disposition = f'attachment; filename="{quote(file_name)}"'
        url = client.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": self._settings.vault_bucket_name,
                "Key": key,
                "ResponseContentDisposition": disposition,
            },
            ExpiresIn=self._settings.vault_presigned_ttl_seconds,
        )
        return str(url)


class MockVaultStorage:
    """Deterministic fake URLs for AWS-free local dev + tests.

    The URLs are syntactically plausible but point nowhere — they let the API
    contract (init → upload → confirm → download) be exercised end-to-end without
    S3. A real byte PUT is only exercised against a deployed bucket (F2 staging).
    """

    _BASE = "https://mock-s3.local"

    def upload_url(self, *, key: str, content_type: str) -> str:
        return f"{self._BASE}/{key}?op=put&content-type={content_type}"

    def download_url(self, *, key: str, file_name: str) -> str:
        return f"{self._BASE}/{key}?op=get&filename={file_name}"


def get_vault_storage(request: Request) -> VaultStorage:
    """Return the process-wide VaultStorage stashed on app.state by the lifespan.

    Mirrors ``get_agent_runtime`` — tests override this dependency to inject a
    ``MockVaultStorage`` (or a spy) without touching AWS.
    """
    storage = getattr(request.app.state, "vault_storage", None)
    if storage is None:  # pragma: no cover — guarded by lifespan startup
        raise HTTPException(status_code=503, detail="vault_storage_not_configured")
    return cast(VaultStorage, storage)
