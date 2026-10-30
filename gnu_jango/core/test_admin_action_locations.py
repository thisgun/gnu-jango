"""Every admin speaks Django's action-location API, so no admin page breaks when the old one goes."""
import pytest
from django.contrib import admin
from django.contrib.admin import Action, ActionLocation

ADMINS = sorted(admin.site._registry.values(), key=lambda model_admin: str(model_admin))


@pytest.mark.parametrize("model_admin", ADMINS, ids=str)
def test_actions_are_listed_per_location(rf, admin_user, model_admin):
    request = rf.get("/admin/")
    request.user = admin_user
    for location in ActionLocation:
        # An override without action_location raises TypeError here (Django only warns, for now).
        actions = model_admin.get_actions(request, action_location=location)
        assert all(isinstance(action, Action) for action in actions.values())
        # Nothing reaches the change form unless it was declared for it.
        assert all(location in action.locations for action in actions.values())
