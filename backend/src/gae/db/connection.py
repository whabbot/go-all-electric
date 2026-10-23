"""Short-lived clients for synchronous FastAPI threadpool handlers and CLI commands."""

from collections.abc import Iterator
from contextlib import contextmanager

from pymongo import MongoClient
from pymongo.database import Database

from gae.settings import get_settings


class DatabaseUnavailable(RuntimeError):
    pass


@contextmanager
def database() -> Iterator[Database]:
    uri = get_settings().mongodb_uri
    if uri is None or not uri.get_secret_value().strip():
        raise DatabaseUnavailable("MongoDB is not configured")
    with MongoClient(
        uri.get_secret_value(),
        serverSelectionTimeoutMS=5000,
        connectTimeoutMS=5000,
        socketTimeoutMS=15000,
        tz_aware=True,
    ) as client:
        yield client["go_all_electric"]
