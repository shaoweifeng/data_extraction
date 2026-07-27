from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def ai_models_list(request):
    from core.services.ai_models_config import get_models_for_frontend

    return Response(get_models_for_frontend())

