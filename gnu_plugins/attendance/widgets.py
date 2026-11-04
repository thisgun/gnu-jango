"""The 출석체크 widget for the theme's home sidebar (Slot "home.sidebar" in plugin.py)."""

from . import services

TITLE = "출석체크"
CHECK_IN_URL = "/api/v1/plugins/attendance/check-in"
LOGIN_URL = "/login"


def home_widget(request):
    point = services.rules()["point"]
    user = request.user
    if not user.is_authenticated:
        return {
            "title": TITLE,
            "body": f"로그인하고 출석하면 {point}포인트를 드려요.",
            "actions": [{"label": "로그인", "method": "GET", "url": LOGIN_URL}],
        }

    summary = services.summary(user)
    stats = [
        {"label": "연속 출석", "value": f"{summary['streak']}일"},
        {"label": "이번 달", "value": f"{len(summary['days'])}일"},
    ]
    if summary["checked_in_today"]:
        return {"title": TITLE, "body": "오늘 출석을 마쳤어요.", "stats": stats, "actions": []}
    return {
        "title": TITLE,
        "body": f"오늘 출석하면 {point}포인트를 드려요.",
        "stats": stats,
        "actions": [{"label": "출석하기", "method": "POST", "url": CHECK_IN_URL, "primary": True}],
    }
