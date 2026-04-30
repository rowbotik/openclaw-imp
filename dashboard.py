#!/usr/bin/env python3
"""Small LAN dashboard for Imp Zero settings.

The dashboard intentionally edits only a fixed allowlist of non-secret .env
settings. Secrets stay in .env and are never rendered into the page.
"""

from __future__ import annotations

from html import escape
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import subprocess
import tempfile
from urllib.parse import parse_qs


APP_DIR = Path(__file__).resolve().parent
ENV_PATH = APP_DIR / ".env"
HOST = os.environ.get("IMP_DASHBOARD_HOST", "0.0.0.0")
PORT = int(os.environ.get("IMP_DASHBOARD_PORT", "8080"))
SERVICE_NAME = os.environ.get("IMP_SERVICE_NAME", "openclaw-imp.service")

OPENAI_VOICES = [
    "alloy", "ash", "ballad", "coral", "echo", "fable", "marin",
    "nova", "onyx", "sage", "shimmer", "verse", "cedar",
]
BODY_COLORS = ["yellow", "pink", "red", "blue", "green"]
IDLE_MOODS = [
    "happy", "idle", "excited", "proud", "curious", "sleepy", "love",
    "sad", "angry", "alert", "connected", "low_power", "error",
]
TTS_PROVIDERS = ["openai", "elevenlabs"]

TEXT_KEYS = {
    "TTS_PROVIDER",
    "OPENAI_TTS_MODEL",
    "OPENAI_TTS_VOICE",
    "OPENAI_TTS_INSTRUCTIONS",
    "ELEVENLABS_VOICE_ID",
    "ELEVENLABS_MODEL_ID",
    "ELEVENLABS_OUTPUT_FORMAT",
    "AUDIO_OUTPUT_DEVICE",
    "AUDIO_OUTPUT_CARD",
    "IMP_IDLE_MOOD",
    "IMP_BODY_COLOR",
}
NUMERIC_KEYS = {
    "OPENAI_TTS_SPEED": (0.25, 4.0),
    "OPENAI_TTS_GAIN_DB": (0.0, 18.0),
    "SPEAKER_VOLUME": (0, 100),
    "LCD_BACKLIGHT": (0, 100),
    "UI_MAX_FPS": (1, 12),
    "DISPLAY_SLEEP_TIMEOUT": (0, 3600),
}
BOOL_KEYS = {"ENABLE_TTS"}
ALLOWED_KEYS = TEXT_KEYS | set(NUMERIC_KEYS) | BOOL_KEYS

DEFAULTS = {
    "ENABLE_TTS": "true",
    "TTS_PROVIDER": "openai",
    "OPENAI_TTS_MODEL": "gpt-4o-mini-tts-2025-12-15",
    "OPENAI_TTS_VOICE": "fable",
    "OPENAI_TTS_SPEED": "1.0",
    "OPENAI_TTS_GAIN_DB": "9",
    "OPENAI_TTS_INSTRUCTIONS": (
        "Speak like a tiny helpful imp: warm, mischievous, compact, and "
        "expressive. Do not sound babyish. Keep it natural and quick."
    ),
    "ELEVENLABS_VOICE_ID": "",
    "ELEVENLABS_MODEL_ID": "eleven_flash_v2_5",
    "ELEVENLABS_OUTPUT_FORMAT": "pcm_24000",
    "AUDIO_OUTPUT_DEVICE": "plughw:1,0",
    "AUDIO_OUTPUT_CARD": "1",
    "SPEAKER_VOLUME": "100",
    "LCD_BACKLIGHT": "70",
    "UI_MAX_FPS": "3",
    "DISPLAY_SLEEP_TIMEOUT": "0",
    "IMP_IDLE_MOOD": "happy",
    "IMP_BODY_COLOR": "yellow",
}


def read_env() -> tuple[list[str], dict[str, str]]:
    if not ENV_PATH.exists():
        return [], DEFAULTS.copy()
    lines = ENV_PATH.read_text().splitlines()
    values = DEFAULTS.copy()
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return lines, values


