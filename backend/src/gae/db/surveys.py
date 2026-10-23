"""One document per survey; UUID identifiers never encode a property address."""

from datetime import UTC, datetime
from uuid import uuid4

from pymongo import ReturnDocument
from pymongo.collection import Collection

from gae.db.models import Survey, SurveyInput


def decode(document: dict | None) -> Survey | None:
    if document is None:
        return None
    return Survey.model_validate(
        {"id": document["_id"], **{k: v for k, v in document.items() if k != "_id"}}
    )


class SurveyRepository:
    def __init__(self, collection: Collection):
        self.collection = collection

    def create(self, value: SurveyInput) -> Survey:
        now = datetime.now(UTC)
        document = {"_id": str(uuid4()), **value.model_dump(), "created_at": now, "updated_at": now}
        self.collection.insert_one(document)
        return decode(document)  # type: ignore[return-value]

    def get(self, survey_id: str) -> Survey | None:
        return decode(self.collection.find_one({"_id": survey_id}))

    def update(self, survey_id: str, value: SurveyInput) -> Survey | None:
        # PUT replaces all user-editable fields, retaining creation time and identity.
        return decode(
            self.collection.find_one_and_update(
                {"_id": survey_id},
                {"$set": {**value.model_dump(), "updated_at": datetime.now(UTC)}},
                return_document=ReturnDocument.AFTER,
            )
        )

    def recent(self, limit: int = 20) -> list[Survey]:
        return [
            decode(doc)
            for doc in self.collection.find()
            .sort([("updated_at", -1), ("_id", -1)])
            .limit(max(1, min(limit, 100)))
        ]

    def delete(self, survey_id: str) -> bool:
        return self.collection.delete_one({"_id": survey_id}).deleted_count == 1
