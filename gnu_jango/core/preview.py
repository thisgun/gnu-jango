"""Preview deployments cannot send payments, mail, SMS, or scheduled jobs."""
from django.http import JsonResponse


class PreviewSafetyMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path.lower()
        if any(part in path for part in ("/payments", "/payment/", "/webhook", "/oauth", "/social/", "/sms/", "/api/internal/cron")):
            response = JsonResponse({"ok": False, "error": "External integrations are disabled in Preview."}, status=403)
        else:
            response = self.get_response(request)
        response["X-Robots-Tag"] = "noindex, nofollow, noarchive"
        return response
