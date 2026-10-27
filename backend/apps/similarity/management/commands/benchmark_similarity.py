import time
import tracemalloc

from django.core.management.base import BaseCommand

from apps.similarity.services.matching import compare_documents


class Command(BaseCommand):
    help = 'Benchmark deterministic similarity in memory; does not access DB, Redis, files, or external providers.'

    def add_arguments(self, parser):
        parser.add_argument('--words', type=int, default=5000)

    def handle(self, *args, **options):
        count = max(100, min(options['words'], 50000))
        words = [f'token{index}' for index in range(count)]
        paragraph_size = 100
        source_paragraphs = [' '.join(words[i:i + paragraph_size]) for i in range(0, count, paragraph_size)]
        target_paragraphs = list(source_paragraphs)
        source = {'sections': [{'title': 'Methods', 'category': 'methodology', 'section_key': 'methods',
                                'paragraphs': source_paragraphs}]}
        target = {'sections': [{'title': 'Methods', 'category': 'methodology', 'section_key': 'methods',
                                'paragraphs': target_paragraphs}]}
        tracemalloc.start()
        started = time.perf_counter()
        result = compare_documents(source, target)
        elapsed = time.perf_counter() - started
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        self.stdout.write(self.style.SUCCESS(
            f'{count} source words: {elapsed:.3f}s, peak {peak / 1024 / 1024:.2f} MiB, '
            f'{result["exact_match_count"]} exact matches (in-memory fixture; no provider or persistent data).'))
