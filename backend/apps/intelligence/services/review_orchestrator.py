import hashlib
import json
import logging
import time
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import Sum

from apps.intelligence.models import (AIUsageRecord, AnalysisChunkResult, AnalysisIssue,
                                      AnalysisSectionResult, WritingSuggestion)
from .analyzer import chunk_section_with_ranges, normalized_sections, prompt_for, word_count
from .providers.base import AIProviderError
from .providers.factory import get_provider
from .prompts.system import PROMPT_VERSION

logger = logging.getLogger(__name__)


def _estimated_cost(input_tokens: int, output_tokens: int):
    input_price = settings.AI_INPUT_COST_PER_MILLION
    output_price = settings.AI_OUTPUT_COST_PER_MILLION
    if input_price is None or output_price is None:
        return None
    return (Decimal(input_tokens) * input_price + Decimal(output_tokens) * output_price) / Decimal(1_000_000)


def _fingerprint(issue: dict) -> str:
    canonical = '|'.join(' '.join(str(issue.get(key, '')).casefold().split())
                         for key in ('category', 'title', 'evidence_text'))
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def _fingerprint_candidates(issue: dict) -> tuple[str, ...]:
    """Include the pre-normalization fingerprint so resumed legacy jobs stay deduplicated."""
    legacy = '|'.join(str(issue.get(key, '')).casefold().strip()
                      for key in ('category', 'title', 'evidence_text'))
    return tuple(dict.fromkeys((
        _fingerprint(issue), hashlib.sha256(legacy.encode('utf-8')).hexdigest(),
    )))


def _merge(values):
    return list(dict.fromkeys(value.strip() for value in values if isinstance(value, str) and value.strip()))


def _persist_chunk(job, section_result, chunk_record, result, paragraph_map, duration_ms):
    payload = result.output.model_dump(mode='json')
    accepted = []
    for issue in payload['issues']:
        evidence = issue['evidence_text']
        source_index = next((i for i, text in paragraph_map if evidence in text), None)
        if source_index is None:
            # An evidence span crossing paragraph boundaries has no single
            # paragraph anchor in the current API contract. Do not mis-anchor it.
            logger.info('Rejected review issue without a single-paragraph evidence anchor', extra={
                'analysis_job_id': str(job.pk), 'section_category': section_result.section_category,
            })
            continue
        accepted.append({**issue, 'source_paragraph_index': source_index})
    payload['issues'] = accepted
    request_key = f'{section_result.section_key}:{chunk_record.chunk_index}'
    with transaction.atomic():
        chunk_record.structured_result = payload
        chunk_record.status = AnalysisChunkResult.Status.COMPLETED
        chunk_record.error_category = ''
        chunk_record.save(update_fields=('structured_result', 'status', 'error_category', 'updated_at'))
        AIUsageRecord.objects.get_or_create(
            job=job, request_key=request_key,
            defaults={
                'user': job.owner, 'provider': job.provider, 'model_identifier': job.model_identifier,
                'input_tokens': result.input_tokens, 'output_tokens': result.output_tokens,
                'reasoning_tokens': getattr(result, 'reasoning_tokens', None),
                'estimated_cost': _estimated_cost(result.input_tokens, result.output_tokens),
                'processing_duration_ms': duration_ms,
            },
        )
        _rebuild_section(job, section_result)


