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

    def __init__(self, third_person: bool = False):
        self._buffer = ""
        self._table_notice_used = False
        self._third_person = third_person

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
        if self._third_person:
            spoken = daemon_says(spoken)
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


def daemon_says(text: str) -> str:
    """Wrap a spoken chunk so Imp talks about Daemon in third person."""
    text = re.sub(r"\s+", " ", (text or "").strip())
    if not text:
        return ""
    if re.match(r"(?i)^daemon\s+(says|said|thinks|will|can|has|is)\b", text):
        return text

    rewritten = _rewrite_first_person(text)
    first_word = rewritten.split(" ", 1)[0].lower().strip(".,:;!?")
    if first_word in {"he", "he'll", "he'd", "he's", "his", "him", "that"}:
        return f"Daemon says {rewritten[0].lower()}{rewritten[1:]}"
    return f"Daemon says: {rewritten}"


def _rewrite_first_person(text: str) -> str:
    replacements = [
        (r"(?i)^i['’]ll\b", "he'll"),
        (r"(?i)^i will\b", "he will"),
        (r"(?i)^i can\b", "he can"),
        (r"(?i)^i am\b", "he is"),
        (r"(?i)^i['’]m\b", "he is"),
        (r"(?i)^i have\b", "he has"),
        (r"(?i)^i['’]ve\b", "he has"),
        (r"(?i)^i need\b", "he needs"),
        (r"(?i)^i think\b", "he thinks"),
        (r"(?i)^i recommend\b", "he recommends"),
        (r"(?i)^i suggest\b", "he suggests"),
        (r"(?i)^i see\b", "he sees"),
        (r"(?i)^i\b", "he"),
        (r"(?i)\bmy\b", "his"),
        (r"(?i)\bmine\b", "his"),
        (r"(?i)\bme\b", "him"),
    ]
    out = text
    for pattern, repl in replacements:
        out = re.sub(pattern, repl, out)
    return out
