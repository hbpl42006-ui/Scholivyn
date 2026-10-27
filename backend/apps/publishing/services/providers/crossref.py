from urllib.parse import urlencode

from .base import get_json


class CrossrefJournalsProvider:
    name = 'crossref'
    host = 'api.crossref.org'
    endpoint = 'https://api.crossref.org/journals'

    def search(self, query, limit):
        payload = get_json(self.endpoint, self.host, self.name,
                           params=urlencode({'query':query[:250], 'rows':min(limit, 50)})) or {}
        rows = []
        for item in (payload.get('message') or {}).get('items') or []:
            name = (item.get('title') or '').strip()
            issns = list(dict.fromkeys(item.get('ISSN') or []))
            provider_id = 'issn:' + (issns[0] if issns else name.casefold())
            if not name or provider_id == 'issn:': continue
            rows.append({'provider':self.name, 'provider_id':provider_id, 'name':name,
                'issns':issns, 'publisher':item.get('publisher') or '', 'website':'',
                'subjects':[], 'open_access':None, 'doaj_listed':None,
                'works_count':item.get('counts', {}).get('total-dois'), 'publication_activity':[],
                'source_url':f"https://api.crossref.org/journals/{issns[0]}" if issns else self.endpoint,
                'raw_metadata':{key:item.get(key) for key in ('title','ISSN','publisher','counts','last-status-check-time','breakdowns') if key in item}})
        return rows
