import logging
import re

logger = logging.getLogger(__name__)

STOP_WORDS = {
    "어떻게", "하려면", "무엇", "뭐", "무엇을", "방법", "어떤", "어디", "언제", "왜",
    "인가요", "인가", "되나요", "되려면", "할까요", "해주세요", "알려주세요", "좀", "수", "있나요",
    "있을까요", "있습니까", "하나요", "해요", "합니다", "하다", "하", "것", "수도", "그리고",
    "the", "what", "how", "where", "when", "can", "do", "does", "is", "are", "to", "a", "an",
}
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_.+-]*|[0-9]+|[\uac00-\ud7a3]+|[^\W_]+", re.UNICODE)
_KIWI = None
_KIWI_TRIED = False
_FALLBACK_LOGGED = False


def _get_kiwi():
    global _KIWI, _KIWI_TRIED, _FALLBACK_LOGGED
    if _KIWI_TRIED:
        return _KIWI
    _KIWI_TRIED = True
    try:
        from kiwipiepy import Kiwi

        _KIWI = Kiwi()
        logger.info("Handbook search tokenizer: kiwipiepy morphology enabled.")
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        if not _FALLBACK_LOGGED:
            logger.warning(
                "kiwipiepy is unavailable; handbook search uses the built-in Korean 2-gram tokenizer (%s).",
                type(exc).__name__,
            )
            _FALLBACK_LOGGED = True
    return _KIWI


def _normalise_token(token):
    return str(token or "").strip().lower()


def _fallback_tokens(text):
    tokens = []
    for word in _WORD_RE.findall(str(text or "").lower()):
        if word in STOP_WORDS:
            continue
        if re.fullmatch(r"[\uac00-\ud7a3]+", word):
            tokens.extend(word[index : index + 2] for index in range(len(word) - 1))
        else:
            tokens.append(word)
    return [token for token in tokens if token and token not in STOP_WORDS]


def tokenize(text):
    """Use Kiwi morphemes when installed; otherwise use pure-Python Hangul 2-grams."""
    kiwi = _get_kiwi()
    if kiwi is None:
        return _fallback_tokens(text)

    tokens = []
    accepted = ("NN", "VV", "VA", "XR", "SL", "SH", "SN", "MAG", "MM")
    for token in kiwi.tokenize(str(text or "")):
        if token.tag.startswith(accepted):
            form = _normalise_token(token.form)
            if form and form not in STOP_WORDS:
                tokens.append(form)
    # Kiwi can split code-like and foreign strings into punctuation tokens; retain these intact.
    tokens.extend(
        word.lower()
        for word in re.findall(r"[A-Za-z][A-Za-z0-9_.+-]*|[0-9]+", str(text or ""))
        if word.lower() not in STOP_WORDS
    )
    return tokens
