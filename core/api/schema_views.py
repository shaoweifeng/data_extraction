"""提供版本化的 OpenAPI 契约文件。"""

import json

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.http import require_GET


@require_GET
def openapi_schema(request):
    schema_path = settings.BASE_DIR / 'docs' / 'openapi.json'
    with schema_path.open(encoding='utf-8') as stream:
        schema = json.load(stream)
    return JsonResponse(schema)
