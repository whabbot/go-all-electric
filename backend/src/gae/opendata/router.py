"""Read-only open-data endpoints. Responses are private and must not be cached."""

from collections.abc import Iterator
from dataclasses import asdict
from datetime import date
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Response

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


@router.get("/epc/search")
def epc_search(
    response: Response,
    client: Client,
    settings: Config,
    postcode: Annotated[str, Query(max_length=10)],
):
    return _run(
        response, lambda: {"addresses": EPCClient(client, settings.epc_api_token).search(postcode)}
    )


@router.get("/epc/{certificate_id}")
def epc_certificate(certificate_id: str, response: Response, client: Client, settings: Config):
    return _run(
        response, lambda: EPCClient(client, settings.epc_api_token).certificate(certificate_id)
    )


@router.get("/weather/degree-days")
def degree_days(
    response: Response,
    client: Client,
    postcode: Annotated[str, Query(max_length=10)],
    start: date,
    end: date,
):
    return _run(response, lambda: asdict(WeatherClient(client).degree_days(postcode, start, end)))
