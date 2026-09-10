"""
GCS Sync Utility for Cloud Run
==============================

Syncs processed data from Google Cloud Storage to local filesystem on startup.
Cloud Run containers are ephemeral, so data must be synced on cold starts.

The sync is incremental - only downloads files that don't exist locally or
have been modified in GCS.

Usage:
    from src.api.gcs_sync import sync_from_gcs, is_gcs_enabled

    if is_gcs_enabled():
        sync_from_gcs()

Environment Variables:
    DATA_BUCKET: GCS bucket name (e.g., "cag-data-project-id")
    DATA_DIR: Local data directory (default: /app/data)
"""

import os
import logging
from pathlib import Path
from typing import Optional, List

logger = logging.getLogger(__name__)

# Configuration
DATA_BUCKET = os.getenv("DATA_BUCKET", "")
DATA_DIR = Path(os.getenv("DATA_DIR", "/app/data"))


def is_gcs_enabled() -> bool:
    """Check if GCS sync is enabled (DATA_BUCKET is set)."""
    return bool(DATA_BUCKET)


def get_gcs_client():
    """Get Google Cloud Storage client."""
    try:
        from google.cloud import storage
        return storage.Client()
    except ImportError:
        logger.error("google-cloud-storage not installed. Run: pip install google-cloud-storage")
        return None
    except Exception as e:
        logger.error(f"Failed to initialize GCS client: {e}")
        return None


def sync_from_gcs(
    prefixes: Optional[List[str]] = None,
    force: bool = False
) -> int:
    """
    Sync processed data from GCS to local filesystem.

    Args:
        prefixes: List of GCS prefixes to sync (default: ["processed/", "manifests/"])
        force: If True, re-download even if file exists locally

    Returns:
        Number of files downloaded
    """
    if not is_gcs_enabled():
        logger.info("GCS sync disabled (DATA_BUCKET not set)")
        return 0

    client = get_gcs_client()
    if not client:
        return 0

    if prefixes is None:
        prefixes = ["processed/", "manifests/"]

    try:
        bucket = client.bucket(DATA_BUCKET)
        downloaded = 0

        for prefix in prefixes:
            logger.info(f"Syncing gs://{DATA_BUCKET}/{prefix} to {DATA_DIR}")

            blobs = bucket.list_blobs(prefix=prefix)

            for blob in blobs:
                # Skip directory placeholders
                if blob.name.endswith("/") or blob.name.endswith(".placeholder"):
                    continue

                # Calculate local path
                relative_path = blob.name
                local_path = DATA_DIR / relative_path
                local_path.parent.mkdir(parents=True, exist_ok=True)

                # Check if download needed
                should_download = force or not local_path.exists()

                if not should_download and local_path.exists():
                    # Check if GCS version is newer
                    local_mtime = local_path.stat().st_mtime
                    gcs_mtime = blob.updated.timestamp() if blob.updated else 0
                    should_download = gcs_mtime > local_mtime

                if should_download:
                    try:
                        blob.download_to_filename(str(local_path))
                        downloaded += 1
                        logger.debug(f"Downloaded: {blob.name}")
                    except Exception as e:
                        logger.warning(f"Failed to download {blob.name}: {e}")

        logger.info(f"GCS sync complete: {downloaded} files downloaded to {DATA_DIR}")
        return downloaded

    except Exception as e:
        logger.error(f"GCS sync failed: {e}")
        return 0


def upload_to_gcs(
    local_path: Path,
    gcs_prefix: str = "processed/"
) -> bool:
    """
    Upload a local file to GCS.

    Args:
        local_path: Local file path
        gcs_prefix: GCS prefix (default: "processed/")

    Returns:
        True if upload successful
    """
    if not is_gcs_enabled():
        logger.warning("GCS upload disabled (DATA_BUCKET not set)")
        return False

    client = get_gcs_client()
    if not client:
        return False

    try:
        bucket = client.bucket(DATA_BUCKET)

        # Calculate GCS path relative to DATA_DIR
        if local_path.is_relative_to(DATA_DIR):
            relative_path = local_path.relative_to(DATA_DIR)
        else:
            relative_path = local_path.name

        gcs_path = f"{gcs_prefix.rstrip('/')}/{relative_path}"
        blob = bucket.blob(gcs_path)

        blob.upload_from_filename(str(local_path))
        logger.info(f"Uploaded: {local_path} -> gs://{DATA_BUCKET}/{gcs_path}")
        return True

    except Exception as e:
        logger.error(f"Failed to upload {local_path}: {e}")
        return False


def sync_directory_to_gcs(
    local_dir: Path,
    gcs_prefix: str
) -> int:
    """
    Sync an entire local directory to GCS.

    Args:
        local_dir: Local directory to sync
        gcs_prefix: GCS prefix to upload to

    Returns:
        Number of files uploaded
    """
    if not is_gcs_enabled():
        logger.warning("GCS sync disabled (DATA_BUCKET not set)")
        return 0

    if not local_dir.exists():
        logger.warning(f"Directory does not exist: {local_dir}")
        return 0

    uploaded = 0
    for file_path in local_dir.rglob("*"):
        if file_path.is_file():
            relative = file_path.relative_to(local_dir)
            gcs_path = f"{gcs_prefix.rstrip('/')}/{relative}"
            if upload_to_gcs(file_path, gcs_prefix):
                uploaded += 1

    logger.info(f"Synced {uploaded} files from {local_dir} to gs://{DATA_BUCKET}/{gcs_prefix}")
    return uploaded


def list_gcs_files(prefix: str = "processed/") -> List[str]:
    """
    List files in GCS bucket.

    Args:
        prefix: GCS prefix to list

    Returns:
        List of file names
    """
    if not is_gcs_enabled():
        return []

    client = get_gcs_client()
    if not client:
        return []

    try:
        bucket = client.bucket(DATA_BUCKET)
        blobs = bucket.list_blobs(prefix=prefix)

        files = []
        for blob in blobs:
            if not blob.name.endswith("/") and not blob.name.endswith(".placeholder"):
                files.append(blob.name)

        return files

    except Exception as e:
        logger.error(f"Failed to list GCS files: {e}")
        return []


def get_manifest_path() -> Path:
    """
    Get the path to manifest.json, syncing from GCS if needed.

    Returns:
        Path to local manifest.json
    """
    local_manifest = DATA_DIR / "processed" / "manifest.json"

    if not local_manifest.exists() and is_gcs_enabled():
        # Try to sync just the manifest
        sync_from_gcs(prefixes=["processed/manifest.json"])

    return local_manifest
