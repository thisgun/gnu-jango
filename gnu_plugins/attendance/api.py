"""POST /api/v1/plugins/attendance/check-in and GET /api/v1/plugins/attendance/me[?month=YYYY-MM]."""

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated

from gnu_jango.api.response import api_error, api_response

from . import services


@extend_schema(exclude=True)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def check_in_view(request):
    attendance, created = services.check_in(request.user)
    data = {**services.summary(request.user), "created": created, "point": attendance.point}
    return api_response(data=data, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


@extend_schema(exclude=True)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def me_view(request):
    month = None
    if request.query_params.get("month"):
        month = services.parse_month(request.query_params["month"])
        if month is None:
            return api_error("month must look like 2026-10.", status=400, code="invalid_month")
    return api_response(data=services.summary(request.user, month))
