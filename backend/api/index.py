"""Vercel Python entrypoint for the FastAPI application.

The established application assembly is preserved in index_base. This wrapper
adds the public deal-flow router without changing authenticated Owner OS routes.
"""

from api.index_base import app
from app.public_intake import router as public_intake_router

app.include_router(public_intake_router)

__all__ = ["app"]
