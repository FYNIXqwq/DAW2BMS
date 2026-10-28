"""Localize presentation while keeping backend messages and JSON stable.

Message is a str with an English canonical value plus an untranslated template
and typed parameters. Progress routing never depends on the displayed language.
"""
from __future__ import annotations

import argparse
import builtins
from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache
from importlib.resources import files
import json
import locale
import os
import threading
import sys

LANGUAGES = {"zh-TW": "繁體中文", "en": "English", "ja": "日本語", "ko": "한국어"}
_language = ContextVar("daw2bms_language", default="en")
_argparse_lock = threading.RLock()


def normalize_language(value: str | None) -> str:
    name = (value or "").replace("_", "-").split(".")[0].lower()
    if name.startswith("zh") or "chinese" in name:
        return "zh-TW"
    if name.startswith("ja") or "japanese" in name:
        return "ja"
    if name.startswith("ko") or "korean" in name:
        return "ko"
    return "en"


def system_language() -> str:
    if sys.platform == "win32":
        try:
            import ctypes
            get_language = ctypes.windll.kernel32.GetUserDefaultUILanguage
            get_language.restype = ctypes.c_ushort
            get_language.argtypes = []
            language_id = get_language()
            return normalize_language(locale.windows_locale.get(language_id, "en"))
        except (AttributeError, OSError):
            pass
    try:
        category = getattr(locale, "LC_MESSAGES", locale.LC_CTYPE)
        return normalize_language(locale.getlocale(category)[0])
    except (ValueError, TypeError):
        return "en"


def resolve_language(explicit=None, saved=None) -> str:
    return normalize_language(explicit or os.environ.get("DAW2BMS_LANG") or saved or system_language())


@lru_cache(maxsize=4)
def catalog(language: str) -> dict[str, str]:
    return json.loads(files("daw2bms.locales").joinpath(f"{normalize_language(language)}.json").read_text(encoding="utf-8"))


class Message(str):
    def __new__(cls, source: str, **params):
        instance = super().__new__(cls, source.format(**params) if params else source)
        instance.source = source
        instance.params = params
        return instance


class JoinedMessages(str):
    def __new__(cls, messages, separator=", "):
        values = tuple(messages)
        instance = super().__new__(cls, separator.join(map(str, values)))
        instance.messages, instance.separator = values, separator
        return instance


def msg(source: str, **params) -> Message:
    return Message(source, **params)


def render(value, language=None) -> str:
    language = normalize_language(language or _language.get())
    if isinstance(value, JoinedMessages):
        return value.separator.join(render(item, language) if isinstance(item, (Message, JoinedMessages, Exception)) else str(item)
                                    for item in value.messages)
    if isinstance(value, Exception):
        return render(value.args[0], language) if len(value.args) == 1 else str(value)
    if isinstance(value, Message):
        template = catalog(language).get(value.source, catalog("en").get(value.source, value.source))
        params = {key: render(item, language) if isinstance(item, (Message, JoinedMessages, Exception)) else item
                  for key, item in value.params.items()}
        try:
            return template.format(**params) if params else template
        except (KeyError, ValueError, IndexError):
            return str(value)
    # Plain strings are raw data/logs from outside the message system.
    return str(value)


def tr(source: str, language=None, **params) -> str:
    return render(msg(source, **params), language)


@contextmanager
def language_context(language):
    token = _language.set(normalize_language(language))
    try:
        yield
    finally:
        _language.reset(token)


def localized_print(*values, **kwargs):
    builtins.print(*(render(value) for value in values), **kwargs)


def configure_console():
    # Redirected Windows streams may otherwise use a legacy code page incapable
    # of encoding all four languages. Test/caller StringIO streams stay intact.
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="backslashreplace")
            except (ValueError, OSError):
                pass


def split_language_args(argv):
    """Accept --lang before/after the subcommand, respecting the -- boundary."""
    cleaned, explicit, index = [], None, 0
    while index < len(argv):
        value = argv[index]
        if value == "--":
            cleaned.extend(argv[index:])
            break
        if value == "--lang" or value.startswith("--lang="):
            if value == "--lang":
                index += 1
                if index == len(argv):
                    raise ValueError(msg("--lang requires one of: zh-TW, en, ja, ko"))
                explicit = argv[index]
            else:
                explicit = value.split("=", 1)[1]
            if explicit not in LANGUAGES:
                raise ValueError(msg("Unsupported language: {p0}. Choose zh-TW, en, ja or ko.", p0=explicit))
        else:
            cleaned.append(value)
        index += 1
    return resolve_language(explicit), cleaned, explicit


@contextmanager
def argparse_translations():
    """Scope argparse's gettext hook to parser construction and parsing only."""
    with _argparse_lock:
        original = argparse._
        original_plural = argparse.ngettext
        argparse._ = lambda source: catalog(_language.get()).get(source, catalog("en").get(source, source))
        argparse.ngettext = lambda single, plural, n: argparse._(single if n == 1 else plural)
        try:
            yield
        finally:
            argparse._, argparse.ngettext = original, original_plural
