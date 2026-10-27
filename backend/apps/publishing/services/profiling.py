import re
import unicodedata

from apps.citations.models import CitationAnalysisJob
from apps.research.models import DocumentVersion
from apps.similarity.models import SimilarityJob
from ..models import ManuscriptProfile, PublicationReadinessAssessment


def _clean(value):
    return re.sub(r'\s+', ' ', str(value or '')).strip()


def profile_document(version):
    metadata = version.extraction_metadata or {}
    sections = metadata.get('sections') or []
    named = {str(row.get('category') or row.get('section_key') or '').casefold(): row for row in sections}
    def section_text(keys):
        for key, row in named.items():
            if key in keys:
                records = row.get('paragraph_records') or []
                return '\n'.join(_clean(item.get('text')) for item in records if _clean(item.get('text'))) or '\n'.join(row.get('paragraphs') or [])
        return ''
    abstract = section_text({'abstract'})
    keywords_text = section_text({'keywords'})
    keywords = [x.strip(' ;,.') for x in re.split(r'[,;|]', keywords_text.partition(':')[2] or keywords_text) if x.strip(' ;,.')]
    reference_rows = [row for row in sections if str(row.get('category') or row.get('section_key') or '').casefold() in {'references','bibliography','works cited','reference list'}]
    paragraphs = []
    for row in sections:
        paragraphs.extend([_clean(item.get('text')) for item in (row.get('paragraph_records') or []) if _clean(item.get('text'))])
        if not row.get('paragraph_records'):
            paragraphs.extend([_clean(text) for text in row.get('paragraphs') or [] if _clean(text)])
    if not paragraphs:
        paragraphs = [_clean(row.get('text')) for row in metadata.get('unclassified') or [] if _clean(row.get('text'))]
    title = _clean((metadata.get('metadata') or {}).get('title') or metadata.get('title'))
    if not title:
        for row in sections:
            if str(row.get('category') or '').casefold() in {'title','document_title'}:
                title = _clean(row.get('title'))
                break
    method = section_text({'methodology','methods','materials and methods','research methods'})
    text = '\n'.join(paragraphs)
    normalized = unicodedata.normalize('NFKC', text)
    word_count = len(re.findall(r"\b[\w'-]+\b", normalized, flags=re.UNICODE))
    title_abstract = f'{title} {abstract}'.casefold()
    article_type = next((label for phrase, label in (
        ('systematic review','systematic review'),('meta-analysis','meta-analysis'),('case report','case report'),
        ('protocol','study protocol'),('randomized','clinical research'),('experiment','empirical research')) if phrase in title_abstract), '')
    stop = {'about','after','also','among','based','between','could','from','have','into','more','most','other','research','study','that','their','these','this','through','using','were','which','with'}
    terms = re.findall(r'[\w\u00c0-\u024f\u4e00-\u9fff]{3,}', unicodedata.normalize('NFKC', f'{title} {abstract}').casefold())
    topic_counts = {}
    for term in terms:
        if term not in stop:
            topic_counts[term] = topic_counts.get(term, 0) + 1
    topics = [term for term, _ in sorted(topic_counts.items(), key=lambda pair: (-pair[1], pair[0]))[:15]]
    return {'title':title, 'abstract':abstract, 'keywords':keywords[:30], 'research_field':version.document.project.research_field,
        'methodology':method, 'article_type':article_type, 'word_count':word_count,
        'references_count':sum(len(row.get('paragraph_records') or row.get('paragraphs') or []) for row in reference_rows),
        'research_topics':topics, 'section_names':[str(row.get('title') or '') for row in sections if row.get('title')]}


def get_or_create_profile(owner, version):
    inferred = profile_document(version)
    profile, created = ManuscriptProfile.objects.get_or_create(owner=owner, document_version=version, defaults={'inferred':inferred})
    if not created and profile.inferred != inferred:
        profile.inferred = inferred
        profile.save(update_fields=('inferred','updated_at'))
    return profile