def normalize_value(key: str, raw: str) -> str:
    value = (raw or "").strip()
    if key in BOOL_KEYS:
        return "true" if value.lower() in {"true", "1", "yes", "on"} else "false"
    if key in NUMERIC_KEYS:
        low, high = NUMERIC_KEYS[key]
        try:
            number = float(value)
        except ValueError:
            number = float(DEFAULTS[key])
        number = max(float(low), min(float(high), number))
        if number.is_integer():
            return str(int(number))
        return f"{number:.2f}".rstrip("0").rstrip(".")
    if key == "TTS_PROVIDER" and value not in TTS_PROVIDERS:
        return DEFAULTS[key]
    if key == "OPENAI_TTS_VOICE" and value not in OPENAI_VOICES:
        return DEFAULTS[key]
    if key == "IMP_BODY_COLOR" and value == "cream":
        return "pink"
    if key == "IMP_BODY_COLOR" and value not in BODY_COLORS:
        return DEFAULTS[key]
    if key == "IMP_IDLE_MOOD" and value not in IDLE_MOODS:
        return DEFAULTS[key]
    if "\n" in value or "\r" in value:
        value = " ".join(value.splitlines())
    return value


def write_env(updates: dict[str, str]) -> None:
    lines, current = read_env()
    merged = {key: current.get(key, DEFAULTS.get(key, "")) for key in ALLOWED_KEYS}
    for key, value in updates.items():
        if key in ALLOWED_KEYS:
            merged[key] = normalize_value(key, value)

    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        if "=" not in line or line.strip().startswith("#"):
            out.append(line)
            continue
        key = line.split("=", 1)[0].strip()
        if key in ALLOWED_KEYS:
            out.append(f"{key}={merged[key]}")
            seen.add(key)
        else:
            out.append(line)

    missing = [key for key in DEFAULTS if key in ALLOWED_KEYS and key not in seen]
    if missing:
        if out and out[-1].strip():
            out.append("")
        out.append("# Dashboard-managed tuning")
        for key in missing:
            out.append(f"{key}={merged.get(key, DEFAULTS[key])}")

    fd, tmp_name = tempfile.mkstemp(prefix=".env.", dir=str(APP_DIR), text=True)
    with os.fdopen(fd, "w") as tmp:
        tmp.write("\n".join(out).rstrip() + "\n")
    os.replace(tmp_name, ENV_PATH)


def run_cmd(args: list[str], timeout: int = 20) -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            args,
            cwd=APP_DIR,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except Exception as exc:
        return False, str(exc)
    output = (proc.stdout + proc.stderr).strip()
    return proc.returncode == 0, output


def restart_imp() -> tuple[bool, str]:
    return run_cmd(["sudo", "-n", "systemctl", "restart", SERVICE_NAME], timeout=30)


def service_status() -> str:
    ok, output = run_cmd(["systemctl", "is-active", SERVICE_NAME], timeout=5)
    return output if output else ("active" if ok else "unknown")


def apply_volume(values: dict[str, str]) -> None:
    card = normalize_value("AUDIO_OUTPUT_CARD", values.get("AUDIO_OUTPUT_CARD", "1"))
    volume = normalize_value("SPEAKER_VOLUME", values.get("SPEAKER_VOLUME", "100"))
    for control in ("Master", "PCM", "Headphone", "Speaker"):
        run_cmd(["amixer", "-q", "-c", card, "set", control, f"{volume}%"], timeout=5)


def test_tts(phrase: str) -> tuple[bool, str]:
    phrase = (phrase or "Imp voice check.").strip()[:240]
    code = (
        "from tts_openai import TTSPlayer; "
        "p=TTSPlayer(); "
        f"p.submit({phrase!r}); "
        "p.flush()"
    )
    return run_cmd(["python3", "-c", code], timeout=90)


