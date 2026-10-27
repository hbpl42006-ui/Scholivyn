import json
import hashlib
import re
from dataclasses import dataclass

from django.conf import settings

from apps.intelligence.services.prompts.sections import SECTION_FOCUS
from apps.intelligence.services.prompts.system import SYSTEM_INSTRUCTIONS
from .section_classifier import classify_heading


@dataclass(frozen=True)
class ManuscriptSection:
    key: str
    title: str
    category: str
    paragraphs: tuple[str, ...]


def normalized_sections(extraction: dict) -> list[ManuscriptSection]:
    result = []
    for index, item in enumerate(extraction.get('sections', [])):
        title = str(item.get('title') or f'Section {index + 1}')[:180]
        paragraphs = tuple(str(p).strip() for p in item.get('paragraphs', []) if str(p).strip())
        if paragraphs:
            stable = hashlib.sha256(title.encode('utf-8')).hexdigest()[:16]
            section_key = str(item.get('section_key') or f'{index}-{stable}')[:120]
            result.append(ManuscriptSection(section_key, title, classify_heading(title), paragraphs))
    if not result:
        paragraphs = tuple(str(p).strip() for p in extraction.get('paragraphs', []) if str(p).strip())
        if paragraphs:
            result.append(ManuscriptSection('0-full-text', 'Extracted manuscript', 'other', paragraphs))
    return result


def word_count(sections: list[ManuscriptSection]) -> int:
    return sum(len(re.findall(r"\b[\w’'-]+\b", paragraph)) for section in sections for paragraph in section.paragraphs)


def _encoding():
    try:
        import tiktoken
    except ImportError:
        # Conservative UTF-8 byte budgeting if optional native tokenizer wheels
        # are unavailable (e.g. minimal test environments).
        class ByteBudgetEncoding:
            def encode(self, value):
                return list(value.encode('utf-8'))

            def decode(self, tokens):
                return bytes(tokens).decode('utf-8', errors='ignore')
        return ByteBudgetEncoding()
    try:
        try:
            return tiktoken.encoding_for_model(settings.AI_MODEL)
        except (KeyError, ValueError):
            return tiktoken.get_encoding('cl100k_base')
    except Exception:
        # Encoding vocabularies may be absent from the local cache. Never make
        # background analysis depend on network access to tokenize a document.
        class ByteBudgetEncoding:
            def encode(self, value):
                return list(value.encode('utf-8'))

            def decode(self, tokens):
                return bytes(tokens).decode('utf-8', errors='ignore')
        return ByteBudgetEncoding()


def _split_long_paragraph(text: str, encoding, limit: int) -> list[tuple[int, int, str]]:
    """Split by token budget while retaining source character offsets for checkpoints."""
    if len(encoding.encode(text)) <= limit:
        return [(0, len(text), text)]
    ranges = []
    start = 0
    while start < len(text):
        low, high = start + 1, len(text)
        while low < high:
            middle = (low + high + 1) // 2
            if len(encoding.encode(text[start:middle])) <= limit:
                low = middle
            else:
                high = middle - 1
        end = max(start + 1, low)
        if end < len(text):
            boundary = max(text.rfind(' ', start, end), text.rfind('\n', start, end))
            if boundary > start + (end - start) // 2:
                end = boundary
        ranges.append((start, end, text[start:end]))
        start = end
    return ranges


def chunk_section_with_ranges(section: ManuscriptSection, limit: int | None = None):
    encoding = _encoding()
    limit = max(128, int(limit or settings.AI_MAX_CHUNK_TOKENS))
    chunks = []
    current = []
    current_tokens = 0
    for paragraph_index, paragraph in enumerate(section.paragraphs):
        for start, end, piece in _split_long_paragraph(paragraph, encoding, limit):
            tokens = len(encoding.encode(piece))
            if current and current_tokens + tokens > limit:
                chunks.append(current)
                # A single previous paragraph provides bounded adjacent context.
                previous = current[-1]
                current = [previous] if len(encoding.encode(previous[3])) < limit // 3 else []
                current_tokens = sum(len(encoding.encode(item[3])) for item in current)
            current.append((paragraph_index, start, end, piece))
            current_tokens += tokens
    if current:
        chunks.append(current)
    return chunks


def chunk_section(section: ManuscriptSection, limit: int | None = None) -> list[list[tuple[int, str]]]:
    return [[(paragraph_index, text) for paragraph_index, _start, _end, text in chunk]
            for chunk in chunk_section_with_ranges(section, limit)]


def estimate_tokens(value: str) -> int:
    return len(_encoding().encode(value))


def prompt_for(section: ManuscriptSection, reviewer_profile: str, paragraphs: list[tuple[int, str]]) -> tuple[str, str]:
    focus = SECTION_FOCUS.get(section.category, 'Review clarity, logical structure, evidence support, and academic precision.')
    profile = 'General academic research.'
    if reviewer_profile == 'computer_science':
        profile = 'Computer Science: consider baselines, algorithm details, evaluation design, reproducibility, and dataset splits where relevant.'
    elif reviewer_profile == 'artificial_intelligence':
        profile = 'AI/ML research: additionally consider data splitting, leakage risk as a possibility only, class imbalance, metrics, cross-validation, tuning, baselines, and reproducibility.'
    instructions = f'{SYSTEM_INSTRUCTIONS}\n\nSelected reviewer profile: {profile}\nSection focus: {focus}'
    content = json.dumps({
        'section_title': section.title,
        'section_category': section.category,
        'paragraphs': [{'paragraph_index': index, 'text': text} for index, text in paragraphs],
    }, ensure_ascii=False)
    return instructions, content
