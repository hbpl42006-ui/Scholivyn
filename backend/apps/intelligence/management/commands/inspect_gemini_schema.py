import json

from django.conf import settings
from django.core.management.base import BaseCommand
from google.genai import types

from apps.intelligence.services.providers.gemini_provider import (
    GEMINI_SCHEMA_KEYWORDS,
    gemini_response_json_schema,
)


def inspect_schema_structure(schema):
    node_count = 0
    maximum_depth = 0
    reference_count = 0
    unsupported = set()

    def visit(schema_node, depth):
        nonlocal node_count, maximum_depth, reference_count
        node_count += 1
        maximum_depth = max(maximum_depth, depth)
        if isinstance(schema_node, dict):
            for key, child in schema_node.items():
                if key not in GEMINI_SCHEMA_KEYWORDS:
                    unsupported.add(key)
                    continue
                if key == '$ref':
                    reference_count += 1
                if key == 'properties' and isinstance(child, dict):
                    for property_schema in child.values():
                        visit(property_schema, depth + 1)
                elif key in {'items', 'additionalProperties'} and isinstance(child, dict):
                    visit(child, depth + 1)
                elif key in {'anyOf', 'oneOf'} and isinstance(child, list):
                    for alternative in child:
                        visit(alternative, depth + 1)
                elif key == '$defs' and isinstance(child, dict):
                    for definition in child.values():
                        visit(definition, depth + 1)

    visit(schema, 1)
    return {
        'schema_bytes': len(json.dumps(schema, separators=(',', ':')).encode('utf-8')),
        'node_count': node_count,
        'maximum_depth': maximum_depth,
        'reference_count': reference_count,
        'unsupported_keywords': sorted(unsupported),
        'top_level_fields': sorted(schema.get('properties', {})),
    }


class Command(BaseCommand):
    help = 'Inspect the outgoing Gemini structured-output schema without making a provider request.'
    requires_system_checks = []

    def handle(self, *args, **options):
        schema = gemini_response_json_schema()
        # Validate that this installed SDK accepts the exact config field/value
        # used by GeminiReviewProvider. No client or network call is created.
        config = types.GenerateContentConfig(
            system_instruction='[omitted for privacy]',
            response_mime_type='application/json',
            response_json_schema=schema,
            max_output_tokens=settings.AI_MAX_OUTPUT_TOKENS,
            temperature=0,
        )
        report = {
            'provider': 'gemini',
            'model': settings.AI_MODEL,
            'request_config_fields': sorted(config.model_fields_set),
            'schema': inspect_schema_structure(config.response_json_schema),
        }
        self.stdout.write(json.dumps(report, indent=2, sort_keys=True))
