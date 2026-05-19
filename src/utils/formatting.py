"""Text formatting helpers for Telegram MarkdownV2."""

from __future__ import annotations

import re


# Characters that must be escaped in MarkdownV2
_MD2_ESCAPE_RE = re.compile(r"([_*\[\]()~`>#+\-=|{}.!\\])")


def escape_md(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2 parse mode."""
    return _MD2_ESCAPE_RE.sub(r"\\\1", text)
