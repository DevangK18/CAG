"""No Flash-Lite model is a default anywhere: every Flash role uses gemini-3.8-flash."""

import dataclasses
import inspect
from pathlib import Path

import src.core.config as core_config
from src.core.phase10_models import Phase10ModelConfig
from src.entity_graph import canonicalizer

SRC = Path(__file__).resolve().parents[2] / "src"


def _model_defaults():
    for obj in vars(core_config).values():
        if dataclasses.is_dataclass(obj) and isinstance(obj, type):
            for f in dataclasses.fields(obj):
                if isinstance(f.default, str) and "gemini" in f.default:
                    yield f"{obj.__name__}.{f.name}", f.default
    for f in dataclasses.fields(Phase10ModelConfig):
        yield f"Phase10ModelConfig.{f.name}", f.default
    for name, fn in inspect.getmembers(canonicalizer, inspect.isfunction):
        for p in inspect.signature(fn).parameters.values():
            if isinstance(p.default, str) and "gemini" in p.default:
                yield f"canonicalizer.{name}({p.name})", p.default


def test_no_default_model_is_lite():
    defaults = dict(_model_defaults())
    assert defaults, "no model defaults found"
    assert not {k: v for k, v in defaults.items() if "lite" in v.lower()}


def test_no_lite_model_named_in_source():
    hits = [
        str(path.relative_to(SRC))
        for path in SRC.rglob("*.py")
        if "flash-lite" in path.read_text(encoding="utf-8").lower()
    ]
    assert hits == []
