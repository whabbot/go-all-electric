import copy
import json
from dataclasses import asdict, replace
from datetime import date, timedelta
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from gae.heatpump.measured import estimate_measured
from gae.main import app
from gae.opendata.bill import measured_from_bill, measured_from_degree_days
from gae.opendata.epc import EPCClient
from gae.opendata.http import DataUnavailable
from gae.opendata.mapping import map_epc
from gae.opendata.router import http_client
from gae.opendata.weather import WeatherClient, degree_days_from_daily
from gae.settings import Settings, get_settings

FIXTURES = Path(__file__).parent / "fixtures"
POSTCODE = "ZZ1 1ZZ"  # deliberately synthetic, no real home or real bill
TOKEN = "synthetic-bearer-for-test"
START, END = date(2023, 7, 1), date(2024, 6, 30)


def fixture(name):
    return json.loads((FIXTURES / name).read_text())


def client_for(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def annual_weather(start=START, end=END):
    days = (end - start).days + 1
    return degree_days_from_daily(
        POSTCODE,
        start,
        end,
        {
            "time": [(start + timedelta(days=i)).isoformat() for i in range(days)],
            "temperature_2m_mean": [10.5] * days,
        },
    )


def test_new_epc_schema_feeds_existing_maths_and_never_leaks_token():
    seen = []

    def handle(request):
        seen.append(request)
        assert request.headers["authorization"] == "Bearer " + TOKEN
        assert request.url.host == "api.get-energy-performance-data.communities.gov.uk"
        if request.url.path == "/api/certificate":
            assert request.url.params["certificate_number"] == "1111-2222-3333-4444-5555"
            return httpx.Response(200, json=fixture("certificate.json"))
        assert request.url.path == "/api/codes/info"
        assert request.url.params["schemaVersion"] == "RdSAP-Schema-21.0.1"
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "key": "C",
                        "values": [
                            {
                                "value": "1930-1949",
                                "assessmentType": "RdSAP",
                                "schemaVersion": "RdSAP-Schema-21.0.1",
                            }
                        ],
                    }
                ]
            },
        )

    result = EPCClient(client_for(handle), SecretStr(TOKEN)).certificate("1111-2222-3333-4444-5555")
    assert len(seen) == 4
    assert result["fabric_inputs"]["year_built"] == 1930
    assert result["fabric_inputs"]["loft_insulation_mm"] == 100
    assert result["estimate"]["design_load_kw"]["central"] > 0
    assert result["main_heating_fuel"] == "gas"
    assert result["confidence"]["glazing"]["confidence"] == "low"
    assert TOKEN not in str(result)


def test_search_paginates_then_picks_latest_per_home():
    def handle(request):
        page = int(request.url.params["current_page"])
        row = {
            "uprn": 123,
            "addressLine1": "1 Synthetic Example Lane",
            "postcode": POSTCODE,
            "registrationDate": f"202{page}-01-01",
            "certificateNumber": f"1111-2222-3333-4444-{page:04}",
        }
        return httpx.Response(
            200,
            json={
                "data": [row],
                "pagination": {
                    "nextPage": 2 if page == 1 else None,
                },
            },
        )

    result = EPCClient(client_for(handle), SecretStr(TOKEN)).search("zz11zz")
    assert len(result) == 1
    assert result[0]["registration_date"] == "2022-01-01"


def test_search_empty_and_unconfigured():
    client = client_for(lambda _: httpx.Response(404))
    assert EPCClient(client, SecretStr(TOKEN)).search(POSTCODE) == []
    client_400 = client_for(lambda _: httpx.Response(400))
    assert EPCClient(client_400, SecretStr(TOKEN)).search(POSTCODE) == []
    with pytest.raises(DataUnavailable, match="EPC_API_TOKEN"):
        EPCClient(client, None).search(POSTCODE)


@pytest.mark.parametrize("status", [401, 403, 429, 500, 302])
def test_error_bodies_never_leak_credentials(status):
    client = client_for(lambda _: httpx.Response(status, text=TOKEN))
    with pytest.raises(DataUnavailable) as exc:
        EPCClient(client, SecretStr(TOKEN)).certificate("1111-2222-3333-4444-5555")
    assert TOKEN not in str(exc.value)


def test_ambiguous_elements_have_named_low_confidence_defaults():
    record = fixture("certificate.json")["data"]
    record["walls"].append({"description": "Solid brick, insulated"})
    record["roofs"] = [{"description": "Flat, insulated"}]
    record["floors"] = [{"description": "Other premises below"}]
    result = map_epc(record)
    for field in ("year_built", "wall_type", "loft_insulation_mm", "floor_insulated"):
        assert result.confidence[field].confidence == "low"
        assert result.confidence[field].default is not None
    assert result.fabric_inputs["floor_insulated"] is False


