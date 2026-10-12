from rest_framework.response import Response


def api_response(data=None, *, meta=None, errors=None, status=None, ok=True):
    return Response(
        {
            "success": ok,
            "ok": ok,
            "data": data if data is not None else {},
            "message": "" if ok else "API Error",
            "meta": meta if meta is not None else {},
            "errors": errors if errors is not None else {},
        },
        status=status,
    )


def api_error(message, *, status=400, code="error", details=None):
    return Response(
        {
            "success": False,
            "ok": False,
            "data": {},
            "message": message,
            "errors": details if isinstance(details, dict) else {code: message},
            "code": code,
            "meta": {},
        },
        status=status,
    )
