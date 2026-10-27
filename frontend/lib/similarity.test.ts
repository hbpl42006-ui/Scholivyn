import { describe, expect, it } from 'vitest';
import { filterSimilarityMatches, similarityEvidenceHref, type SimilarityMatch } from './similarity';

const row = (match_type: SimilarityMatch['match_type'], section: string, similarity: number) => ({
  id: 1, match_type, similarity, source_word_count: 8, citation_label: 'quoted_or_cited',
  source_section_key: 's', source_section_title: section, source_paragraph_id: 'p1', source_paragraph_index: 0,
  source_start: 0, source_end: 10, source_text: '', source_match_text: '', source_before: '', source_after: '', source_filename: 'one.docx', source_revision: 1,
  target_section_key: 't', target_section_title: section, target_paragraph_id: 'p2', target_paragraph_index: 0,
  target_start: 0, target_end: 10, target_text: '', target_match_text: '', target_before: '', target_after: '', target_filename: 'two.docx', target_revision: 1,
} as SimilarityMatch);

describe('similarity match filters', () => {
  const matches = [row('exact', 'Methods', 1), row('near_duplicate', 'Results', 0.84)];
  it('filters by type, section and minimum similarity without losing evidence objects', () => {
    expect(filterSimilarityMatches(matches, 'near_duplicate', 'Results', 0.8)).toEqual([matches[1]]);
    expect(filterSimilarityMatches(matches, 'exact', 'all', 0.8)).toEqual([matches[0]]);
    expect(filterSimilarityMatches(matches, 'all', 'Results', 0.9)).toEqual([]);
  });

  it('navigates to the exact pinned version and paragraph evidence anchor', () => {
    expect(similarityEvidenceHref('project-id', 'document-id', 'version-id', 'methods', 4))
      .toBe('/dashboard/projects/project-id/documents/document-id?version=version-id#source-methods-4');
  });
});