def input_text(name: str, values: dict[str, str], label: str, typ: str = "text") -> str:
    return (
        f'<label><span>{escape(label)}</span>'
        f'<input type="{typ}" name="{name}" value="{escape(values.get(name, ""))}">'
        "</label>"
    )


def input_range(name: str, values: dict[str, str], label: str, low: str, high: str, step: str) -> str:
    value = escape(values.get(name, DEFAULTS.get(name, "")))
    return (
        f'<label><span>{escape(label)} <output>{value}</output></span>'
        f'<input type="range" name="{name}" min="{low}" max="{high}" step="{step}" '
        f'value="{value}" oninput="this.previousElementSibling.querySelector('
        f"'output').value=this.value\">"
        "</label>"
    )


def select_box(name: str, values: dict[str, str], label: str, options: list[str]) -> str:
    selected = values.get(name, DEFAULTS.get(name, ""))
    opts = []
    for opt in options:
        attr = " selected" if opt == selected else ""
        opts.append(f'<option value="{escape(opt)}"{attr}>{escape(opt)}</option>')
    return f'<label><span>{escape(label)}</span><select name="{name}">{"".join(opts)}</select></label>'


def textarea(name: str, values: dict[str, str], label: str) -> str:
    return (
        f'<label class="wide"><span>{escape(label)}</span>'
        f'<textarea name="{name}" rows="4">{escape(values.get(name, ""))}</textarea>'
        "</label>"
    )


