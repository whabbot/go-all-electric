"""FastAPI app. Run with `uv run uvicorn gae.main:app --reload` from backend/."""

from typing import Annotated

from fastapi import Depends, FastAPI
from pydantic import BaseModel

from gae.opendata.router import router as opendata_router
from gae.settings import Settings, get_settings

app = FastAPI(title="Go All-Electric", version="0.1.0")
app.include_router(opendata_router)


class Health(BaseModel):
    status: str
    # Booleans only: whether each integration has credentials, never the credentials.
    configured: dict[str, bool]


@app.get("/api/health")
def health(settings: Annotated[Settings, Depends(get_settings)]) -> Health:
    return Health(status="ok", configured=settings.configured())
