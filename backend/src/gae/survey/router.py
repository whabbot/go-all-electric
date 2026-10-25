"""Survey routes: the end-to-end analysis (streamed) and the one-context review that follows it.

`POST /api/analysis` streams newline-delimited JSON events so the UI can show the verification
loop as it runs: `step` (progress), `log` (one verification entry), then exactly one `result`
or `error`. Uploads are read into memory before the stream starts and dropped with the request.
"""

import base64
import json
import logging
import queue
import threading
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import ValidationError

from gae.db.connection import database
from gae.db.datasheets import AtlasDatasheetLookup, DatasheetLookup
from gae.db.models import SurveyInput
from gae.db.seed import load_seed
from gae.db.surveys import SurveyRepository
from gae.gemini.client import GeminiError, StructuredModel
from gae.gemini.datasheets import InMemoryDatasheetLookup
from gae.gemini.review import review
from gae.gemini.router import (
    MAX_QUOTE_PAGES,
    MAX_REVIEW_BYTES,
    SeedFallbackLookup,
    _gemini_failed,
    _read,
    _read_video,
    get_gemini,
)
from gae.gemini.schemas import MathsBundle, MediaInput, PhotoKind, QuoteInput, ReviewRequest
from gae.gemini.schemas import ReviewResult as GeminiReviewResult
from gae.opendata.epc import CERTIFICATE_PATTERN, EPCClient
from gae.opendata.http import DataUnavailable
from gae.opendata.weather import WeatherClient
from gae.plan.solar import LiveSolarYield
from gae.settings import Settings, get_settings
from gae.survey.analysis import AnalysisRefused, Services, run_analysis
from gae.survey.known import MAX_RADIATORS, KnownDetails
from gae.survey.schemas import ReviewContext

router = APIRouter(prefix="/api", tags=["Survey"])
logger = logging.getLogger(__name__)

ServicesFactory = Callable[[], AbstractContextManager[Services]]


@contextmanager
def datasheet_lookup() -> Iterator[DatasheetLookup]:
    """Atlas when configured (falling back to the public seed on errors), else the seed."""
    uri = get_settings().mongodb_uri
    if uri is None or not uri.get_secret_value().strip():
        yield InMemoryDatasheetLookup(load_seed())
        return
    with database() as db:
        yield SeedFallbackLookup(AtlasDatasheetLookup(db["datasheets"]))


def save_to_atlas(survey: SurveyInput) -> str:
    with database() as db:
        return SurveyRepository(db["surveys"]).create(survey).id


def get_services(
    settings: Annotated[Settings, Depends(get_settings)],
    gemini: Annotated[StructuredModel, Depends(get_gemini)],
) -> ServicesFactory:
    # A factory, not a yield dependency: the analysis runs while the response streams, after
    # FastAPI would have closed request-scoped resources.
    @contextmanager
    def open_services() -> Iterator[Services]:
        with httpx.Client() as http, datasheet_lookup() as lookup:
            yield Services(
                gemini=gemini,
                epc=EPCClient(http, settings.epc_api_token).mapped,
                weather=WeatherClient(http),
                datasheets=lookup,
                save=save_to_atlas,
                solar=LiveSolarYield(http),
            )

    return open_services


Factory = Annotated[ServicesFactory, Depends(get_services)]
Upload = Annotated[UploadFile | None, File()]
MAX_PHOTOS_PER_RADIATOR = 3


def _radiator_groups(
    uploads: list[UploadFile], index: list[int], known: KnownDetails | None
) -> list[list[UploadFile]]:
    """Photos grouped by radiator: several photos of one radiator are one radiator."""
    if not index and len(uploads) == 1:
        index = [0]
    if len(index) != len(uploads):
        raise HTTPException(422, "Each radiator photo needs a radiator_index")
    count = max([i + 1 for i in index] + [len(known.radiators) if known else 0])
    if any(i < 0 for i in index) or count > MAX_RADIATORS:
        raise HTTPException(422, f"Add at most {MAX_RADIATORS} radiators.")
    groups: list[list[UploadFile]] = [[] for _ in range(count)]
    for upload, i in zip(uploads, index, strict=True):
        groups[i].append(upload)
    if any(len(g) > MAX_PHOTOS_PER_RADIATOR for g in groups):
        raise HTTPException(422, f"Add at most {MAX_PHOTOS_PER_RADIATOR} photos per radiator.")
    return groups


