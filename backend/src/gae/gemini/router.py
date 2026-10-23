"""Gemini routes: instant photo check, verified extraction, quote checker, one-context review.

Uploads are read into memory, sent to Gemini and dropped with the request: nothing is written
to disk or the database here, and responses carry readings, never images.
"""

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pymongo.errors import PyMongoError
from starlette.formparsers import MultiPartParser

from gae.db.connection import DatabaseUnavailable, database
from gae.db.datasheets import AtlasDatasheetLookup, DatasheetLookup
from gae.db.models import Datasheet
from gae.db.seed import load_seed
from gae.gemini.client import GeminiClient, GeminiError, GeminiNotConfigured, StructuredModel
from gae.gemini.datasheets import InMemoryDatasheetLookup
from gae.gemini.extract import extract, glance
from gae.gemini.quotes import SizeContext, flag_quote
from gae.gemini.review import review
from gae.gemini.sanitize import sanitize_image
from gae.gemini.schemas import (
    PhotoCheckResult,
    PhotoKind,
    QuoteCheckResult,
    RadiatorVideoResult,
    ReviewRequest,
    ReviewResult,
    VerifiedReading,
)
from gae.gemini.video import (
    ALLOWED_VIDEO_MIMES,
    MAX_VIDEO_BYTES,
    extract_radiator_video,
    sanitize_video,
)
from gae.settings import Settings, get_settings

MAX_UPLOAD_BYTES = 15 * 1024 * 1024
MAX_REVIEW_BYTES = 18 * 1024 * 1024
MAX_QUOTES_PER_REQUEST = 5
MAX_QUOTE_PAGES = 8
# Starlette spools uploads over 1 MB to a temp file; keep them in memory up to the cap instead.
MultiPartParser.spool_max_size = MAX_VIDEO_BYTES

router = APIRouter(prefix="/api", tags=["Gemini"])


def get_gemini(settings: Annotated[Settings, Depends(get_settings)]) -> StructuredModel:
    if settings.gemini_api_key is None:
        raise HTTPException(503, "Gemini is not configured on the server")
    try:
        return GeminiClient(
            settings.gemini_api_key,
            lead_model=settings.gemini_lead_model,
            fast_model=settings.gemini_fast_model,
        )
    except GeminiNotConfigured:
        raise HTTPException(503, "Gemini is not configured on the server") from None


class SeedFallbackLookup:
    """Atlas first; on a database error, the public seed in memory, so a read still checks."""

    def __init__(self, primary: DatasheetLookup):
        self.primary = primary
        self.fallback = InMemoryDatasheetLookup(load_seed())

    def find_by_make_model(self, text: str, limit: int = 5) -> list[Datasheet]:
        try:
            return self.primary.find_by_make_model(text, limit)
        except PyMongoError:
            return self.fallback.find_by_make_model(text, limit)

    def get_full_datasheet_text(self, datasheet_id: str) -> str | None:
        try:
            return self.primary.get_full_datasheet_text(datasheet_id)
        except PyMongoError:
            return self.fallback.get_full_datasheet_text(datasheet_id)

    def search_by_spec(self, **kwargs) -> list[Datasheet]:
        try:
            return self.primary.search_by_spec(**kwargs)
        except PyMongoError:
            return self.fallback.search_by_spec(**kwargs)


def get_datasheets() -> Iterator[DatasheetLookup]:
    try:
        with database() as db:
            yield SeedFallbackLookup(AtlasDatasheetLookup(db["datasheets"]))
    except DatabaseUnavailable:
        yield InMemoryDatasheetLookup(load_seed())


Gemini = Annotated[StructuredModel, Depends(get_gemini)]
Datasheets = Annotated[DatasheetLookup, Depends(get_datasheets, scope="function")]


def _read(upload: UploadFile) -> tuple[bytes, str]:
    mime = (upload.content_type or "").lower()
    if not (mime.startswith("image/") or mime == "application/pdf"):
        raise HTTPException(415, "Upload a photo (JPEG, PNG, HEIC, WebP) or a PDF")
    data = upload.file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File too large: 15 MB maximum")
    if not data:
        raise HTTPException(422, "Empty file")
    if mime.startswith("image/"):
        data, mime = sanitize_image(data, mime)
    return data, mime


def _read_video(upload: UploadFile) -> tuple[bytes, str]:
    mime = (upload.content_type or "").split(";", 1)[0].strip().lower()
    if mime in ("video/x-m4v", "video/mp4v-es"):
        mime = "video/mp4"
    elif mime == "video/mov":
        mime = "video/quicktime"
    if mime not in ALLOWED_VIDEO_MIMES:
        raise HTTPException(415, "Upload an MP4, MOV or WebM video clip")
    data = upload.file.read(MAX_VIDEO_BYTES + 1)
    if len(data) > MAX_VIDEO_BYTES:
        raise HTTPException(413, "Video too large: 100 MB maximum")
    if not data:
        raise HTTPException(422, "Empty video file")
    try:
        clean_data, norm_mime, _ = sanitize_video(data, mime)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    return clean_data, norm_mime


