"""Persistence routes. Bind to localhost for the single-user hackathon demo."""

from collections.abc import Iterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pymongo.database import Database
from pymongo.errors import PyMongoError

from gae.db.connection import DatabaseUnavailable, database
from gae.db.datasheets import AtlasDatasheetLookup, EquipmentKind
from gae.db.models import SearchResults, Survey, SurveyInput
from gae.db.surveys import SurveyRepository

router = APIRouter(prefix="/api", tags=["Atlas"])


def get_database() -> Iterator[Database]:
    try:
        with database() as db:
            yield db
    except PyMongoError, DatabaseUnavailable:
        # Never include driver errors: they may include credentials, hosts or query content.
        raise HTTPException(
            503, "Data service unavailable; check server configuration and indexes"
        ) from None


DB = Annotated[Database, Depends(get_database, scope="function")]


@router.get("/datasheets/search", response_model=SearchResults)
def search_datasheets(
    db: DB,
    q: Annotated[str, Query(min_length=2, max_length=300)],
    limit: Annotated[int, Query(ge=1, le=20)] = 5,
    kind: EquipmentKind | None = None,
) -> SearchResults:
    if not q.strip():
        raise HTTPException(422, "Enter a make or model")
    return AtlasDatasheetLookup(db["datasheets"]).search(q.strip(), limit, kind)


@router.post("/surveys", response_model=Survey, status_code=201)
def create_survey(value: SurveyInput, db: DB) -> Survey:
    return SurveyRepository(db["surveys"]).create(value)


@router.get("/surveys", response_model=list[Survey])
def recent_surveys(db: DB, limit: Annotated[int, Query(ge=1, le=100)] = 20) -> list[Survey]:
    return SurveyRepository(db["surveys"]).recent(limit)


@router.get("/surveys/{survey_id}", response_model=Survey)
def get_survey(survey_id: UUID, db: DB) -> Survey:
    survey = SurveyRepository(db["surveys"]).get(str(survey_id))
    if survey is None:
        raise HTTPException(404, "Survey not found")
    return survey


@router.put("/surveys/{survey_id}", response_model=Survey)
def replace_survey(survey_id: UUID, value: SurveyInput, db: DB) -> Survey:
    survey = SurveyRepository(db["surveys"]).update(str(survey_id), value)
    if survey is None:
        raise HTTPException(404, "Survey not found")
    return survey


@router.delete("/surveys/{survey_id}", status_code=204)
def delete_survey(survey_id: UUID, db: DB) -> Response:
    if not SurveyRepository(db["surveys"]).delete(str(survey_id)):
        raise HTTPException(404, "Survey not found")
    return Response(status_code=204)
