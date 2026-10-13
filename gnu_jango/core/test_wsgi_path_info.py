"""Vercel's Python runtime hands Django a still percent-encoded PATH_INFO; the WSGI wrapper decodes it."""

from django.test import SimpleTestCase

from gnu_jango.core.wsgi_path import decode_percent_encoded_path_info

KOREAN_BOARD = "%EC%9E%90%EC%9C%A0%EA%B2%8C%EC%8B%9C%ED%8C%90"  # 자유게시판


def captured_environ(environ):
    seen = {}

    def app(env, start_response):
        seen.update(env)
        return [b""]

    decode_percent_encoded_path_info(app)(environ, lambda *args: None)
    return seen


class DecodePercentEncodedPathInfoTests(SimpleTestCase):
    def test_a_percent_encoded_path_becomes_the_pep3333_form(self):
        environ = captured_environ({"PATH_INFO": f"/api/v1/boards/{KOREAN_BOARD}"})
        # PEP 3333: the URL-decoded bytes as a latin-1 str, which Django turns back into UTF-8 text.
        decoded = environ["PATH_INFO"].encode("latin-1").decode("utf-8")
        self.assertEqual(decoded, "/api/v1/boards/자유게시판")

    def test_an_encoded_ascii_character_is_decoded(self):
        self.assertEqual(captured_environ({"PATH_INFO": "/api/v1/stat%75s"})["PATH_INFO"], "/api/v1/status")

    def test_a_path_without_escapes_is_left_alone(self):
        self.assertEqual(captured_environ({"PATH_INFO": "/api/v1/status"})["PATH_INFO"], "/api/v1/status")

    def test_an_already_decoded_non_ascii_path_is_not_decoded_twice(self):
        # A server that decodes (gunicorn, runserver) passes latin-1 text, never raw escapes.
        already = "/bbs/자유게시판%".encode("utf-8").decode("latin-1")
        self.assertEqual(captured_environ({"PATH_INFO": already})["PATH_INFO"], already)

    def test_the_query_string_is_untouched(self):
        environ = captured_environ({"PATH_INFO": "/search", "QUERY_STRING": "q=%EC%9E%90"})
        self.assertEqual(environ["QUERY_STRING"], "q=%EC%9E%90")