def _known(raw: str | None) -> KnownDetails | None:
    if raw is None:
        return None
    try:
        return KnownDetails.model_validate_json(raw)
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(part) for part in first["loc"])
        # The message names the rule broken, never echoes the value sent.
        message = f"Check the details you entered ({where}): {first['msg']}"
        raise HTTPException(422, message) from None


@router.post("/analysis")
def analyse(
    services: Factory,
    certificate_id: Annotated[str, Form(pattern=CERTIFICATE_PATTERN)],
    boiler_plate: Upload = None,
    radiators: Annotated[list[UploadFile] | None, File()] = None,
    radiator_index: Annotated[list[int] | None, Form()] = None,
    known: Annotated[str | None, Form(max_length=10_000)] = None,
    radiator_video: Upload = None,
    fuse_cutout: Upload = None,
    outdoor_space: Upload = None,
    gas_bill: Annotated[list[UploadFile] | None, File()] = None,
    loft: Upload = None,
) -> StreamingResponse:
    entered = _known(known)
    rad_groups = _radiator_groups(radiators or [], radiator_index or [], entered)
    uploads = {
        PhotoKind.BOILER_PLATE: boiler_plate,
        PhotoKind.FUSE_CUTOUT: fuse_cutout,
        PhotoKind.OUTDOOR_SPACE: outdoor_space,
        PhotoKind.LOFT: loft,
    }
    files = {kind: _read(upload) for kind, upload in uploads.items() if upload is not None}
    if len(gas_bill or []) > 6:
        raise HTTPException(422, "Up to 6 gas bill photos")
    bill_files = [_read(upload) for upload in gas_bill or []]
    rad_files = [[_read(upload) for upload in group] for group in rad_groups]
    total_photo_bytes = sum(len(data) for data, _ in files.values()) + sum(
        len(data) for group in rad_files for data, _ in group
    )
    total_photo_bytes += sum(len(data) for data, _ in bill_files)
    if total_photo_bytes > MAX_REVIEW_BYTES:
        raise HTTPException(413, "Attachments too large for one analysis: 18 MB maximum")
    raw_video = _read_video(radiator_video) if radiator_video is not None else None
    events: queue.Queue[dict | None] = queue.Queue()

    def work() -> None:
        nonlocal raw_video
        try:
            with services() as live:
                result = run_analysis(
                    live,
                    certificate_id,
                    files,
                    events.put,
                    radiator_video=raw_video,
                    radiator_files=rad_files,
                    known=entered,
                    bill_files=bill_files,
                )
            events.put({"type": "result", "result": result.model_dump(mode="json")})
        except AnalysisRefused as exc:
            events.put({"type": "error", "status": exc.status_code, "message": str(exc)})
        except DataUnavailable as exc:
            events.put({"type": "error", "status": exc.status_code, "message": str(exc)})
        except ValueError as exc:
            events.put({"type": "error", "status": 422, "message": str(exc)})
        except Exception as exc:
            # Type only: messages can echo request content.
            logger.error("analysis failed (%s)", type(exc).__name__)
            events.put(
                {"type": "error", "status": 500, "message": "The analysis failed; try again."}
            )
        finally:
            files.clear()
            rad_files.clear()
            raw_video = None
            events.put(None)

    threading.Thread(target=work, daemon=True).start()

    def stream() -> Iterator[str]:
        while (event := events.get()) is not None:
            yield json.dumps(event) + "\n"

    return StreamingResponse(
        stream(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-store, private", "X-Accel-Buffering": "no"},
    )


def _media(kind: str, upload: UploadFile, radiator: int | None = None) -> MediaInput:
    data, mime = _read(upload)
    return MediaInput(
        kind=kind,
        data_base64=base64.b64encode(data).decode("ascii"),
        mime_type=mime,
        radiator=radiator,
    )


@router.post("/analysis/review", response_model=GeminiReviewResult)
def review_analysis(
    gemini: Annotated[StructuredModel, Depends(get_gemini)],
    context: Annotated[str, Form(max_length=200_000)],
    boiler_plate: Upload = None,
    radiators: Annotated[list[UploadFile] | None, File()] = None,
    radiator_index: Annotated[list[int] | None, Form()] = None,
    fuse_cutout: Upload = None,
    outdoor_space: Upload = None,
    gas_bill: Annotated[list[UploadFile] | None, File()] = None,
    loft: Upload = None,
    quotes: Annotated[list[UploadFile] | None, File()] = None,
    quote_index: Annotated[list[int] | None, Form()] = None,
) -> GeminiReviewResult:
    """One Argon context over everything, after the bundle is on screen (1.5-2 minutes)."""
    try:
        ctx = ReviewContext.model_validate_json(context)
    except ValidationError:
        raise HTTPException(422, "Send the analysis bundle and readings as context") from None
    rad_groups = _radiator_groups(radiators or [], radiator_index or [], None)
    quotes = quotes or []
    quote_index = quote_index or []
    if len(quotes) != len(quote_index) or any(not 0 <= i < len(ctx.quotes) for i in quote_index):
        raise HTTPException(422, "Each quote page needs a quote_index matching context.quotes")
    pages: dict[int, list[MediaInput]] = {}
    for upload, i in zip(quotes, quote_index, strict=True):
        pages.setdefault(i, []).append(_media("quote", upload))
    if any(len(p) > MAX_QUOTE_PAGES for p in pages.values()):
        raise HTTPException(422, "Eight pages per quote at most")
    photos: list[MediaInput] = []
    if boiler_plate is not None:
        photos.append(_media("boiler_plate", boiler_plate))
    for number, group in enumerate(rad_groups, start=1):
        photos.extend(_media("radiators", upload, number) for upload in group)
    for kind, upload in (
        ("fuse_cutout", fuse_cutout),
        ("outdoor_space", outdoor_space),
        ("loft", loft),
    ):
        if upload is not None:
            photos.append(_media(kind, upload))
    if len(gas_bill or []) > 6:
        raise HTTPException(422, "Up to 6 gas bill photos")
    photos.extend(_media("gas_bill", upload) for upload in (gas_bill or [])[1:])
    request = ReviewRequest(
        photos=photos,
        bill=_media("gas_bill", gas_bill[0]) if gas_bill else None,
        # Building fields only; review.py allowlists again before anything reaches Gemini.
        epc_record=ctx.epc.model_dump(mode="json"),
        boiler=ctx.boiler,
        bill_reading=ctx.bill,
        radiators=ctx.radiators,
        radiator_video=ctx.radiator_video,
        fuse_cutout=ctx.fuse_cutout,
        outdoor_space=ctx.outdoor_space,
        loft=ctx.loft,
        entered=ctx.entered,
        quotes=[
            QuoteInput(
                quote_id=q.quote_id,
                reading=q.reading,
                document=pages[i][0] if pages.get(i) else None,
                pages=pages.get(i, [])[1:],
            )
            for i, q in enumerate(ctx.quotes)
        ],
        maths=MathsBundle(
            measured=ctx.bundle.measured or {},
            fabric=ctx.bundle.fabric,
            cross_check=ctx.bundle.cross_check or {},
            costs_by_flow_temp=ctx.bundle.costs_by_flow_temp,
            target_spec=ctx.bundle.target_spec,
        ),
    )
    documents = [page for group in pages.values() for page in group]
    media = [*request.photos, *([request.bill] if request.bill else []), *documents]
    if sum(len(m.data_base64) * 3 // 4 for m in media) > MAX_REVIEW_BYTES:
        raise HTTPException(413, "Attachments too large for one review: 18 MB maximum")
    try:
        with datasheet_lookup() as lookup:
            return review(gemini, lookup, request, purpose="/api/analysis/review")
    except GeminiError as exc:
        raise _gemini_failed(exc) from None
