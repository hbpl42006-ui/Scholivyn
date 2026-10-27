from urllib.parse import quote, urlencode

from django.conf import settings

from .base import MetadataProviderError, safe_json_get


class CrossrefProvider:
    name = 'crossref'
    host = 'api.crossref.org'
    base = 'https://api.crossref.org/works'

    def lookup(self, reference):
        doi = reference.get('doi_normalized') or ''
        if doi:
            params = urlencode({'mailto': settings.CROSSREF_MAILTO}) if settings.CROSSREF_MAILTO else ''
            data = safe_json_get(f'{self.base}/{quote(doi, safe="")}', self.host, self.name, params)
            item = data.get('message') or {}
            return self._normalize(item, f'{self.base}/{quote(doi, safe="")}') if item else None
        title = (reference.get('title') or '').strip()
        if not title: raise MetadataProviderError('insufficient_reference_metadata')
        params = {'query.title': title, 'rows': '1'}
        if settings.CROSSREF_MAILTO: params['mailto'] = settings.CROSSREF_MAILTO
        data = safe_json_get(self.base, self.host, self.name, urlencode(params))
        items = (data.get('message') or {}).get('items') or []
        return self._normalize(items[0], self.base) if items else None

    @staticmethod
    def _normalize(item, source_url):
        authors = [f"{row.get('family', '')} {row.get('given', '')}".strip() for row in item.get('author') or []]
        dates = item.get('published-print') or item.get('published-online') or item.get('created') or {}
        date_parts = dates.get('date-parts') or [[None]]
        year = date_parts[0][0] if date_parts and date_parts[0] else None
        return {'title': (item.get('title') or [''])[0], 'authors': authors,
                'year': year if isinstance(year, int) else None,
                'publication': (item.get('container-title') or [''])[0],
                'doi': item.get('DOI') or '', 'source_url': source_url}
