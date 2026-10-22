"""
Static URLs with a content version, so a browser never runs stale JavaScript or CSS.

    {% load versioned_static %}
    {% vstatic 'dashboard/css/app.css' %}  ->  /static/dashboard/css/app.css?v=<hash>
    {% js_importmap %}                      ->  <script type="importmap"> for the JS modules

The version is the first 12 hex digits of the SHA-256 of the file content. It is
recomputed whenever the file's modification time changes, so editing a file
changes its URL even while the server keeps running. The JavaScript modules
import each other through bare specifiers ("ms/overview.js") that the import map
resolves to versioned URLs; a version on the entry script alone would not
reach the modules it imports.
"""
import hashlib
import json
import os

from django import template
from django.contrib.staticfiles import finders
from django.templatetags.static import static
from django.utils.html import format_html
from django.utils.safestring import mark_safe

register = template.Library()

# bare module specifier -> static path
JS_MODULES = {
    'ms/format.js': 'dashboard/js/format.js',
    'ms/charts.js': 'dashboard/js/charts.js',
    'ms/overview.js': 'dashboard/js/overview.js',
    'ms/live.js': 'dashboard/js/live.js',
    'ms/replay.js': 'dashboard/js/replay.js',
}

_cache = {}  # absolute path -> (mtime_ns, size, version)


def file_version(path):
    """Content version of a static file (12 hex digits), or 'missing'."""
    absolute = finders.find(path)
    if not absolute:
        return 'missing'
    stat = os.stat(absolute)
    key = (stat.st_mtime_ns, stat.st_size)
    cached = _cache.get(absolute)
    if cached and cached[:2] == key:
        return cached[2]
    with open(absolute, 'rb') as f:
        version = hashlib.sha256(f.read()).hexdigest()[:12]
    _cache[absolute] = (*key, version)
    return version


def versioned_url(path):
    return f'{static(path)}?v={file_version(path)}'


@register.simple_tag
def vstatic(path):
    return versioned_url(path)


@register.simple_tag
def js_importmap():
    imports = {spec: versioned_url(path) for spec, path in JS_MODULES.items()}
    return format_html('<script type="importmap">{}</script>', mark_safe(json.dumps({'imports': imports})))
