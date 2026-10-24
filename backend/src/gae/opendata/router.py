"""Read-only open-data endpoints. Responses are private and must not be cached."""

from collections.abc import Iterator
from dataclasses import asdict
from datetime import date
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from gae.opendata.epc import EPCClient
from gae.opendata.http import DataUnavailable
from gae.opendata.weather import WeatherClient
from gae.settings import Settings, get_settings

router = APIRouter(prefix="/api", tags=["open data"])


def http_client() -> Iterator[httpx.Client]:
    with httpx.Client() as client:
        yield client


Client = Annotated[httpx.Client, Depends(http_client)]
Config = Annotated[Settings, Depends(get_settings)]


def _run(response: Response, action):
    response.headers["Cache-Control"] = "no-store, private"
    try:
        return action()
    except DataUnavailable as exc:
        raise HTTPException(
            exc.status_code, str(exc), headers={"Cache-Control": "no-store"}
        ) from None
    except ValueError as exc:
        raise HTTPException(422, str(exc), headers={"Cache-Control": "no-store"}) from None


class EpcSearchRequest(BaseModel):
    postcode: str = Field(max_length=10)


class EpcCertificateRequest(BaseModel):
    certificate_id: str


class DegreeDaysRequest(BaseModel):
    postcode: str = Field(max_length=10)
    start: date
    end: date


# Identifying inputs belong in bodies: platform request logs record URLs.
@router.post("/epc/search")
def epc_search(
    request: EpcSearchRequest,
    response: Response,
    client: Client,
    settings: Config,
):
    return _run(
        response,
        lambda: {"addresses": EPCClient(client, settings.epc_api_token).search(request.postcode)},
    )


@router.post("/epc/certificate")
def epc_certificate(
    request: EpcCertificateRequest, response: Response, client: Client, settings: Config
):
    return _run(
        response,
        lambda: EPCClient(client, settings.epc_api_token).certificate(request.certificate_id),
    )


@router.post("/weather/degree-days")
def degree_days(request: DegreeDaysRequest, response: Response, client: Client):
    return _run(
        response,
        lambda: asdict(
            WeatherClient(client).degree_days(request.postcode, request.start, request.end)
        ),
    )
