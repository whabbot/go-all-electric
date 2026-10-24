"""Platform request logs include URLs: identifying inputs must stay in bodies."""

import re

import pytest
from fastapi import Depends, FastAPI, Query
from fastapi.dependencies.utils import get_flat_params
from fastapi.routing import APIRoute, iter_route_contexts

from gae.main import app


def assert_private_route_urls(application):
    checked = set()
    for route in iter_route_contexts(application.routes):
        path = route.path or ""
        names = [path]
        if isinstance(route.original_route, APIRoute):
            names.extend(
                name
                for field in get_flat_params(route.dependant)
                if field.field_info.in_.value in {"query", "path"}
                for name in (field.name, field.alias)
            )
        for name in names:
            compact = re.sub(r"[^a-z0-9]", "", name.lower())
            assert not re.search(
                r"postcode|certificateid|certificatenumber|uprn|address", compact
            ), f"Identifying URL input on {path}: {name}"
        checked.add(path)
    return checked


def test_all_app_routes_keep_identifiers_out_of_urls():
    checked = assert_private_route_urls(app)
    # Ensure included routers are traversed, not just the app's direct routes.
    assert {"/api/epc/search", "/api/epc/certificate", "/api/weather/degree-days"} <= checked


@pytest.mark.parametrize("name", ["postcode", "certificate_id", "certificateId", "UPRN", "address"])
def test_route_guard_detects_identifying_paths_and_hidden_dependency_queries(name):
    unsafe = FastAPI()
    unsafe.get("/lookup/{" + name + "}")(lambda: None)
    with pytest.raises(AssertionError, match="Identifying URL input"):
        assert_private_route_urls(unsafe)

    def dependency(value: str = Query(alias=name)):
        return value

    unsafe = FastAPI()
    unsafe.get("/lookup", dependencies=[Depends(dependency)], include_in_schema=False)(lambda: None)
    with pytest.raises(AssertionError, match="Identifying URL input"):
        assert_private_route_urls(unsafe)