@pytest.mark.parametrize(
    "label, expected",
    [
        ("Solid brick, no insulation (assumed)", "solid_brick"),
        ("Solid brick, with external insulation", "solid_insulated"),
        ("Cavity wall, filled cavity", "cavity_filled"),
        ("Cavity wall, as built, insulated (assumed)", "cavity_filled"),
    ],
)
def test_wall_mapping_handles_negative_insulation(label, expected):
    record = fixture("certificate.json")["data"]
    record["walls"] = [{"description": label}]
    assert map_epc(record).fabric_inputs["wall_type"] == expected


def test_unsupported_geometry_and_missing_area_do_not_invent_estimates():
    record = fixture("certificate.json")["data"]
    record["dwelling_type"] = "Ground-floor flat"
    assert map_epc(record).estimate is None
    record["dwelling_type"] = "Semi-detached house"
    record["total_floor_area"] = "NaN"
    result = map_epc(record)
    assert result.estimate is None and "floor area" in result.reason
    assert result.fabric_inputs["floor_area_m2"] is None


def test_boiler_is_not_misclassified_as_oil():
    record = fixture("certificate.json")["data"]
    record["main_heating"] = [{"description": "Boiler and radiators, anthracite"}]
    assert map_epc(record).main_heating_fuel == "other"


def test_centroid_and_exact_weather_request():
    seen = []

    def handle(request):
        seen.append(request)
        if request.url.host == "api.postcodes.io":
            return httpx.Response(200, json={"result": {"latitude": 51.5, "longitude": -0.1}})
        assert request.url.host == "archive-api.open-meteo.com"
        assert request.url.params["daily"] == "temperature_2m_mean"
        assert request.url.params["timezone"] == "Europe/London"
        assert request.url.params["start_date"] == "2024-01-01"
        return httpx.Response(200, json=fixture("weather.json"))

    result = WeatherClient(client_for(handle)).degree_days(
        POSTCODE, date(2024, 1, 1), date(2024, 1, 3)
    )
    assert result.heating_degree_days == 15
    assert result.missing_day_count == 0 and result.days_expected == 3
    assert result.base_temperature_c == 15.5
    assert "latitude" not in asdict(result) and "longitude" not in asdict(result)
    assert len(seen) == 2


@pytest.mark.parametrize("temperatures", [[5.5, None, 18], [5.5], [5.5, float("nan"), 18]])
def test_missing_weather_is_not_silently_filled(temperatures):
    daily = fixture("weather.json")["daily"]
    daily["temperature_2m_mean"] = temperatures
    result = degree_days_from_daily(POSTCODE, date(2024, 1, 1), date(2024, 1, 3), daily)
    assert result.heating_degree_days is None and result.missing_day_count > 0


def test_duplicate_day_does_not_replace_missing_day():
    daily = fixture("weather.json")["daily"]
    daily["time"][1] = daily["time"][0]
    result = degree_days_from_daily(POSTCODE, date(2024, 1, 1), date(2024, 1, 3), daily)
    assert result.missing_day_count == 2


def test_bill_uses_arbitrary_year_window_and_exact_weather():
    class FakeWeather:
        def degree_days(self, postcode, start, end):
            assert (postcode, start, end) == (POSTCODE, START, END)
            return annual_weather()

    result = measured_from_bill(
        start=START, end=END, gas_kwh=12000, postcode=POSTCODE, weather_client=FakeWeather()
    )
    expected = estimate_measured(annual_gas_kwh=12000, heating_degree_days=366 * 5)
    assert result.status == "ok" and result.estimate == expected
    assert result.weather.days_expected == 366


def test_bill_missing_or_wrong_period_weather_couldnt_tell():
    weather = annual_weather()
    for bad in (
        replace(weather, missing_day_count=1, heating_degree_days=None),
        replace(weather, start=date(2023, 1, 1)),
    ):
        result = measured_from_degree_days(start=START, end=END, gas_kwh=12000, weather=bad)
        assert result.status == "couldnt_tell" and result.estimate is None


@pytest.mark.parametrize("gas", [float("nan"), -1, 0, float("inf")])
def test_invalid_bill_never_fetches_weather(gas):
    result = measured_from_bill(
        start=START, end=END, gas_kwh=gas, postcode=POSTCODE, weather_client=None
    )
    assert result.status == "couldnt_tell"


def test_monthly_bill_baseline_and_rejection_of_partial_months():
    monthly = {month: 1000 if month not in (6, 7, 8) else 100 for month in range(1, 13)}
    result = measured_from_degree_days(
        start=START,
        end=END,
        gas_kwh=sum(monthly.values()),
        monthly_gas_kwh=monthly,
        weather=annual_weather(),
    )
    assert result.status == "ok" and result.estimate.baseline_gas_kwh.central == 1200
    result = measured_from_degree_days(
        start=START, end=END, gas_kwh=12000, monthly_gas_kwh={6: 100}, weather=annual_weather()
    )
    assert result.status == "couldnt_tell"


