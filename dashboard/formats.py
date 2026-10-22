"""
One date format everywhere, in one time zone.

Dates and times are shown as "22 Oct 2026, 07:23:31" in settings.TIME_ZONE, which
the header names once. The scripts use the same format and zone (format.js reads the
zone from <body data-timezone>). Exports (CSV, JSON APIs) keep ISO 8601 in UTC.
"""
from django.conf import settings
from django.utils import dateformat, timezone

DATETIME_FORMAT = 'j M Y, H:i:s'
DATETIME_INPUT_FORMAT = 'j M Y, H:i'
# The same formats for datetime.strptime (Maintenance form); seconds are optional.
DATETIME_PARSE_FORMATS = ['%d %b %Y, %H:%M:%S', '%d %b %Y, %H:%M']


def format_datetime(value, fmt=DATETIME_FORMAT):
    if value is None:
        return ''
    if timezone.is_aware(value):
        value = timezone.localtime(value)
    return dateformat.format(value, fmt)


def timezone_label():
    """The display time zone and its current offset, e.g. 'Asia/Riyadh (UTC+3)'."""
    offset = timezone.localtime().utcoffset()
    minutes = int(offset.total_seconds() // 60)
    sign = '+' if minutes >= 0 else '−'
    hours, rest = divmod(abs(minutes), 60)
    return f"{settings.TIME_ZONE} (UTC{sign}{hours}{f':{rest:02d}' if rest else ''})"
