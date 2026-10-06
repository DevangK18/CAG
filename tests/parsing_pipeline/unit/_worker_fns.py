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