def _gemini_failed() -> HTTPException:
    # No upstream detail: it can echo request content.
    return HTTPException(502, "Gemini couldn't read this right now; please try again")


@router.post("/photos/check", response_model=PhotoCheckResult)
def check_photo(
    gemini: Gemini, kind: Annotated[PhotoKind, Form()], file: Annotated[UploadFile, File()]
) -> PhotoCheckResult:
    data, mime = _read(file)
    try:
        return glance(gemini, kind, data, mime)
    except GeminiError:
        raise _gemini_failed() from None


@router.post("/photos/extract", response_model=VerifiedReading)
def extract_photo(
    gemini: Gemini,
    datasheets: Datasheets,
    kind: Annotated[PhotoKind, Form()],
    file: Annotated[UploadFile, File()],
) -> VerifiedReading:
    data, mime = _read(file)
    try:
        return extract(gemini, datasheets, kind, data, mime)
    except GeminiError:
        raise _gemini_failed() from None


@router.post("/radiators/video", response_model=RadiatorVideoResult)
def check_radiator_video_route(
    gemini: Gemini,
    file: Annotated[UploadFile, File()],
    design_load_kw: Annotated[float | None, Form()] = None,
) -> RadiatorVideoResult:
    data, mime = _read_video(file)
    try:
        return extract_radiator_video(gemini, data, mime, design_load_kw=design_load_kw)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    except GeminiError:
        raise _gemini_failed() from None


@router.post("/quotes/check", response_model=list[QuoteCheckResult])
def check_quotes(
    gemini: Gemini,
    datasheets: Datasheets,
    quotes: Annotated[list[UploadFile], File()],
    quote_index: Annotated[list[int], Form()],
    quote_name: Annotated[list[str], Form()],
    size_low_kw: Annotated[float | None, Form()] = None,
    size_high_kw: Annotated[float | None, Form()] = None,
    design_load_kw: Annotated[float | None, Form()] = None,
) -> list[QuoteCheckResult]:
    if len(quotes) != len(quote_index) or len(quotes) != len(quote_name):
        raise HTTPException(422, "Each page needs a quote_index and quote_name")
    grouped: dict[int, list[tuple[bytes, str]]] = {}
    names: dict[int, str] = {}
    for upload, idx, name in zip(quotes, quote_index, quote_name, strict=True):
        data, mime = _read(upload)
        grouped.setdefault(idx, []).append((data, mime))
        names[idx] = name.strip() or upload.filename or "quote"
    if len(grouped) > MAX_QUOTES_PER_REQUEST:
        raise HTTPException(422, "Five quotes at most")
    for pages in grouped.values():
        if len(pages) > MAX_QUOTE_PAGES:
            raise HTTPException(422, "Eight pages per quote at most")
    size = None
    if size_low_kw is not None and size_high_kw is not None:
        size = SizeContext(size_low_kw, size_high_kw, design_load_kw)
    order = sorted(grouped)
    # Each quote is an independent read: run them together so three quotes take one read's time.
    with ThreadPoolExecutor(max_workers=len(order) or 1) as pool:
        futures = []
        for idx in order:
            (first_data, first_mime), *rest = grouped[idx]
            futures.append(
                pool.submit(
                    extract,
                    gemini,
                    datasheets,
                    "quote",
                    first_data,
                    first_mime,
                    media_parts=rest or None,
                )
            )
        try:
            verified = [future.result() for future in futures]
        except GeminiError:
            raise _gemini_failed() from None
    return [flag_quote(names[idx], v, size) for idx, v in zip(order, verified, strict=True)]


@router.post("/review", response_model=ReviewResult)
def review_all(gemini: Gemini, datasheets: Datasheets, body: ReviewRequest) -> ReviewResult:
    media = [*body.photos, *([body.bill] if body.bill else [])]
    media += [page for q in body.quotes if q.document for page in (q.document, *q.pages)]
    # Gemini caps inline data at 20 MB per request, prompt included.
    if sum(len(m.data_base64) * 3 // 4 for m in media) > MAX_REVIEW_BYTES:
        raise HTTPException(413, "Attachments too large for one review: 18 MB maximum")
    try:
        return review(gemini, datasheets, body)
    except GeminiError:
        raise _gemini_failed() from None
    except ValueError:
        raise HTTPException(422, "Attachments must be base64 photos or PDFs") from None
