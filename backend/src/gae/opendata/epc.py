"""2026 MHCLG replacement API. Bearer token, not legacy Basic auth."""

import re
from dataclasses import asdict

import httpx
from pydantic import SecretStr

from gae.opendata.http import DataUnavailable, get_json
from gae.opendata.mapping import FabricMapping, map_epc
from gae.opendata.weather import normalise_postcode

BASE_URL = "https://api.get-energy-performance-data.communities.gov.uk"
CERTIFICATE_PATTERN = r"\d{4}-\d{4}-\d{4}-\d{4}-\d{4}"


class EPCClient:
    def __init__(self, client: httpx.Client, token: SecretStr | None):
        self.client = client
        self.token = token

    def _get(self, path: str, params: dict) -> dict:
        if self.token is None or not self.token.get_secret_value().strip():
            raise DataUnavailable("EPC lookup needs EPC_API_TOKEN from the GOV.UK service.", 503)
        return get_json(
            self.client,
            BASE_URL + path,
            params=params,
            headers={
                "Authorization": "Bearer " + self.token.get_secret_value(),
                "Accept": "application/json",
            },
        )

    def search(self, postcode: str) -> list[dict]:
        """One latest certificate per UPRN (address tuple if no UPRN), with bounded pagination."""
        postcode = normalise_postcode(postcode)
        latest: dict[tuple, dict] = {}
        for page in range(1, 21):
            try:
                payload = self._get(
                    "/api/domestic/search",
                    {
                        "postcode": postcode,
                        "current_page": page,
                        "page_size": 5000,
                    },
                )
            except DataUnavailable as exc:
                if exc.status_code == 404 and page == 1:
                    return []
                raise
            rows = payload.get("data")
            pagination = payload.get("pagination", {})
            if not isinstance(rows, list) or not isinstance(pagination, dict):
                raise DataUnavailable("Couldn't read EPC search results.")
            for row in rows:
                if not isinstance(row, dict):
                    raise DataUnavailable("Couldn't read EPC search results.")
                identifier = row.get("certificateNumber", "")
                stamp = row.get("registrationDate", "")
                if not isinstance(identifier, str) or not re.fullmatch(
                    CERTIFICATE_PATTERN, identifier
                ):
                    raise DataUnavailable("Couldn't read EPC certificate number.")
                if not isinstance(stamp, str) or not re.match(r"\d{4}-\d{2}-\d{2}", stamp):
                    raise DataUnavailable("Couldn't determine the latest EPC registration date.")
                address = [row.get(f"addressLine{i}") for i in range(1, 5)]
                address = [part for part in address if isinstance(part, str) and part.strip()]
                if not address:
                    raise DataUnavailable("Couldn't identify an EPC address.")
                key = (
                    ("uprn", str(row["uprn"]))
                    if row.get("uprn")
                    else ("address", *(part.casefold().strip() for part in address), postcode)
                )
                summary = {
                    "certificate_id": identifier,
                    "address": ", ".join(address),
                    "postcode": postcode,
                    "registration_date": stamp,
                    "current_energy_efficiency_band": row.get("currentEnergyEfficiencyBand"),
                }
                old = latest.get(key)
                if old is None or (stamp, identifier) > (
                    old["registration_date"],
                    old["certificate_id"],
                ):
                    latest[key] = summary
            next_page = pagination.get("nextPage")
            if next_page is None:
                return sorted(latest.values(), key=lambda row: row["address"].casefold())
            if next_page != page + 1:
                raise DataUnavailable("Couldn't read EPC pagination; results may be incomplete.")
        raise DataUnavailable("Too many EPC pages; couldn't safely select the latest records.")

    def certificate(self, certificate_id: str) -> dict:
        raw_summary, mapping = self.mapped(certificate_id)
        return {"certificate_id": certificate_id, "raw_summary": raw_summary, **asdict(mapping)}

    def mapped(self, certificate_id: str) -> tuple[dict, FabricMapping]:
        """Allowlisted raw summary and the typed fabric mapping, for callers doing the maths."""
        if not re.fullmatch(CERTIFICATE_PATTERN, certificate_id):
            raise ValueError(
                "Use a 20-digit certificate number in 0000-0000-0000-0000-0000 format."
            )
        data = self._get("/api/certificate", {"certificate_number": certificate_id}).get("data")
        if not isinstance(data, dict):
            raise DataUnavailable("Couldn't read EPC certificate data.")
        # The same schema can contain SAP and RdSAP labels for the same key.
        schema = data.get("schema_type")
        assessment = data.get("assessment_type")

        def label_for(name: str, key) -> str | None:
            if key is None or not isinstance(schema, str) or not isinstance(assessment, str):
                return None
            try:
                codes = self._get(
                    "/api/codes/info",
                    {"code": name, "key": str(key), "schemaVersion": schema},
                ).get("data", [])
                if not isinstance(codes, list):
                    return None
                labels = {
                    value["value"]
                    for code in codes
                    if isinstance(code, dict)
                    and str(code.get("key")) == str(key)
                    and isinstance(code.get("values"), list)
                    for value in code["values"]
                    if isinstance(value, dict)
                    and value.get("schemaVersion") == schema
                    and value.get("assessmentType") == assessment
                    and isinstance(value.get("value"), str)
                }
                return next(iter(labels)) if len(labels) == 1 else None
            except DataUnavailable:
                # Undecodable age stays low confidence; unresolved geometry is refused.
                return None

        parts = data.get("sap_building_parts", [])
        bands = (
            {
                str(p["construction_age_band"])
                for p in parts
                if isinstance(p, dict) and p.get("construction_age_band")
            }
            if isinstance(parts, list)
            else set()
        )
        age_label = (
            label_for("construction_age_band", next(iter(bands))) if len(bands) == 1 else None
        )
        property_label = built_form_label = None
        if not data.get("dwelling_type"):
            property_label = label_for("property_type", data.get("property_type"))
            built_form_label = label_for("built_form", data.get("built_form"))
        fields = (
            "address_line_1",
            "address_line_2",
            "address_line_3",
            "address_line_4",
            "postcode",
            "registration_date",
            "schema_type",
            "assessment_type",
            "total_floor_area",
            "dwelling_type",
            "property_type",
            "built_form",
            "walls",
            "roofs",
            "floors",
            "window",
            "windows",
            "main_heating",
            "construction_age_band",
        )
        return (
            {key: data[key] for key in fields if key in data},
            map_epc(
                data,
                age_label=age_label,
                property_label=property_label,
                built_form_label=built_form_label,
            ),
        )
