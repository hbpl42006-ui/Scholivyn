"""Deterministic citation/reference parsing with paragraph-local source offsets."""
import re
import unicodedata
from urllib.parse import urlsplit

DOI_RE = re.compile(r'(?i)\b(?:https?://(?:dx\.)?doi\.org/|doi\s*:\s*)?(10\.\d{4,9}/[^\s<>"\]]+)')
URL_RE = re.compile(r'https?://[^\s<>"\]]+', re.I)
YEAR_RE = re.compile(r'\b(18\d{2}|19\d{2}|20\d{2}|21\d{2})([a-z])?\b')
NUMERIC_CITATION_RE = re.compile(r'\[(?P<body>\s*\d+(?:\s*[-\u2013\u2014]\s*\d+)?(?:\s*[,;]\s*\d+(?:\s*[-\u2013\u2014]\s*\d+)?)*)\]')
APA_NARRATIVE_RE = re.compile(r'(?P<author>\b[A-Z][\w\u2019\'-]{1,40}(?:\s+et\s+al\.)?)\s*\((?P<year>(?:18|19|20|21)\d{2}[a-z]?)\)', re.I)
APA_ITEM_RE = re.compile(r'(?P<author>[A-Z][\w\u2019\'-]{1,40}(?:\s+et\s+al\.|\s+(?:&|and)\s+[A-Z][\w\u2019\'-]{1,40})?)\s*,?\s+(?P<year>(?:18|19|20|21)\d{2}[a-z]?)', re.I)
NUMBERED_REF_RE = re.compile(r'^\s*(?:\[(\d{1,4})\]|(\d{1,4})[.)])\s*(.*)$', re.S)


def normalize_doi(value):
    if not value:
        return ''
    match = DOI_RE.search(str(value).strip())
    return match.group(1).rstrip('.,;:)]}').casefold() if match else ''


def _paragraphs(metadata):
    for section in metadata.get('sections') or []:
        title = str(section.get('title') or '')
        category = str(section.get('category') or '').casefold()
        is_reference = category in {'references', 'bibliography', 'works cited', 'reference list'} or title.strip().casefold() in {'references', 'bibliography', 'works cited', 'reference list'}
        records = section.get('paragraph_records') or []
        if not records:
            records = [{'text': value, 'source_id': '', 'paragraph_index': i} for i, value in enumerate(section.get('paragraphs') or [])]
        for i, row in enumerate(records):
            text = str(row.get('text') or '')
            if text.strip():
                yield {'text': text, 'section_key': str(section.get('section_key') or ''), 'section_title': title,
                       'category': category, 'in_references': is_reference, 'paragraph_id': str(row.get('source_id') or ''),
                       'paragraph_index': int(row.get('paragraph_index') if row.get('paragraph_index') is not None else i)}
    if not (metadata.get('sections') or []):
        for i, row in enumerate(metadata.get('unclassified') or []):
            text = str(row.get('text') or '')
            if text.strip():
                yield {'text': text, 'section_key': 'unclassified', 'section_title': 'Unclassified content',
                       'category': '', 'in_references': False, 'paragraph_id': str(row.get('source_id') or ''), 'paragraph_index': i}


def _expand_numbers(body):
    values = []
    for part in re.split(r'[,;]', body):
        part = part.strip()
        span = re.fullmatch(r'(\d+)\s*[-\u2013\u2014]\s*(\d+)', part)
        if span:
            lo, hi = map(int, span.groups())
            values.extend(range(lo, hi + 1)) if lo <= hi and hi - lo <= 100 else values.extend((lo, hi))
        elif part.isdigit():
            values.append(int(part))
    return list(dict.fromkeys(values))


def _author_key(value):
    normalized = unicodedata.normalize('NFKC', value).casefold().strip()
    normalized = re.split(r'\s+(?:&|and)\s+', normalized, maxsplit=1)[0]
    normalized = re.sub(r'\bet\s+al\.?\b', '', normalized)
    family = normalized.split(',', 1)[0]
    names = re.findall(r'[\w\u00c0-\u024f\u4e00-\u9fff]+', family)
    return names[-1] if names else ''


