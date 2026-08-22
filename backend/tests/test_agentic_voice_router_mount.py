import os
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_wholesale_ops.db")


def test_agentic_voice_router_is_mounted_in_vercel_entrypoint():
    source = (Path(__file__).resolve().parents[1] / "api/index.py").read_text()
    assert "from app.agentic_voice_brain import router as agentic_voice_router" in source
    assert "app.include_router(agentic_voice_router)" in source
