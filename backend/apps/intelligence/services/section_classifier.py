import re


ALIASES = (
    ('abstract', ('abstract',)),
    ('keywords', ('keywords', 'key words')),
    ('introduction', ('introduction', 'background', 'problem statement')), 
    ('literature_review', ('literature review', 'literature survey', 'related literature')),
    ('related_work', ('related work', 'prior work', 'previous work')),
    ('methodology', ('methodology', 'methods', 'research methods', 'experimental setup', 'materials and methods')),
    ('results', ('results', 'findings', 'experimental results')),
    ('discussion', ('discussion', 'results and discussion')),
    ('conclusion', ('conclusion', 'conclusions', 'future work', 'conclusion and future work')),
    ('references', ('references', 'bibliography', 'works cited')),
)


def classify_heading(title: str) -> str:
    normalized = re.sub(r'[^a-z0-9 ]+', ' ', title.casefold())
    normalized = ' '.join(normalized.split())
    for category, aliases in ALIASES:
        if normalized in aliases:
            return category
    if 'literature review' in normalized:
        return 'literature_review'
    if 'method' in normalized:
        return 'methodology'
    if 'result' in normalized:
        return 'results'
    if 'discussion' in normalized:
        return 'discussion'
    return 'other'
