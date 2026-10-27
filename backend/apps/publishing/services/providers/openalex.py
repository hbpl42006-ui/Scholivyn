from urllib.parse import urlencode, urlsplit

from django.conf import settings

from .base import get_json


class OpenAlexSourcesProvider:
    name = 'openalex'
    host = 'api.openalex.org'
    endpoint = 'https://api.openalex.org/sources'

    def search(self, query, limit):
        params = {'search':query[:250], 'filter':'type:journal', 'per_page':min(limit, 50),
                  'select':'id,display_name,issn,issn_l,host_organization_name,homepage_url,topics,is_oa,is_in_doaj,works_count,counts_by_year'}
        if settings.OPENALEX_API_KEY: params['api_key'] = settings.OPENALEX_API_KEY
        payload = get_json(self.endpoint, self.host, self.name, params=urlencode(params)) or {}
        rows = []
        for item in payload.get('results') or []:
            provider_id = str(item.get('id') or '').rstrip('/').split('/')[-1]
            name = (item.get('display_name') or '').strip()
            if not provider_id or not name: continue
            topics = [row.get('display_name') for row in item.get('topics') or [] if row.get('display_name')]
            website = item.get('homepage_url') or ''
            parsed = urlsplit(website)
            if parsed.scheme not in {'http','https'} or not parsed.hostname or parsed.username or parsed.password:
                website = ''
            rows.append({'provider':self.name, 'provider_id':provider_id, 'name':name,
                'issns':list(dict.fromkeys((item.get('issn') or []) + ([item['issn_l']] if item.get('issn_l') else []))),
                'publisher':item.get('host_organization_name') or '', 'website':website,
                'subjects':topics[:30], 'open_access':item.get('is_oa'), 'doaj_listed':item.get('is_in_doaj'),
                'works_count':item.get('works_count'), 'publication_activity':item.get('counts_by_year') or [],
                'source_url':f'https://openalex.org/{provider_id}',
                'raw_metadata':{key:item.get(key) for key in ('id','display_name','issn','issn_l','host_organization_name','homepage_url','topics','is_oa','is_in_doaj','works_count','counts_by_year')}})
        return rows
