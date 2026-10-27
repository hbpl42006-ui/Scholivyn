import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from django.urls import reverse
from rest_framework.test import APIClient

from apps.research.models import DocumentVersion, ResearchDocument, ResearchProject
from apps.publishing.models import (
    JournalMetadataSnapshot,
    JournalRecommendationJob,
    ManuscriptProfile,
    PublicationReadinessAssessment,
)
from apps.publishing.services.profiling import get_or_create_profile, profile_document, save_readiness
from apps.publishing.services.recommendations import build_recommendations, identity_evidence, normalize_issn
from apps.publishing.tasks import process_journal_recommendation


def create_version(owner, *, status=DocumentVersion.ProcessingStatus.COMPLETED, title='A research title'):
    project = ResearchProject.objects.create(owner=owner, title='Research project', research_field='Cardiology')
    document = ResearchDocument.objects.create(project=project, owner=owner, original_filename='paper.docx')
    return DocumentVersion.objects.create(
        document=document,
        revision_number=1,
        original_filename='paper.docx',
        file_extension='.docx',
        mime_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        file_size=100,
        storage_key=f'test/{uuid.uuid4().hex}',
        processing_status=status,
        extraction_metadata={
            'metadata': {'title': title},
            'sections': [
                {'category': 'abstract', 'title': 'Abstract', 'paragraphs': ['Heart disease prediction using clinical data.']},
                {'category': 'keywords', 'title': 'Keywords', 'paragraphs': ['cardiology, prediction']},
                {'category': 'methodology', 'title': 'Methods', 'paragraphs': ['We evaluated a model.']},
                {'category': 'references', 'title': 'References', 'paragraphs': ['Reference one.']},
                {'category': 'introduction', 'title': 'Introduction', 'paragraphs': ['Study context.']},
                {'category': 'results', 'title': 'Results', 'paragraphs': ['Findings.']},
                {'category': 'discussion', 'title': 'Discussion', 'paragraphs': ['Interpretation.']},
                {'category': 'conclusion', 'title': 'Conclusion', 'paragraphs': ['Conclusion.']},
            ],
        },
    )


class PublishingFixture(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='researcher', email='researcher@example.test', password='not-used')
        self.other = get_user_model().objects.create_user(username='other', email='other@example.test', password='not-used')
        self.version = create_version(self.user)
        self.profile = get_or_create_profile(self.user, self.version)


class ProfileAndReadinessTests(PublishingFixture):
    def test_profile_is_derived_from_pinned_version_and_does_not_change_document(self):
        original = self.version.extraction_metadata.copy()
        result = profile_document(self.version)
        self.assertEqual(result['title'], 'A research title')
        self.assertEqual(result['keywords'], ['cardiology', 'prediction'])
        self.assertEqual(result['methodology'], 'We evaluated a model.')
        self.assertEqual(result['references_count'], 1)
        self.assertEqual(self.version.extraction_metadata, original)

    def test_corrections_are_separate_from_inferred_profile(self):
        client = APIClient()
        client.force_authenticate(self.user)
        response = client.patch(reverse('publishing-profile-detail', args=[self.profile.pk]), {
            'corrections': {'title': 'Corrected title', 'research_topics': ['cardiology']},
        }, format='json')
        self.assertEqual(response.status_code, 200)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.inferred['title'], 'A research title')
        self.assertEqual(self.profile.metadata['title'], 'Corrected title')

    def test_profile_and_readiness_are_owner_scoped(self):
        client = APIClient()
        client.force_authenticate(self.other)
        response = client.get(reverse('publishing-profile-detail', args=[self.profile.pk]))
        self.assertEqual(response.status_code, 404)
        response = client.post(reverse('publication-readiness'), {'document_version_id': str(self.version.pk)}, format='json')
        self.assertEqual(response.status_code, 404)

    def test_only_completed_owned_versions_can_be_profiled(self):
        pending = create_version(self.user, status=DocumentVersion.ProcessingStatus.PENDING)
        client = APIClient()
        client.force_authenticate(self.user)
        response = client.post(reverse('publishing-profiles'), {'document_version_id': str(pending.pk)}, format='json')
        self.assertEqual(response.status_code, 404)

    def test_readiness_uses_cautious_labels_and_is_pinned_to_version(self):
        assessment = save_readiness(self.user, self.version)
        self.assertIsInstance(assessment, PublicationReadinessAssessment)
        by_key = {item['key']: item for item in assessment.checklist}
        self.assertEqual(by_key['title']['status'], 'requires_manual_review')
        self.assertIn(by_key['ethics']['status'], {'not_checked', 'requires_manual_review'})
        self.assertIn('optional', by_key['ethics']['detail'].lower())
        self.assertEqual(assessment.document_version_id, self.version.pk)

    def test_missing_extracted_title_is_not_reported_as_a_verified_violation(self):
        version = create_version(self.user, title='')
        assessment = save_readiness(self.user, version)
        title_item = next(item for item in assessment.checklist if item['key'] == 'title')
        self.assertEqual(title_item['status'], 'potential_issue')

    def test_submission_letter_uses_profile_title_and_keeps_placeholders(self):
        client = APIClient()
        client.force_authenticate(self.user)
        response = client.get(reverse('submission-preparation') + f'?document_version_id={self.version.pk}')
        self.assertEqual(response.status_code, 200)
        self.assertIn('A research title', response.data['cover_letter'])
        self.assertIn('[Editor name]', response.data['cover_letter'])