def _citation_rows(paragraph):
    text = paragraph['text']
    rows = []
    for match in NUMERIC_CITATION_RE.finditer(text):
        before, after = text[:match.start()].rstrip(), text[match.end():].lstrip()
        if (before.endswith(('=', '^', '_', '(', '{')) or after.startswith(('=', '^', '_'))
                or (match.start() > 0 and text[match.start() - 1].isalnum())):
            continue
        rows.append({'style': 'ieee', 'raw_text': match.group(0), 'numeric_values': _expand_numbers(match.group('body')),
                     'author_keys': [], 'years': [], 'start_offset': match.start(), 'end_offset': match.end()})
    for match in APA_NARRATIVE_RE.finditer(text):
        rows.append({'style': 'apa7', 'raw_text': match.group(0), 'numeric_values': [],
                     'author_keys': [_author_key(match.group('author'))], 'years': [match.group('year')],
                     'start_offset': match.start(), 'end_offset': match.end()})
    for group in re.finditer(r'\(([^()]{1,240})\)', text):
        content = group.group(1)
        items = list(re.finditer(r'[^;]+', content))
        parsed = []
        for item in items:
            value = item.group(0).strip()
            match = APA_ITEM_RE.search(value)
            if match:
                parsed.append((item, value, match))
        if not parsed:
            continue
        for item, raw, parsed_citation in parsed:
            leading = len(item.group(0)) - len(item.group(0).lstrip())
            start = group.start(1) + item.start() + leading
            rows.append({'style': 'apa7', 'raw_text': raw, 'numeric_values': [],
                         'author_keys': [_author_key(parsed_citation.group('author'))],
                         'years': [parsed_citation.group('year')],
                         'start_offset': start, 'end_offset': start + len(raw)})
    rows.sort(key=lambda row: (row['start_offset'], row['end_offset']))
    return list({(row['start_offset'], row['end_offset'], row['style']): row for row in rows}.values())


def _reference_fields(raw):
    number_match = NUMBERED_REF_RE.match(raw)
    number = int(number_match.group(1) or number_match.group(2)) if number_match else None
    content = number_match.group(3).strip() if number_match else raw.strip()
    doi_match = DOI_RE.search(content)
    doi = doi_match.group(1).rstrip('.,;:)]}') if doi_match else ''
    year_match = YEAR_RE.search(content)
    year = int(year_match.group(1)) if year_match else None
    authors, author_key, title = [], '', ''
    publication = ''
    if year_match:
        prefix = content[:year_match.start()].strip(' .,:;()[]')
        authors = [part.strip() for part in re.split(r'\s+(?:&|and)\s+|;\s*', prefix) if part.strip()]
        author_key = _author_key(authors[0]) if authors else ''
        tail = content[year_match.end():].lstrip(' .,:;()[]')
        title = re.split(r'\.\s+(?=[A-Z])|\s+https?://|\s+doi\s*:', tail, maxsplit=1)[0].strip(' .,:;')[:1000]
    if not title:
        parts = [part.strip(' .,:;') for part in re.split(r'\.\s+', content) if part.strip(' .,:;')]
        title = (parts[1] if number is not None and len(parts) > 1 else (parts[0] if parts else ''))[:1000]
    urls = []
    for candidate in URL_RE.findall(content):
        candidate = candidate.rstrip('.,;:)]}')
        if urlsplit(candidate).scheme == 'https':
            urls.append(candidate[:1000])
    return {'reference_number': number, 'authors': authors[:20], 'author_key': author_key,
            'title': title, 'publication': publication, 'year': year, 'doi': doi,
            'doi_normalized': normalize_doi(doi), 'urls': list(dict.fromkeys(urls))[:10],
            'confidence': 'heuristic' if title or year or doi else 'low'}


def extract_document_citations(metadata, max_references=1500):
    citations, references = [], []
    reference_paragraph_count = 0
    for paragraph in _paragraphs(metadata or {}):
        if paragraph['in_references']:
            reference_paragraph_count += 1
            if len(references) < max_references:
                references.append({**paragraph, **_reference_fields(paragraph['text']), 'raw_text': paragraph['text'][:12000],
                                   'start_offset': 0, 'end_offset': len(paragraph['text'])})
        else:
            citations.extend({**paragraph, **row} for row in _citation_rows(paragraph))
    styles = [row['style'] for row in citations]
    detected = 'ieee' if styles.count('ieee') > styles.count('apa7') else 'apa7' if 'apa7' in styles else 'unsupported'
    return {'citations': citations, 'references': references, 'detected_style': detected,
            'reference_limit_reached': reference_paragraph_count > max_references}
