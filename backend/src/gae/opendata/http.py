"""Bounded external calls with public, credential-free failure messages."""

from typing import Any

import httpx


class DataUnavailable(Exception):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


def get_json(client: httpx.Client, url: str, *, params=None, headers=None) -> dict[str, Any]:
    try:
        response = client.get(
            url, params=params, headers=headers, timeout=20, follow_redirects=False
        )
        if response.status_code == 404:
            raise DataUnavailable("Couldn't find a matching record.", 404)
        if response.status_code in (401, 403):
            raise DataUnavailable(
                "Data provider credentials were rejected; check server setup.", 503
            )
        if response.status_code == 429:
            raise DataUnavailable("Data provider is rate limited; try again later.", 503)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError
        return payload
    except (httpx.HTTPError, ValueError):
        # Never forward upstream error bodies, URLs, request objects or auth headers.
        raise DataUnavailable("Couldn't read the data provider; try again later.") from None
