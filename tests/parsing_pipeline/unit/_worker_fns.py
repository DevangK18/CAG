"""Per-report functions for the --workers tests (a light module the worker processes import)."""


def tag_report(task, emitter, suffix):
    """Return the report ID with a suffix, raising one red flag."""
    emitter.emit_red_flag("6", "test flag", {"n": 1})
    return f"{task.report_id}{suffix}"


def fail_on_b(task, emitter):
    if task.report_id == "B":
        raise ValueError("boom on B")
    return task.report_id


def prior_flag_count(task, emitter):
    """How many red flags the worker's emitter already holds for this report."""
    return len(emitter.get_red_flags(task.report_id))


def crash_first_time(task, emitter):
    """Die like a native crash the first time a report is seen, succeed the second."""
    import os
    import signal
    from pathlib import Path

    marker = Path(task.marker_dir) / task.report_id
    if not marker.exists():
        marker.write_text("crashed")
        os.kill(os.getpid(), signal.SIGSEGV)
    task.processing_status = "layout_complete"
    task.layout = {0: []}
    return task


def crash_always(task, emitter):
    import os
    import signal

    os.kill(os.getpid(), signal.SIGSEGV)


def hang_on_a(task, emitter):
    """A conversion that never returns for report A; B converts at once."""
    import time

    if task.report_id == "A":
        time.sleep(3600)
    task.processing_status = "layout_complete"
    task.layout = {0: []}
    return task