class RecommendationApiTests(PublishingFixture):
    def test_external_search_requires_explicit_consent(self):
        client = APIClient()
        client.force_authenticate(self.user)
        with patch('apps.publishing.views.process_journal_recommendation.apply_async') as enqueue:
            response = client.post(reverse('journal-recommendations'), {
                'profile_id': self.profile.pk,
                'client_request_id': str(uuid.uuid4()),
                'consent_to_external_metadata': False,
            }, format='json')
        self.assertEqual(response.status_code, 400)
        enqueue.assert_not_called()
        self.assertEqual(JournalRecommendationJob.objects.count(), 0)

    def test_create_is_idempotent_and_another_user_cannot_view_job(self):
        client = APIClient()
        client.force_authenticate(self.user)
        request_id = str(uuid.uuid4())
        payload = {'profile_id': self.profile.pk, 'client_request_id': request_id,
                   'consent_to_external_metadata': True, 'preferences': {'open_access_required': True}}
        with patch('apps.publishing.views.process_journal_recommendation.apply_async') as enqueue:
            with self.captureOnCommitCallbacks(execute=True):
                first = client.post(reverse('journal-recommendations'), payload, format='json')
            second = client.post(reverse('journal-recommendations'), payload, format='json')
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.data['id'], second.data['id'])
        self.assertEqual(enqueue.call_count, 1)
        client.force_authenticate(self.other)
        response = client.get(reverse('journal-recommendation-detail', args=[first.data['id']]))
        self.assertEqual(response.status_code, 404)

    def test_saved_journal_must_be_in_requesting_users_history(self):
        snapshot = JournalMetadataSnapshot.objects.create(provider='openalex', provider_id='S1', name='Journal',
            source_url='https://openalex.org/S1', verified_at=timezone.now())
        client = APIClient()
        client.force_authenticate(self.other)
        response = client.post(reverse('saved-journals'), {'journal_id': snapshot.pk}, format='json')
        self.assertEqual(response.status_code, 404)


