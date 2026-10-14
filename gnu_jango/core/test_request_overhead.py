"""Per-request database work that every page multiplies: visit rows, visit stats and session saves.

A page makes 11-19 API calls. Each used to write a visit row nobody counts, the settings call
re-counted the whole visit history, and a signed-in member's session was saved on every call.
"""

from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.sessions.backends.db import SessionStore
from django.core.cache import cache
from django.http import HttpResponse
from django.test import RequestFactory, TestCase
from django.utils import timezone

from gnu_jango.core.middleware import SESSION_REFRESH_SECONDS, ThrottledSessionMiddleware
from gnu_jango.core.models import SearchKeyword, VisitLog

BROWSER = "Mozilla/5.0 (Windows NT 10.0) Chrome/120"


class VisitRowTests(TestCase):
    def test_api_calls_are_not_logged_as_visits(self):
        self.client.get("/api/v1/settings", HTTP_USER_AGENT=BROWSER)
        self.client.get("/api/v1/boards", HTTP_USER_AGENT=BROWSER)

        self.assertEqual(VisitLog.objects.filter(path__startswith="/api/").count(), 0)

    def test_a_search_call_without_a_word_and_the_logo_are_not_logged(self):
        self.client.get("/api/v1/search/popular", HTTP_USER_AGENT=BROWSER)
        self.client.get("/img/logo.png", HTTP_USER_AGENT=BROWSER)

        self.assertEqual(VisitLog.objects.count(), 0)

    def test_a_search_call_is_still_recorded_for_the_popular_words(self):
        self.client.get("/api/v1/search", {"q": "lamp"}, HTTP_USER_AGENT=BROWSER)

        self.assertTrue(SearchKeyword.objects.filter(keyword="lamp").exists())

    def test_a_page_is_still_logged(self):
        self.client.get("/", HTTP_USER_AGENT=BROWSER)

        self.assertEqual(VisitLog.objects.filter(path="/").count(), 1)


class VisitStatsTests(TestCase):
    def setUp(self):
        cache.clear()

    def visit(self, when, ip):
        log = VisitLog.objects.create(method="GET", path="/boards/free", status_code=200, ip_address=ip)
        VisitLog.objects.filter(pk=log.pk).update(created_at=when)

    def stats(self):
        return self.client.get("/api/v1/settings").json()["data"]["visit"]

    def test_todays_visits_show_at_once_while_past_days_come_from_the_cache(self):
        now = timezone.now()
        self.visit(now - timedelta(days=1), "203.0.113.1")
        self.assertEqual(self.stats(), {"today": 0, "yesterday": 1, "max": 1, "total": 1})

        self.visit(now, "203.0.113.2")
        self.visit(now, "203.0.113.3")
        self.visit(now - timedelta(days=1), "203.0.113.4")  # a past day is not re-counted right away

        self.assertEqual(self.stats(), {"today": 2, "yesterday": 1, "max": 2, "total": 3})

    def test_the_settings_call_does_not_recount_the_history_every_time(self):
        self.visit(timezone.now() - timedelta(days=3), "203.0.113.1")
        self.stats()

        with self.assertNumQueries(1):  # only today's rows (settings themselves come from a cache)
            from gnu_jango.api.v1_community import visit_stats

            visit_stats()


class SessionRefreshTests(TestCase):
    def setUp(self):
        self.member = get_user_model().objects.create_user(username="member1", password="pw-member-123")
        self.factory = RequestFactory()

    def respond(self, session, path="/api/v1/settings"):
        request = self.factory.get(path)
        request.session = session
        return ThrottledSessionMiddleware(lambda r: HttpResponse("ok")).process_response(request, HttpResponse("ok"))

    def signed_in_session(self):
        session = SessionStore()
        session["_auth_user_id"] = str(self.member.pk)
        session.save()
        return SessionStore(session.session_key)

    def test_a_session_is_refreshed_once_and_then_left_alone_for_a_while(self):
        key = self.signed_in_session().session_key

        first = self.respond(SessionStore(key))
        second = self.respond(SessionStore(key))

        self.assertIn("sessionid", first.cookies)
        self.assertNotIn("sessionid", second.cookies)
        self.assertIn("Cookie", second["Vary"])

    def test_the_session_is_refreshed_again_after_the_interval(self):
        key = self.signed_in_session().session_key
        self.respond(SessionStore(key))

        later = timezone.now().timestamp() + SESSION_REFRESH_SECONDS + 1
        with mock.patch("gnu_jango.core.middleware.time.time", return_value=later):
            response = self.respond(SessionStore(key))

        self.assertIn("sessionid", response.cookies)

    def test_a_changed_session_is_always_saved(self):
        key = self.signed_in_session().session_key
        self.respond(SessionStore(key))

        session = SessionStore(key)
        session["cart_note"] = "kept"
        response = self.respond(session)

        self.assertIn("sessionid", response.cookies)
        self.assertEqual(SessionStore(key)["cart_note"], "kept")

    def test_a_visitor_without_a_session_gets_none(self):
        response = self.respond(SessionStore())

        self.assertNotIn("sessionid", response.cookies)
