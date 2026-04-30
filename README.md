# openclaw-imp

Imp Zero is a voice terminal for a remote [OpenClaw](https://openclaw.ai) gateway, built on a Raspberry Pi Zero W/2 W with a [PiSugar WhisPlay board](https://www.pisugar.com). Press the button, speak, and the little Gigapet-style Imp on the LCD speaks between you and Daemon.

## How it works

```
Button press -> Record audio -> Transcribe (OpenAI) -> Stream LLM response (OpenClaw) -> Display on LCD
                                                                                     -> Speak aloud (OpenAI or ElevenLabs TTS)
```

1. **Press & hold** the button to record your voice via ALSA
2. **Release** — the WAV is sent to OpenAI for transcription (~0.7s)
3. The transcript (with conversation history) is streamed to an **OpenClaw gateway** for a response
4. Text streams onto the **LCD** in real time with pixel-accurate word wrapping
5. Optionally **speaks the response** via OpenAI or ElevenLabs TTS as sentences complete
6. The idle screen shows a **clock, date, battery %, and WiFi status**

The device maintains **conversation memory** across exchanges and includes a **silence gate** to skip empty recordings.

The display character is intentionally low-frame-rate pixel art, closer to a Gigapet than a smooth avatar. See `assets/imp-reference.svg` for the editable visual reference; runtime drawing is generated with PIL so the Pi does not need SVG rendering support.

To export inspectable PNG sprites from the runtime drawing code:

```bash
python3 render_imp_sprites.py
```

## Hardware

- **Raspberry Pi Zero 2 W** (or Pi Zero W)
- **[PiSugar WhisPlay board](https://www.pisugar.com)** — LCD, push-to-talk button, LED, speaker, microphone
- **PiSugar battery** (optional) — shows charge level on screen

## Setup

### Prerequisites

- Raspberry Pi OS with Desktop (Bookworm or later). Do not start with Lite for WhisPlay bring-up.
- Python 3.11+
- An [OpenAI API key](https://platform.openai.com/api-keys) for speech-to-text
- An optional ElevenLabs API key and voice ID if using ElevenLabs TTS
- A remote [OpenClaw](https://openclaw.ai) gateway reachable through Tailscale Serve

Recommended Raspberry Pi Imager settings:

```text
hostname: imp-zero
username: pi
password: apple
```

### Install dependencies

```bash
sudo apt install -y alsa-utils sox python3-numpy python3-pil
pip install requests python-dotenv   # or: pip install -r requirements.txt
```

Install the WhisPlay hardware driver at `/home/pi/Whisplay/Driver/`:

```bash
git clone https://github.com/PiSugar/Whisplay.git --depth 1 ~/Whisplay
cd ~/Whisplay/Driver
sudo bash install_wm8960_drive.sh
sudo reboot
```

After reboot, validate hardware first:

```bash
aplay -l
arecord -l
cd ~/Whisplay/example
sudo bash run_test.sh
sudo bash mic_test.sh
```

From the app directory, run the bundled summary check:

```bash
./imp-zero-check.sh
```

### Configure

Copy the example env file and fill in your keys:

```bash
cp .env.example .env
```

Edit `.env`:

```bash
OPENAI_API_KEY=sk-your-openai-api-key
OPENCLAW_TOKEN=your-openclaw-gateway-token
OPENCLAW_BASE_URL=https://gateway-host.tailnet-name.ts.net
ENABLE_TTS=true
AUDIO_DEVICE=plughw:1,0
AUDIO_OUTPUT_DEVICE=plughw:1,0
```

Use plain `KEY=value` lines in `.env`; the systemd service reads this file directly.

### Run

```bash
python3 main.py
```

Or deploy as a systemd service (see below).

## Configuration

All settings are configured via environment variables (loaded from `.env`):

| Variable | Default | Description |
|---|---|---|
| `OPENAI_API_KEY` | _(required)_ | OpenAI API key for transcription and OpenAI TTS |
| `OPENCLAW_TOKEN` | _(required)_ | Auth token for the OpenClaw gateway |
| `OPENCLAW_BASE_URL` | `http://localhost:18789` | Remote OpenClaw gateway URL; for Tailscale Serve use the HTTPS serve URL |
| `OPENAI_TRANSCRIBE_MODEL` | `gpt-4o-mini-transcribe` | Speech-to-text model |
| `ENABLE_TTS` | `true` | Speak responses aloud |
| `TTS_PROVIDER` | `openai` | `openai` or `elevenlabs` |
| `OPENAI_TTS_MODEL` | `gpt-4o-mini-tts-2025-12-15` | OpenAI TTS model |
| `OPENAI_TTS_VOICE` | `coral` | OpenAI TTS voice |
| `OPENAI_TTS_SPEED` | `1.1` | OpenAI TTS speed (0.25-4.0) |
| `OPENAI_TTS_GAIN_DB` | `9` | Software volume boost in dB |
| `ELEVENLABS_API_KEY` | _(optional)_ | Required when `TTS_PROVIDER=elevenlabs` |
| `ELEVENLABS_VOICE_ID` | _(optional)_ | Required when `TTS_PROVIDER=elevenlabs` |
| `ELEVENLABS_MODEL_ID` | `eleven_flash_v2_5` | ElevenLabs TTS model |
| `ELEVENLABS_OUTPUT_FORMAT` | `pcm_24000` | ElevenLabs output; PCM is wrapped into WAV for local playback |
| `AUDIO_DEVICE` | `plughw:1,0` | ALSA input device |
| `AUDIO_OUTPUT_DEVICE` | `plughw:1,0` | ALSA output device |
| `AUDIO_SAMPLE_RATE` | `16000` | Recording sample rate |
| `LCD_BACKLIGHT` | `70` | Backlight brightness (0–100) |
| `UI_MAX_FPS` | `3` | Max display refresh rate; intentionally low for chunky Gigapet-style animation |
| `DISPLAY_SLEEP_TIMEOUT` | `0` | Seconds before blanking the display while idle; `0` keeps the Imp visible |
| `CONVERSATION_HISTORY_LENGTH` | `5` | Past exchanges to keep for context |
| `SILENCE_RMS_THRESHOLD` | `200` | Audio RMS below this is skipped |

### ElevenLabs TTS

Keep OpenAI for transcription, then set these values for ElevenLabs speech:

```text
TTS_PROVIDER=elevenlabs
ELEVENLABS_API_KEY=your-elevenlabs-api-key
ELEVENLABS_VOICE_ID=your-elevenlabs-voice-id
```

## Deploy with systemd

The included `sync.sh` script deploys to Imp Zero and sets up the service:

```bash
./sync.sh
```

This rsyncs the project to `pi@imp-zero.local:/home/pi/openclaw-imp/`, installs the systemd unit, and restarts the service. It intentionally does not sync `.env`; keep the real keys on the Pi. Logs are available via:

```bash
# On the Pi:
sudo journalctl -u openclaw-imp -f

# Or check the debug log:
cat /tmp/openclaw.log
```

For first bring-up, keep the service stopped until `.env` has real values:

```bash
sudo systemctl disable --now openclaw-imp
nano /home/pi/openclaw-imp/.env
sudo systemctl enable --now openclaw-imp
sudo journalctl -u openclaw-imp -f
```

## Project structure

```
main.py               — Entry point and orchestrator
display.py            — LCD rendering (status, responses, idle clock, spinner)
openclaw_client.py    — Streaming HTTP client for the remote OpenClaw gateway
transcribe_openai.py  — Speech-to-text via OpenAI API
tts_openai.py         — Text-to-speech via OpenAI or ElevenLabs + ALSA playback
record_audio.py       — Audio recording via ALSA arecord
button_ptt.py         — Push-to-talk button state machine
config.py             — Centralized configuration from .env
sync.sh               — Deploy script (rsync + systemd restart)
imp-zero-check.sh     — Pi-side hardware/config validation summary
render_imp_sprites.py — Exports generated Imp state sprites as PNGs
assets/imp-moodboard.png — Mood board reference for expression/state design
assets/imp-reference.svg — Editable reference for the Gigapet-style Imp
```

## License

MIT
