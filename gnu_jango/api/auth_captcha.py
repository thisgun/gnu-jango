"""Registration captcha (image and audio) of the auth API."""

import io
import math
import secrets
import struct
import wave
from pathlib import Path

from django.conf import settings
from django.http import HttpResponse
from django.views.decorators.cache import never_cache
from PIL import Image, ImageDraw, ImageFont
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny




CAPTCHA_SESSION_KEY = "g5_captcha_key"


CAPTCHA_ATTEMPT_SESSION_KEY = "g5_captcha_count"


CAPTCHA_MAX_FAILURES = 6


CAPTCHA_ALPHABET = "23456789"


def _new_captcha_code():
    return "".join(secrets.choice(CAPTCHA_ALPHABET) for _ in range(6))


def _store_captcha(request, code):
    request.session[CAPTCHA_SESSION_KEY] = str(code)
    request.session[CAPTCHA_ATTEMPT_SESSION_KEY] = 0
    request.session.modified = True


def _captcha_matches(request, value):
    expected = str(request.session.get(CAPTCHA_SESSION_KEY, "")).strip()
    submitted = str(value or "").strip()
    if not expected or not submitted:
        return False
    try:
        failed_attempts = int(request.session.get(CAPTCHA_ATTEMPT_SESSION_KEY, 0))
    except (TypeError, ValueError):
        failed_attempts = CAPTCHA_MAX_FAILURES
    if failed_attempts >= CAPTCHA_MAX_FAILURES:
        return False
    if secrets.compare_digest(expected, submitted):
        return True

    request.session[CAPTCHA_ATTEMPT_SESSION_KEY] = failed_attempts + 1
    request.session.modified = True
    return False


def _consume_captcha(request):
    removed = False
    for key in (CAPTCHA_SESSION_KEY, CAPTCHA_ATTEMPT_SESSION_KEY):
        if key in request.session:
            request.session.pop(key, None)
            removed = True
    if removed:
        request.session.modified = True


def _captcha_font(size=34):
    for font_name in ("arial.ttf", "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(font_name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _captcha_image(code):
    image = Image.new("RGB", (160, 60), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    font = _captcha_font()

    for _ in range(9):
        x1, y1 = secrets.randbelow(160), secrets.randbelow(60)
        x2, y2 = secrets.randbelow(160), secrets.randbelow(60)
        color = (
            140 + secrets.randbelow(90),
            140 + secrets.randbelow(90),
            140 + secrets.randbelow(90),
        )
        draw.line((x1, y1, x2, y2), fill=color, width=1)

    for index, char in enumerate(code):
        x = 15 + index * 22 + secrets.randbelow(4)
        y = 10 + secrets.randbelow(10)
        color = (
            20 + secrets.randbelow(80),
            40 + secrets.randbelow(90),
            60 + secrets.randbelow(100),
        )
        draw.text((x, y), char, font=font, fill=color)

    for _ in range(120):
        x, y = secrets.randbelow(160), secrets.randbelow(60)
        image.putpixel(
            (x, y),
            (
                120 + secrets.randbelow(120),
                120 + secrets.randbelow(120),
                120 + secrets.randbelow(120),
            ),
        )

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _captcha_audio_roots():
    configured = str(getattr(settings, "CAPTCHA_AUDIO_MP3_ROOT", "") or "").strip()
    if configured:
        yield Path(configured)

    templates_dir = getattr(settings, "TEMPLATES_DIR", None)
    if templates_dir:
        yield Path(templates_dir) / "statics" / "kcaptcha" / "mp3" / "basic"

    yield Path(r"C:\xampp824\www\gnuboard5_3\plugin\kcaptcha\mp3\basic")


def _captcha_mp3_audio(code):
    digits = [char for char in str(code) if char.isdigit()]
    if not digits:
        return b""

    for root in _captcha_audio_roots():
        try:
            files = [root / f"{digit}.mp3" for digit in digits]
        except TypeError:
            continue
        if not all(path.is_file() for path in files):
            continue

        chunks = []
        for path in files:
            try:
                chunks.append(path.read_bytes())
            except OSError:
                chunks = []
                break
        if chunks:
            return b"".join(chunks)

    return b""


def _captcha_tone_audio(code):
    sample_rate = 16000
    digit_seconds = 0.28
    gap_seconds = 0.08
    amplitude = 10500
    buffer = io.BytesIO()

    def tone_samples(frequency, seconds):
        total = int(sample_rate * seconds)
        fade = max(1, int(sample_rate * 0.015))
        for index in range(total):
            envelope = 1.0
            if index < fade:
                envelope = index / fade
            elif total - index < fade:
                envelope = max(0.0, (total - index) / fade)
            sample = int(amplitude * envelope * math.sin(2 * math.pi * frequency * index / sample_rate))
            yield struct.pack("<h", sample)

    def silence_samples(seconds):
        return b"\x00\x00" * int(sample_rate * seconds)

    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        for char in str(code):
            if not char.isdigit():
                continue
            digit = int(char)
            frequency = 420 + digit * 70
            wav.writeframes(b"".join(tone_samples(frequency, digit_seconds)))
            wav.writeframes(silence_samples(gap_seconds))

    return buffer.getvalue()


def _captcha_audio(code):
    mp3 = _captcha_mp3_audio(code)
    if mp3:
        return mp3, "audio/mpeg"
    return _captcha_tone_audio(code), "audio/wav"


def _no_cache_audio_response(content, content_type):
    response = HttpResponse(content, content_type=content_type)
    response["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response["Pragma"] = "no-cache"
    response["Content-Disposition"] = "inline"
    return response


@never_cache
@api_view(["GET"])
@permission_classes([AllowAny])
def captcha_view(request):
    code = _new_captcha_code()
    _store_captcha(request, code)
    response = HttpResponse(_captcha_image(code), content_type="image/png")
    response["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response["Pragma"] = "no-cache"
    return response


@never_cache
@api_view(["GET"])
@permission_classes([AllowAny])
def captcha_audio_view(request):
    code = str(request.session.get(CAPTCHA_SESSION_KEY, "") or "").strip()
    if not code:
        code = _new_captcha_code()
        _store_captcha(request, code)
    content, content_type = _captcha_audio(code)
    return _no_cache_audio_response(content, content_type)
