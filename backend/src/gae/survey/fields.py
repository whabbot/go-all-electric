"""Shared survey field models."""

from pydantic import BaseModel

from gae.heatpump.ranges import Confidence


class NamedDefault(BaseModel):
    input: str
    name: str
    value: str
    note: str
    confidence: Confidence
