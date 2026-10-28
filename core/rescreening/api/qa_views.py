"""Preview-confirm handoff without replacing prior QA assessments."""
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from core.rescreening.api.common import boundary, project_for
from core.rescreening.api.import_views import _accepting_work
from core.rescreening.services import qa_handoff


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
@boundary
def handoff(request):
    project = project_for(request)
    if request.method == 'GET':
        result = qa_handoff.preview(project)
    else:
        _accepting_work()
        result = qa_handoff.handoff(project=project, user=request.user,
            confirmation_token=request.data.get('confirmation_token'),
            acknowledge_differences=request.data.get('acknowledge_differences', False))
    return Response({'ok': True, 'data': result})
