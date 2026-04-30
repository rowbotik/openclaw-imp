#!/bin/bash
set -euo pipefail

echo "== Imp Zero hardware =="
hostname
uname -a

echo
echo "== Audio cards =="
aplay -l || true
arecord -l || true

echo
echo "== WhisPlay driver =="
if [ -d /home/pi/Whisplay/Driver ]; then
  echo "WhisPlay driver directory present: /home/pi/Whisplay/Driver"
else
  echo "Missing /home/pi/Whisplay/Driver"
fi

echo
echo "== Python imports =="
python3 - <<'PY'
import importlib

for name in ("PIL", "requests", "dotenv", "numpy"):
    try:
        importlib.import_module(name)
        print(f"{name}: ok")
    except Exception as exc:
        print(f"{name}: missing ({exc})")
PY

echo
echo "== Environment =="
if [ -f .env ]; then
  python3 - <<'PY'
try:
    from dotenv import dotenv_values
except Exception as exc:
    print(f"Cannot read .env with python-dotenv yet: {exc}")
    raise SystemExit(0)

cfg = dotenv_values(".env")
for key in (
    "OPENAI_API_KEY",
    "OPENCLAW_TOKEN",
    "OPENCLAW_BASE_URL",
    "ENABLE_TTS",
    "TTS_PROVIDER",
    "ELEVENLABS_API_KEY",
    "ELEVENLABS_VOICE_ID",
    "AUDIO_DEVICE",
    "AUDIO_OUTPUT_DEVICE",
):
    value = cfg.get(key)
    if key.endswith("KEY") or key.endswith("TOKEN") or key.endswith("VOICE_ID"):
        shown = "set" if value else "missing"
    else:
        shown = value if value else "missing"
    print(f"{key}: {shown}")
PY
else
  echo "Missing .env; copy .env.example to .env and fill in secrets."
fi

echo
echo "Run python3 main.py after these checks look right."
