"""Convert assistant Markdown into speech-friendly chunks."""

from __future__ import annotations

import re


_SENTENCE_END_RE = re.compile(r"[.!?]\s|\n\n")
_TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$")


def _looks_like_table_row(line: str) -> bool:
    stripped = line.strip()
    return stripped.count("|") >= 2 and not stripped.startswith("http")


def _strip_markdown(text: str) -> str:
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"^[ \t]*#{1,6}\s*", "", text, flags=re.M)
    text = re.sub(r"^[ \t]*[-*+]\s+", "", text, flags=re.M)
    text = re.sub(r"^[ \t]*\d+[.)]\s+", "", text, flags=re.M)
    text = re.sub(r"[*_~]{1,3}", "", text)
    text = re.sub(r"https?://\S+", " link ", text)
    text = text.replace("|", ", ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def speechify_markdown(text: str, *, table_notice: bool = True) -> tuple[str, bool]:
    """Return speech-friendly text and whether a table was removed.

    Tables are useful on the LCD, but raw Markdown pipes and separator rows sound
    terrible when spoken. This keeps nearby prose and replaces table blocks with a
    short notice at most once per caller.
    """
    lines = text.splitlines()
    out: list[str] = []
    removed_table = False
    in_table = False

    for i, line in enumerate(lines):
        prev_line = lines[i - 1] if i > 0 else ""
        next_line = lines[i + 1] if i + 1 < len(lines) else ""
        is_separator = bool(_TABLE_SEPARATOR_RE.match(line))
        is_table_row = _looks_like_table_row(line)
        table_context = (
            is_separator
            or (is_table_row and _TABLE_SEPARATOR_RE.match(next_line or ""))
            or (is_table_row and _TABLE_SEPARATOR_RE.match(prev_line or ""))
            or (in_table and is_table_row)
        )

        if table_context:
            removed_table = True
            in_table = True
            continue

        if in_table and not line.strip():
            in_table = False
            continue
        in_table = False
        out.append(line)

    spoken = _strip_markdown("\n".join(out))
    if removed_table and table_notice:
        notice = "I put a table on the screen."
        spoken = f"{spoken} {notice}".strip() if spoken else notice
    return spoken, removed_table


class SpeechChunker:
    """Incrementally batch streamed Markdown into safe TTS chunks."""

    def __init__(self):
        self._buffer = ""
        self._table_notice_used = False

    def append(self, text: str) -> list[str]:
        self._buffer += text
        ready: list[str] = []

        while True:
            split_at = self._next_split()
            if split_at is None:
                break
            raw = self._buffer[:split_at].strip()
            self._buffer = self._buffer[split_at:]
            spoken = self._speechify(raw)
            if spoken:
                ready.append(spoken)

        return ready

    def flush(self) -> list[str]:
        raw = self._buffer.strip()
        self._buffer = ""
        spoken = self._speechify(raw)
        return [spoken] if spoken else []

    def _speechify(self, raw: str) -> str:
        if not raw:
            return ""
        spoken, removed_table = speechify_markdown(
            raw,
            table_notice=not self._table_notice_used,
        )
        if removed_table:
            self._table_notice_used = True
        return spoken

    def _next_split(self) -> int | None:
        if not self._buffer.strip():
            return None

        # Markdown tables are block-level; wait for the blank line after the table
        # before deciding what should be spoken.
        if self._contains_open_table():
            blank = self._buffer.find("\n\n")
            return blank + 2 if blank >= 0 else None

        table_split = self._closed_table_split()
        if table_split is not None:
            return table_split

        matches = list(_SENTENCE_END_RE.finditer(self._buffer))
        if len(matches) >= 2:
            return matches[1].end()

        # For long prose without punctuation, avoid holding speech forever.
        if len(self._buffer) > 380:
            last_space = self._buffer.rfind(" ", 0, 320)
            return last_space if last_space > 120 else 320
        return None

    def _contains_open_table(self) -> bool:
        lines = self._buffer.splitlines()
        for i, line in enumerate(lines):
            if not _looks_like_table_row(line):
                continue
            next_line = lines[i + 1] if i + 1 < len(lines) else ""
            if _TABLE_SEPARATOR_RE.match(next_line):
                return "\n\n" not in "\n".join(lines[i:])
        return False

    def _closed_table_split(self) -> int | None:
        lines = self._buffer.splitlines(keepends=True)
        for i, line in enumerate(lines):
            if not _looks_like_table_row(line):
                continue
            next_line = lines[i + 1] if i + 1 < len(lines) else ""
            if not _TABLE_SEPARATOR_RE.match(next_line):
                continue
            char_pos = sum(len(part) for part in lines[:i])
            blank = self._buffer.find("\n\n", char_pos)
            if blank >= 0:
                return blank + 2
        return None