class RankingAndProviderTests(PublishingFixture):
    def test_issn_checksum_and_cross_provider_identity(self):
        self.assertEqual(normalize_issn('0378-5955'), '03785955')
        self.assertEqual(normalize_issn('0378-5954'), '')
        state, discrepancies = identity_evidence([
            {'name': 'Journal of Cardiology', 'issns': ['0378-5955'], 'publisher': 'Publisher'},
            {'name': 'Journal of Cardiology', 'issns': ['0378-5955'], 'publisher': 'Publisher'},
        ])
        self.assertEqual(state, 'cross_provider_issn_match')
        self.assertEqual(discrepancies, [])
        state, _ = identity_evidence([
            {'name': 'Journal A', 'issns': ['0378-5955']},
            {'name': 'Journal B', 'issns': ['0028-0836']},
        ])
        self.assertEqual(state, 'discrepancy')

    def test_provider_response_is_normalized_and_no_external_request_occurs(self):
        payload = {'results': [{'id': 'https://openalex.org/S123', 'display_name': 'Cardiology Journal',
            'issn': ['0378-5955'], 'issn_l': '0378-5955', 'host_organization_name': 'Publisher',
            'homepage_url': 'https://journal.example.test', 'topics': [{'display_name': 'Cardiology'}],
            'is_oa': True, 'is_in_doaj': False, 'works_count': 123, 'counts_by_year': []}]}
        with patch('apps.publishing.services.providers.openalex.get_json', return_value=payload) as get_json:
            from apps.publishing.services.providers.openalex import OpenAlexSourcesProvider
            rows = OpenAlexSourcesProvider().search('cardiology', 5)
        get_json.assert_called_once()
        self.assertEqual(rows[0]['provider_id'], 'S123')
        self.assertTrue(rows[0]['open_access'])
        self.assertEqual(rows[0]['issns'], ['0378-5955'])
        self.assertEqual(rows[0]['source_url'], 'https://openalex.org/S123')

    def test_worker_is_idempotent_and_persists_deterministic_provider_results(self):
        from apps.publishing.services import providers

        class StubProvider:
            def __init__(self, name, issn):
                self.name, self.issn, self.calls = name, issn, 0

            def search(self, query, limit):
                self.calls += 1
                return [{'provider': self.name, 'provider_id': self.name + '-1', 'name': 'Cardiology Journal',
                    'issns': [self.issn], 'publisher': 'Publisher', 'website': '', 'subjects': ['cardiology'],
                    'open_access': True, 'doaj_listed': None, 'works_count': 42, 'publication_activity': [],
                    'source_url': 'https://example.test/' + self.name, 'raw_metadata': {}}]

        openalex = StubProvider('openalex', '0378-5955')
        crossref = StubProvider('crossref', '0378-5955')
        job = JournalRecommendationJob.objects.create(owner=self.user, profile=self.profile,
            client_request_id=uuid.uuid4(), consent_to_external_metadata=True)
        with patch.object(providers, 'PROVIDERS', (openalex, crossref)), patch.object(process_journal_recommendation, 'apply_async'):
            result = process_journal_recommendation.run(str(job.pk))
            duplicate = process_journal_recommendation.run(str(job.pk))
        job.refresh_from_db()
        self.assertEqual(result['status'], JournalRecommendationJob.Status.COMPLETED)
        self.assertEqual(duplicate['status'], JournalRecommendationJob.Status.COMPLETED)
        self.assertEqual((openalex.calls, crossref.calls), (1, 1))
        self.assertEqual(job.journal_snapshots.count(), 2)
        self.assertEqual(job.recommendations.count(), 1)
        self.assertEqual(job.recommendations.first().journal.identity_status, 'cross_provider_issn_match')


@override_settings(JOURNAL_RETRY_LIMIT=1)
class RetryResumeTests(PublishingFixture):
    def test_retryable_provider_failure_resumes_without_repeating_completed_provider(self):
        from apps.publishing.services import providers
        from apps.publishing.services.providers.base import JournalProviderError

        class FirstProvider:
            name = 'openalex'
            calls = 0
            def search(self, query, limit):
                self.calls += 1
                return [{'provider':self.name,'provider_id':'openalex-1','name':'Journal A','issns':['0378-5955'],
                    'publisher':'','website':'','subjects':['cardiology'],'open_access':None,'doaj_listed':None,
                    'works_count':1,'publication_activity':[],'source_url':'https://openalex.org/S1','raw_metadata':{}}]

        class SecondProvider:
            name = 'crossref'
            calls = 0
            fail = True
            def search(self, query, limit):
                self.calls += 1
                if self.fail:
                    raise JournalProviderError('provider_rate_limited', True, 1)
                return []

        first, second = FirstProvider(), SecondProvider()
        job = JournalRecommendationJob.objects.create(owner=self.user, profile=self.profile,
            client_request_id=uuid.uuid4(), consent_to_external_metadata=True)
        with patch.object(providers, 'PROVIDERS', (first, second)), patch.object(process_journal_recommendation, 'apply_async'), patch.object(
            process_journal_recommendation, 'retry', side_effect=RuntimeError('scheduled retry')):
            with self.assertRaisesRegex(RuntimeError, 'scheduled retry'):
                process_journal_recommendation.run(str(job.pk))
        job.refresh_from_db()
        self.assertEqual(job.status, JournalRecommendationJob.Status.QUEUED)
        self.assertEqual(job.providers_completed, ['openalex'])
        self.assertEqual(first.calls, 1)
        second.fail = False
        with patch.object(providers, 'PROVIDERS', (first, second)), patch.object(process_journal_recommendation, 'apply_async'):
            result = process_journal_recommendation.run(str(job.pk))
        job.refresh_from_db()
        self.assertEqual(result['status'], JournalRecommendationJob.Status.COMPLETED)
        self.assertEqual(first.calls, 1)
        self.assertEqual(second.calls, 2)
        self.assertEqual(job.recommendations.count(), 1)
