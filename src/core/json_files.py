"""Writing JSON files that other threads or processes may read at the same time."""

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Union


def write_json_atomic(path: Union[str, Path], data: Any, **dump_kwargs) -> None:
    """Write to a temporary file in the same directory, then rename over `path`.

    A reader sees either the old file or the new one, never a half-written one.
    """
    path = Path(path)
    dump_kwargs.setdefault("indent", 2)
    dump_kwargs.setdefault("ensure_ascii", False)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, **dump_kwargs)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