def render_page(message: str = "") -> bytes:
    _, values = read_env()
    checked = " checked" if values.get("ENABLE_TTS", "true").lower() == "true" else ""
    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Imp Zero</title>
  <style>
    :root {{ color-scheme: dark; --bg:#050505; --panel:#151515; --line:#303030; --text:#f8f8f8; --muted:#aaa; --accent:#ffd31f; }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; background: var(--bg); color: var(--text); font: 15px/1.45 system-ui, -apple-system, BlinkMacSystemFont, sans-serif; }}
    main {{ width: min(960px, calc(100vw - 28px)); margin: 0 auto; padding: 22px 0 32px; }}
    header {{ display: flex; justify-content: space-between; gap: 16px; align-items: center; margin-bottom: 18px; }}
    h1 {{ font-size: 28px; margin: 0; color: var(--accent); }}
    h2 {{ font-size: 16px; margin: 0 0 12px; }}
    .status {{ color: var(--muted); text-align: right; }}
    .message {{ border: 1px solid #5b4a12; background: #201a08; color: #ffeaa1; padding: 10px 12px; border-radius: 8px; margin: 0 0 16px; }}
    form {{ display: grid; gap: 14px; }}
    section {{ border: 1px solid var(--line); background: var(--panel); border-radius: 8px; padding: 16px; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 12px; }}
    label {{ display: grid; gap: 6px; }}
    label span {{ color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .04em; }}
    input, select, textarea {{ width: 100%; border: 1px solid #3a3a3a; border-radius: 6px; background: #070707; color: var(--text); padding: 10px; font: inherit; }}
    input[type="range"] {{ padding: 0; accent-color: var(--accent); }}
    textarea {{ resize: vertical; }}
    .wide {{ grid-column: 1 / -1; }}
    .toggle {{ display: flex; align-items: center; gap: 8px; color: var(--muted); }}
    .toggle input {{ width: auto; }}
    .actions {{ display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }}
    button {{ border: 1px solid #5a4810; border-radius: 6px; background: var(--accent); color: #090909; padding: 10px 14px; font-weight: 700; cursor: pointer; }}
    button.secondary {{ background: #111; color: var(--text); border-color: #444; }}
    .sample {{ flex: 1 1 280px; }}
  </style>
</head>
<body>
<main>
  <header>
    <div><h1>Imp Zero</h1><div class="status">Dashboard on port {PORT}</div></div>
    <div class="status">Voice service: {escape(service_status())}</div>
  </header>
  {f'<div class="message">{escape(message)}</div>' if message else ''}
  <form method="post" action="/save">
    <section>
      <h2>Speech</h2>
      <div class="grid">
        <label class="toggle"><input type="checkbox" name="ENABLE_TTS"{checked}> Speak replies</label>
        {select_box("TTS_PROVIDER", values, "Provider", TTS_PROVIDERS)}
        {select_box("OPENAI_TTS_VOICE", values, "OpenAI voice", OPENAI_VOICES)}
        {input_text("OPENAI_TTS_MODEL", values, "OpenAI model")}
        {input_range("OPENAI_TTS_SPEED", values, "Speed", "0.25", "4", "0.05")}
        {input_range("OPENAI_TTS_GAIN_DB", values, "Gain dB", "0", "18", "1")}
        {input_text("ELEVENLABS_VOICE_ID", values, "ElevenLabs voice ID")}
        {input_text("ELEVENLABS_MODEL_ID", values, "ElevenLabs model")}
        {input_text("ELEVENLABS_OUTPUT_FORMAT", values, "ElevenLabs output")}
        {textarea("OPENAI_TTS_INSTRUCTIONS", values, "Voice instructions")}
      </div>
    </section>
    <section>
      <h2>Audio</h2>
      <div class="grid">
        {input_text("AUDIO_OUTPUT_DEVICE", values, "Output device")}
        {input_text("AUDIO_OUTPUT_CARD", values, "Output card", "number")}
        {input_range("SPEAKER_VOLUME", values, "Speaker volume", "0", "100", "1")}
      </div>
    </section>
    <section>
      <h2>Display</h2>
      <div class="grid">
        {input_range("LCD_BACKLIGHT", values, "Backlight", "0", "100", "1")}
        {input_range("UI_MAX_FPS", values, "Animation FPS", "1", "12", "1")}
        {input_text("DISPLAY_SLEEP_TIMEOUT", values, "Sleep timeout seconds", "number")}
        {select_box("IMP_IDLE_MOOD", values, "Idle mood", IDLE_MOODS)}
        {select_box("IMP_BODY_COLOR", values, "Body color", BODY_COLORS)}
      </div>
    </section>
    <section class="actions">
      <button type="submit">Save & Restart Imp</button>
      <button class="secondary" type="submit" formaction="/restart">Restart Only</button>
      <input class="sample" name="TEST_PHRASE" value="Imp voice check. Fable mode.">
      <button class="secondary" type="submit" formaction="/test-tts">Test Speak</button>
    </section>
  </form>
</main>
</body>
</html>"""
    return html.encode()


class Handler(BaseHTTPRequestHandler):
    def _send(self, body: bytes, status: HTTPStatus = HTTPStatus.OK) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path not in {"/", "/index.html"}:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self._send(render_page())

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        form = parse_qs(self.rfile.read(length).decode(), keep_blank_values=True)
        values = {key: form.get(key, [""])[0] for key in ALLOWED_KEYS}
        if "ENABLE_TTS" not in form:
            values["ENABLE_TTS"] = "false"

        if self.path == "/save":
            write_env(values)
            _, current = read_env()
            apply_volume(current)
            ok, output = restart_imp()
            msg = "Saved settings and restarted Imp." if ok else f"Saved settings, restart failed: {output}"
            self._send(render_page(msg))
            return

        if self.path == "/restart":
            ok, output = restart_imp()
            msg = "Restarted Imp." if ok else f"Restart failed: {output}"
            self._send(render_page(msg))
            return

        if self.path == "/test-tts":
            ok, output = test_tts(form.get("TEST_PHRASE", ["Imp voice check."])[0])
            msg = "Test phrase sent to speaker." if ok else f"Test speak failed: {output}"
            self._send(render_page(msg))
            return

        self.send_error(HTTPStatus.NOT_FOUND)

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"[dashboard] {self.address_string()} {fmt % args}")


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Imp dashboard listening on http://{HOST}:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
