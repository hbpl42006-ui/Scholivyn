"""Owner-scoped retention checks shared by similarity and research APIs."""
from django.db.models import Q

from apps.intelligence.models import AnalysisJob, WritingSuggestion
from .models import SimilarityJob


def collect_deletion_dependencies(owner, versions):
    """Describe dependencies without disclosing another account's report data."""
    version_ids = list(versions.values_list('pk', flat=True))
    if not version_ids:
        return {
            'reports': [], 'foreign_report_dependency': False,
            'analysis_count': 0, 'writing_suggestion_count': 0,
        }

    related_jobs = SimilarityJob.objects.filter(
        Q(source_version_id__in=version_ids) |
        Q(comparisons__target_version_id__in=version_ids)
    ).distinct()
    foreign_report_dependency = related_jobs.exclude(owner=owner).exists()
    reports = []
    for job in related_jobs.filter(owner=owner).select_related(
            'source_version__document', 'source_version__document__project').prefetch_related(
                'comparisons__target_version__document__project'):
        references = []
        if job.source_version_id in version_ids:
            version = job.source_version
            references.append({
                'role': 'source', 'filename': version.original_filename,
                'project': version.document.project.title, 'revision': version.revision_number,
            })
        for comparison in job.comparisons.all():
            if comparison.target_version_id in version_ids:
                version = comparison.target_version
                references.append({
                    'role': 'comparison target', 'filename': version.original_filename,
                    'project': version.document.project.title, 'revision': version.revision_number,
                })
        reports.append({
            'id': str(job.pk),
            'source_filename': job.source_version.original_filename,
            'source_project': job.source_version.document.project.title,
            'status': job.status,
            'references': references,
        })

    return {
        'reports': reports,
        'foreign_report_dependency': foreign_report_dependency,
        'analysis_count': AnalysisJob.objects.filter(document_version_id__in=version_ids).count(),
        'writing_suggestion_count': WritingSuggestion.objects.filter(document_version_id__in=version_ids).count(),
    }


def deletion_conflict(dependencies, *, confirmed):
    """Return a safe API conflict payload, or None when deletion may proceed."""
    reports = dependencies['reports']
    if dependencies['analysis_count'] or dependencies['writing_suggestion_count']:
        return {
            'detail': 'This manuscript has retained AI review history. Delete is blocked so those reviews and evidence references remain intact.',
            'protected_ai_analysis_count': dependencies['analysis_count'],
            'protected_writing_suggestion_count': dependencies['writing_suggestion_count'],
            'dependent_similarity_reports': reports,
            'confirmation_required': bool(reports),
            'blocked_by_other_account': dependencies['foreign_report_dependency'],
        }
    if dependencies['foreign_report_dependency']:
        return {
            'detail': 'A retained comparison owned by another account references this version. It cannot be removed from this account.',
            'protected_ai_analysis_count': 0,
            'protected_writing_suggestion_count': 0,
            'dependent_similarity_reports': reports,
            'confirmation_required': bool(reports),
            'blocked_by_other_account': True,
        }
    if reports and not confirmed:
        return {
            'detail': 'Retained similarity reports reference this manuscript. Review them and confirm if you want to delete those reports and continue.',
            'protected_ai_analysis_count': 0,
            'protected_writing_suggestion_count': 0,
            'dependent_similarity_reports': reports,
            'confirmation_required': True,
            'blocked_by_other_account': False,
        }
    return None


def delete_dependent_reports(owner, dependencies):
    """Delete only the explicitly confirmed reports owned by this requester."""
    ids = [row['id'] for row in dependencies['reports']]
    if ids:
        SimilarityJob.objects.filter(owner=owner, pk__in=ids).delete()
