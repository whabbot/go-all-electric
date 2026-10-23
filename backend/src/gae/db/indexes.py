"""Idempotent index provisioning: uv run python -m gae.db.indexes.

Search indexes build asynchronously. Wait for queryable=true before searching.
Definitions follow MongoDB's autoEmbed and Search string field documentation.
"""

from pymongo.database import Database
from pymongo.errors import PyMongoError
from pymongo.operations import SearchIndexModel

from gae.db.connection import DatabaseUnavailable, database
from gae.db.datasheets import EMBEDDING_MODEL, TEXT_INDEX, VECTOR_INDEX

TEXT_DEFINITION = {
    "mappings": {
        "dynamic": False,
        "fields": {
            "kind": {"type": "token"},
            "make": {"type": "string"},
            "model": {"type": "string"},
            "text": {"type": "string"},
        },
    }
}
VECTOR_DEFINITION = {
    "fields": [
        {"type": "autoEmbed", "modality": "text", "path": "text", "model": EMBEDDING_MODEL},
        {"type": "filter", "path": "kind"},
        {"type": "filter", "path": "nominal_capacity_kw"},
    ]
}


def ensure_indexes(db: Database) -> None:
    db["surveys"].create_index([("updated_at", -1), ("_id", -1)], name="surveys_recent")
    db["datasheets"].create_index([("kind", 1), ("nominal_capacity_kw", 1)])
    collection = db["datasheets"]
    existing = {item["name"]: item for item in collection.list_search_indexes()}
    for name, definition, index_type in [
        (TEXT_INDEX, TEXT_DEFINITION, "search"),
        (VECTOR_INDEX, VECTOR_DEFINITION, "vectorSearch"),
    ]:
        if name not in existing:
            collection.create_search_index(
                SearchIndexModel(
                    name=name,
                    definition=definition,
                    type=index_type,
                )
            )
        elif existing[name].get("latestDefinition") != definition:
            collection.update_search_index(name, definition)


def main() -> None:
    try:
        with database() as db:
            ensure_indexes(db)
    except PyMongoError, DatabaseUnavailable:
        raise SystemExit("Index setup failed: check database access and feature support.") from None
    print("Index definitions submitted; wait for both Search indexes to become queryable.")


if __name__ == "__main__":
    main()
