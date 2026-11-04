from django.urls import path

from . import api

app_name = "attendance_api"

urlpatterns = [
    path("check-in", api.check_in_view, name="check-in"),
    path("me", api.me_view, name="me"),
]
