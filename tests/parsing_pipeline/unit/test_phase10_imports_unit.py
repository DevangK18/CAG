"""The parsing pipeline's Phase 10 code must not need API-only settings (ENTITY_GRAPH_DSN)."""
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]

CODE = """
import sys
from src.batch_pipeline.batch_service import BatchService
from src.batch_pipeline.enrichment.gemini_visual_extractor import GeminiVisualExtractor
from src.core.phase10_models import Phase10ModelConfig
assert Phase10ModelConfig().visual
GeminiVisualExtractor.__init__  # class loads
assert "src.core.config" not in sys.modules, "Phase 10 imports the RAG config"
print("ok")
"""


def test_phase10_modules_import_without_api_settings(tmp_path):
    env = {k: v for k, v in os.environ.items() if k != "ENTITY_GRAPH_DSN"}
    env["PYTHONPATH"] = str(REPO)
    # cwd has no .env, so load_dotenv() cannot supply the DSN either
    out = subprocess.run([sys.executable, "-c", CODE], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr[-2000:]
