"""Deterministic shingle and exact-span comparison over extracted paragraphs.

This is a selected-source similarity aid, not a plagiarism classifier. All
positions are Unicode code-point offsets into the immutable extracted text.
"""
from collections import defaultdict
from dataclasses import dataclass
import re
import unicodedata

from django.conf import settings

REFERENCE_CATEGORIES = {'references', 'bibliography', 'works cited', 'reference list'}
REFERENCE_TITLE = re.compile(r'^(?:references|bibliography|works cited|reference list)$', re.I)
CITATION_SIGNAL = re.compile(r'(?:\[[0-9,;\s\-–]+\]|\([A-Z][^()]{0,80}\b(?:19|20)\d{2}[a-z]?\)|\b(?:19|20)\d{2}[a-z]?\s*\))')


@dataclass(frozen=True)
class Token:
    value: str
    start: int
    end: int


@dataclass(frozen=True)
class Paragraph:
    text: str
    section_key: str
    section_title: str
    paragraph_id: str
    paragraph_index: int
    category: str


def tokens(text):
    """NFKC/casefold token values while retaining source-text offsets."""
    result = []
    start = None
    index = 0
    while index < len(text):
        char = text[index]
        category = unicodedata.category(char)
        is_letter_or_number = category[0] in ('L', 'N') and char != '_'
        is_mark = category[0] == 'M'
        if start is None:
            if is_letter_or_number:
                start = index
        elif is_letter_or_number or is_mark:
            pass
        elif char in ("'", '’') and index + 1 < len(text) and unicodedata.category(text[index + 1])[0] == 'L':
            pass
        else:
            normalized = unicodedata.normalize('NFKC', text[start:index]).casefold()
            if normalized:
                result.append(Token(normalized, start, index))
            start = index if is_letter_or_number else None
        index += 1
    if start is not None:
        normalized = unicodedata.normalize('NFKC', text[start:]).casefold()
        if normalized:
            result.append(Token(normalized, start, len(text)))
    return result


def paragraphs_from_metadata(metadata):
    result = []
    for section in metadata.get('sections') or []:
        title = str(section.get('title') or '')
        category = str(section.get('category') or '').casefold()
        if category in REFERENCE_CATEGORIES or REFERENCE_TITLE.match(title.strip()):
            continue
        records = section.get('paragraph_records') or []
        if records:
            for index, record in enumerate(records):
                text = str(record.get('text') or '')
                if text.strip():
                    result.append(Paragraph(text, str(section.get('section_key') or ''), title,
                                            str(record.get('source_id') or ''),
                                            int(record.get('paragraph_index') if record.get('paragraph_index') is not None else index), category))
        else:
            for index, text in enumerate(section.get('paragraphs') or []):
                if str(text).strip():
                    result.append(Paragraph(str(text), str(section.get('section_key') or ''), title, '', index, category))
    if not result:
        for index, record in enumerate(metadata.get('unclassified') or []):
            text = str(record.get('text') or '')
            if text.strip():
                result.append(Paragraph(text, 'unclassified', 'Unclassified content',
                                        str(record.get('source_id') or ''), index, 'other'))
    return result


def _shingles(token_list, size):
    if len(token_list) < size:
        return set()
    return {tuple(item.value for item in token_list[index:index + size])
            for index in range(len(token_list) - size + 1)}


def _citation_label(source_text, start, end, target_text, target_start, target_end):
    def signals(text, left, right):
        context = text[max(0, left - 120):min(len(text), right + 120)]
        quoted = any(mark in context for mark in ('"', '“', '”', '‘', '’'))
        cited = bool(CITATION_SIGNAL.search(context))
        return quoted or cited
    return 'quoted_or_cited' if signals(source_text, start, end) or signals(target_text, target_start, target_end) else 'potentially_unattributed'


def _merge_spans(spans):
    merged = []
    for span in sorted(spans, key=lambda row: (row['s0'], row['t0'], row['s1'], row['t1'])):
        if merged and span['s0'] <= merged[-1]['s1'] and span['t0'] <= merged[-1]['t1']:
            prior = merged[-1]
            prior['s1'] = max(prior['s1'], span['s1'])
            prior['t1'] = max(prior['t1'], span['t1'])
            prior['kind'] = 'exact' if prior['kind'] == span['kind'] == 'exact' else 'near_duplicate'
            prior['similarity'] = max(prior['similarity'], span['similarity'])
        else:
            merged.append(dict(span))
    return merged


