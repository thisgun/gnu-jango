"""The deposit deadline of an issued virtual account (ShopOrder.od_vbank_due_date).

Toss stores its dueDate (ISO, Korean time). NICEPAY rows store the same ISO form since #188;
older NICEPAY rows hold VbankExpDate + VbankExpTime as YYYYMMDDhhmmss. A date without a time
is open until the end of that day."""

from datetime import datetime, time
from zoneinfo import ZoneInfo

from django.utils.dateparse import parse_date, parse_datetime

KOREA_TIME = ZoneInfo("Asia/Seoul")


def parse_vbank_due_date(value):
    """The deadline as an aware datetime, or None when the stored text is not a date."""
    text = str(value or "").strip()
    try:
        if text.isdigit():
            parsed = datetime.strptime(text, {8: "%Y%m%d", 14: "%Y%m%d%H%M%S"}[len(text)])
            if len(text) == 8:
                parsed = datetime.combine(parsed.date(), time.max)
        else:
            day = parse_date(text) if len(text) == 10 else None
            parsed = datetime.combine(day, time.max) if day else parse_datetime(text)
    except (KeyError, ValueError):
        return None
    if parsed is None:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=KOREA_TIME)


def vbank_due_date_display(value):
    """The deadline as the order page and the mail print it ("2026-11-21 23:59", Korean time); the
    stored text when it is not a date."""
    due = parse_vbank_due_date(value)
    if due is None:
        return str(value or "").strip()
    return due.astimezone(KOREA_TIME).strftime("%Y-%m-%d %H:%M")
