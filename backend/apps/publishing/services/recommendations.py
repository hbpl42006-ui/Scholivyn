import re
from collections import defaultdict

from django.utils import timezone

from ..models import JournalMetadataSnapshot, JournalRecommendation


def normalize_issn(value):
    value = re.sub(r'[^0-9Xx]', '', str(value or '')).upper()
    if len(value) != 8: return ''
    total = sum(int(char) * (8-index) for index, char in enumerate(value[:7]))
    check = (11 - total % 11) % 11
    return value if ('X' if check == 10 else str(check)) == value[-1] else ''


def identity_evidence(records):
    issn_sets = [{normalize_issn(value) for value in row.get('issns', [])} - {''} for row in records]
    non_empty = [value for value in issn_sets if value]
    all_ids = set.union(*issn_sets) if issn_sets else set()
    issues = []
    if not all_ids: return 'unverified', ['No valid ISSN was provided by these metadata records.']
    shared_issn = len(non_empty) > 1 and bool(set.intersection(*non_empty))
    if len(non_empty) > 1 and not shared_issn:
        return 'discrepancy', ['Provider ISSN records do not agree.']
    names = {re.sub(r'[^a-z0-9]+',' ',row.get('name','').casefold()).strip() for row in records if row.get('name')}
    if len(names) > 1: issues.append('Journal names differ between metadata providers; inspect the linked source records.')
    publishers = {re.sub(r'[^a-z0-9]+',' ',row.get('publisher','').casefold()).strip() for row in records if row.get('publisher')}
    if len(publishers) > 1: issues.append('Publisher metadata differs between providers; verify against the official journal site.')
    identity = 'discrepancy' if issues else 'cross_provider_issn_match' if shared_issn else 'identifier_present_unverified'
    return identity, issues


def rank_journal(profile, journal, preferences):
    manuscript = profile.metadata
    topics = {str(term).casefold().strip() for term in manuscript.get('research_topics', []) + manuscript.get('keywords', []) if str(term).strip()}
    field = str(manuscript.get('research_field') or '').casefold().strip()
    subjects = {str(term).casefold().strip() for term in journal.subjects or [] if str(term).strip()}
    overlap = len(topics & subjects) / len(topics | subjects) if topics and subjects else None
    field_match = 1.0 if field and any(field in subject or subject in field for subject in subjects) else 0.0 if field and subjects else None
    activity = 1.0 if (journal.works_count or 0) > 0 else 0.0 if journal.works_count is not None else None
    oa_required = preferences.get('open_access_required') is True
    oa_match = (1.0 if journal.open_access is True else 0.0) if oa_required and journal.open_access is not None else None
    components = [('topic_overlap', overlap, .50), ('field_relevance', field_match, .25),
                  ('publication_activity', activity, .15), ('open_access_preference', oa_match, .10)]
    available = [(name, value, weight) for name, value, weight in components if value is not None]
    score = round(100 * sum(value*weight for _, value, weight in available) / sum(weight for _, _, weight in available)) if available else 0
    factors = {name: {'score':round(value*100) if value is not None else None,
                      'evidence': ('Metadata matched the manuscript profile.' if value is not None else 'Not available from current metadata sources.')}
               for name, value, _ in components}
    missing = [name for name, value, _ in components if value is None]
    missing.extend(['Article-type compatibility is not supplied by the current metadata sources.',
                    'This is a suitability ranking, not an acceptance probability or publication guarantee.'])
    return {'score':score, 'factors':factors, 'missing_evidence':missing}


def persist_provider_rows(job, provider, rows):
    now = timezone.now()
    for row in rows:
        existing = job.journal_snapshots.filter(provider=provider, provider_id=row['provider_id']).order_by('-verified_at').first()
        if existing:
            continue
        snapshot_values = {**row, 'provider':provider, 'verified_at':now,
                           'identity_status':'unverified', 'discrepancies':[]}
        snapshot = JournalMetadataSnapshot.objects.create(**snapshot_values)
        job.journal_snapshots.add(snapshot)
        # Provider/idempotent task re-delivery at the same task tick must not duplicate a snapshot.
        if snapshot.identity_status == 'unverified':
            snapshot.identity_status, snapshot.discrepancies = identity_evidence([row])
            snapshot.save(update_fields=('identity_status','discrepancies'))


def build_recommendations(job):
    from .providers import PROVIDERS
    from django.conf import settings
    from ..models import JournalRecommendationJob
    profile = job.profile
    metadata = profile.metadata
    query_terms = [str(item).strip() for item in metadata.get('keywords', []) if str(item).strip()][:8]
    query_terms.extend([str(item).strip() for item in metadata.get('research_topics', []) if str(item).strip()][:8])
    if metadata.get('research_field'): query_terms.insert(0, str(metadata['research_field']))
    if metadata.get('title'): query_terms.append(str(metadata['title']))
    query = ' '.join(dict.fromkeys(query_terms))[:250]
    if not query: raise ValueError('profile_has_no_search_terms')
    completed = list(job.providers_completed or [])
    for provider in PROVIDERS:
        if provider.name in completed: continue
        rows = provider.search(query, settings.JOURNAL_MAX_RESULTS)
        job.refresh_from_db(fields=('status',))
        if job.status == JournalRecommendationJob.Status.CANCELLED:
            return 0
        persist_provider_rows(job, provider.name, rows)
        completed.append(provider.name)
        JournalRecommendationJob.objects.filter(pk=job.pk).update(providers_completed=completed, updated_at=timezone.now())
        job.providers_completed = completed
        JournalRecommendationJob.objects.filter(pk=job.pk).update(progress=min(85, 10 + 35*len(completed)))
    # Prefer OpenAlex for richer subject/OA fields. Deduplicate by validated ISSN;
    # without identifiers, use exact normalized names and mark identity uncertain.
    grouped = defaultdict(list)
    snapshots = list(job.journal_snapshots.all().order_by('-verified_at'))
    parents = list(range(len(snapshots)))
    def root(index):
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index
    issn_owner, name_owner = {}, {}
    for index, row in enumerate(snapshots):
        ids = {normalize_issn(value) for value in row.issns} - {''}
        normalized_name = re.sub(r'[^a-z0-9]+',' ',row.name.casefold()).strip()
        keys = [('issn', value) for value in ids] or [('name', normalized_name)]
        for key in keys:
            owners = issn_owner if key[0] == 'issn' else name_owner
            if key[1] in owners:
                left, right = root(index), root(owners[key[1]])
                if left != right: parents[right] = left
            else:
                owners[key[1]] = index
    for index, row in enumerate(snapshots):
        grouped[root(index)].append(row)
    selected = []
    for records in grouped.values():
        records.sort(key=lambda row: (row.provider != 'openalex', row.verified_at), reverse=False)
        preferred = records[0]
        evidence = [{'name':row.name, 'publisher':row.publisher, 'issns':row.issns} for row in records]
        identity, discrepancies = identity_evidence(evidence)
        preferred.identity_status = identity
        preferred.discrepancies = discrepancies
        preferred.save(update_fields=('identity_status','discrepancies'))
        selected.append(preferred)
    JournalRecommendation.objects.filter(job=job).delete()
    for journal in selected:
        ranked = rank_journal(profile, journal, job.preferences or {})
        JournalRecommendation.objects.create(job=job, journal=journal, **ranked)
    return len(selected)
