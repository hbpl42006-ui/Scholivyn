from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from apps.intelligence.schemas import SectionReviewOutput


@dataclass(frozen=True)
class ProviderResult:
    output: 'SectionReviewOutput'
    input_tokens: int
    output_tokens: int
    response_headers: dict[str, str] | None = None
    # A subset of output_tokens; None means the provider did not expose a split.
    reasoning_tokens: int | None = None


class AIProviderError(Exception):
    def __init__(self, category: str, safe_message: str, *, retryable: bool = False,
                 retry_after_seconds: float | None = None):
        super().__init__(safe_message)
        self.category = category
        self.safe_message = safe_message
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds


class AcademicReviewProvider(Protocol):
    provider_name: str

    def review(self, *, instructions: str, content: str, correlation_id: str) -> ProviderResult: ...
