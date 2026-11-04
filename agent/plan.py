"""Skeleton structured output. EDIT ME 4: add the fields your path needs; keep escalation and citations."""
from typing import Literal

from pydantic import BaseModel, Field


class Answer(BaseModel):
    language: Literal["en", "ta"]
    answer: str = Field(description="The answer, in the user's language")
    steps: list[str] = Field(default_factory=list, description="What to do next, short steps")
    escalation: str = Field(description="When and who to ask for human help")
    citations: list[str] = Field(description="Guidance ids returned by lookup_guidance")


class Critique(BaseModel):
    ok: bool
    problems: list[str] = Field(default_factory=list)
