"""{{ value|msdatetime }} and {% display_timezone %}: see dashboard/formats.py."""
from django import template
from django.conf import settings

from dashboard import formats

register = template.Library()


@register.filter
def msdatetime(value):
    return formats.format_datetime(value)


@register.simple_tag
def display_timezone():
    return formats.timezone_label()


@register.simple_tag
def timezone_name():
    return settings.TIME_ZONE
