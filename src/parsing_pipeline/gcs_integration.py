"""
GCS Integration for Parsing Pipeline
=====================================

Provides Cloud Storage integration for the parsing pipeline when running
on Compute Engine or locally with GCS bucket.

Usage:
    from src.parsing_pipeline.gcs_integration import (
        is_gcs_enabled,
        download_manifest,
        upload_processed_files,
        sync_raw_pdfs,
    )

Environment Variables:
    DATA_BUCKET: GCS bucket name (e.g., "cag-data-project-id")
    DATA_DIR: Local data directory (default: ./data)
"""

import os
import logging
from pathlib import Path
from typing import Optional, List

logger = logging.getLogger(__name__)

# Configuration
DATA_BUCKET = os.getenv("DATA_BUCKET", "")
DATA_DIR = Path(os.getenv("DATA_DIR", "data"))


def is_gcs_enabled() -> bool:
    """Check if GCS integration is enabled."""
    return bool(DATA_BUCKET)


def get_gcs_client():
    """Get Google Cloud Storage client."""
    try:
        from google.cloud import storage
        return storage.Client()
    except ImportError:
        logger.error("google-cloud-storage not installed")
        return None
    except Exception as e:
        logger.error(f"Failed to initialize GCS client: {e}")
        return None


def download_manifest(manifest_name: str, local_dir: Optional[Path] = None) -> Path:
    """
    Download manifest file from GCS if not present locally.

    Args:
        manifest_name: Name of the manifest file (e.g., "CAG_Union_Reports.xlsx")
        local_dir: Local directory to save to (default: DATA_DIR)

    Returns:
        Path to local manifest file
    """
    local_dir = local_dir or DATA_DIR
    local_path = local_dir / manifest_name

    # Check if already exists locally
    if local_path.exists():
        logger.info(f"Manifest exists locally: {local_path}")
        return local_path

    if not is_gcs_enabled():
        # Local mode - expect file to exist
        if not local_path.exists():
            raise FileNotFoundError(f"Manifest not found: {local_path}")
        return local_path

    # Download from GCS
    client = get_gcs_client()
    if not client:
        raise RuntimeError("GCS client not available")

    try:
        bucket = client.bucket(DATA_BUCKET)
        gcs_path = f"manifests/{manifest_name}"
        blob = bucket.blob(gcs_path)

        if not blob.exists():
            raise FileNotFoundError(f"Manifest not found in GCS: gs://{DATA_BUCKET}/{gcs_path}")

        local_dir.mkdir(parents=True, exist_ok=True)
        blob.download_to_filename(str(local_path))
        logger.info(f"Downloaded manifest: gs://{DATA_BUCKET}/{gcs_path} -> {local_path}")

        return local_path

    except Exception as e:
        logger.error(f"Failed to download manifest: {e}")
        raise


def upload_pdf(local_path: Path, tier: str) -> bool:
    """
    Upload a PDF to GCS.

    Args:
        local_path: Path to local PDF file
        tier: Government body type (union, state, local_body)

    Returns:
        True if upload successful
    """
    if not is_gcs_enabled():
        return True  # Local mode, no upload needed

    client = get_gcs_client()
    if not client:
        return False

    try:
        bucket = client.bucket(DATA_BUCKET)
        gcs_path = f"raw/{tier}/{local_path.name}"
        blob = bucket.blob(gcs_path)

        blob.upload_from_filename(str(local_path))
        logger.debug(f"Uploaded PDF: {local_path} -> gs://{DATA_BUCKET}/{gcs_path}")
        return True

    except Exception as e:
        logger.warning(f"Failed to upload PDF {local_path}: {e}")
        return False


def upload_processed_file(local_path: Path, tier: str) -> bool:
    """
    Upload a processed JSON file to GCS.

    Args:
        local_path: Path to local JSON file
        tier: Government body type (union, state, local_body)

    Returns:
        True if upload successful
    """
    if not is_gcs_enabled():
        return True  # Local mode, no upload needed

    client = get_gcs_client()
    if not client:
        return False

    try:
        bucket = client.bucket(DATA_BUCKET)
        gcs_path = f"processed/{tier}/{local_path.name}"
        blob = bucket.blob(gcs_path)

        blob.upload_from_filename(str(local_path))
        logger.info(f"Uploaded processed file: gs://{DATA_BUCKET}/{gcs_path}")
        return True

    except Exception as e:
        logger.warning(f"Failed to upload {local_path}: {e}")
        return False


def upload_processed_directory(local_dir: Path) -> int:
    """
    Upload all processed files from a directory to GCS.

    Args:
        local_dir: Local directory containing processed files

    Returns:
        Number of files uploaded
    """
    if not is_gcs_enabled():
        logger.info("GCS not enabled, skipping upload")
        return 0

    client = get_gcs_client()
    if not client:
        return 0

    uploaded = 0
    bucket = client.bucket(DATA_BUCKET)

    # Upload all JSON files
    for tier_dir in ["union", "state", "local_body"]:
        tier_path = local_dir / tier_dir
        if not tier_path.exists():
            continue

        for file_path in tier_path.glob("*.json"):
            try:
                gcs_path = f"processed/{tier_dir}/{file_path.name}"
                blob = bucket.blob(gcs_path)
                blob.upload_from_filename(str(file_path))
                uploaded += 1
                logger.debug(f"Uploaded: {gcs_path}")
            except Exception as e:
                logger.warning(f"Failed to upload {file_path}: {e}")

    # Upload manifest.json if exists
    manifest_path = local_dir / "manifest.json"
    if manifest_path.exists():
        try:
            blob = bucket.blob("processed/manifest.json")
            blob.upload_from_filename(str(manifest_path))
            uploaded += 1
            logger.info("Uploaded manifest.json")
        except Exception as e:
            logger.warning(f"Failed to upload manifest.json: {e}")

    logger.info(f"Uploaded {uploaded} processed files to GCS")
    return uploaded


def sync_raw_pdfs(tier: str, local_dir: Optional[Path] = None) -> int:
    """
    Download raw PDFs from GCS to local directory.

    Args:
        tier: Government body type (union, state, local_body)
        local_dir: Local directory (default: DATA_DIR/raw/{tier})

    Returns:
        Number of files downloaded
    """
    if not is_gcs_enabled():
        return 0

    client = get_gcs_client()
    if not client:
        return 0

    local_dir = local_dir or (DATA_DIR / "raw" / tier)
    local_dir.mkdir(parents=True, exist_ok=True)

    try:
        bucket = client.bucket(DATA_BUCKET)
        prefix = f"raw/{tier}/"

        downloaded = 0
        for blob in bucket.list_blobs(prefix=prefix):
            if blob.name.endswith(".pdf"):
                filename = blob.name.split("/")[-1]
                local_path = local_dir / filename

                if not local_path.exists():
                    blob.download_to_filename(str(local_path))
                    downloaded += 1
                    logger.debug(f"Downloaded: {blob.name}")

        logger.info(f"Downloaded {downloaded} PDFs for {tier}")
        return downloaded

    except Exception as e:
        logger.error(f"Failed to sync PDFs: {e}")
        return 0


def check_pdf_exists_in_gcs(tier: str, filename: str) -> bool:
    """
    Check if a PDF exists in GCS.

    Args:
        tier: Government body type
        filename: PDF filename

    Returns:
        True if exists in GCS
    """
    if not is_gcs_enabled():
        return False

    client = get_gcs_client()
    if not client:
        return False

    try:
        bucket = client.bucket(DATA_BUCKET)
        blob = bucket.blob(f"raw/{tier}/{filename}")
        return blob.exists()
    except Exception:
        return False
