"""Keep Unfold interactive without granting its CSP exception to public pages."""

from unittest.mock import patch

from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings
from django.urls import resolve, reverse

from gnu_jango.core import middleware


@override_settings(DEBUG=False, G5_CSP_ALLOW_UNSAFE_SCRIPT=False)
class AdminContentSecurityPolicyTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.headers = middleware.G5SecurityHeadersMiddleware(lambda request: HttpResponse())
        # The default policy is built at import time. Rebuild it under the
        # production settings even when the runner started with DEBUG enabled.
        policy = patch.object(middleware, "CONTENT_SECURITY_POLICY", middleware.build_content_security_policy())
        policy.start()
        self.addCleanup(policy.stop)

    def response_for(self, path, *, resolved=True):
        request = self.factory.get(path)
        request.resolver_match = resolve(path) if resolved else None
        return self.headers(request)

    def script_sources(self, response):
        return response["Content-Security-Policy"].split("script-src ", 1)[1].split(";", 1)[0].split()

    def test_unfold_admin_pages_allow_alpine_expressions(self):
        for name in (
            "admin:index",
            "admin:login",
            "admin-theme-settings",
            "admin-sample-data",
            "admin-shop-settings",
        ):
            with self.subTest(view=name):
                response = self.response_for(reverse(name))
                self.assertIn("'unsafe-eval'", self.script_sources(response))
                self.assertNotIn("'unsafe-inline'", self.script_sources(response))
                self.assertEqual(response["Cache-Control"], "no-store, private")

    def test_public_pages_and_theme_preview_keep_the_strict_script_policy(self):
        for path in (
            "/",
            "/shop",
            "/api/v1/status",
            reverse("admin-theme-preview", kwargs={"theme_name": "nextjs_default"}),
        ):
            with self.subTest(path=path):
                response = self.response_for(path)
                self.assertNotIn("'unsafe-eval'", self.script_sources(response))
                self.assertNotIn("'unsafe-inline'", self.script_sources(response))

    def test_admin_path_alone_does_not_grant_the_exception(self):
        response = self.response_for("/admin/not-a-resolved-admin-view/", resolved=False)
        self.assertNotIn("'unsafe-eval'", self.script_sources(response))
