"""Structured observations produced from an application surface."""

from pydantic import BaseModel


class ElementObservation(BaseModel):
    """One useful element observed on the current application surface."""

    ref: str
    role: str
    name: str


class Observation(BaseModel):
    """Compact structured view of the current application surface."""

    url: str
    title: str
    text: str = ""
    elements: list[ElementObservation]
