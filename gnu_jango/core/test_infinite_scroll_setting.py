"""The infinite scroll switch in the site settings (cf_infinite_scroll)."""

from django import forms
from django.core.cache import cache
from django.test import TestCase

from gnu_jango.config.Configforms import ConfigsForm
from gnu_jango.config.models import Config


class InfiniteScrollSettingTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def infinite_scroll(self, url="/api/v1/settings"):
        data = self.client.get(url).json()["data"]
        return (data["settings"] if "settings" in data else data)["infinite_scroll"]

    def test_it_is_off_by_default(self):
        self.assertIs(self.infinite_scroll(), False)

    def test_turning_it_on_reaches_the_settings_api_and_the_page_snapshot(self):
        Config.objects.update_or_create(name="cf_infinite_scroll", defaults={"value": "1"})
        cache.clear()

        self.assertIs(self.infinite_scroll(), True)
        self.assertIs(self.infinite_scroll("/api/v1/home"), True)

    def test_the_admin_form_shows_a_board_checkbox_and_saves_it(self):
        form = ConfigsForm()
        field = form.fields["cf_infinite_scroll"]

        self.assertIsInstance(field, forms.BooleanField)
        self.assertFalse(field.initial)
        bound = next(bound for bound in form if bound.name == "cf_infinite_scroll")
        self.assertEqual(bound.group_key, "2_board")
        self.assertTrue(bound.is_checkbox)

        form.cleaned_data = {"cf_infinite_scroll": True}
        form.save()
        cache.clear()
        self.assertIs(self.infinite_scroll(), True)

        form = ConfigsForm()
        form.cleaned_data = {"cf_infinite_scroll": False}
        form.save()
        cache.clear()
        self.assertIs(self.infinite_scroll(), False)
