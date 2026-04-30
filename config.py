import os
from dotenv import load_dotenv

load_dotenv()


OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_TRANSCRIBE_MODEL = os.environ.get(
    "OPENAI_TRANSCRIBE_MODEL", "gpt-4o-mini-transcribe"
)
OPENAI_TTS_MODEL = os.environ.get("OPENAI_TTS_MODEL", "gpt-4o-mini-tts-2025-12-15")
OPENAI_TTS_VOICE = os.environ.get("OPENAI_TTS_VOICE", "coral")
OPENAI_TTS_SPEED = float(os.environ.get("OPENAI_TTS_SPEED", "1.1"))  # 0.25–4.0
OPENAI_TTS_GAIN_DB = float(os.environ.get("OPENAI_TTS_GAIN_DB", "9"))  # extra dB boost (e.g. 9 ≈ 2.8× louder)
OPENAI_TTS_INSTRUCTIONS = os.environ.get(
    "OPENAI_TTS_INSTRUCTIONS",
    "Speak in a warm, sweet, and playful tone with a gentle high pitch. "
    "Sound like an adorable, tiny friend who is genuinely excited to help. "
    "Use natural breathing and smooth pacing — never robotic or monotone. "
    "Let sentences flow into each other without awkward pauses.",
)
TTS_PROVIDER = os.environ.get("TTS_PROVIDER", "openai").lower()
ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID = os.environ.get("ELEVENLABS_VOICE_ID", "")
ELEVENLABS_MODEL_ID = os.environ.get("ELEVENLABS_MODEL_ID", "eleven_flash_v2_5")
ELEVENLABS_OUTPUT_FORMAT = os.environ.get("ELEVENLABS_OUTPUT_FORMAT", "pcm_24000")
ELEVENLABS_OPTIMIZE_STREAMING_LATENCY = os.environ.get(
    "ELEVENLABS_OPTIMIZE_STREAMING_LATENCY", "3"
)
ELEVENLABS_STABILITY = os.environ.get("ELEVENLABS_STABILITY", "")
ELEVENLABS_SIMILARITY_BOOST = os.environ.get("ELEVENLABS_SIMILARITY_BOOST", "")

OPENCLAW_BASE_URL = os.environ.get("OPENCLAW_BASE_URL", "http://localhost:18789")
OPENCLAW_TOKEN = os.environ.get("OPENCLAW_TOKEN", "")

AUDIO_DEVICE = os.environ.get("AUDIO_DEVICE", "plughw:1,0")
AUDIO_OUTPUT_DEVICE = os.environ.get("AUDIO_OUTPUT_DEVICE", "plughw:1,0")
AUDIO_OUTPUT_CARD = int(os.environ.get("AUDIO_OUTPUT_CARD", "1"))  # ALSA card for amixer
AUDIO_SAMPLE_RATE = int(os.environ.get("AUDIO_SAMPLE_RATE", "16000"))

DRY_RUN = not OPENAI_API_KEY

LCD_BACKLIGHT = int(os.environ.get("LCD_BACKLIGHT", "70"))
UI_MAX_FPS = int(os.environ.get("UI_MAX_FPS", "4"))

# Speak the assistant response through the selected TTS provider.
ENABLE_TTS = os.environ.get("ENABLE_TTS", "true").lower() in ("true", "1", "yes")

# Number of past exchanges (user+assistant pairs) to keep for conversation context
CONVERSATION_HISTORY_LENGTH = int(os.environ.get("CONVERSATION_HISTORY_LENGTH", "5"))

# RMS energy threshold below which audio is considered silence (16-bit range: 0–32768)
SILENCE_RMS_THRESHOLD = float(os.environ.get("SILENCE_RMS_THRESHOLD", "200"))


def print_config():
    """Print non-secret config for debugging."""
    print(f"OPENAI_TRANSCRIBE_MODEL = {OPENAI_TRANSCRIBE_MODEL}")
    print(f"OPENAI_TTS_MODEL        = {OPENAI_TTS_MODEL}")
    print(f"OPENAI_TTS_VOICE        = {OPENAI_TTS_VOICE}")
    print(f"OPENAI_TTS_SPEED        = {OPENAI_TTS_SPEED}")
    print(f"OPENAI_TTS_GAIN_DB      = {OPENAI_TTS_GAIN_DB}")
    print(f"OPENAI_TTS_INSTRUCTIONS = {OPENAI_TTS_INSTRUCTIONS[:60]}...")
    print(f"TTS_PROVIDER            = {TTS_PROVIDER}")
    print(f"ELEVENLABS_MODEL_ID     = {ELEVENLABS_MODEL_ID}")
    print(f"ELEVENLABS_OUTPUT_FMT   = {ELEVENLABS_OUTPUT_FORMAT}")
    print(f"ELEVENLABS_API_KEY set  = {bool(ELEVENLABS_API_KEY)}")
    print(f"ELEVENLABS_VOICE_ID set = {bool(ELEVENLABS_VOICE_ID)}")
    print(f"OPENCLAW_BASE_URL       = {OPENCLAW_BASE_URL}")
    print(f"AUDIO_DEVICE            = {AUDIO_DEVICE}")
    print(f"AUDIO_OUTPUT_DEVICE     = {AUDIO_OUTPUT_DEVICE}")
    print(f"AUDIO_SAMPLE_RATE       = {AUDIO_SAMPLE_RATE}")
    print(f"DRY_RUN                 = {DRY_RUN}")
    print(f"LCD_BACKLIGHT           = {LCD_BACKLIGHT}")
    print(f"OPENAI_API_KEY set      = {bool(OPENAI_API_KEY)}")
    print(f"OPENCLAW_TOKEN set      = {bool(OPENCLAW_TOKEN)}")
    print(f"ENABLE_TTS              = {ENABLE_TTS}")
    print(f"CONVERSATION_HISTORY    = {CONVERSATION_HISTORY_LENGTH}")
    print(f"SILENCE_RMS_THRESHOLD   = {SILENCE_RMS_THRESHOLD}")
