"""Conservative citation reconciliation; never rewrites manuscript text."""
from collections import defaultdict
import re
import unicodedata


def _text_key(value):
    return ' '.join(unicodedata.normalize('NFKC', str(value)).casefold().split())


def _finding(code, severity, explanation, citation=None, reference=None):
    source = citation or reference or {}
    return {'citation': citation, 'reference': reference, 'code': code, 'severity': severity,
            'explanation': explanation, 'source_section_key': source.get('section_key', ''),
            'source_section_title': source.get('section_title', ''), 'source_paragraph_id': source.get('paragraph_id', ''),
            'source_paragraph_index': source.get('paragraph_index'), 'source_start': source.get('start_offset'),
            'source_end': source.get('end_offset')}


def reconcile(citations, references, citation_style='auto'):
    matches, findings = [], []
    if citation_style == 'auto':
        ieee = sum(row['style'] == 'ieee' for row in citations)
        apa = sum(row['style'] == 'apa7' for row in citations)
        citation_style = 'ieee' if ieee > apa else 'apa7' if apa else 'auto'
    by_number, by_author_year, by_doi, by_text = defaultdict(list), defaultdict(list), defaultdict(list), defaultdict(list)
    for reference in references:
        number = reference.get('reference_number')
        if number is not None: by_number[number].append(reference)
        if reference.get('author_key') and reference.get('year'): by_author_year[(reference['author_key'], reference['year'])].append(reference)
        if reference.get('doi_normalized'): by_doi[reference['doi_normalized']].append(reference)
        key = _text_key(reference.get('raw_text', ''))
        if key: by_text[key].append(reference)
    cited_ids = set()
    for citation in citations:
        candidates = []
        if citation['style'] == 'ieee':
            for number in citation.get('numeric_values', []):
                numbered = by_number.get(number, [])
                if len(numbered) == 1:
                    reference = numbered[0]
                    cited_ids.add(id(reference))
                    matches.append({'citation': citation, 'reference': reference, 'status': 'matched',
                                    'issue_code': '', 'explanation': f'Numeric citation [{number}] matched one bibliography entry.'})
                elif len(numbered) > 1:
                    cited_ids.update(id(reference) for reference in numbered)
                    matches.append({'citation': citation, 'reference': None, 'status': 'ambiguous',
                                    'issue_code': 'ambiguous_match', 'explanation': f'Numeric citation [{number}] matches multiple bibliography entries.'})
                    findings.append(_finding('ambiguous_citation_match', 'warning',
                        f'More than one bibliography entry uses reference number {number}.', citation))
                else:
                    matches.append({'citation': citation, 'reference': None, 'status': 'unmatched',
                                    'issue_code': 'numeric_reference_missing', 'explanation': f'No bibliography entry uses reference number {number}.'})
                    findings.append(_finding('numeric_reference_missing', 'definite_error',
                        f'Numeric citation [{number}] has no bibliography entry with that number.', citation))
            continue
        elif citation['style'] == 'apa7':
            for author in citation.get('author_keys', []):
                for year_text in citation.get('years', []):
                    year_match = re.match(r'\d{4}', year_text)
                    if year_match: candidates.extend(by_author_year.get((author, int(year_match.group())), []))
        else:
            findings.append(_finding('unsupported_citation_format', 'warning', 'This citation syntax was not recognized by the supported IEEE/APA parser.', citation))
            matches.append({'citation': citation, 'reference': None, 'status': 'not_checked', 'issue_code': 'unsupported_format', 'explanation': 'Unsupported citation syntax; no match was inferred.'})
            continue
        candidates = list({id(ref): ref for ref in candidates}.values())
        if len(candidates) == 1:
            ref = candidates[0]; cited_ids.add(id(ref))
            matches.append({'citation': citation, 'reference': ref, 'status': 'matched', 'issue_code': '', 'explanation': 'Citation identifier matched one bibliography entry.'})
        elif len(candidates) > 1:
            cited_ids.update(id(ref) for ref in candidates)
            matches.append({'citation': citation, 'reference': None, 'status': 'ambiguous', 'issue_code': 'ambiguous_match', 'explanation': 'The citation key matches multiple bibliography entries.'})
            findings.append(_finding('ambiguous_citation_match', 'warning', 'More than one bibliography entry matches this citation key.', citation))
        else:
            matches.append({'citation': citation, 'reference': None, 'status': 'unmatched', 'issue_code': 'citation_without_reference', 'explanation': 'No bibliography entry matches this citation key.'})
            findings.append(_finding('citation_without_reference', 'definite_error', 'No corresponding bibliography entry was detected.', citation))
    for reference in references:
        if id(reference) not in cited_ids:
            matches.append({'citation': None, 'reference': reference, 'status': 'unmatched', 'issue_code': 'reference_not_cited', 'explanation': 'This bibliography entry was not linked to an in-text citation.'})
            findings.append(_finding('reference_not_cited', 'warning', 'This reference was not detected as cited in the manuscript body.', reference=reference))
        missing = [label for key, label in (('title', 'title'), ('year', 'publication year'), ('authors', 'author')) if not reference.get(key)]
        if missing:
            findings.append(_finding('incomplete_reference', 'warning', 'Parsed reference text appears to be missing: ' + ', '.join(missing) + '.', reference=reference))
        if reference.get('confidence') == 'low':
            matches.append({'citation': None, 'reference': reference, 'status': 'incomplete', 'issue_code': 'incomplete_reference', 'explanation': 'Reference details could not be confidently parsed from source text.'})
    for label, index in (('DOI', by_doi), ('bibliographic text', by_text)):
        for key, duplicates in index.items():
            if len(duplicates) > 1:
                for reference in duplicates[1:]:
                    findings.append(_finding('duplicate_reference', 'warning', f'This entry duplicates another reference by normalized {label}.', reference=reference))
    if citation_style == 'ieee':
        numbers = sorted({r['reference_number'] for r in references if r.get('reference_number') is not None})
        if numbers and numbers != list(range(1, max(numbers) + 1)):
            findings.append(_finding('broken_numeric_numbering', 'definite_error', 'Numbered bibliography entries are not a continuous sequence starting at 1.'))
    elif citation_style == 'apa7':
        authors = [r.get('author_key', '') for r in references if r.get('author_key')]
        if authors and authors != sorted(authors):
            findings.append(_finding('apa_reference_order', 'warning', 'Parsed reference author keys are not alphabetically ordered; verify APA 7 ordering manually.'))
    return {'matches': matches, 'findings': findings, 'detected_style': citation_style}
