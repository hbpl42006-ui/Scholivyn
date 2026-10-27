"""Opt-in, metadata-only lookups against fixed Crossref/OpenAlex endpoints."""
import re
import unicodedata

from .providers import CrossrefProvider, OpenAlexProvider
from .providers.base import MetadataProviderError


PROVIDERS = (CrossrefProvider(), OpenAlexProvider())


def _tokens(text):
    value = unicodedata.normalize('NFKC', str(text or '')).casefold()
    return set(re.findall(r'[\w\u00c0-\u024f\u4e00-\u9fff]+', value))


def compare_metadata(reference, metadata):
    expected, actual = _tokens(reference.title), _tokens(metadata.get('title'))
    title_score = len(expected & actual) / max(1, len(expected | actual))
    discrepancies = []
    if expected and title_score < 0.65: discrepancies.append('title')
    if reference.year and metadata.get('year') and reference.year != metadata['year']: discrepancies.append('year')
    if reference.author_key and metadata.get('authors'):
        author_text = ' '.join(metadata['authors']).casefold()
        if reference.author_key not in author_text: discrepancies.append('authors')
    if reference.doi_normalized and metadata.get('doi'):
        from .extraction import normalize_doi
        if normalize_doi(metadata['doi']) != reference.doi_normalized: discrepancies.append('doi')
    confidence = max(0.0, min(1.0, title_score * 0.85 + (0.1 if reference.year and metadata.get('year') == reference.year else 0)
                              + (0.05 if reference.author_key and reference.author_key in ' '.join(metadata.get('authors') or []).casefold() else 0)))
    if discrepancies and ((reference.doi_normalized and metadata.get('doi')) or title_score >= 0.65):
        status = 'mismatch'
    elif reference.doi_normalized and metadata.get('doi') and not discrepancies:
        status = 'matched'
    elif title_score >= 0.90 and not discrepancies:
        status = 'matched'
    elif confidence < 0.65:
        status = 'ambiguous'
    else:
        status = 'mismatch' if discrepancies else 'matched'
    return {'status': status, 'confidence': round(confidence, 3), 'discrepancies': discrepancies,
            'explanation': ('Registry metadata differs in: ' + ', '.join(discrepancies) + '.') if discrepancies
                           else 'Registry candidate is consistent with the parsed bibliographic fields.'}


def check_reference(reference, provider):
    result = provider.lookup({'doi_normalized': reference.doi_normalized, 'title': reference.title})
    if result is None:
        return {'status': 'not_found', 'confidence': None, 'metadata': {}, 'source_url': '', 'error_category': ''}
    comparison = compare_metadata(reference, result)
    safe_metadata = {key: result.get(key) for key in ('title', 'authors', 'year', 'publication', 'doi')}
    safe_metadata['discrepancies'] = comparison['discrepancies']
    safe_metadata['explanation'] = comparison['explanation']
    return {'status': comparison['status'], 'confidence': comparison['confidence'], 'metadata': safe_metadata,
            'source_url': result.get('source_url', ''), 'error_category': ''}


__all__ = ('MetadataProviderError', 'PROVIDERS', 'check_reference', 'compare_metadata')
