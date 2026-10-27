from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from apps.citations.services.metadata import compare_metadata
from apps.citations.services.providers.base import MetadataProviderError, safe_json_get
from apps.citations.services.providers.crossref import CrossrefProvider
from apps.citations.services.providers.openalex import OpenAlexProvider


class MetadataSafetyTests(SimpleTestCase):
    def test_metadata_comparison_flags_mismatches_without_authenticity_claim(self):
        class Ref:
            title='A study of citations'; year=2020; author_key='smith'; doi_normalized='10.1234/example'
        result = compare_metadata(Ref(), {'title':'A different paper','year':2021,'authors':['Jane Doe'],'doi':'10.1234/other'})
        self.assertEqual(result['status'], 'mismatch')
        self.assertEqual(set(result['discrepancies']), {'title','year','authors','doi'})
        self.assertNotIn('authentic', result['explanation'].casefold())

    @override_settings(CITATION_PROVIDER_TIMEOUT=4, CITATION_PROVIDER_MAX_RESPONSE_BYTES=32)
    def test_provider_hosts_are_fixed_https_allowlisted_and_redirects_are_disabled(self):
        with self.assertRaises(MetadataProviderError):
            safe_json_get('http://api.crossref.org/works', 'api.crossref.org', 'crossref')
        with self.assertRaises(MetadataProviderError):
            safe_json_get('https://evil.example/works', 'api.crossref.org', 'crossref')
        self.assertEqual(CrossrefProvider.host, 'api.crossref.org')
        self.assertEqual(OpenAlexProvider.host, 'api.openalex.org')

    @patch('apps.citations.services.providers.crossref.safe_json_get')
    def test_crossref_normalizes_a_doi_record(self, get):
        get.return_value = {'message': {'title':['A Study'],'DOI':'10.1234/abc','author':[{'family':'Smith','given':'Jane'}],
            'published-print':{'date-parts':[[2022]]},'container-title':['Journal']}}
        result = CrossrefProvider().lookup({'doi_normalized':'10.1234/abc'})
        self.assertEqual(result['title'], 'A Study')
        self.assertEqual(result['year'], 2022)
        self.assertEqual(result['source_url'], 'https://api.crossref.org/works/10.1234%2Fabc')

    @patch('apps.citations.services.providers.openalex.safe_json_get')
    @override_settings(OPENALEX_API_KEY='mock-only-secret')
    def test_openalex_uses_configured_key_only_as_encoded_allowlisted_query(self, get):
        get.return_value = {'title':'Research title','publication_year':2024,'doi':'https://doi.org/10.1/a',
            'authorships':[{'author':{'display_name':'A Researcher'}}],'id':'https://api.openalex.org/works/W1'}
        result = OpenAlexProvider().lookup({'doi_normalized':'10.1/a'})
        self.assertEqual(result['authors'], ['A Researcher'])
        args, _kwargs = get.call_args
        self.assertTrue(args[0].startswith('https://api.openalex.org/works/'))
        self.assertEqual(args[1], 'api.openalex.org')
