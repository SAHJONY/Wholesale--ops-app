import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_wholesale_ops.db")


def test_agentic_voice_router_is_mounted_in_vercel_entrypoint():
    source = open("api/index.py").read()
    assert "from app.agentic_voice_brain import router as agentic_voice_router" in source
    assert "app.include_router(agentic_voice_router)" in source
