"""Pack route: installer email drafts. Text in, text out: no photos, and nothing is sent."""

from fastapi import APIRouter

from gae.gemini.router import Datasheets, Gemini
from gae.pack.drafts import draft_installer_emails
from gae.pack.schemas import InstallerDraftsRequest, InstallerDraftsResult

router = APIRouter(prefix="/api/pack", tags=["Pack"])


@router.post("/installer-drafts", response_model=InstallerDraftsResult)
def installer_drafts(
    gemini: Gemini, datasheets: Datasheets, body: InstallerDraftsRequest
) -> InstallerDraftsResult:
    """One checked email per quote; a Gemini failure falls back to the template per draft."""
    return draft_installer_emails(gemini, datasheets, body)
