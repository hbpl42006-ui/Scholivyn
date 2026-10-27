from io import BytesIO

from django.db.models import Count, Sum
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, KeepTogether
from xml.sax.saxutils import escape


def build_analysis_report(job) -> bytes:
    """Render a deterministic PDF from persisted review rows; no model call or storage path."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=letter, rightMargin=0.65 * inch, leftMargin=0.65 * inch,
        topMargin=0.65 * inch, bottomMargin=0.65 * inch,
        title=f'Scholivyn analysis - {job.document.original_filename}',
        author='Scholivyn',
    )
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name='ScholivynTitle', parent=styles['Title'],
        textColor=colors.HexColor('#102a43'), spaceAfter=10,
    ))
    styles.add(ParagraphStyle(
        name='SectionTitle', parent=styles['Heading2'],
        textColor=colors.HexColor('#146c80'), spaceBefore=12,
    ))
    styles.add(ParagraphStyle(
        name='SmallText', parent=styles['BodyText'], fontSize=8,
        leading=11, textColor=colors.HexColor('#52606d'),
    ))

    sections = list(job.section_results.prefetch_related('issues__writing_suggestion'))
    issues = list(job.issues.select_related('section').prefetch_related('writing_suggestion').order_by('-severity', 'created_at'))
    chunks = job.chunks.exclude(status='superseded')
    usage = job.usage_records.aggregate(
        input_tokens=Sum('input_tokens'),
        output_tokens=Sum('output_tokens'),
        reasoning_token_total=Sum('reasoning_tokens'),
        usage_count=Count('id'),
        reasoning_count=Count('reasoning_tokens'),
    )

    story = [
        Paragraph('Scholivyn', styles['ScholivynTitle']),
        Paragraph('Academic manuscript review', styles['Heading2']),
        Paragraph(escape(job.document.original_filename), styles['BodyText']),
        Paragraph(
            f'Project: {escape(job.project.title)} | Revision: {job.document_version.revision_number} | '
            f'Reviewed: {timezone.localtime(job.created_at).strftime("%Y-%m-%d %H:%M %Z")}',
            styles['SmallText'],
        ),
        Paragraph(
            f'Provider disclosure: {escape(job.provider)} / {escape(job.model_identifier)} | '
            f'Prompt {escape(job.prompt_version)}',
            styles['SmallText'],
        ),
        Paragraph(f'Analysis status: {escape(job.get_status_display())}', styles['SmallText']),
        Paragraph('Scope and limitations', styles['Heading2']),
        Paragraph(
            'This report contains AI-generated editorial and methodological observations from extracted '
            'manuscript text. It is not external citation verification, a substitute for expert review, '
            'or a prediction of publication acceptance. No plagiarism or AI-authorship score is provided.',
            styles['BodyText'],
        ),
        Spacer(1, 10),
        Paragraph('Review overview', styles['Heading2']),
        Paragraph(
            f'{len(sections)} reviewed sections | {len(issues)} evidence-linked findings | '
            f'{chunks.filter(status="completed").count()} completed chunks | '
            f'{chunks.filter(status="failed").count()} failed chunks.',
            styles['BodyText'],
        ),
    ]

    input_tokens = usage['input_tokens'] or 0
    output_tokens = usage['output_tokens'] or 0
    usage_text = f'Token usage: {input_tokens:,} input | {output_tokens:,} output'
    if usage['usage_count'] and usage['reasoning_count'] == usage['usage_count']:
        usage_text += f' (includes {usage["reasoning_token_total"] or 0:,} reasoning tokens)'
    elif usage['usage_count']:
        usage_text += ' (reasoning-token breakdown unavailable for some requests)'
    story.append(Paragraph(usage_text, styles['SmallText']))
    if job.status != 'completed':
        story.append(Paragraph(
            'This is a partial review; one or more chunks did not complete.',
            styles['SmallText'],
        ))

    severity_order = ('critical', 'high', 'medium', 'low', 'informational')
    for section in sections:
        story.append(Paragraph(escape(section.section_title), styles['SectionTitle']))
        story.append(Paragraph(
            f'Section status: {escape(section.processing_status)} | '
            f'{section.completed_chunks} completed chunks | {section.failed_chunks} failed chunks',
            styles['SmallText'],
        ))
        if section.review_summary:
            story.append(Paragraph(escape(section.review_summary), styles['BodyText']))
        for label, values in (
            ('Strengths', section.strengths),
            ('Areas to strengthen', section.weaknesses),
            ('Recommendations', section.recommendations),
        ):
            if values:
                story.append(Paragraph(f'<b>{label}</b>', styles['BodyText']))
                story.extend(
                    Paragraph(f'- {escape(value)}', styles['BodyText'])
                    for value in values
                )
        for issue in (item for item in issues if item.section_id == section.id):
            blocks = [
                Paragraph(
                    f'<b>{escape(issue.severity.upper())}: {escape(issue.title)}</b>',
                    styles['BodyText'],
                ),
                Paragraph(
                    f'<b>Decision:</b> {escape(issue.resolution_status)}',
                    styles['SmallText'],
                ),
                Paragraph(f'<b>Evidence:</b> {escape(issue.evidence_snippet)}', styles['SmallText']),
                Paragraph(escape(issue.explanation), styles['BodyText']),
                Paragraph(
                    f'<b>Recommendation:</b> {escape(issue.suggested_improvement)}',
                    styles['BodyText'],
                ),
            ]
            suggestion = getattr(issue, 'writing_suggestion', None)
            if suggestion is not None:
                blocks.append(Paragraph(
                    f'<b>Suggested wording (not applied):</b> {escape(suggestion.suggested_text)}',
                    styles['SmallText'],
                ))
            story.append(KeepTogether(blocks))

    story.extend([Spacer(1, 16), Paragraph('Revision checklist', styles['Heading2'])])
    open_issues = [item for item in issues if item.resolution_status == 'open']
    if open_issues:
        for issue in sorted(open_issues, key=lambda item: severity_order.index(item.severity)):
            story.append(Paragraph(
                f'[ ] [{escape(issue.severity)}] {escape(issue.title)} - '
                f'{escape(issue.suggested_improvement)}',
                styles['BodyText'],
            ))
    else:
        story.append(Paragraph('No open issues are recorded for this analysis.', styles['BodyText']))
    doc.build(story)
    return buffer.getvalue()
