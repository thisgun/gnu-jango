"""WSGI helpers for servers that do not follow PEP 3333 to the letter."""

from urllib.parse import unquote_to_bytes


def decode_percent_encoded_path_info(app):
    """Decode a PATH_INFO that the server passed still percent-encoded.

    PEP 3333 expects PATH_INFO to be URL-decoded, as a str holding the raw bytes in latin-1. Vercel's
    Python runtime passes the request path as sent (``/boards/%EC%9E%90...``), so Django looked up
    board "%EC%9E%90..." and every non-ASCII URL (Korean board names) failed. Only a pure-ASCII path
    containing an escape is decoded: a decoding server already produced latin-1 text instead.
    """

    def wrapper(environ, start_response):
        path = environ.get("PATH_INFO", "")
        if "%" in path and path.isascii():
            environ["PATH_INFO"] = unquote_to_bytes(path).decode("latin-1")
        return app(environ, start_response)

    return wrapper