def _rebuild_section(job, section_result):
    chunks = list(section_result.chunks.filter(status=AnalysisChunkResult.Status.COMPLETED).order_by('chunk_index'))
    summaries, strengths, weaknesses, recommendations = [], [], [], []
    for chunk in chunks:
        data = chunk.structured_result
        summaries.append(data.get('summary', ''))
        strengths.extend(data.get('strengths', []))
        weaknesses.extend(data.get('weaknesses', []))
        recommendations.extend(data.get('recommendations', []))
        for issue_data in data.get('issues', []):
            candidates = _fingerprint_candidates(issue_data)
            issue = AnalysisIssue.objects.filter(job=job, fingerprint__in=candidates).first()
            created = issue is None
            if created:
                issue, _ = AnalysisIssue.objects.get_or_create(
                    job=job,
                    fingerprint=candidates[0],
                    defaults={
                        'section': section_result,
                        'category': issue_data['category'][:60],
                        'severity': issue_data['severity'],
                        'title': issue_data['title'][:220],
                        'explanation': issue_data['explanation'],
                        'evidence_snippet': issue_data['evidence_text'],
                        'source_paragraph_index': issue_data.get('source_paragraph_index'),
                        'suggested_improvement': issue_data['recommendation'],
                    },
                )
            if created and issue_data.get('suggested_text'):
                WritingSuggestion.objects.get_or_create(
                    issue=issue,
                    defaults={
                        'document_version': job.document_version,
                        'original_text': issue_data['evidence_text'],
                        'suggested_text': issue_data['suggested_text'],
                        'explanation': issue_data['recommendation'],
                        'source_paragraph_index': issue_data.get('source_paragraph_index'),
                    },
                )
    section_result.review_summary = '\n\n'.join(_merge(summaries))
    section_result.strengths = _merge(strengths)
    section_result.weaknesses = _merge(weaknesses)
    section_result.recommendations = _merge(recommendations)
    section_result.completed_chunks = len(chunks)
    section_result.failed_chunks = section_result.chunks.filter(status=AnalysisChunkResult.Status.FAILED).count()
    pending = section_result.chunks.exclude(
        status__in=(AnalysisChunkResult.Status.COMPLETED, AnalysisChunkResult.Status.FAILED,
                    AnalysisChunkResult.Status.SUPERSEDED)).exists()
    section_result.processing_status = (
        AnalysisSectionResult.ProcessingStatus.PROCESSING if pending else
        AnalysisSectionResult.ProcessingStatus.FAILED if section_result.failed_chunks else
        AnalysisSectionResult.ProcessingStatus.COMPLETED
    )
    section_result.save(update_fields=('review_summary', 'strengths', 'weaknesses', 'recommendations',
                                       'completed_chunks', 'failed_chunks', 'processing_status', 'updated_at'))


def prepare_job_chunks(job, sections):
    prepared = []
    for section in sections:
        section_result, _ = AnalysisSectionResult.objects.get_or_create(
            job=job, section_key=section.key,
            defaults={'section_title': section.title, 'section_category': section.category},
        )
        configured_limit = job.chunk_token_limit or settings.AI_MAX_CHUNK_TOKENS
        chunks = chunk_section_with_ranges(section, configured_limit)
        for index, ranges in enumerate(chunks):
            record, _ = AnalysisChunkResult.objects.get_or_create(
                section=section_result, chunk_index=index,
                defaults={'job': job, 'source_ranges': _ranges_for_chunk(ranges)},
            )
            if not record.source_ranges:
                record.source_ranges = _ranges_for_chunk(ranges)
                record.save(update_fields=('source_ranges', 'updated_at'))
            if record.status == AnalysisChunkResult.Status.SUPERSEDED:
                prepared.extend(_descendant_chunks(section, section_result, record))
            else:
                prepared.append((section, section_result, _resolve_ranges(section, record.source_ranges), record))
    return prepared


def _ranges_for_chunk(ranges):
    return [{'paragraph_index': index, 'start': start, 'end': end} for index, start, end, _ in ranges]


def _resolve_ranges(section, ranges):
    resolved = []
    for item in ranges:
        index = int(item['paragraph_index'])
        start, end = int(item['start']), int(item['end'])
        paragraph = section.paragraphs[index]
        resolved.append((index, paragraph[start:end]))
    return resolved


def _descendant_chunks(section, section_result, parent):
    descendants = []
    children = parent.child_chunks.all().order_by('chunk_index')
    for child in children:
        if child.status == AnalysisChunkResult.Status.SUPERSEDED:
            descendants.extend(_descendant_chunks(section, section_result, child))
        else:
            descendants.append((section, section_result, _resolve_ranges(section, child.source_ranges), child))
    return descendants


