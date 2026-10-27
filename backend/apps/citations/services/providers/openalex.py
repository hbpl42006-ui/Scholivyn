from urllib.parse import quote, urlencode

from django.conf import settings

from .base import MetadataProviderError, safe_json_get


class OpenAlexProvider:
    name = 'openalex'
    host = 'api.openalex.org'
    base = 'https://api.openalex.org/works'

    def lookup(self, reference):
        doi = reference.get('doi_normalized') or ''
        if doi:
            path = f'{self.base}/{quote("https://doi.org/" + doi, safe="")}'
            data = safe_json_get(path, self.host, self.name, urlencode(self._key_dict()))
            if not data or data.get('error'): return None
            return self._normalize(data, path)
        title = (reference.get('title') or '').strip()
        if not title: raise MetadataProviderError('insufficient_reference_metadata')
        params = {'search': title, 'per-page': '1', 'select': 'id,doi,title,publication_year,authorships,primary_location'}
        params.update(self._key_dict())
        data = safe_json_get(self.base, self.host, self.name, urlencode(params))
        rows = data.get('results') or []
        return self._normalize(rows[0], self.base) if rows else None

    @staticmethod
    def _key_dict():
        return {'api_key': settings.OPENALEX_API_KEY} if settings.OPENALEX_API_KEY else {}

    @staticmethod
    def _normalize(item, source_url):
        authors = []
        for row in item.get('authorships') or []:
            author = (row.get('author') or {}).get('display_name')
            if author: authors.append(author)
        venue = ((item.get('primary_location') or {}).get('source') or {}).get('display_name') or ''
        return {'title': item.get('title') or '', 'authors': authors,
                'year': item.get('publication_year') if isinstance(item.get('publication_year'), int) else None,
                'publication': venue, 'doi': item.get('doi') or '', 'source_url': source_url}