def readiness_checklist(owner, version):
    profile, _ = ManuscriptProfile.objects.get_or_create(owner=owner, document_version=version,
        defaults={'inferred':profile_document(version)})
    data = profile.metadata
    names = {re.sub(r'[^a-z]+',' ',name.casefold()).strip() for name in data.get('section_names', [])}
    checks = []
    def add(key, label, status, detail): checks.append({'key':key,'label':label,'status':status,'detail':detail})
    add('title','Research title','requires_manual_review' if data.get('title') else 'potential_issue',
        'A title was extracted; confirm it is the intended submission title.' if data.get('title') else 'No title was reliably extracted; confirm or add the submission title.')
    add('abstract','Abstract','requires_manual_review' if data.get('abstract') else 'potential_issue',
        'Review abstract scope and target-journal requirements.' if data.get('abstract') else 'No abstract section was detected; requirements vary by article type and journal.')
    add('keywords','Keywords','requires_manual_review' if data.get('keywords') else 'potential_issue',
        'Confirm keyword count and format against verified journal instructions.' if data.get('keywords') else 'No keyword section was detected; it may be optional for some journals.')
    for key, aliases in {'introduction':{'introduction','background'},'methods':{'methods','methodology','materials and methods'},
                         'results':{'results','findings'},'discussion':{'discussion'},'conclusion':{'conclusion','conclusions'}}.items():
        present = bool(names & aliases)
        add('section_'+key, key.title()+' section', 'requires_manual_review' if present else 'not_checked',
            'Section detected; confirm suitability for the target journal.' if present else 'Not detected. Section requirements depend on article type and target journal.')
    citations = CitationAnalysisJob.objects.filter(owner=owner, document_version=version, status=CitationAnalysisJob.Status.COMPLETED).first()
    add('citation_consistency','Citation/reference consistency',
        'potential_issue' if citations and (citations.unmatched_count or citations.ambiguous_count or citations.incomplete_count) else 'requires_manual_review' if citations else 'not_checked',
        'A completed structural citation check found items requiring review.' if citations and (citations.unmatched_count or citations.ambiguous_count or citations.incomplete_count) else 'Structural checks do not certify citation correctness.' if citations else 'Run citation checks to inspect in-text/reference consistency.')
    similarity = SimilarityJob.objects.filter(owner=owner, source_version=version, status=SimilarityJob.Status.COMPLETED).first()
    add('similarity','Similarity report','requires_manual_review' if similarity else 'not_checked',
        'Interpret similarity matches in context; similarity is not a plagiarism finding.' if similarity else 'No completed similarity report is associated with this version.')
    raw_text = ' '.join(str(text) for row in (version.extraction_metadata or {}).get('sections', []) for text in row.get('paragraphs', []))
    for key, label, patterns in (
        ('ethics','Ethics statement',('ethic approval','institutional review board','irb')),
        ('funding','Funding statement',('funding','financial support')),
        ('conflicts','Conflicts of interest',('conflict of interest','competing interest')),
        ('data','Data availability',('data availability','data are available')),
        ('contributions','Author contributions',('author contributions','contributions of authors'))):
        present = any(pattern in raw_text.casefold() for pattern in patterns)
        add(key,label,'requires_manual_review' if present else 'not_checked',
            'A possible statement was detected; verify the wording and journal-specific policy.' if present else 'No statement was detected. This may be optional; check target-journal instructions.')
    add('figures_tables','Figure/table callouts','requires_manual_review' if re.search(r'\b(?:fig(?:ure)?|table)\s+\d+', raw_text, re.I) else 'not_checked',
        'Callouts were detected; confirm all figures/tables are supplied and cited.' if re.search(r'\b(?:fig(?:ure)?|table)\s+\d+', raw_text, re.I) else 'No figure/table callout was detected in extracted paragraph text.')
    add('word_count','Word count','requires_manual_review',f"{data.get('word_count',0)} words extracted; compare with journal limits, which are not inferred here.")
    return checks


def save_readiness(owner, version):
    checklist = readiness_checklist(owner, version)
    issues = sum(row['status'] == 'verified_issue' for row in checklist)
    potential = sum(row['status'] == 'potential_issue' for row in checklist)
    assessment, _ = PublicationReadinessAssessment.objects.update_or_create(owner=owner, document_version=version,
        defaults={'checklist':checklist, 'summary':{'verified_issues':issues,'potential_issues':potential,
            'manual_review':sum(row['status']=='requires_manual_review' for row in checklist), 'not_checked':sum(row['status']=='not_checked' for row in checklist)}})
    return assessment
