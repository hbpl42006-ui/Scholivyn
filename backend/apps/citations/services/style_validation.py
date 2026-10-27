"""Structural style checks; not a comprehensive style-compliance certificate."""


def validate_style(citations, selected_style):
    if selected_style not in {'ieee', 'apa7'}:
        return ([{'code': 'unsupported_citation_style', 'severity': 'warning',
                 'explanation': 'Automatic detection did not identify IEEE or APA 7 confidently; style-specific checks were not applied.'}]
                if citations else [])
    return [{'citation': citation, 'reference': None, 'code': 'mixed_citation_style', 'severity': 'warning',
             'explanation': f'This citation uses {citation["style"]} syntax in a {selected_style.upper()}-selected analysis.'}
            for citation in citations if citation['style'] != selected_style]
