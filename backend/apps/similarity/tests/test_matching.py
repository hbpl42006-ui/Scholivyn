from types import SimpleNamespace

from django.test import SimpleTestCase, override_settings

from apps.similarity.services.matching import compare_documents, compare_paragraphs, tokens


def metadata(text, *, title='Introduction', category='introduction', key='intro', source_id='p-001'):
    return {'sections': [{'title': title, 'category': category, 'section_key': key,
                          'paragraph_records': [{'text': text, 'source_id': source_id, 'paragraph_index': 0}]}]}


@override_settings(SIMILARITY_MIN_PASSAGE_WORDS=5, SIMILARITY_NEAR_THRESHOLD=.65,
                   SIMILARITY_SHINGLE_SIZE=3, SIMILARITY_MAX_DOCUMENT_WORDS=1000)
class SimilarityMatchingTests(SimpleTestCase):
    def test_tokens_normalize_unicode_and_keep_original_offsets(self):
        text = 'Cafe\u0301 and Stra' + chr(0xDF) + 'e'
        parsed = tokens(text)
        self.assertEqual([item.value for item in parsed], ['caf' + chr(0xE9), 'and', 'strasse'])
        self.assertEqual(text[parsed[0].start:parsed[0].end], 'Cafe\u0301')

    def test_exact_match_preserves_offsets_and_evidence(self):
        left = SimpleNamespace(text='Prefix. Alpha beta gamma delta epsilon zeta suffix.')
        right = SimpleNamespace(text='Other. Alpha beta gamma delta epsilon zeta ending.')
        found = compare_paragraphs(left, right, min_words=5, shingle_size=3)
        self.assertTrue(found)
        self.assertEqual(found[0]['match_type'], 'exact')
        self.assertEqual(left.text[found[0]['source_start']:found[0]['source_end']], 'Alpha beta gamma delta epsilon zeta')
        self.assertEqual(found[0]['citation_label'], 'potentially_unattributed')

    def test_overlapping_exact_candidates_merge_without_duplicate_passages(self):
        text = 'alpha beta gamma delta epsilon zeta eta theta iota kappa'
        found = compare_paragraphs(SimpleNamespace(text=text), SimpleNamespace(text=text), min_words=5, shingle_size=2)
        self.assertEqual(len(found), 1)
        self.assertEqual(text[found[0]['source_start']:found[0]['source_end']], text)
        self.assertEqual(found[0]['source_word_count'], 10)

    def test_citation_context_is_labeled_without_claiming_plagiarism(self):
        result = compare_documents(metadata('Prior work [12] used a carefully validated clinical cohort and robust statistical methods.'),
                                   metadata('Prior work [12] used a carefully validated clinical cohort and robust statistical methods.'))
        self.assertEqual(result['matches'][0]['citation_label'], 'quoted_or_cited')
        self.assertEqual(result['matched_percentage'], 100)

    def test_unicode_quotation_marks_are_treated_as_a_quotation_signal(self):
        body = '“A carefully measured clinical cohort improves reproducible outcome estimates.”'
        found = compare_paragraphs(SimpleNamespace(text=body), SimpleNamespace(text=body), min_words=5, shingle_size=2)
        self.assertEqual(found[0]['citation_label'], 'quoted_or_cited')

    def test_reference_sections_are_not_in_denominator_or_scanned(self):
        source = {'sections': [
            {'title': 'Introduction', 'category': 'introduction', 'section_key': 'i', 'paragraph_records': [{'text': 'A unique research paragraph with enough words to make the comparison pass.'}]},
            {'title': 'References', 'category': 'references', 'section_key': 'r', 'paragraph_records': [{'text': 'same citation text copied between both documents and bibliographies'}]},
        ]}
        target = {'sections': [{'title': 'References', 'category': 'references', 'section_key': 'r2', 'paragraph_records': [{'text': 'same citation text copied between both documents and bibliographies'}]}]}
        result = compare_documents(source, target)
        self.assertEqual(result['source_word_count'], 12)
        self.assertEqual(result['matches'], [])

    def test_near_duplicate_detection_is_deterministic(self):
        left = SimpleNamespace(text='alpha beta gamma delta epsilon zeta eta theta iota kappa lambda')
        right = SimpleNamespace(text='alpha beta gamma delta epsilon zeta eta theta iota kappa altered')
        one = compare_paragraphs(left, right, min_words=5, near_threshold=.7, shingle_size=2)
        two = compare_paragraphs(left, right, min_words=5, near_threshold=.7, shingle_size=2)
        self.assertEqual(one, two)
        self.assertTrue(one)

    def test_near_duplicate_offsets_point_to_original_unicode_passages(self):
        source = SimpleNamespace(text='alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu')
        target = SimpleNamespace(text='alpha beta gamma delta altered zeta eta theta changed kappa lambda mu')
        found = compare_paragraphs(source, target, min_words=5, near_threshold=.25, shingle_size=3)
        self.assertTrue(found)
        match = found[0]
        self.assertEqual(match['match_type'], 'near_duplicate')
        self.assertEqual(source.text[match['source_start']:match['source_end']], source.text)
        self.assertEqual(target.text[match['target_start']:match['target_end']], target.text)

    def test_unrelated_and_short_text_return_no_match(self):
        self.assertEqual(compare_paragraphs(SimpleNamespace(text='red blue green orange purple'),
                                            SimpleNamespace(text='one two three four five'), min_words=5, shingle_size=2), [])
        self.assertEqual(compare_paragraphs(SimpleNamespace(text='same words here'),
                                            SimpleNamespace(text='same words here'), min_words=5, shingle_size=2), [])

    def test_long_manuscript_limit_is_enforced(self):
        with self.assertRaisesRegex(ValueError, 'word limit'):
            compare_documents(metadata('word ' * 1001), metadata('word ' * 1001))

    def test_empty_document_has_zero_denominator(self):
        result = compare_documents({'sections': []}, {'sections': []})
        self.assertEqual((result['source_word_count'], result['matched_percentage']), (0, 0))

    def test_overlapping_matches_across_targets_do_not_inflate_source_denominator(self):
        source = metadata('A carefully measured clinical cohort improves reproducible outcome estimates for the study.')
        target = metadata('A carefully measured clinical cohort improves reproducible outcome estimates for the study.')
        result = compare_documents(source, target)
        self.assertEqual(result['matched_source_words'], result['source_word_count'])
        self.assertEqual(result['matched_percentage'], 100)
