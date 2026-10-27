import uuid
from datetime import timedelta
from unittest.mock import patch

import pymupdf
from django.contrib.auth import get_user_model
from django.db.models.deletion import ProtectedError
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.research.models import DocumentVersion, ResearchDocument, ResearchProject
from apps.intelligence.models import AnalysisJob
from apps.similarity.models import SimilarityComparison, SimilarityJob, SimilarityMatch
from apps.similarity.tasks import process_similarity_job

User = get_user_model()


def extraction(body):
    return {'sections': [{'title': 'Introduction', 'category': 'introduction', 'section_key': 'intro',
                          'paragraphs': [body], 'paragraph_records': [{'source_id': 'p-001', 'paragraph_index': 0, 'text': body}]}]}


@override_settings(SIMILARITY_MIN_PASSAGE_WORDS=5, SIMILARITY_NEAR_THRESHOLD=.7, SIMILARITY_SHINGLE_SIZE=3)
class SimilarityApiAndTaskTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username='similarity-owner', email='owner@example.test', password='ValidPassword!42')
        self.other = User.objects.create_user(username='similarity-other', email='other@example.test', password='ValidPassword!42')
        self.client = APIClient()
        self.client.force_authenticate(self.owner)
        self.source = self.version(self.owner, 'source.docx', 'This is the original manuscript passage about robust clinical methods and carefully measured cohort outcomes.')
        self.target = self.version(self.owner, 'target.docx', 'This is the original manuscript passage about robust clinical methods and carefully measured cohort outcomes.')

    def version(self, user, filename, body):
        project = ResearchProject.objects.create(owner=user, title=filename)
        document = ResearchDocument.objects.create(owner=user, project=project, original_filename=filename)
        return DocumentVersion.objects.create(document=document, revision_number=1, original_filename=filename,
            file_extension='.docx', mime_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            file_size=10, storage_key=f'{uuid.uuid4().hex}.docx', processing_status='completed',
            extraction_metadata=extraction(body))

    def test_create_queues_and_idempotency_prevents_duplicate_jobs(self):
        payload = {'source_version_id': str(self.source.pk), 'target_version_ids': [str(self.target.pk)], 'client_request_id': str(uuid.uuid4())}
        with patch('apps.similarity.views.process_similarity_job.delay') as enqueue:
            with self.captureOnCommitCallbacks(execute=True):
                first = self.client.post('/api/v1/similarity/', payload, format='json')
            second = self.client.post('/api/v1/similarity/', payload, format='json')
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(SimilarityJob.objects.count(), 1)
        enqueue.assert_called_once()

    def test_unavailable_worker_leaves_retryable_job_with_safe_error(self):
        payload = {'source_version_id': str(self.source.pk), 'target_version_ids': [str(self.target.pk)], 'client_request_id': str(uuid.uuid4())}
        with patch('apps.similarity.views.process_similarity_job.delay', side_effect=RuntimeError('private broker detail')):
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.post('/api/v1/similarity/', payload, format='json')
        self.assertEqual(response.status_code, 201)
        job = SimilarityJob.objects.get(pk=response.data['id'])
        self.assertEqual(job.status, 'failed')
        self.assertNotIn('private broker detail', job.error_message)

    def test_other_users_cannot_select_or_read_versions(self):
        foreign = self.version(self.other, 'private.docx', 'Private text not available to this requester.')
        response = self.client.post('/api/v1/similarity/', {'source_version_id': str(self.source.pk),
            'target_version_ids': [str(foreign.pk)], 'client_request_id': str(uuid.uuid4())}, format='json')
        self.assertEqual(response.status_code, 404)
        job = SimilarityJob.objects.create(owner=self.other, source_version=foreign, client_request_id=uuid.uuid4(),
            min_passage_words=5, near_threshold=.7, shingle_size=3)
        self.assertEqual(self.client.get(f'/api/v1/similarity/{job.pk}/').status_code, 404)

    def test_processing_persists_match_evidence_and_is_idempotent_on_redelivery(self):
        job = SimilarityJob.objects.create(owner=self.owner, source_version=self.source, client_request_id=uuid.uuid4(),
            min_passage_words=5, near_threshold=.7, shingle_size=3, total_targets=1)
        from apps.similarity.models import SimilarityComparison
        comparison = SimilarityComparison.objects.create(job=job, target_version=self.target)
        result = process_similarity_job.run(str(job.pk))
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(job.__class__.objects.get(pk=job.pk).status, 'completed')
        self.assertTrue(SimilarityMatch.objects.filter(comparison=comparison, match_type='exact').exists())
        count = SimilarityMatch.objects.count()
        self.assertEqual(process_similarity_job.run(str(job.pk))['status'], 'completed')
        self.assertEqual(SimilarityMatch.objects.count(), count)
        match = SimilarityMatch.objects.get(comparison=comparison)
        self.assertEqual(self.source.extraction_metadata['sections'][0]['paragraph_records'][0]['text'][match.source_start:match.source_end],
                         'This is the original manuscript passage about robust clinical methods and carefully measured cohort outcomes')
        detail = self.client.get(f'/api/v1/similarity/{job.pk}/')
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.data['comparisons'][0]['matches'][0]['source_match_text'],
                         self.source.extraction_metadata['sections'][0]['paragraph_records'][0]['text'][match.source_start:match.source_end])
        self.assertEqual(detail.data['source_document_id'], str(self.source.document_id))
        self.assertEqual(detail.data['source_project_id'], str(self.source.document.project_id))
        target_detail = detail.data['comparisons'][0]
        self.assertEqual(target_detail['target_document_id'], str(self.target.document_id))
        self.assertEqual(target_detail['target_project_id'], str(self.target.document.project_id))
        self.assertEqual(target_detail['target_version_id'], str(self.target.pk))
        report = self.client.get(f'/api/v1/similarity/{job.pk}/report/')
        self.assertEqual(report.status_code, 200)
        payload = b''.join(report.streaming_content)
        self.assertTrue(payload.startswith(b'%PDF'))
        pdf = pymupdf.open(stream=payload, filetype='pdf')
        report_text = '\n'.join(page.get_text() for page in pdf)
        self.assertIn('Selected-source similarity report', report_text)
        self.assertIn('source.docx', report_text)
        self.assertIn('target.docx', report_text)
        self.assertIn('robust clinical methods', report_text)
        self.assertIn('not equivalent to Turnitin', report_text)
        pdf.close()

    def test_processing_remains_pinned_to_selected_document_version(self):
        job = SimilarityJob.objects.create(owner=self.owner, source_version=self.source, client_request_id=uuid.uuid4(),
            min_passage_words=5, near_threshold=.7, shingle_size=3, total_targets=1)
        comparison = SimilarityComparison.objects.create(job=job, target_version=self.target)
        later = DocumentVersion.objects.create(document=self.target.document, revision_number=2,
            original_filename='target.docx', file_extension='.docx',
            mime_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document', file_size=12,
            storage_key=f'{uuid.uuid4().hex}.docx', processing_status='completed',
            extraction_metadata=extraction('A completely different later version with distinct scientific language and measured variables.'))
        self.assertEqual(process_similarity_job.run(str(job.pk))['status'], 'completed')
        comparison.refresh_from_db()
        self.assertEqual(comparison.target_version_id, self.target.pk)
        self.assertNotEqual(comparison.target_version_id, later.pk)
        match = comparison.matches.first()
        text = self.target.extraction_metadata['sections'][0]['paragraph_records'][0]['text']
        self.assertEqual(text[match.target_start:match.target_end],
            'This is the original manuscript passage about robust clinical methods and carefully measured cohort outcomes')

    def test_multiple_identical_target_matches_count_source_words_as_union(self):
        extra = self.version(self.owner, 'target-copy.docx',
            'This is the original manuscript passage about robust clinical methods and carefully measured cohort outcomes.')
        job = SimilarityJob.objects.create(owner=self.owner, source_version=self.source, client_request_id=uuid.uuid4(),
            min_passage_words=5, near_threshold=.7, shingle_size=3, total_targets=2)
        SimilarityComparison.objects.create(job=job, target_version=self.target)
        SimilarityComparison.objects.create(job=job, target_version=extra)
        self.assertEqual(process_similarity_job.run(str(job.pk))['status'], 'completed')
        job.refresh_from_db()
        self.assertEqual(job.matched_source_words, job.source_word_count)
        self.assertEqual(job.matched_percentage, 100)

    def test_failed_job_retry_keeps_completed_comparison(self):
        job = SimilarityJob.objects.create(owner=self.owner, source_version=self.source, client_request_id=uuid.uuid4(),
            min_passage_words=5, near_threshold=.7, shingle_size=3, total_targets=1, status='failed')
        from apps.similarity.models import SimilarityComparison
        comparison = SimilarityComparison.objects.create(job=job, target_version=self.target, status='completed')
        SimilarityMatch.objects.create(comparison=comparison, match_type='exact', source_section_title='Introduction',
            source_paragraph_index=0, source_start=0, source_end=10, target_section_title='Introduction',
            target_paragraph_index=0, target_start=0, target_end=10, similarity=1, source_word_count=2,
            citation_label='potentially_unattributed')
        with patch('apps.similarity.views.process_similarity_job.delay'):
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.post(f'/api/v1/similarity/{job.pk}/retry/', {}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(SimilarityMatch.objects.filter(comparison=comparison).count(), 1)
        with patch('apps.similarity.tasks.compare_documents', side_effect=AssertionError('completed target must not be recomputed')) as compare:
            self.assertEqual(process_similarity_job.run(str(job.pk))['status'], 'completed')
        compare.assert_not_called()

    def test_report_is_private_and_contains_selected_scope_disclaimer(self):
        job = SimilarityJob.objects.create(owner=self.owner, source_version=self.source, client_request_id=uuid.uuid4(),
            min_passage_words=5, near_threshold=.7, shingle_size=3, status='completed',
            source_word_count=15, matched_source_words=10, matched_percentage=66.67, total_targets=1)
        response = self.client.get(f'/api/v1/similarity/{job.pk}/report/')
        self.assertEqual(response.status_code, 200)
        payload = b''.join(response.streaming_content)
        self.assertTrue(payload.startswith(b'%PDF'))
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get(f'/api/v1/similarity/{job.pk}/report/').status_code, 404)

    def test_owner_can_delete_similarity_report_without_deleting_manuscripts(self):
        job = SimilarityJob.objects.create(owner=self.owner, source_version=self.source, client_request_id=uuid.uuid4(),
            min_passage_words=5, near_threshold=.7, shingle_size=3, status='completed')
        SimilarityComparison.objects.create(job=job, target_version=self.target, status='completed')
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.delete(f'/api/v1/similarity/{job.pk}/').status_code, 404)
        self.assertTrue(SimilarityJob.objects.filter(pk=job.pk).exists())
        self.client.force_authenticate(self.owner)
        self.assertEqual(self.client.delete(f'/api/v1/similarity/{job.pk}/').status_code, 204)
        self.assertEqual(self.client.delete(f'/api/v1/similarity/{job.pk}/').status_code, 404)
        self.assertEqual(self.client.get(f'/api/v1/similarity/{job.pk}/').status_code, 404)
        self.assertEqual(self.client.get(f'/api/v1/similarity/{job.pk}/report/').status_code, 404)
        self.assertTrue(DocumentVersion.objects.filter(pk__in=(self.source.pk, self.target.pk)).exists())

    def test_document_delete_requires_explicit_report_confirmation_and_only_removes_owned_report(self):
        job = SimilarityJob.objects.create(owner=self.owner, source_version=self.source, client_request_id=uuid.uuid4(),
            min_passage_words=5, near_threshold=.7, shingle_size=3, status='completed')
        SimilarityComparison.objects.create(job=job, target_version=self.target, status='completed')
        target_document = self.target.document
        response = self.client.delete(f'/api/v1/documents/{target_document.pk}/')
        self.assertEqual(response.status_code, 409)
        self.assertTrue(response.data['confirmation_required'])
        self.assertEqual([item['id'] for item in response.data['dependent_similarity_reports']], [str(job.pk)])
        self.assertTrue(DocumentVersion.objects.filter(pk=self.target.pk).exists())
        confirmed = self.client.delete(f'/api/v1/documents/{target_document.pk}/',
            {'delete_dependent_similarity_reports': True}, format='json')
        self.assertEqual(confirmed.status_code, 204)
        self.assertFalse(ResearchDocument.objects.filter(pk=target_document.pk).exists())
        self.assertFalse(SimilarityJob.objects.filter(pk=job.pk).exists())
        self.assertTrue(ResearchDocument.objects.filter(pk=self.source.document_id).exists())

    def test_project_delete_requires_confirmation_for_reports_and_preserves_unrelated_source(self):
        job = SimilarityJob.objects.create(owner=self.owner, source_version=self.source, client_request_id=uuid.uuid4(),
            min_passage_words=5, near_threshold=.7, shingle_size=3, status='completed')
        SimilarityComparison.objects.create(job=job, target_version=self.target, status='completed')
        project = self.target.document.project
        response = self.client.delete(f'/api/v1/projects/{project.pk}/')
        self.assertEqual(response.status_code, 409)
        self.assertTrue(response.data['confirmation_required'])
        confirmed = self.client.delete(f'/api/v1/projects/{project.pk}/',
            {'delete_dependent_similarity_reports': True}, format='json')
        self.assertEqual(confirmed.status_code, 204)
        self.assertFalse(SimilarityJob.objects.filter(pk=job.pk).exists())
        self.assertFalse(ResearchProject.objects.filter(pk=project.pk).exists())
        self.assertTrue(ResearchProject.objects.filter(pk=self.source.document.project_id).exists())

    def test_historical_ai_reviews_block_document_and_project_deletion(self):
        version = self.target
        review = AnalysisJob.objects.create(owner=self.owner, project=version.document.project,
            document=version.document, document_version=version, provider='test', model_identifier='offline-test')
        response = self.client.delete(f'/api/v1/documents/{version.document_id}/',
            {'delete_dependent_similarity_reports': True}, format='json')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['protected_ai_analysis_count'], 1)
        self.assertTrue(AnalysisJob.objects.filter(pk=review.pk).exists())
        self.assertTrue(ResearchDocument.objects.filter(pk=version.document_id).exists())
        project_response = self.client.delete(f'/api/v1/projects/{version.document.project_id}/',
            {'delete_dependent_similarity_reports': True}, format='json')
        self.assertEqual(project_response.status_code, 409)
        self.assertTrue(AnalysisJob.objects.filter(pk=review.pk).exists())
        with self.assertRaises(ProtectedError):
            version.document.delete()
        self.assertTrue(AnalysisJob.objects.filter(pk=review.pk).exists())

    def test_foreign_owned_dependent_report_blocks_deletion_without_disclosing_it(self):
        foreign_job = SimilarityJob.objects.create(owner=self.other, source_version=self.source,
            client_request_id=uuid.uuid4(), min_passage_words=5, near_threshold=.7, shingle_size=3)
        response = self.client.delete(f'/api/v1/documents/{self.source.document_id}/',
            {'delete_dependent_similarity_reports': True}, format='json')
        self.assertEqual(response.status_code, 409)
        self.assertTrue(response.data['blocked_by_other_account'])
        self.assertEqual(response.data['dependent_similarity_reports'], [])
        self.assertTrue(SimilarityJob.objects.filter(pk=foreign_job.pk).exists())
        self.assertTrue(ResearchDocument.objects.filter(pk=self.source.document_id).exists())

    def test_cancel_prevents_worker_from_processing(self):
        job = SimilarityJob.objects.create(owner=self.owner, source_version=self.source, client_request_id=uuid.uuid4(),
            min_passage_words=5, near_threshold=.7, shingle_size=3, status='queued')
        response = self.client.post(f'/api/v1/similarity/{job.pk}/cancel/', {}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(process_similarity_job.run(str(job.pk))['status'], 'cancelled')

    def test_stale_processing_lease_is_reclaimed_after_worker_loss(self):
        job = SimilarityJob.objects.create(owner=self.owner, source_version=self.source, client_request_id=uuid.uuid4(),
            min_passage_words=5, near_threshold=.7, shingle_size=3, status='processing',
            lease_until=timezone.now() - timedelta(seconds=1), total_targets=1)
        from apps.similarity.models import SimilarityComparison
        SimilarityComparison.objects.create(job=job, target_version=self.target)
        self.assertEqual(process_similarity_job.run(str(job.pk))['status'], 'completed')