def compare_paragraphs(source, target, *, min_words=None, near_threshold=None, shingle_size=None):
    min_words = min_words or settings.SIMILARITY_MIN_PASSAGE_WORDS
    near_threshold = settings.SIMILARITY_NEAR_THRESHOLD if near_threshold is None else near_threshold
    shingle_size = shingle_size or settings.SIMILARITY_SHINGLE_SIZE
    left, right = tokens(source.text), tokens(target.text)
    if min(len(left), len(right)) < min_words:
        return []
    index = defaultdict(list)
    for j in range(len(right) - shingle_size + 1):
        index[tuple(t.value for t in right[j:j + shingle_size])].append(j)
    candidates = set()
    for i in range(len(left) - shingle_size + 1):
        positions = index.get(tuple(t.value for t in left[i:i + shingle_size]), ())
        if len(positions) <= 64:
            candidates.update((i, j) for j in positions)
    spans = []
    exact = set()
    for i, j in sorted(candidates):
        a, b = i, j
        while a and b and left[a - 1].value == right[b - 1].value:
            a -= 1; b -= 1
        x, y = i + shingle_size, j + shingle_size
        while x < len(left) and y < len(right) and left[x].value == right[y].value:
            x += 1; y += 1
        if x - a >= min_words:
            exact.add((a, x, b, y))
    for a, x, b, y in sorted(exact):
        spans.append({'s0': a, 's1': x, 't0': b, 't1': y, 'kind': 'exact', 'similarity': 1.0})
    if not spans:
        left_shingles, right_shingles = _shingles(left, shingle_size), _shingles(right, shingle_size)
        union = left_shingles | right_shingles
        similarity = len(left_shingles & right_shingles) / len(union) if union else 0.0
        if similarity >= near_threshold:
            spans.append({'s0': 0, 's1': len(left), 't0': 0, 't1': len(right),
                          'kind': 'near_duplicate', 'similarity': similarity})
    output = []
    for span in _merge_spans(spans):
        source_start, source_end = left[span['s0']].start, left[span['s1'] - 1].end
        target_start, target_end = right[span['t0']].start, right[span['t1'] - 1].end
        output.append({'match_type': span['kind'], 'source_start': source_start, 'source_end': source_end,
                       'target_start': target_start, 'target_end': target_end,
                       'similarity': round(span['similarity'], 6), 'source_word_count': span['s1'] - span['s0'],
                       'citation_label': _citation_label(source.text, source_start, source_end,
                                                        target.text, target_start, target_end)})
    return output


def compare_documents(source_metadata, target_metadata, *, min_words=None, near_threshold=None, shingle_size=None):
    min_words = settings.SIMILARITY_MIN_PASSAGE_WORDS if min_words is None else min_words
    near_threshold = settings.SIMILARITY_NEAR_THRESHOLD if near_threshold is None else near_threshold
    shingle_size = settings.SIMILARITY_SHINGLE_SIZE if shingle_size is None else shingle_size
    source_paragraphs = paragraphs_from_metadata(source_metadata)
    target_paragraphs = paragraphs_from_metadata(target_metadata)
    word_count = sum(len(tokens(item.text)) for item in source_paragraphs)
    if word_count > settings.SIMILARITY_MAX_DOCUMENT_WORDS:
        raise ValueError('The selected manuscript exceeds the configured similarity word limit.')
    matches = []
    target_shingle_index = defaultdict(set)
    target_token_cache = []
    for target_index, target in enumerate(target_paragraphs):
        target_tokens = tokens(target.text)
        target_token_cache.append(target_tokens)
        for shingle_index in range(max(0, len(target_tokens) - shingle_size + 1)):
            target_shingle_index[tuple(token.value for token in target_tokens[shingle_index:shingle_index + shingle_size])].add(target_index)
    for source_index, source in enumerate(source_paragraphs):
        source_tokens = tokens(source.text)
        candidate_targets = set()
        for shingle_index in range(max(0, len(source_tokens) - shingle_size + 1)):
            candidate_targets.update(target_shingle_index.get(
                tuple(token.value for token in source_tokens[shingle_index:shingle_index + shingle_size]), ()))
        for target_index in sorted(candidate_targets):
            target = target_paragraphs[target_index]
            for match in compare_paragraphs(source, target, min_words=min_words,
                                            near_threshold=near_threshold, shingle_size=shingle_size):
                matches.append({**match, 'source_section_key': source.section_key,
                                'source_section_title': source.section_title,
                                'source_paragraph_id': source.paragraph_id,
                                'source_paragraph_index': source.paragraph_index,
                                'target_section_key': target.section_key,
                                'target_section_title': target.section_title,
                                'target_paragraph_id': target.paragraph_id,
                                'target_paragraph_index': target.paragraph_index,
                                '_source_index': source_index, '_target_index': target_index})
    unique = {}
    for match in matches:
        key = (match['_source_index'], match['_target_index'], match['source_start'], match['source_end'],
               match['target_start'], match['target_end'])
        prior = unique.get(key)
        if prior is None or (match['similarity'], match['match_type'] == 'exact') > (prior['similarity'], prior['match_type'] == 'exact'):
            unique[key] = match
    clean_matches = [{key: value for key, value in match.items() if not key.startswith('_')}
                     for match in unique.values()]
    clean_matches.sort(key=lambda item: (item['source_section_title'].casefold(), item['source_paragraph_index'], item['source_start'], item['target_paragraph_index']))
    covered = defaultdict(list)
    for match in clean_matches:
        covered[(match['source_section_key'], match['source_paragraph_id'], match['source_paragraph_index'])].append((match['source_start'], match['source_end']))
    source_lookup = {(p.section_key, p.paragraph_id, p.paragraph_index): p for p in source_paragraphs}
    matched_words = 0
    for key, spans in covered.items():
        paragraph = source_lookup.get(key)
        if paragraph is None:
            continue
        united = []
        for start, end in sorted(spans):
            if united and start <= united[-1][1]:
                united[-1] = (united[-1][0], max(united[-1][1], end))
            else:
                united.append((start, end))
        paragraph_tokens = tokens(paragraph.text)
        matched_words += sum(1 for start, end in united for token in paragraph_tokens if token.start >= start and token.end <= end)
    return {'matches': clean_matches, 'source_word_count': word_count, 'matched_source_words': matched_words,
            'matched_percentage': round(100 * matched_words / word_count, 2) if word_count else 0.0,
            'exact_match_count': sum(item['match_type'] == 'exact' for item in clean_matches),
            'near_match_count': sum(item['match_type'] == 'near_duplicate' for item in clean_matches)}
