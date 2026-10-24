"""FastAPI app. Run with `uv run uvicorn gae.main:app --reload` from backend/."""

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from gae.db.router import router as db_router
from gae.gemini.router import router as gemini_router
from gae.opendata.router import router as opendata_router
from gae.pack.router import router as pack_router
from gae.security import ApiGuard, load_access
from gae.settings import Settings, get_settings
from gae.survey.router import router as survey_router


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Refuse to start rather than serve with a broken or unsafe access configuration.
    load_access(get_settings())
    yield


app = FastAPI(title="Go All-Electric", version="0.1.0", lifespan=lifespan)
app.add_middleware(ApiGuard)
app.include_router(opendata_router)
app.include_router(db_router)
app.include_router(gemini_router)
app.include_router(survey_router)
app.include_router(pack_router)


class Health(BaseModel):
    status: str
    # Booleans only: whether each integration has credentials, never the credentials.
    configured: dict[str, bool]


@app.get("/api/health")
def health(settings: Annotated[Settings, Depends(get_settings)]) -> Health:
    return Health(status="ok", configured=settings.configured())


@app.get("/api/access", include_in_schema=False)
def access() -> dict[str, bool]:
    """A cheap authenticated probe; does not consume the Gemini allowance."""
    return {"ok": True}


def serve_frontend(directory: Path) -> None:
    """Register after API routes; missing APIs/assets must remain real 404s."""
    if not directory.is_dir():
        return
    app.mount("/assets", StaticFiles(directory=directory / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def frontend(path: str) -> FileResponse:
        candidate = (directory / path).resolve()
        if not candidate.is_relative_to(directory.resolve()) or path.startswith("api/"):
            raise HTTPException(404)
        if candidate.is_file():
            return FileResponse(candidate)
        if "." in Path(path).name:
            raise HTTPException(404)
        return FileResponse(directory / "index.html")


serve_frontend(Path(__file__).parent / "static")
