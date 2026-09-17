"""
Phase 10 Service: High-level orchestration for Overview & Summary generation.

This is a convenience wrapper around BatchService for programmatic use.
For CLI usage, use submit_jobs.py, check_status.py, and process_results.py.
"""

from pathlib import Path
from datetime import datetime

from .batch_service import BatchService


class Phase10Service:
    """
    High-level orchestrator for Phase 10 processing.
    
    Usage:
        service = Phase10Service()
        
        # Submit jobs for existing reports
        result = service.submit_for_reports(json_files)
        
        # Check if ready
        status = service.get_status()
        
        # Process when ready (use CLI for this)
        # python -m services.batch_pipeline.process_results
    """
    
    def __init__(
        self,
        processed_dir: str = "data/processed",
        jobs_dir: str = "data/batch_jobs"
    ):
        self.processed_dir = Path(processed_dir)
        self.jobs_dir = Path(jobs_dir)
        self.batch_service = BatchService(
            jobs_dir=str(self.jobs_dir),
            processed_dir=str(self.processed_dir)
        )
    
    def submit_for_reports(self, json_files: list[Path]) -> dict:
        """
        Submit Phase 10 batch jobs for a list of report JSON files.
        
        Args:
            json_files: List of *_chunks.json file paths
        
        Returns:
            Dict with batch IDs and tracker path
        """
        print(f"\n{'='*60}")
        print("PHASE 10: Submitting Batch Jobs")
        print(f"{'='*60}")
        print(f"Reports: {len(json_files)}")
        
        # Submit overview batch
        overview_batch_id = self.batch_service.submit_overview_batch(json_files)
        
        # Submit summary batch  
        summary_batch_id = self.batch_service.submit_summary_batch(json_files)
        
        # Create tracker
        report_ids = [f.stem.replace("_chunks", "") for f in json_files]
        tracker_path = self.batch_service.create_job_tracker(
            overview_batch_id=overview_batch_id,
            summary_batch_id=summary_batch_id,
            report_ids=report_ids
        )
        
        return {
            "overview_batch_id": overview_batch_id,
            "summary_batch_id": summary_batch_id,
            "tracker_path": str(tracker_path),
            "report_count": len(json_files),
        }
    
    def get_status(self, tracker_path: Path | None = None) -> dict:
        """
        Get current status of Phase 10 processing.
        
        Returns:
            Dict with status info and readiness flag
        """
        if tracker_path is None:
            tracker_path = self.batch_service.get_latest_job()
        
        if not tracker_path or not tracker_path.exists():
            return {"error": "No job tracker found", "ready": False}
        
        tracker = self.batch_service.update_job_status(tracker_path)
        
        return {
            "job_id": tracker["job_id"],
            "status": tracker["status"],
            "overview_status": tracker["overview_batch"]["status"],
            "summary_status": tracker["summary_batch"]["status"],
            "ready": tracker["status"] == "ready_for_processing",
            "tracker_path": str(tracker_path),
        }
    
    def find_all_chunk_files(self) -> list[Path]:
        """Find all *_chunks.json files in the processed directory."""
        return sorted(self.processed_dir.glob("*_chunks.json"))
    
    def submit_all(self) -> dict:
        """
        Submit Phase 10 jobs for all chunk files in processed directory.
        
        Convenience method equivalent to:
            service.submit_for_reports(service.find_all_chunk_files())
        """
        json_files = self.find_all_chunk_files()
        
        if not json_files:
            return {"error": "No *_chunks.json files found"}
        
        return self.submit_for_reports(json_files)
