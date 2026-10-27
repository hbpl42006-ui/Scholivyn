from django.test import SimpleTestCase

from apps.citations.services.extraction import extract_document_citations, normalize_doi
from apps.citations.services.matching import reconcile


class CitationExtractionTests(SimpleTestCase):
    def test_ieee_ranges_and_multiple_citations_keep_paragraph_offsets(self):
        text = 'Earlier work supports this result [1, 3–5]. Another source [2].'
        metadata = {'sections':[{'section_key':'intro','title':'Introduction','paragraph_records':[
            {'source_id':'p-17','paragraph_index':17,'text':text}]}]}
        result = extract_document_citations(metadata)
        self.assertEqual([item['numeric_values'] for item in result['citations']], [[1,3,4,5],[2]])
        row = result['citations'][0]
        self.assertEqual(row['paragraph_id'], 'p-17')
        self.assertEqual(text[row['start_offset']:row['end_offset']], '[1, 3–5]')

    def test_mathematical_arrays_are_not_numeric_citations(self):
        metadata = {'sections':[{'title':'Methods','paragraphs':['x = [1, 2] and index_[3] but prior work [4].']} ]}
        self.assertEqual([row['numeric_values'] for row in extract_document_citations(metadata)['citations']], [[4]])

    def test_apa_parenthetical_multiple_and_narrative_forms(self):
        result = extract_document_citations({'sections':[{'title':'Discussion','paragraphs':[
            'Prior work (Smith, 2024; Jones et al., 2022) supports Smith (2024).']} ]})
        rows = result['citations']
        self.assertEqual(len(rows), 3)
        self.assertEqual([row['author_keys'] for row in rows], [['smith'],['jones'],['smith']])
        self.assertEqual([row['years'] for row in rows], [['2024'],['2022'],['2024']])

    def test_reference_extraction_detects_number_year_doi_url_and_normalizes_doi(self):
        raw = '[7] Smith, J. (2021). A reliable title. Journal of Tests. https://doi.org/10.1234/ABC.XY.'
        result = extract_document_citations({'sections':[{'title':'References','category':'references',
            'paragraph_records':[{'source_id':'ref-7','paragraph_index':91,'text':raw}]}]})
        ref = result['references'][0]
        self.assertEqual(ref['reference_number'], 7)
        self.assertEqual(ref['year'], 2021)
        self.assertEqual(ref['doi_normalized'], '10.1234/abc.xy')
        self.assertEqual(ref['paragraph_id'], 'ref-7')
        self.assertEqual(raw[ref['start_offset']:ref['end_offset']], raw)
        self.assertEqual(normalize_doi('DOI: 10.5678/Test.ABC).'), '10.5678/test.abc')

    def test_matching_reports_unmatched_ambiguous_duplicates_and_reference_not_cited(self):
        citations = [
            {'style':'ieee','numeric_values':[1,9],'author_keys':[],'years':[],'raw_text':'[1, 9]'},
        ]
        ref1 = {'reference_number':1,'doi_normalized':'10.1/a','raw_text':'[1] Smith. T. 2020.','author_key':'smith','year':2020,'authors':['Smith'],'title':'T','confidence':'heuristic'}
        ref2 = {'reference_number':1,'doi_normalized':'10.1/a','raw_text':'[1] Smith. T. 2020.','author_key':'smith','year':2020,'authors':['Smith'],'title':'T','confidence':'heuristic'}
        ref3 = {'reference_number':2,'doi_normalized':'','raw_text':'[2] Doe. U. 2022.','author_key':'doe','year':2022,'authors':['Doe'],'title':'U','confidence':'heuristic'}
        result = reconcile(citations, [ref1,ref2,ref3], 'ieee')
        self.assertIn('ambiguous', [row['status'] for row in result['matches']])
        self.assertIn('reference_not_cited', [row['issue_code'] for row in result['matches']])
        self.assertIn('duplicate_reference', [row['code'] for row in result['findings']])
        self.assertIn('numeric_reference_missing', [row['code'] for row in result['findings']])

    def test_grouped_ieee_citation_matches_each_distinct_reference_individually(self):
        citation = {'style':'ieee','numeric_values':[1,2],'author_keys':[],'years':[],'raw_text':'[1, 2]'}
        references = [
            {'reference_number':1,'raw_text':'[1] Smith. 2020.','author_key':'smith','year':2020,'authors':['Smith'],'title':'One','confidence':'heuristic'},
            {'reference_number':2,'raw_text':'[2] Doe. 2021.','author_key':'doe','year':2021,'authors':['Doe'],'title':'Two','confidence':'heuristic'},
        ]
        result = reconcile([citation], references, 'ieee')
        citation_matches = [row for row in result['matches'] if row['citation'] is citation]
        self.assertEqual([row['reference']['reference_number'] for row in citation_matches], [1,2])
        self.assertEqual([row['status'] for row in citation_matches], ['matched','matched'])
        self.assertFalse(result['findings'])

    def test_empty_and_unicode_corpus_is_safe_and_deterministic(self):
        metadata = {'sections':[{'title':'Introduction','paragraphs':['引用研究 [1].']},
                                {'title':'References','paragraphs':['[1] 李明. 2020. 中文研究.']} ]}
        self.assertEqual(extract_document_citations(metadata), extract_document_citations(metadata))