@transaction.atomic
def _split_oversized_chunk(section, section_result, paragraph_map, record):
    """Persist a range-only split plan so retries/restarts never reprocess completed siblings."""
    ranges = record.source_ranges
    if len(ranges) > 1:
        midpoint = len(ranges) // 2
        parts = (ranges[:midpoint], ranges[midpoint:])
    elif ranges:
        item = ranges[0]
        index, start, end = int(item['paragraph_index']), int(item['start']), int(item['end'])
        source = section.paragraphs[index]
        midpoint = start + (end - start) // 2
        boundary = source.rfind(' ', start + max(1, (midpoint - start) // 2), midpoint)
        if boundary > start:
            midpoint = boundary
        if midpoint <= start or midpoint >= end:
            return []
        parts = ([{**item, 'end': midpoint}], [{**item, 'start': midpoint}])
    else:
        return []
    record.status = AnalysisChunkResult.Status.SUPERSEDED
    record.error_category = 'provider_payload_too_large'
    record.save(update_fields=('status', 'error_category', 'updated_at'))
    last_index = section_result.chunks.order_by('-chunk_index').values_list('chunk_index', flat=True).first() or 0
    children = []
    for offset, source_ranges in enumerate(parts, start=1):
        child, _ = AnalysisChunkResult.objects.get_or_create(
            section=section_result, chunk_index=last_index + offset,
            defaults={'job': record.job, 'parent_chunk': record, 'source_ranges': list(source_ranges)},
        )
        children.append((section, section_result, _resolve_ranges(section, child.source_ranges), child))
    return children


def execute_job(job, progress_callback, cancelled_callback):
    provider = get_provider()
    sections = normalized_sections(job.document_version.extraction_metadata)
    total_words = word_count(sections)
    if not sections:
        raise AIProviderError('no_extracted_text', 'No extracted manuscript text is available for review.')
    if total_words > settings.AI_MAX_DOCUMENT_WORDS:
        raise AIProviderError('document_limit', f'This manuscript exceeds the configured {settings.AI_MAX_DOCUMENT_WORDS:,}-word analysis limit.')
    prepared = prepare_job_chunks(job, sections)
    cursor = 0
    while cursor < len(prepared):
        section, section_result, paragraph_map, chunk_record = prepared[cursor]
        cursor += 1
        if cancelled_callback():
            return 'cancelled'
        if chunk_record.status in (AnalysisChunkResult.Status.COMPLETED, AnalysisChunkResult.Status.SUPERSEDED):
            continue
        instructions, content = prompt_for(section, job.reviewer_profile, paragraph_map)
        started = time.monotonic()
        try:
            result = provider.review(instructions=instructions, content=content, correlation_id=str(job.pk))
            _persist_chunk(job, section_result, chunk_record, result, paragraph_map,
                            int((time.monotonic() - started) * 1000))
        except AIProviderError as exc:
            if exc.category == 'provider_payload_too_large':
                children = _split_oversized_chunk(section, section_result, paragraph_map, chunk_record)
                if children:
                    prepared[cursor:cursor] = children
                    _rebuild_section(job, section_result)
                    continue
                exc = AIProviderError(
                    'provider_payload_too_large', 'A manuscript fragment remains too large for the configured provider limits.',
                )
            if exc.retryable and chunk_record.retry_count < settings.AI_MAX_RETRIES:
                chunk_record.retry_count += 1
                chunk_record.status = AnalysisChunkResult.Status.QUEUED
                chunk_record.error_category = exc.category
                chunk_record.save(update_fields=('retry_count', 'status', 'error_category', 'updated_at'))
                _rebuild_section(job, section_result)
                completed = job.chunks.filter(status=AnalysisChunkResult.Status.COMPLETED).count()
                total = max(1, job.chunks.exclude(status=AnalysisChunkResult.Status.SUPERSEDED).count())
                progress_callback(min(99, int(completed * 100 / total)))
                raise
            chunk_record.status = AnalysisChunkResult.Status.FAILED
            chunk_record.error_category = exc.category
            chunk_record.save(update_fields=('status', 'error_category', 'updated_at'))
            _rebuild_section(job, section_result)
            logger.warning('AI analysis section failed', extra={'analysis_job_id': str(job.pk), 'category': exc.category})
        completed = job.chunks.filter(status=AnalysisChunkResult.Status.COMPLETED).count()
        total = max(1, job.chunks.exclude(status=AnalysisChunkResult.Status.SUPERSEDED).count())
        progress_callback(min(99, int(completed * 100 / total)))
    failed = job.chunks.filter(status=AnalysisChunkResult.Status.FAILED).exists()
    pending = job.chunks.filter(status=AnalysisChunkResult.Status.QUEUED).exists()
    if pending:
        return AnalysisJobStatus.PARTIAL if job.chunks.filter(status=AnalysisChunkResult.Status.COMPLETED).exists() else AnalysisJobStatus.FAILED
    succeeded = job.chunks.filter(status=AnalysisChunkResult.Status.COMPLETED).exists()
    if failed and succeeded:
        return AnalysisJobStatus.PARTIAL
    if failed:
        return AnalysisJobStatus.FAILED
    return AnalysisJobStatus.COMPLETED


class AnalysisJobStatus:
    PARTIAL = 'partially_completed'
    FAILED = 'failed'
    COMPLETED = 'completed'
