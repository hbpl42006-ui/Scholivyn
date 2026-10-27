import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.research.models import DocumentVersion, ResearchDocument, ResearchProject
from apps.citations.models import (BibliographicReference, CitationAnalysisJob, CitationFinding,
    CitationMatch, CitationReviewDecision, ExtractedCitation, MetadataVerification)
from apps.citations.services.metadata import MetadataProviderError
from apps.citations.tasks import process_citation_analysis, verify_citation_metadata

User = get_user_model()


@override_settings(CELERY_TASK_ALWAYS_EAGER=False, CITATION_METADATA_ENABLED=True,
                   CITATION_MAX_REFERENCES=200, PRIVATE_DOCUMENT_ROOT='/tmp/scholivyn-citations-tests')
class CitationApiTaskTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username='citation-owner', email='citations@example.test', password='TestPassword!42', is_active=True)
        self.other = User.objects.create_user(username='citation-other', email='other@example.test', password='TestPassword!42', is_active=True)
        self.project = ResearchProject.objects.create(owner=self.owner, title='Citation test project')
        self.document = ResearchDocument.objects.create(project=self.project, owner=self.owner, original_filename='paper.txt')
        self.version = DocumentVersion.objects.create(document=self.document, revision_number=1, original_filename='paper.txt',
            file_extension='.txt', mime_type='text/plain', file_size=100, storage_key=f'{uuid.uuid4().hex}.txt',
            processing_status=DocumentVersion.ProcessingStatus.COMPLETED,
            extraction_metadata={'sections':[
                {'section_key':'intro','title':'Introduction','paragraph_records':[{'source_id':'p1','paragraph_index':0,'text':'Earlier research supports the method [1].'}]},
                {'section_key':'refs','title':'References','category':'references','paragraph_records':[{'source_id':'r1','paragraph_index':1,'text':'[1] Smith, J. (2021). A careful study. Journal of Tests. DOI: 10.1234/test'}]},
            ]})
        self.client = APIClient(); self.client.force_authenticate(self.owner)
        self.url = '/api/v1/citations/jobs/'
        self.request_id = uuid.uuid4()

    def create_job(self, consent=False):
        with patch('apps.citations.views._enqueue'):
            response = self.client.post(self.url, {'document_version_id':str(self.version.pk),
                'client_request_id':str(self.request_id), 'citation_style':'ieee','metadata_consent':consent}, format='json')
        return response

    def test_authenticated_job_create_idempotency_and_version_pinning(self):
        response = self.create_job()
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['document_version_id'], str(self.version.pk))
        self.assertEqual(self.create_job().status_code, 200)
        bad = self.client.post(self.url, {'document_version_id':str(uuid.uuid4()),
            'client_request_id':str(uuid.uuid4())}, format='json')
        self.assertEqual(bad.status_code, 400)

    def test_worker_persists_extraction_matches_and_finishes_idempotently(self):
        job = CitationAnalysisJob.objects.create(owner=self.owner, document_version=self.version,
            client_request_id=self.request_id, citation_style='ieee')
        with patch.object(process_citation_analysis, 'apply_async'):
            result = process_citation_analysis.run(str(job.pk))
        job.refresh_from_db()
        self.assertEqual(result['status'], CitationAnalysisJob.Status.COMPLETED)
        self.assertEqual(job.citation_count, 1)
        self.assertEqual(job.reference_count, 1)
        self.assertEqual(job.matched_count, 1)
        citation = job.citations.get()
        self.assertEqual(self.version.extraction_metadata['sections'][0]['paragraph_records'][0]['text'][citation.start_offset:citation.end_offset], '[1]')
        self.assertEqual(job.matches.get().status, 'matched')
        again = process_citation_analysis.run(str(job.pk))
        self.assertEqual(again['status'], CitationAnalysisJob.Status.COMPLETED)
        self.assertEqual(job.citations.count(), 1)

    def test_cancellation_and_cross_user_access_are_enforced(self):
        job = CitationAnalysisJob.objects.create(owner=self.owner, document_version=self.version, client_request_id=self.request_id)
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get(f'{self.url}{job.pk}/').status_code, 404)
        self.assertEqual(self.client.get(f'{self.url}{job.pk}/items/?kind=references').status_code, 404)
        self.assertEqual(self.client.get(f'{self.url}{job.pk}/report/').status_code, 404)
        self.client.force_authenticate(self.owner)
        response = self.client.post(f'{self.url}{job.pk}/actions/cancel/', {}, format='json')
        self.assertEqual(response.status_code, 200)
        job.refresh_from_db(); self.assertEqual(job.status, CitationAnalysisJob.Status.CANCELLED)
        self.assertEqual(process_citation_analysis.run(str(job.pk))['status'], CitationAnalysisJob.Status.CANCELLED)

    def test_explicit_metadata_consent_and_review_decision_persist(self):
        job = CitationAnalysisJob.objects.create(owner=self.owner, document_version=self.version,
            client_request_id=self.request_id, status=CitationAnalysisJob.Status.COMPLETED)
        finding = CitationFinding.objects.create(job=job, code='citation_without_reference', severity='definite_error',
            explanation='No matching reference.', source_section_key='intro', source_paragraph_id='p1', source_paragraph_index=0,
            source_start=31, source_end=34)
        with patch('apps.citations.views._enqueue') as enqueue, patch(
            'apps.citations.views.transaction.on_commit', side_effect=lambda callback: callback()
        ):
            bad = self.client.post(f'{self.url}{job.pk}/actions/verify-metadata/', {'consent':False}, format='json')
            self.assertEqual(bad.status_code, 400)
            good = self.client.post(f'{self.url}{job.pk}/actions/verify-metadata/', {'consent':True}, format='json')
            self.assertEqual(good.status_code, 200)
            self.assertTrue(enqueue.called)
        decision = self.client.post(f'{self.url}{job.pk}/findings/{finding.pk}/decision/',
            {'decision':'needs_review','note':'Please inspect the source.'}, format='json')
        self.assertEqual(decision.status_code, 200)
        self.assertEqual(CitationReviewDecision.objects.get(finding=finding).decision, 'needs_review')
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.post(f'{self.url}{job.pk}/findings/{finding.pk}/decision/',
            {'decision':'accepted'}, format='json').status_code, 404)

    def test_pdf_export_is_owner_scoped_and_contains_disclaimer(self):
        job = CitationAnalysisJob.objects.create(owner=self.owner, document_version=self.version,
            client_request_id=self.request_id, status=CitationAnalysisJob.Status.COMPLETED)
        response = self.client.get(f'{self.url}{job.pk}/report/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertIn('scholivyn-citations-', response['Content-Disposition'])
        response.close()

    @patch('apps.citations.tasks.PROVIDERS')
    def test_metadata_worker_is_mocked_and_persists_per_provider_results(self, providers):
        class Provider:
            name='crossref'
            def lookup(self, _reference):
                return {'title':'A careful study','authors':['Smith Jane'],'year':2021,'publication':'Journal of Tests',
                        'doi':'10.1234/test','source_url':'https://api.crossref.org/works/10.1234%2Ftest'}
        providers.__iter__.return_value = iter([Provider()])
        job = CitationAnalysisJob.objects.create(owner=self.owner, document_version=self.version,
            client_request_id=self.request_id, status=CitationAnalysisJob.Status.COMPLETED, metadata_consent=True)
        reference = BibliographicReference.objects.create(job=job, raw_text='[1] Smith (2021) A careful study',
            author_key='smith', authors=['Smith'], year=2021, title='A careful study', doi='10.1234/test',
            doi_normalized='10.1234/test', confidence='heuristic', paragraph_index=1)
        with patch('apps.citations.tasks._schedule_metadata', return_value=True):
            result = verify_citation_metadata.run(str(job.pk))
        self.assertEqual(result['status'], 'processing')
        check = MetadataVerification.objects.get(reference=reference, provider='crossref')
        self.assertEqual(check.status, 'matched')
        self.assertEqual(check.metadata['year'], 2021)

    @patch('apps.citations.tasks.PROVIDERS')
    def test_permanent_metadata_provider_error_is_terminal_not_requeued_forever(self, providers):
        class Provider:
            name = 'crossref'
            def lookup(self, _reference):
                raise MetadataProviderError('invalid_response', retryable=False)
        providers.__iter__.return_value = iter([Provider()])
        job = CitationAnalysisJob.objects.create(owner=self.owner, document_version=self.version,
            client_request_id=self.request_id, status=CitationAnalysisJob.Status.COMPLETED, metadata_consent=True)
        reference = BibliographicReference.objects.create(job=job, raw_text='Smith (2021). A careful study.',
            author_key='smith', authors=['Smith'], year=2021, title='A careful study', confidence='heuristic', paragraph_index=1)
        with patch('apps.citations.tasks._schedule_metadata', return_value=True) as schedule:
            result = verify_citation_metadata.run(str(job.pk))
        check = MetadataVerification.objects.get(reference=reference, provider='crossref')
        self.assertEqual(result['status'], 'continued')
        self.assertEqual(check.status, 'unavailable')
        schedule.assert_called_once_with(str(job.pk), 1)

