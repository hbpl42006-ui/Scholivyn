from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ReviewIssueOutput(BaseModel):
    model_config = ConfigDict(extra='forbid')

    category: str = Field(min_length=2, max_length=60)
    severity: Literal['critical', 'high', 'medium', 'low', 'informational']
    title: str = Field(min_length=3, max_length=220)
    explanation: str = Field(min_length=8, max_length=4000)
    evidence_text: str = Field(min_length=4, max_length=1600)
    recommendation: str = Field(min_length=5, max_length=3000)
    suggested_text: str | None = Field(default=None, max_length=4000)


class SectionReviewOutput(BaseModel):
    model_config = ConfigDict(extra='forbid')

    summary: str = Field(min_length=5, max_length=5000)
    strengths: list[str] = Field(max_length=12)
    weaknesses: list[str] = Field(max_length=12)
    recommendations: list[str] = Field(max_length=12)
    issues: list[ReviewIssueOutput] = Field(max_length=40)
