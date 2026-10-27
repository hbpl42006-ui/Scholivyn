from .crossref import CrossrefJournalsProvider
from .openalex import OpenAlexSourcesProvider

PROVIDERS = (OpenAlexSourcesProvider(), CrossrefJournalsProvider())
