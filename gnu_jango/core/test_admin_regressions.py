"""Regression tests for the admin/API hardening done in this work cycle.

Covers behaviour that the smoke check (page rendering only) does not:
- migrate_gnuboard5 raw-SQL table-name guard
- ConfigsForm secret masking + mass-assignment guard
- CsrfExemptSessionAuthentication (admin session must not 403 token API POSTs)
- add_menu_form staff/POST guard + the result_list fix
"""

import json

from django import forms
from django.contrib.auth import get_user_model
from django.test import Client, SimpleTestCase, TestCase
from django.urls import reverse

from gnu_jango.config.Configforms import SECRET_CONFIG_FIELDS, ConfigsForm
from gnu_jango.config.models import Config
from gnu_jango.core.management.commands.migrate_gnuboard5 import _safe_table

User = get_user_model()


class SafeTableNameTests(SimpleTestCase):
    def test_accepts_valid_identifiers(self):
        for name in ("g5_member", "g5_write_free", "G5_Board"):
            self.assertEqual(_safe_table(name), name)

    def test_rejects_injection_attempts(self):
        for bad in ("g5; DROP TABLE x", "a b", "tbl`", "", "g5-member", "x'y"):
            with self.assertRaises(ValueError):
                _safe_table(bad)


class ConfigsFormSecurityTests(TestCase):
    def test_secret_fields_use_masked_password_widget(self):
        form = ConfigsForm()
        checked = 0
        for name in SECRET_CONFIG_FIELDS:
            if name in form.fields:
                widget = form.fields[name].widget
                self.assertIsInstance(widget, forms.PasswordInput, name)
                self.assertFalse(widget.render_value, name)
                checked += 1
        self.assertGreater(checked, 0, "expected at least one secret config field")

    def test_non_secret_field_is_not_masked(self):
        form = ConfigsForm()
        if "cf_title" in form.fields:
            self.assertNotIsInstance(form.fields["cf_title"].widget, forms.PasswordInput)

    def test_save_ignores_unknown_config_names(self):
        # Defense against mass-assignment: an unexpected key in cleaned_data
        # must never be written to the Config table.
        form = ConfigsForm()
        form.cleaned_data = {"__unexpected__": "x"}
        form.save()
        self.assertFalse(Config.objects.filter(name="__unexpected__").exists())


class AdminApiCsrfCoexistenceTests(TestCase):
    def test_session_auth_does_not_block_token_api_post(self):
        # An admin Django session in the same browser must not make DRF's
        # SessionAuthentication 403 a token-based API POST ("CSRF Failed").
        user = User.objects.create_user(
            username="sessionuser", email="su@example.com", password="pw12345678"
        )
        client = Client(enforce_csrf_checks=True)
        client.force_login(user)
        resp = client.post(
            reverse("api_v1:auth-login"),
            data=json.dumps({"mb_id": "nobody", "mb_password": "wrong-password"}),
            content_type="application/json",
        )
        # Without CsrfExemptSessionAuthentication this is 403 before the view
        # runs; now it reaches the view (invalid creds -> 401/422).
        self.assertNotEqual(resp.status_code, 403)


class AddMenuFormSecurityTests(TestCase):
    def test_anonymous_post_is_redirected_to_login(self):
        resp = self.client.post(reverse("add_menu_form"), {"type": "group"})
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/admin/login", resp["Location"])

    def test_get_is_rejected(self):
        staff = User.objects.create_user(
            username="staff1", email="s1@example.com", password="pw12345678", is_staff=True
        )
        self.client.force_login(staff)
        resp = self.client.get(reverse("add_menu_form"))
        self.assertEqual(resp.status_code, 405)  # @require_POST

    def test_staff_post_returns_all_rows(self):
        from gnu_jango.bbs.models import Group

        Group.objects.create(gr_id="g1", gr_subject="Group One")
        Group.objects.create(gr_id="g2", gr_subject="Group Two")
        staff = User.objects.create_user(
            username="staff2", email="s2@example.com", password="pw12345678", is_staff=True
        )
        self.client.force_login(staff)
        resp = self.client.post(reverse("add_menu_form"), {"type": "group"})
        self.assertEqual(resp.status_code, 200)
        # Previously the loop overwrote result_list with the last row only.
        self.assertEqual(len(resp.context["result_list"]), 2)
