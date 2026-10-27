"""Selected-source boundary for similarity providers.

Future licensed/public providers can implement this protocol only after their
coverage and access terms are approved. This release deliberately ships only
the owner-scoped workspace provider and performs no web/database searches.
"""
from dataclasses import dataclass
from typing import Protocol

from django.shortcuts import get_object_or_404

from apps.research.models import DocumentVersion
from apps.similarity.models import SimilarityJob


@dataclass(frozen=True)
class SelectedVersion:
    version: DocumentVersion
    extraction_metadata: dict


class SimilaritySourceProvider(Protocol):
    def load_selected_versions(self, job: SimilarityJob) -> tuple[SelectedVersion, list[SelectedVersion]]: ...


class OwnedWorkspaceVersionProvider:
    """Return only source/target versions already selected by this owner."""

    def load_selected_versions(self, job):
        scope = DocumentVersion.objects.select_related('document__project').filter(
            document__owner_id=job.owner_id, document__project__owner_id=job.owner_id,
            processing_status=DocumentVersion.ProcessingStatus.COMPLETED)
        source = get_object_or_404(scope, pk=job.source_version_id)
        targets = list(scope.filter(similarity_target_comparisons__job_id=job.pk).distinct())
        if len(targets) != job.total_targets:
            raise ValueError('A selected target version is unavailable in the owner workspace.')
        return (SelectedVersion(source, source.extraction_metadata or {}),
                [SelectedVersion(target, target.extraction_metadata or {}) for target in targets])