def test_routes_use_safe_responses_and_reject_invalid_inputs():
    client = client_for(lambda request: httpx.Response(500, text=TOKEN))
    app.dependency_overrides[http_client] = lambda: client
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None, epc_api_token=TOKEN)
    try:
        with TestClient(app) as api:
            response = api.post("/api/epc/search", json={"postcode": POSTCODE})
            assert response.status_code == 502 and TOKEN not in response.text
            assert response.headers["cache-control"] == "no-store"
            response = api.post(
                "/api/epc/certificate", json={"certificate_id": "not-a-certificate"}
            )
            assert response.status_code == 422
            response = api.post(
                "/api/weather/degree-days",
                json={"postcode": POSTCODE, "start": "2024-02-02", "end": "2024-01-01"},
            )
            assert response.status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_routes_return_epc_and_weather_contracts():
    data = copy.deepcopy(fixture("certificate.json"))
    data["data"].pop("sap_building_parts")

    def handle(request):
        if request.url.host == "api.postcodes.io":
            return httpx.Response(200, json={"result": {"latitude": 51.5, "longitude": -0.1}})
        if request.url.host == "archive-api.open-meteo.com":
            return httpx.Response(200, json=fixture("weather.json"))
        return httpx.Response(200, json=data)

    app.dependency_overrides[http_client] = lambda: client_for(handle)
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None, epc_api_token=TOKEN)
    try:
        with TestClient(app) as api:
            response = api.post(
                "/api/epc/certificate", json={"certificate_id": "1111-2222-3333-4444-5555"}
            )
            assert response.status_code == 200
            assert response.json()["fabric_inputs"]["floor_area_m2"] == 90
            assert TOKEN not in response.text
            assert response.headers["cache-control"] == "no-store, private"
            response = api.post(
                "/api/weather/degree-days",
                json={"postcode": POSTCODE, "start": "2024-01-01", "end": "2024-01-03"},
            )
            assert response.status_code == 200
            assert response.json()["heating_degree_days"] == 15
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize(
    "path, body",
    [
        ("/api/epc/search", {}),
        ("/api/epc/search", {"postcode": "Z" * 11}),
        ("/api/epc/certificate", {}),
        ("/api/weather/degree-days", {"postcode": POSTCODE}),
        (
            "/api/weather/degree-days",
            {"postcode": POSTCODE, "start": "invalid", "end": "2024-01-03"},
        ),
    ],
)
def test_private_routes_require_valid_json_bodies(path, body):
    with TestClient(app) as api:
        assert api.post(path, json=body).status_code == 422
        assert api.get(path).status_code == 405


def test_search_json_body_preserves_address_response():
    row = {
        "uprn": 123,
        "addressLine1": "1 Synthetic Example Lane",
        "postcode": POSTCODE,
        "registrationDate": "2024-01-01",
        "certificateNumber": "1111-2222-3333-4444-5555",
    }
    client = client_for(lambda _: httpx.Response(200, json={"data": [row]}))
    app.dependency_overrides[http_client] = lambda: client
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None, epc_api_token=TOKEN)
    try:
        with TestClient(app) as api:
            response = api.post("/api/epc/search", json={"postcode": POSTCODE})
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store, private"
        assert response.json() == {
            "addresses": [
                {
                    "certificate_id": "1111-2222-3333-4444-5555",
                    "address": "1 Synthetic Example Lane",
                    "postcode": POSTCODE,
                    "registration_date": "2024-01-01",
                    "current_energy_efficiency_band": None,
                }
            ]
        }
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize(
    "start,end",
    [
        (date(2023, 7, 15), date(2024, 7, 14)),
        (date(2024, 2, 29), date(2025, 2, 27)),
        (date(2022, 11, 1), date(2023, 10, 31)),
    ],
)
def test_any_twelve_month_window(start, end):
    result = measured_from_degree_days(
        start=start, end=end, gas_kwh=12000, weather=annual_weather(start, end)
    )
    assert result.status == "ok"


@pytest.mark.parametrize(
    "changes",
    [
        {"days_covered": 3},
        {"base_temperature_c": 18},
        {"heating_degree_days": float("nan")},
    ],
)
def test_inconsistent_supplied_weather_cannot_reach_math(changes):
    weather = replace(annual_weather(), **changes)
    result = measured_from_degree_days(start=START, end=END, gas_kwh=12000, weather=weather)
    assert result.status == "couldnt_tell" and result.estimate is None


def test_network_timeout_is_safe_and_bill_is_unavailable():
    def timeout(request):
        raise httpx.ReadTimeout(TOKEN, request=request)

    provider = WeatherClient(client_for(timeout))
    result = measured_from_bill(
        start=START, end=END, gas_kwh=12000, postcode=POSTCODE, weather_client=provider
    )
    assert result.status == "couldnt_tell"
    assert TOKEN not in result.reason
