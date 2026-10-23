"""Idempotently seed public manufacturer facts: uv run python -m gae.db.seed."""

import json
from importlib.resources import files

from pymongo.collection import Collection
from pymongo.errors import PyMongoError

from gae.db.connection import DatabaseUnavailable, database
from gae.db.models import Datasheet


def load_seed() -> list[Datasheet]:
    return [
        Datasheet.model_validate(row)
        for row in json.loads(files("gae.db").joinpath("datasheets.json").read_text())
    ]


def seed(collection: Collection) -> int:
    sheets = load_seed()
    for sheet in sheets:
        collection.update_one(
            {"_id": sheet.id}, {"$set": sheet.model_dump(mode="json")}, upsert=True
        )
    return len(sheets)


def main() -> None:
    try:
        with database() as db:
            count = seed(db["datasheets"])
    except PyMongoError, DatabaseUnavailable:
        raise SystemExit("Seed failed: check server configuration and database access.") from None
    print(f"Seeded {count} public datasheets (existing IDs updated).")


if __name__ == "__main__":
    main()
