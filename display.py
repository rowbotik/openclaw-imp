import re
import random
import socket
import sys
import os
import threading
import time

try:
    import numpy as np
    _HAS_NUMPY = True
except ImportError:
    _HAS_NUMPY = False

from PIL import Image, ImageDraw, ImageFont

import config
sys.path.append("/home/pi/Whisplay/Driver")
from WhisPlay import WhisPlayBoard  # pyright: ignore[reportMissingImports]

_FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
_FONT_PATH_REGULAR = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
_EMOJI_FONT_PATHS = [
    "/usr/share/fonts/opentype/noto/NotoColorEmoji.ttf",
    "/usr/share/fonts/truetype/noto/NotoEmoji-Regular.ttf",
    "/usr/share/fonts/truetype/noto/NotoEmoji-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf",
    os.path.expanduser("~/.fonts/NotoColorEmoji.ttf"),
    "/usr/share/fonts/truetype/ancient-scripts/Symbola_hint.ttf",
]

STATUS_FONT_SIZE = 16
STATUS_SUB_FONT_SIZE = 12
RESPONSE_FONT_SIZE = 17
TITLE_FONT_SIZE = 14
BATTERY_FONT_SIZE = 10
IMP_LABEL_FONT_SIZE = 8
IMP_LABEL_SCALE = 1
ACCENT_BAR_HEIGHT = 3
POWER_SUPPLY_SYS = "/sys/class/power_supply"
PISUGAR_SOCKET = "/tmp/pisugar-server.sock"


def _load_emoji_font(size: int) -> ImageFont.FreeTypeFont | None:
    for path in _EMOJI_FONT_PATHS:
        if not os.path.exists(path):
            continue
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            # e.g. Noto Color Emoji: "invalid pixel size" (fixed-size font)
            continue
    return None


def _is_emoji(c: str) -> bool:
    if not c:
        return False
    cp = ord(c[0])
    return (
        0x2600 <= cp <= 0x26FF  # Misc Symbols
        or 0x2700 <= cp <= 0x27BF  # Dingbats
        or 0x2B50 <= cp <= 0x2B55
        or 0x1F300 <= cp <= 0x1F5FF  # Misc Symbols and Pictographs
        or 0x1F600 <= cp <= 0x1F64F  # Emoticons
        or 0x1F680 <= cp <= 0x1F6FF  # Transport and Map
        or 0x1F900 <= cp <= 0x1F9FF  # Supplemental Symbols
        or 0x1F000 <= cp <= 0x1F02F  # Mahjong etc
        or 0x1F0A0 <= cp <= 0x1F0FF  # Playing cards
        or 0xFE00 <= cp <= 0xFE0F   # Variation selectors
        or cp == 0x200D             # ZWJ
        or 0x1F3FB <= cp <= 0x1F3FF  # Skin tone modifiers
        or 0xE0020 <= cp <= 0xE007F
    )


def _is_emoji_modifier(c: str) -> bool:
    if not c:
        return False
    cp = ord(c[0])
    return cp == 0x200D or 0xFE00 <= cp <= 0xFE0F or 0x1F3FB <= cp <= 0x1F3FF


def _segment_mixed(text: str):
    """Yield (segment, use_emoji_font). Batches consecutive non-emoji chars into one segment."""
    i = 0
    while i < len(text):
        c = text[i]
        if _is_emoji(c):
            start = i
            i += 1
            while i < len(text) and (_is_emoji_modifier(text[i]) or _is_emoji(text[i])):
                i += 1
            yield (text[start:i], True)
        else:
            start = i
            i += 1
            while i < len(text) and not _is_emoji(text[i]):
                i += 1
            yield (text[start:i], False)


_RE_BOLD = re.compile(r"\*\*(.+?)\*\*|__(.+?)__")
_RE_ITALIC = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)|(?<!_)_(?!_)(.+?)(?<!_)_(?!_)")
_RE_CODE = re.compile(r"`(.+?)`")
_RE_HEADING = re.compile(r"^#{1,6}\s+", re.MULTILINE)
_RE_BULLET = re.compile(r"^[\-\*]\s+", re.MULTILINE)
_RE_NUMLIST = re.compile(r"^\d+[.)]\s+", re.MULTILINE)


def _clean_markdown(text: str) -> str:
    """Strip markdown formatting so LLM responses look clean on a small screen."""
    text = _RE_BOLD.sub(lambda m: m.group(1) or m.group(2), text)
    text = _RE_ITALIC.sub(lambda m: m.group(1) or m.group(2) or "", text)
    text = _RE_CODE.sub(r"\1", text)
    text = _RE_HEADING.sub("", text)
    text = _RE_BULLET.sub("\u2022 ", text)
    text = _RE_NUMLIST.sub("\u2022 ", text)
    return text


def _wifi_connected() -> bool:
    """Check wlan0 interface state (cheap file read, no subprocess)."""
    try:
        with open("/sys/class/net/wlan0/operstate") as f:
            return f.read().strip() == "up"
    except OSError:
        return False


def _read_pisugar_battery() -> tuple[int | None, str | None]:
    """Read battery from PiSugar server (Unix socket). Returns (pct, status) or (None, None)."""
    if not os.path.exists(PISUGAR_SOCKET):
        return (None, None)
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(1.0)
        sock.connect(PISUGAR_SOCKET)
        sock.sendall(b"get battery\n")
        data = sock.recv(64).decode("utf-8", errors="ignore").strip()
        sock.close()
        # Response: "95" or "battery: 95"
        m = re.search(r"(\d+)", data)
        if not m:
            return (None, None)
        pct = max(0, min(100, int(m.group(1))))
        status = None
        try:
            s2 = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s2.settimeout(0.5)
            s2.connect(PISUGAR_SOCKET)
            s2.sendall(b"get battery_charging\n")
            ch = s2.recv(64).decode("utf-8", errors="ignore").strip().lower()
            s2.close()
            if "true" in ch:
                status = "Charging"
            elif "false" in ch:
                status = "Discharging"
        except (OSError, socket.error):
            pass
        return (pct, status)
    except (OSError, socket.error, ValueError):
        return (None, None)


def _read_battery() -> tuple[int | None, str | None]:
    """Read battery capacity (0–100) and status. Tries PiSugar first, then sysfs. Returns (pct, status) or (None, None)."""
    result = _read_pisugar_battery()
    if result[0] is not None:
        return result
    if not os.path.isdir(POWER_SUPPLY_SYS):
        return (None, None)

    def is_battery_dir(base: str) -> bool:
        type_path = os.path.join(base, "type")
        if os.path.isfile(type_path):
            try:
                with open(type_path) as f:
                    return f.read().strip().upper() == "BATTERY"
            except OSError:
                pass
        return False

    for name in sorted(os.listdir(POWER_SUPPLY_SYS)):
        base = os.path.join(POWER_SUPPLY_SYS, name)
        if not os.path.isdir(base):
            continue
        # Accept BAT*, "battery", or any dir whose type file says Battery
        if not (name.upper().startswith("BAT") or name.lower() == "battery" or is_battery_dir(base)):
            continue
        cap_path = os.path.join(base, "capacity")
        status_path = os.path.join(base, "status")
        energy_now_path = os.path.join(base, "energy_now")
        energy_full_path = os.path.join(base, "energy_full")

        pct = None
        if os.path.isfile(cap_path):
            try:
                with open(cap_path) as f:
                    pct = int(f.read().strip())
            except (ValueError, OSError):
                pass
        if pct is None and os.path.isfile(energy_now_path) and os.path.isfile(energy_full_path):
            try:
                with open(energy_now_path) as f:
                    now = int(f.read().strip())
                with open(energy_full_path) as f:
                    full = int(f.read().strip())
                if full > 0:
                    pct = int(100 * now / full)
            except (ValueError, OSError):
                pass

        if pct is not None:
            pct = max(0, min(100, pct))
            status = None
            if os.path.isfile(status_path):
                try:
                    with open(status_path) as f:
                        status = f.read().strip()
                except OSError:
                    pass
            return (pct, status)
    return (None, None)


# ── Pixel-art Imp Zero frame generation ──────────────────────────

_SPX = 8  # each "pixel" is an 8×8 block → 30×30 logical grid on 240×240

_BODY_PALETTES = {
    "yellow": {
        "body": (255, 207, 31),
        "highlight": (255, 232, 78),
        "outline": (126, 91, 0),
        "foot": (230, 171, 0),
        "cheek": (255, 177, 38),
        "zap": (255, 221, 48),
    },
    "pink": {
        "body": (255, 129, 190),
        "highlight": (255, 188, 220),
        "outline": (136, 34, 86),
        "foot": (229, 89, 164),
        "cheek": (255, 207, 226),
        "zap": (255, 232, 78),
    },
    "red": {
        "body": (255, 88, 93),
        "highlight": (255, 146, 150),
        "outline": (112, 24, 28),
        "foot": (207, 54, 59),
        "cheek": (255, 177, 38),
        "zap": (255, 221, 48),
    },
    "blue": {
        "body": (74, 171, 255),
        "highlight": (143, 210, 255),
        "outline": (16, 74, 136),
        "foot": (45, 129, 220),
        "cheek": (255, 177, 38),
        "zap": (255, 221, 48),
    },
    "green": {
        "body": (91, 211, 54),
        "highlight": (158, 239, 115),
        "outline": (32, 96, 20),
        "foot": (63, 169, 39),
        "cheek": (255, 177, 38),
        "zap": (255, 221, 48),
    },
}
_body_palette_name = "pink" if config.IMP_BODY_COLOR == "cream" else config.IMP_BODY_COLOR
_PALETTE = _BODY_PALETTES.get(_body_palette_name, _BODY_PALETTES["yellow"])

_C_BODY = _PALETTE["body"]
_C_HIGHLIGHT = _PALETTE["highlight"]
_C_OUTLINE = _PALETTE["outline"]
_C_FOOT = _PALETTE["foot"]
_C_EYE = (0, 0, 0)
_C_SPARKLE = (255, 255, 255)
_C_CHEEK = _PALETTE["cheek"]
_C_MOUTH_INT = (0, 0, 0)
_C_MOUTH_EDGE = (0, 0, 0)
_C_TONGUE = (255, 88, 93)
_C_HORN = (255, 255, 244)
_C_HORN_SHADOW = (223, 213, 178)
_C_ZAP = _PALETTE["zap"]
_C_GOLD = (255, 221, 48)
_C_RED = (255, 88, 93)
_C_BLUE = (74, 171, 255)
_C_GREEN = (91, 211, 54)
_C_BLACK = (0, 0, 0)
_C_DARK = (24, 24, 24)
_C_GRAY = (120, 120, 120)

# Round body
_MAIN_CELLS: set[tuple[int, int]] = set()
_body_def: dict[int, tuple[int, int]] = {
    5: (13, 16), 6: (11, 18), 7: (9, 20), 8: (8, 21),
    17: (8, 21), 18: (9, 20), 19: (10, 19), 20: (12, 17),
}
for _r in range(9, 17):
    _body_def[_r] = (7, 22)
for _r, (_s, _e) in _body_def.items():
    for _c in range(_s, _e + 1):
        _MAIN_CELLS.add((_c, _r))

# Stubby arms
_ARM_CELLS: set[tuple[int, int]] = set()
for _p in [
    (5, 13), (5, 14), (6, 12), (6, 13), (6, 14),
    (24, 13), (24, 14), (23, 12), (23, 13), (23, 14),
]:
    _ARM_CELLS.add(_p)

# Rounded feet
_FOOT_CELLS: set[tuple[int, int]] = set()
for _p in [
    (10, 20), (11, 20), (12, 20), (11, 21),
    (17, 20), (18, 20), (19, 20), (18, 21),
]:
    _FOOT_CELLS.add(_p)

_BODY_CELLS = _MAIN_CELLS | _ARM_CELLS | _FOOT_CELLS

_HORN_CELLS: set[tuple[int, int]] = {
    (9, 3), (10, 3), (9, 4), (10, 4), (11, 4), (10, 5), (11, 5),
    (19, 3), (20, 3), (18, 4), (19, 4), (20, 4), (18, 5), (19, 5),
}

_EAR_CELLS: set[tuple[int, int]] = {
    (6, 13), (6, 14), (5, 14), (5, 15),
    (23, 13), (23, 14), (24, 14), (24, 15),
}

_TUFT_CELLS: set[tuple[int, int]] = {
    (14, 4), (15, 4), (15, 3), (16, 3), (15, 5), (16, 5), (17, 5),
}

_ZAP_CELLS: set[tuple[int, int]] = {
    (4, 10), (5, 10), (5, 11), (6, 11),
    (3, 13), (4, 13), (4, 14), (5, 14),
    (24, 10), (25, 10), (24, 11), (23, 11),
    (25, 13), (26, 13), (25, 14), (24, 14),
}

# Sphere highlight (upper-left shine)
_HIGHLIGHT_CELLS: set[tuple[int, int]] = set()
for _r in range(5, 10):
    for _c in range(9, 15):
        if (_c, _r) in _MAIN_CELLS:
            _HIGHLIGHT_CELLS.add((_c, _r))

_CHEEK_CELLS: set[tuple[int, int]] = {
    (8, 13), (8, 14), (9, 13), (9, 14),
    (20, 13), (20, 14), (21, 13), (21, 14),
}


def _body_color(cx: int, cy: int) -> tuple[int, int, int]:
    if (cx, cy) in _HIGHLIGHT_CELLS:
        return _C_HIGHLIGHT
    if (cx, cy) in _CHEEK_CELLS:
        return _C_CHEEK
    return _C_BODY


def _spx(draw: ImageDraw.ImageDraw, gx: int, gy: int, color: tuple[int, int, int]):
    x0, y0 = gx * _SPX, gy * _SPX
    draw.rectangle((x0, y0, x0 + _SPX - 1, y0 + _SPX - 1), fill=color)


def _sprite_body(draw: ImageDraw.ImageDraw):
    silhouette = _BODY_CELLS | _HORN_CELLS | _EAR_CELLS | _TUFT_CELLS
    for cx, cy in silhouette:
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            nx, ny = cx + dx, cy + dy
            if (nx, ny) not in silhouette and 0 <= nx < 30 and 0 <= ny < 30:
                _spx(draw, nx, ny, _C_OUTLINE)
    for cx, cy in _ZAP_CELLS:
        _spx(draw, cx, cy, _C_ZAP)
    for cx, cy in _EAR_CELLS:
        _spx(draw, cx, cy, _C_BODY)
    for cx, cy in _BODY_CELLS:
        _spx(draw, cx, cy, _body_color(cx, cy))
    for cx, cy in _TUFT_CELLS:
        _spx(draw, cx, cy, _C_BODY)
    for cx, cy in _HORN_CELLS:
        _spx(draw, cx, cy, _C_HORN if cy <= 3 else _C_HORN_SHADOW)
    # Foot outlines (feet that overlap with body get foot color)
    for cx, cy in _FOOT_CELLS:
        _spx(draw, cx, cy, _C_FOOT)


def _sprite_eyes_open(
    draw: ImageDraw.ImageDraw, dx: int = 0, dy: int = 0, wide: bool = False,
):
    y0 = 7 if wide else 8
    eye_def: dict[int, tuple[int, int]] = {
        y0: (13, 16),
        y0 + 1: (12, 17),
        y0 + 2: (11, 18),
        y0 + 3: (11, 18),
        y0 + 4: (11, 18),
        y0 + 5: (12, 17),
        y0 + 6: (13, 16),
    }
    for ey, (start, end) in eye_def.items():
        for ex in range(start, end + 1):
            _spx(draw, ex, ey, _C_EYE)
    sx = max(12, min(16, 13 + dx))
    sy = max(y0, min(y0 + 3, y0 + dy))
    _spx(draw, sx, sy, _C_SPARKLE)
    _spx(draw, sx, sy + 1, _C_SPARKLE)
    _spx(draw, sx + 1, sy, _C_SPARKLE)


def _sprite_eyes_blink(draw: ImageDraw.ImageDraw):
    for ex in range(11, 19):
        _spx(draw, ex, 11, _C_EYE)


def _sprite_eyes_happy(draw: ImageDraw.ImageDraw):
    """Single closed happy eye arc."""
    for col in range(12, 18):
        _spx(draw, col, 10, _C_EYE)
    _spx(draw, 12, 11, _C_EYE)
    _spx(draw, 17, 11, _C_EYE)


def _sprite_mouth_neutral(draw: ImageDraw.ImageDraw):
    for col in range(13, 17):
        _spx(draw, col, 17, _C_MOUTH_EDGE)


def _sprite_mouth_closed(draw: ImageDraw.ImageDraw):
    for col in range(13, 17):
        _spx(draw, col, 17, _C_MOUTH_EDGE)


def _sprite_mouth_smile(draw: ImageDraw.ImageDraw):
    _spx(draw, 12, 16, _C_MOUTH_EDGE)
    _spx(draw, 17, 16, _C_MOUTH_EDGE)
    for col in range(13, 17):
        _spx(draw, col, 17, _C_MOUTH_EDGE)


def _sprite_mouth_small(draw: ImageDraw.ImageDraw):
    _spx(draw, 14, 16, _C_MOUTH_EDGE)
    _spx(draw, 15, 16, _C_MOUTH_EDGE)
    _spx(draw, 13, 17, _C_MOUTH_EDGE)
    _spx(draw, 16, 17, _C_MOUTH_EDGE)
    _spx(draw, 14, 17, _C_MOUTH_INT)
    _spx(draw, 15, 17, _C_MOUTH_INT)
    _spx(draw, 14, 18, _C_TONGUE)
    _spx(draw, 15, 18, _C_TONGUE)


def _sprite_mouth_open(draw: ImageDraw.ImageDraw):
    for col in range(13, 17):
        _spx(draw, col, 16, _C_MOUTH_EDGE)
        _spx(draw, col, 18, _C_MOUTH_EDGE)
    _spx(draw, 13, 17, _C_MOUTH_EDGE)
    _spx(draw, 16, 17, _C_MOUTH_EDGE)
    _spx(draw, 14, 17, _C_MOUTH_INT)
    _spx(draw, 15, 17, _C_MOUTH_INT)
    _spx(draw, 14, 18, _C_TONGUE)
    _spx(draw, 15, 18, _C_TONGUE)


def _sprite_mouth_wide(draw: ImageDraw.ImageDraw):
    for col in range(12, 18):
        _spx(draw, col, 17, _C_MOUTH_EDGE)
        _spx(draw, col, 20, _C_MOUTH_EDGE)
    for row in (18, 19):
        _spx(draw, 12, row, _C_MOUTH_EDGE)
        _spx(draw, 17, row, _C_MOUTH_EDGE)
        for col in range(13, 17):
            _spx(draw, col, row, _C_MOUTH_INT)
    for col in range(13, 17):
        _spx(draw, col, 19, _C_TONGUE)


def _sprite_mouth_sad(draw: ImageDraw.ImageDraw):
    _spx(draw, 12, 18, _C_MOUTH_EDGE)
    _spx(draw, 17, 18, _C_MOUTH_EDGE)
    for col in range(13, 17):
        _spx(draw, col, 17, _C_MOUTH_EDGE)


def _sprite_mouth_o(draw: ImageDraw.ImageDraw):
    _spx(draw, 14, 17, _C_MOUTH_EDGE)
    _spx(draw, 15, 17, _C_MOUTH_EDGE)
    _spx(draw, 14, 18, _C_TONGUE)
    _spx(draw, 15, 18, _C_TONGUE)


def _sprite_eyes_angry(draw: ImageDraw.ImageDraw):
    _sprite_eyes_open(draw, dx=-1, dy=-1)
    for ex, ey in ((11, 8), (12, 9), (17, 8), (16, 9)):
        _spx(draw, ex, ey, _C_HORN)


def _sprite_eyes_sleepy(draw: ImageDraw.ImageDraw):
    for col in range(11, 19):
        _spx(draw, col, 11, _C_EYE)
    _spx(draw, 12, 12, _C_EYE)
    _spx(draw, 17, 12, _C_EYE)


def _decor_question(draw: ImageDraw.ImageDraw):
    for gx, gy in ((20, 6), (21, 6), (22, 7), (22, 8), (21, 9), (21, 11)):
        _spx(draw, gx, gy, _C_SPARKLE)


def _decor_exclaim(draw: ImageDraw.ImageDraw):
    for gx, gy in ((22, 6), (22, 7), (22, 8), (22, 10)):
        _spx(draw, gx, gy, (255, 88, 93))


def _decor_sleep(draw: ImageDraw.ImageDraw):
    for gx, gy, color in (
        (21, 6, (74, 171, 255)), (22, 5, (74, 171, 255)),
        (23, 4, (74, 171, 255)), (23, 7, (74, 171, 255)),
    ):
        _spx(draw, gx, gy, color)


def _decor_heart(draw: ImageDraw.ImageDraw):
    for gx, gy in ((22, 6), (24, 6), (21, 7), (22, 7), (23, 7), (24, 7), (25, 7), (22, 8), (23, 8), (24, 8), (23, 9)):
        _spx(draw, gx, gy, (255, 88, 93))


def _decor_wifi(draw: ImageDraw.ImageDraw):
    green = (91, 211, 54)
    for gx, gy in ((21, 6), (22, 5), (23, 5), (24, 6), (22, 7), (23, 7), (23, 9)):
        _spx(draw, gx, gy, green)


def _decor_error(draw: ImageDraw.ImageDraw):
    red = (255, 88, 93)
    for offset in range(4):
        _spx(draw, 22 + offset, 5 + offset, red)
        _spx(draw, 25 - offset, 5 + offset, red)


def _decor_low_power(draw: ImageDraw.ImageDraw):
    red = (255, 88, 93)
    _spx(draw, 23, 6, _C_SPARKLE)
    _spx(draw, 24, 6, _C_SPARKLE)
    _spx(draw, 23, 7, _C_SPARKLE)
    _spx(draw, 24, 7, _C_SPARKLE)
    _spx(draw, 24, 8, red)


# ── Pixel accessory overlays ───────────────────────────────────────

_ACCESSORY_NAMES = (
    "bowler",
    "party_hat",
    "crown",
    "bow_tie",
    "halo",
    "headphones",
    "sleep_cap",
    "sparkle_horns",
)


def _accessory_bowler(draw: ImageDraw.ImageDraw):
    for gx in range(11, 19):
        _spx(draw, gx, 5, _C_DARK)
    for gx in range(9, 21):
        _spx(draw, gx, 6, _C_DARK)
    for gx in range(12, 18):
        _spx(draw, gx, 3, _C_DARK)
        _spx(draw, gx, 4, _C_DARK)
    for gx in range(12, 18):
        _spx(draw, gx, 5, _C_GRAY)


def _accessory_party_hat(draw: ImageDraw.ImageDraw):
    rows = {1: (15, 15), 2: (14, 16), 3: (13, 17), 4: (12, 18), 5: (11, 19)}
    for gy, (start, end) in rows.items():
        for gx in range(start, end + 1):
            _spx(draw, gx, gy, _C_BLUE if (gx + gy) % 2 else _C_RED)
    for gx in range(12, 19, 3):
        _spx(draw, gx, 5, _C_GOLD)
    _spx(draw, 15, 0, _C_GOLD)


def _accessory_crown(draw: ImageDraw.ImageDraw):
    for gx in range(11, 19):
        _spx(draw, gx, 5, _C_GOLD)
    for gx, gy in ((11, 4), (12, 3), (15, 2), (18, 3), (19, 4)):
        _spx(draw, gx, gy, _C_GOLD)
    for gx, gy in ((12, 3), (15, 2), (18, 3)):
        _spx(draw, gx, gy + 1, _C_RED)


def _accessory_bow_tie(draw: ImageDraw.ImageDraw):
    for gx, gy in (
        (11, 19), (12, 18), (12, 19), (12, 20), (13, 19),
        (16, 19), (17, 18), (17, 19), (17, 20), (18, 19),
    ):
        _spx(draw, gx, gy, _C_RED)
    _spx(draw, 14, 19, _C_DARK)
    _spx(draw, 15, 19, _C_DARK)


def _accessory_halo(draw: ImageDraw.ImageDraw):
    for gx in range(11, 19):
        _spx(draw, gx, 2, _C_GOLD)
    for gx in (10, 19):
        _spx(draw, gx, 3, _C_GOLD)
    for gx in range(12, 18):
        _spx(draw, gx, 3, (255, 244, 150))


def _accessory_headphones(draw: ImageDraw.ImageDraw):
    for gx in range(10, 20):
        _spx(draw, gx, 6, _C_DARK)
    for gy in range(8, 13):
        _spx(draw, 8, gy, _C_DARK)
        _spx(draw, 21, gy, _C_DARK)
    for gy in range(9, 12):
        _spx(draw, 9, gy, _C_BLUE)
        _spx(draw, 20, gy, _C_BLUE)


def _accessory_sleep_cap(draw: ImageDraw.ImageDraw):
    for gx, gy in (
        (12, 4), (13, 3), (14, 3), (15, 2), (16, 2), (17, 3), (18, 4),
        (13, 4), (14, 4), (15, 4), (16, 4), (17, 4),
    ):
        _spx(draw, gx, gy, _C_BLUE)
    _spx(draw, 19, 4, _C_SPARKLE)
    _spx(draw, 18, 5, _C_SPARKLE)


def _accessory_sparkle_horns(draw: ImageDraw.ImageDraw):
    for gx, gy in ((7, 3), (22, 3), (6, 5), (23, 5), (8, 1), (21, 1)):
        _spx(draw, gx, gy, _C_GOLD)


_ACCESSORY_DRAWERS = {
    "bowler": _accessory_bowler,
    "party_hat": _accessory_party_hat,
    "crown": _accessory_crown,
    "bow_tie": _accessory_bow_tie,
    "halo": _accessory_halo,
    "headphones": _accessory_headphones,
    "sleep_cap": _accessory_sleep_cap,
    "sparkle_horns": _accessory_sparkle_horns,
}


def _apply_accessory(sprite: Image.Image, accessory: str) -> Image.Image:
    img = sprite.copy()
    drawer = _ACCESSORY_DRAWERS.get(accessory)
    if drawer:
        drawer(ImageDraw.Draw(img))
    return img


def _make_sprite(eyes_fn, mouth_fn, decor_fn=None) -> Image.Image:
    img = Image.new("RGB", (240, 240), (0, 0, 0))
    draw = ImageDraw.Draw(img)
    _sprite_body(draw)
    eyes_fn(draw)
    mouth_fn(draw)
    if decor_fn:
        decor_fn(draw)
    return img


def _apply_blink(sprite: Image.Image) -> Image.Image:
    """Return a copy with closed-eye lines drawn over the eye area."""
    img = sprite.copy()
    draw = ImageDraw.Draw(img)
    for ey in range(7, 15):
        for ex in range(11, 19):
            if (ex, ey) in _BODY_CELLS:
                _spx(draw, ex, ey, _body_color(ex, ey))
    _sprite_eyes_blink(draw)
    return img


def _generate_sprite_frames() -> dict[str, Image.Image]:
    bases = {
        "idle": _make_sprite(_sprite_eyes_open, _sprite_mouth_smile),
        "happy": _make_sprite(_sprite_eyes_open, _sprite_mouth_smile),
        "excited": _make_sprite(_sprite_eyes_open, _sprite_mouth_wide),
        "proud": _make_sprite(_sprite_eyes_happy, _sprite_mouth_smile),
        "curious": _make_sprite(_sprite_eyes_open, _sprite_mouth_neutral, _decor_question),
        "listen": _make_sprite(
            lambda d: _sprite_eyes_open(d, wide=True), _sprite_mouth_o,
        ),
        "think1": _make_sprite(
            lambda d: _sprite_eyes_open(d, dx=1, dy=-1), _sprite_mouth_neutral, _decor_question,
        ),
        "think2": _make_sprite(
            lambda d: _sprite_eyes_open(d, dx=-1, dy=-1), _sprite_mouth_neutral, _decor_question,
        ),
        "talk0": _make_sprite(_sprite_eyes_open, _sprite_mouth_closed),
        "talk1": _make_sprite(_sprite_eyes_open, _sprite_mouth_small),
        "talk2": _make_sprite(_sprite_eyes_open, _sprite_mouth_open),
        "talk3": _make_sprite(_sprite_eyes_open, _sprite_mouth_wide),
        "sleepy": _make_sprite(_sprite_eyes_sleepy, _sprite_mouth_o, _decor_sleep),
        "love": _make_sprite(_sprite_eyes_open, _sprite_mouth_small, _decor_heart),
        "sad": _make_sprite(_sprite_eyes_open, _sprite_mouth_sad),
        "angry": _make_sprite(_sprite_eyes_angry, _sprite_mouth_sad),
        "alert": _make_sprite(_sprite_eyes_open, _sprite_mouth_neutral, _decor_exclaim),
        "connected": _make_sprite(_sprite_eyes_open, _sprite_mouth_smile, _decor_wifi),
        "low_power": _make_sprite(_sprite_eyes_open, _sprite_mouth_sad, _decor_low_power),
        "error": _make_sprite(_sprite_eyes_open, _sprite_mouth_sad, _decor_error),
    }
    frames = dict(bases)
    for key, sprite in bases.items():
        frames[key + "_blink"] = _apply_blink(sprite)
    return frames


def _idle_mood_key() -> str:
    allowed = {
        "idle", "happy", "excited", "proud", "curious", "sleepy", "love",
        "sad", "angry", "alert", "connected", "low_power", "error",
    }
    mood = config.IMP_IDLE_MOOD.lower().strip()
    return mood if mood in allowed else "happy"


# Idle / done bob cycle. More in-between frames make higher dashboard FPS values
# feel like a float instead of a jump while preserving whole-pixel sprite motion.
_BOB_CYCLE = [
    0, 0, 0, 0, 0,
    1, 1, 1, 1,
    2, 2, 2,
    3, 3, 3,
    4, 4, 4, 4,
    5, 5, 5,
    6, 6, 6, 6, 6,
    5, 5, 5,
    4, 4, 4, 4,
    3, 3, 3,
    2, 2, 2,
    1, 1, 1, 1,
    0, 0, 0, 0, 0,
]


def _scaled_bob_px(tick: int) -> int:
    max_float = max(0, min(8, getattr(config, "IMP_FLOAT_PIXELS", 3)))
    if max_float == 0:
        return 0
    raw = _BOB_CYCLE[tick % len(_BOB_CYCLE)]
    return int(round(raw / 6 * max_float))


class Display:
    def __init__(self, backlight=70):
        self.board = WhisPlayBoard()
        self.board.set_backlight(backlight)

        self._width = self.board.LCD_WIDTH
        self._height = self.board.LCD_HEIGHT

        self._status_font = ImageFont.truetype(_FONT_PATH, STATUS_FONT_SIZE)
        self._status_sub_font = ImageFont.truetype(_FONT_PATH_REGULAR, STATUS_SUB_FONT_SIZE)
        self._response_font = ImageFont.truetype(_FONT_PATH_REGULAR, RESPONSE_FONT_SIZE)
        self._title_font = ImageFont.truetype(_FONT_PATH, TITLE_FONT_SIZE)
        self._imp_font = ImageFont.truetype(_FONT_PATH, IMP_LABEL_FONT_SIZE)
        try:
            self._battery_font = ImageFont.truetype(_FONT_PATH_REGULAR, BATTERY_FONT_SIZE)
        except OSError:
            self._battery_font = self._status_sub_font  # fallback so battery corner still draws
        self._emoji_status = _load_emoji_font(STATUS_FONT_SIZE)
        self._emoji_response = _load_emoji_font(RESPONSE_FONT_SIZE)

        self._response_buf = ""
        self._last_draw_time = 0.0
        fps = max(1, getattr(config, "UI_MAX_FPS", 10))
        self._min_draw_interval = 1.0 / fps

        self._pad_x = 10
        self._pad_y = 8

        self._default_backlight = backlight
        self._sleeping = False
        self._draw_lock = threading.Lock()
        self._cached_paragraphs: list[str] = []
        self._cached_wrapped: list[list[str]] = []
        self._sprite_frames = _generate_sprite_frames()
        self._accessory_names = ("none",) + _ACCESSORY_NAMES
        self._current_accessory = "none"
        self._next_accessory_tick = 0

        self.clear()

    def sleep(self):
        if self._sleeping:
            return
        self._sleeping = True
        self.clear()
        self.board.set_backlight(0)

    def wake(self):
        if not self._sleeping:
            return
        self._sleeping = False
        self.board.set_backlight(self._default_backlight)

    @property
    def is_sleeping(self) -> bool:
        return self._sleeping

    def _draw_mixed(
        self,
        draw: ImageDraw.ImageDraw,
        xy: tuple[int, int],
        text: str,
        text_font: ImageFont.FreeTypeFont,
        emoji_font: ImageFont.FreeTypeFont | None,
        fill: tuple[int, int, int],
        max_x: int = 0,
    ) -> float:
        """Draw text with emoji fallback (by segment/cluster), returns total width drawn.

        When *max_x* > 0, stop drawing before exceeding that x coordinate.
        """
        x, y = xy
        right_limit = max_x if max_x > 0 else self._width
        for segment, use_emoji in _segment_mixed(text):
            if use_emoji and emoji_font:
                font = emoji_font
                draw_seg = segment
            else:
                font = text_font
                draw_seg = "?" if use_emoji else segment
            try:
                seg_w = font.getlength(draw_seg)
                if x + seg_w > right_limit:
                    for ch in draw_seg:
                        ch_w = font.getlength(ch)
                        if x + ch_w > right_limit:
                            break
                        draw.text((x, y), ch, font=font, fill=fill)
                        x += ch_w
                    return x - xy[0]
                draw.text((x, y), draw_seg, font=font, fill=fill)
                x += seg_w
            except Exception:
                try:
                    draw.text((x, y), "?", font=text_font, fill=fill)
                    x += text_font.getlength("?")
                except Exception:
                    x += text_font.getlength("?")
        return x - xy[0]

    def _text_width_mixed(
        self,
        text: str,
        text_font: ImageFont.FreeTypeFont,
        emoji_font: ImageFont.FreeTypeFont | None,
    ) -> float:
        w = 0.0
        for segment, use_emoji in _segment_mixed(text):
            if use_emoji and emoji_font:
                try:
                    w += emoji_font.getlength(segment)
                except Exception:
                    w += text_font.getlength("?")
            else:
                seg = "?" if use_emoji else segment
                w += text_font.getlength(seg)
        return w

    def _truncate_text(
        self,
        text: str,
        font: ImageFont.FreeTypeFont,
        max_w: float,
        emoji_font: ImageFont.FreeTypeFont | None = None,
    ) -> str:
        """Truncate *text* so it fits within *max_w* pixels, adding '…' if shortened."""
        def _measure(s: str) -> float:
            if emoji_font:
                return self._text_width_mixed(s, font, emoji_font)
            return font.getlength(s)

        if _measure(text) <= max_w:
            return text
        ellipsis_w = font.getlength("…")
        while len(text) > 1 and _measure(text) + ellipsis_w > max_w:
            text = text[:-1]
        return text + "…"

    def _wrap_pixels(
        self,
        text: str,
        font: ImageFont.FreeTypeFont,
        max_w: int,
        emoji_font: ImageFont.FreeTypeFont | None = None,
    ) -> list[str]:
        """Word-wrap text to fit within *max_w* pixels, accounting for emoji font widths."""
        def _measure(s: str) -> float:
            if emoji_font:
                return self._text_width_mixed(s, font, emoji_font)
            return font.getlength(s)

        words = text.split(" ")
        lines: list[str] = []
        cur = ""
        for word in words:
            test = f"{cur} {word}" if cur else word
            if _measure(test) <= max_w:
                cur = test
            else:
                if cur:
                    lines.append(cur)
                if _measure(word) > max_w:
                    buf = ""
                    for ch in word:
                        if _measure(buf + ch) > max_w and buf:
                            lines.append(buf)
                            buf = ch
                        else:
                            buf += ch
                    cur = buf
                else:
                    cur = word
        if cur:
            lines.append(cur)
        return lines

    def _image_to_rgb565(self, image: Image.Image) -> list[int]:
        raw = image.tobytes("raw", "RGB")
        if _HAS_NUMPY:
            arr = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3)
            r = arr[:, 0].astype(np.uint16)
            g = arr[:, 1].astype(np.uint16)
            b = arr[:, 2].astype(np.uint16)
            rgb565 = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
            packed = np.empty(rgb565.shape[0] * 2, dtype=np.uint8)
            packed[0::2] = ((rgb565 >> 8) & 0xFF).astype(np.uint8)
            packed[1::2] = (rgb565 & 0xFF).astype(np.uint8)
            return packed.tolist()
        buf = []
        for i in range(0, len(raw), 3):
            r, g, b = raw[i], raw[i + 1], raw[i + 2]
            rgb565 = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
            buf.append((rgb565 >> 8) & 0xFF)
            buf.append(rgb565 & 0xFF)
        return buf

    def _draw_battery(self, draw: ImageDraw.ImageDraw):
        """Draw battery percentage and status in top-right corner (small). Always draws something."""
        pct, status = _read_battery()
        if pct is not None:
            if status == "Charging":
                label = f"↑{pct}%"
            elif status == "Full":
                label = "100%"
            else:
                label = f"{pct}%"
        else:
            label = "—"  # No battery detected; show placeholder so corner is visible
        tw = self._battery_font.getlength(label)
        x = self._width - tw - self._pad_x
        y = self._pad_y
        draw.text((x, y), label, font=self._battery_font, fill=(120, 120, 120))

    def _draw(self, image: Image.Image):
        buf = self._image_to_rgb565(image)
        with self._draw_lock:
            self.board.draw_image(0, 0, self._width, self._height, buf)

    def _sprite_y_offset(self, sprite: Image.Image) -> int:
        return max(0, int((self._height - sprite.height) / 2))

    def _compose_sprite_frame(
        self,
        sprite: Image.Image,
        y_shift: int = 0,
        shadow: bool = False,
    ) -> Image.Image:
        if sprite.size == (self._width, self._height) and y_shift == 0:
            img = sprite.copy()
            if shadow:
                self._draw_ground_shadow(ImageDraw.Draw(img), self._sprite_y_offset(sprite), y_shift)
            return img
        img = Image.new("RGB", (self._width, self._height), (0, 0, 0))
        if shadow:
            self._draw_ground_shadow(ImageDraw.Draw(img), self._sprite_y_offset(sprite), y_shift)
        img.paste(sprite, (0, self._sprite_y_offset(sprite) - y_shift))
        return img

    def _draw_ground_shadow(self, draw: ImageDraw.ImageDraw, y_offset: int, y_shift: int = 0):
        base_y = min(self._height - 18, y_offset + 218)
        width_pad = max(0, y_shift) * 2
        color = (38, 38, 38)
        for gx in range(10 - min(2, width_pad), 21 + min(2, width_pad)):
            _spx(draw, gx, base_y // _SPX, color)
        for gx in range(12, 19):
            _spx(draw, gx, base_y // _SPX + 1, (24, 24, 24))

    def set_status(
        self,
        text: str,
        color: tuple[int, int, int] = (200, 200, 200),
        subtitle: str | None = None,
        accent_color: tuple[int, int, int] | None = None,
    ):
        """Show a status screen: optional accent bar, main text, optional subtitle."""
        img = Image.new("RGB", (self._width, self._height), (0, 0, 0))
        draw = ImageDraw.Draw(img)

        y_offset = 0
        if accent_color is not None:
            draw.rectangle(
                (0, 0, self._width, ACCENT_BAR_HEIGHT),
                fill=accent_color,
            )
            y_offset = ACCENT_BAR_HEIGHT + 6

        usable_w = self._width - self._pad_x * 2
        lines = self._wrap_pixels(text, self._status_font, usable_w, self._emoji_status)
        line_h = STATUS_FONT_SIZE + 4
        sub_h = STATUS_SUB_FONT_SIZE + 2 if subtitle else 0
        total_h = line_h * len(lines) + sub_h
        y = max(self._pad_y + y_offset, (self._height - total_h) // 2)

        for line in lines:
            tw = self._text_width_mixed(line, self._status_font, self._emoji_status)
            x = max(self._pad_x, int((self._width - tw) / 2))
            self._draw_mixed(
                draw, (x, y), line, self._status_font, self._emoji_status, color,
                max_x=self._width - self._pad_x,
            )
            y += line_h
            if y + line_h > self._height:
                break

        if subtitle and y + STATUS_SUB_FONT_SIZE <= self._height:
            sub = self._truncate_text(subtitle, self._status_sub_font, usable_w)
            sub_w = self._status_sub_font.getlength(sub)
            x = max(self._pad_x, int((self._width - sub_w) / 2))
            draw.text((x, y), sub, font=self._status_sub_font, fill=(100, 100, 100))

        self._draw_battery(draw)
        self._draw(img)
        self._response_buf = ""
        self._cached_paragraphs = []
        self._cached_wrapped = []

    def _draw_pixel_text(
        self,
        image: Image.Image,
        xy: tuple[int, int],
        text: str,
        font: ImageFont.FreeTypeFont,
        fill: tuple[int, int, int],
        scale: int = 2,
    ):
        bbox = font.getbbox(text)
        width = max(1, bbox[2] - bbox[0])
        height = max(1, bbox[3] - bbox[1])
        mask = Image.new("L", (width, height), 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.text((-bbox[0], -bbox[1]), text, font=font, fill=255)
        resample = Image.Resampling.NEAREST if hasattr(Image, "Resampling") else Image.NEAREST
        mask = mask.resize((width * scale, height * scale), resample=resample)
        color = Image.new("RGB", mask.size, fill)
        image.paste(color, xy, mask)

    def set_idle_screen(self):
        """Draw idle screen with the Imp logo, battery, and wifi status."""
        sprite = self._sprite_frames.get(_idle_mood_key(), self._sprite_frames["idle"])
        img = self._compose_sprite_frame(sprite, shadow=config.IMP_SHADOW)
        draw = ImageDraw.Draw(img)

        draw.rectangle((0, 0, self._width, ACCENT_BAR_HEIGHT), fill=(40, 40, 40))

        self._draw_battery(draw)

        # Wifi indicator (top-left)
        if _wifi_connected():
            draw.text((self._pad_x, self._pad_y), "\u25cf", font=self._battery_font, fill=(0, 180, 80))
        else:
            draw.text((self._pad_x, self._pad_y), "\u25cb", font=self._battery_font, fill=(180, 60, 60))

        label = "Imp"
        bbox = self._imp_font.getbbox(label)
        lw = (bbox[2] - bbox[0]) * IMP_LABEL_SCALE
        lh = (bbox[3] - bbox[1]) * IMP_LABEL_SCALE
        self._draw_pixel_text(
            img,
            (int((self._width - lw) / 2), self._height - lh - 2),
            label,
            self._imp_font,
            fill=(72, 72, 72),
            scale=IMP_LABEL_SCALE,
        )

        self._draw(img)
        self._response_buf = ""
        self._cached_paragraphs = []
        self._cached_wrapped = []

    # ── Sprite-based animated character ─────────────────────────────

    _ACCENT_COLORS = {
        "listening": (0, 205, 95),
        "thinking": (18, 18, 18),
        "talking": (0, 200, 100),
        "done": (18, 18, 18),
    }

    def start_character(self, state: str = "done", tts_player=None):
        """Start the animated character loop. tts_player is used for RMS mouth sync."""
        self._stop_animations()
        self._char_state = state
        self._char_tts = tts_player
        self._char_stop = threading.Event()
        t = threading.Thread(target=self._character_loop, daemon=True)
        t.start()
        self._char_thread = t

    def set_character_state(self, state: str):
        self._char_state = state

    def stop_character(self):
        if hasattr(self, "_char_stop"):
            self._char_stop.set()
        if hasattr(self, "_char_thread"):
            self._char_thread.join(timeout=2)

    def _character_loop(self):
        tick = 0
        frame_delay = 1.0 / max(1, getattr(config, "UI_MAX_FPS", 4))
        accessory_mode = getattr(config, "IMP_ACCESSORY_MODE", "random")
        while not self._char_stop.is_set():
            state = self._char_state
            tts = getattr(self, "_char_tts", None)

            # Select sprite frame key
            if state == "talking":
                mouth = tts.get_mouth_shape() if tts else -1
                key = f"talk{mouth}" if mouth >= 0 else "talk0"
            elif state == "listening":
                key = "listen"
            elif state == "thinking":
                key = "think1" if (tick // 15) % 2 == 0 else "think2"
            elif state == "done":
                key = "happy"
            else:
                key = _idle_mood_key()

            # Blink every ~4 s — skip for listening (attentive) and done (happy eyes)
            if (tick % 40) in (0, 1) and state not in ("listening", "done"):
                key += "_blink"

            sprite = self._sprite_frames.get(key, self._sprite_frames["idle"])
            accessory = self._accessory_for_tick(tick, state, accessory_mode)
            if accessory != "none":
                sprite = _apply_accessory(sprite, accessory)

            # Gentle bob for idle / done states
            bob_px = 0
            if state in ("idle", "done"):
                bob_px = _scaled_bob_px(tick)

            img = self._compose_sprite_frame(sprite, bob_px, shadow=config.IMP_SHADOW)

            draw = ImageDraw.Draw(img)

            self._draw_top_indicator(draw, state)

            label = {"listening": "Imp listening...", "thinking": "Imp thinking..."}.get(state, "")
            if label:
                lw = self._status_sub_font.getlength(label)
                draw.text(
                    (int((self._width - lw) / 2), 200),
                    label, font=self._status_sub_font, fill=(120, 120, 120),
                )

            # Subtitle: single line showing the current fragment being spoken
            sub_text = ""
            if tts:
                sub_text = tts.current_text
            if sub_text:
                sub_text = _clean_markdown(sub_text)
                usable_w = self._width - self._pad_x * 2
                sub_font = self._response_font
                sub_y = 200
                draw.rectangle(
                    (0, sub_y - 2, self._width, self._height),
                    fill=(0, 0, 0),
                )
                sub_text = self._truncate_text(
                    sub_text, sub_font, usable_w, self._emoji_response,
                )
                sw = self._text_width_mixed(sub_text, sub_font, self._emoji_response)
                sx = max(self._pad_x, int((self._width - sw) / 2))
                self._draw_mixed(
                    draw, (sx, sub_y), sub_text,
                    sub_font, self._emoji_response, (255, 255, 255),
                    max_x=self._width - self._pad_x,
                )

            self._draw_battery(draw)
            self._draw(img)

            tick += 1
            self._char_stop.wait(timeout=frame_delay)

    def _accessory_for_tick(self, tick: int, state: str, mode: str) -> str:
        if mode == "off":
            return "none"
        if state in ("listening", "thinking"):
            return "none"
        if tick >= self._next_accessory_tick:
            self._next_accessory_tick = tick + random.randint(20, 55)
            if mode == "always":
                self._current_accessory = random.choice(_ACCESSORY_NAMES)
            else:
                self._current_accessory = random.choice(self._accessory_names)
        return self._current_accessory

    def _draw_top_indicator(self, draw: ImageDraw.ImageDraw, state: str):
        draw.rectangle((0, 0, self._width, 14), fill=(0, 0, 0))
        color = self._ACCENT_COLORS.get(state, (18, 18, 18))
        active = state in ("listening", "talking")
        if active:
            draw.rounded_rectangle((58, 0, self._width - 58, 10), radius=5, fill=color)
        else:
            draw.rectangle((58, 0, self._width - 58, 3), fill=color)

    def _stop_animations(self):
        """Stop any running animation (spinner or character)."""
        self.stop_spinner()
        self.stop_character()

    def start_spinner(self, label: str = "Thinking", color: tuple[int, int, int] = (255, 220, 50)):
        self._spinner_stop = threading.Event()
        t = threading.Thread(target=self._spin_loop, args=(label, color), daemon=True)
        t.start()
        self._spinner_thread = t

    def stop_spinner(self):
        if hasattr(self, "_spinner_stop"):
            self._spinner_stop.set()
        if hasattr(self, "_spinner_thread"):
            self._spinner_thread.join(timeout=2)

    def _spin_loop(self, label: str, color: tuple[int, int, int]):
        frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        i = 0
        while not self._spinner_stop.is_set():
            text = f"{frames[i]}  {label}"
            img = Image.new("RGB", (self._width, self._height), (0, 0, 0))
            draw = ImageDraw.Draw(img)
            draw.rectangle((0, 0, self._width, ACCENT_BAR_HEIGHT), fill=color)
            tw = self._text_width_mixed(text, self._status_font, self._emoji_status)
            x = max(self._pad_x, int((self._width - tw) / 2))
            y = (self._height - STATUS_FONT_SIZE) // 2
            self._draw_mixed(
                draw, (x, y), text, self._status_font, self._emoji_status, color,
                max_x=self._width - self._pad_x,
            )
            sub = "Getting answer…"
            sub_w = self._status_sub_font.getlength(sub)
            sx = max(self._pad_x, int((self._width - sub_w) / 2))
            draw.text((sx, y + STATUS_FONT_SIZE + 6), sub, font=self._status_sub_font, fill=(90, 90, 90))
            self._draw_battery(draw)
            self._draw(img)
            i = (i + 1) % len(frames)
            self._spinner_stop.wait(timeout=0.12)

    def set_response_text(self, text: str):
        """Draw full wrapped response text, scrolled to bottom."""
        self._response_buf = text
        self._cached_paragraphs = []
        self._cached_wrapped = []
        self._render_response(force=True)

    def append_response(self, delta: str):
        """Append a streaming delta and redraw (throttled)."""
        was_empty = not self._response_buf
        self._response_buf += delta
        # First token: show immediately; later tokens throttled by _min_draw_interval
        self._render_response(force=was_empty)

    def _render_response(self, force: bool = False):
        now = time.monotonic()
        if not force and (now - self._last_draw_time) < self._min_draw_interval:
            return
        self._last_draw_time = now

        img = Image.new("RGB", (self._width, self._height), (0, 0, 0))
        draw = ImageDraw.Draw(img)

        draw.rectangle((0, 0, self._width, ACCENT_BAR_HEIGHT), fill=(0, 160, 80))

        line_spacing = 4
        usable_w = self._width - self._pad_x * 2
        content_top = self._pad_y + ACCENT_BAR_HEIGHT + 4
        content_bottom = self._height - self._pad_y

        clean = _clean_markdown(self._response_buf)
        paragraphs = clean.split("\n")

        first_changed = len(paragraphs)
        for i, para in enumerate(paragraphs):
            stripped = para.strip() if para.strip() else ""
            if i >= len(self._cached_paragraphs) or self._cached_paragraphs[i] != stripped:
                first_changed = i
                break

        new_cached_paras: list[str] = []
        new_cached_wrapped: list[list[str]] = []
        all_lines: list[str] = []

        for i, para in enumerate(paragraphs):
            stripped = para.strip()
            if i < first_changed:
                new_cached_paras.append(self._cached_paragraphs[i])
                new_cached_wrapped.append(self._cached_wrapped[i])
                all_lines.extend(self._cached_wrapped[i])
            else:
                if not stripped:
                    wrapped = [""]
                else:
                    wrapped = self._wrap_pixels(stripped, self._response_font, usable_w, self._emoji_response)
                new_cached_paras.append(stripped)
                new_cached_wrapped.append(wrapped)
                all_lines.extend(wrapped)

        self._cached_paragraphs = new_cached_paras
        self._cached_wrapped = new_cached_wrapped

        line_h = RESPONSE_FONT_SIZE + line_spacing
        max_visible = (content_bottom - content_top) // line_h
        truncated = len(all_lines) > max_visible

        if truncated:
            all_lines = all_lines[-max_visible:]

        text_color = (230, 235, 240)
        y = content_top
        for line in all_lines:
            if not line:
                y += line_h // 2
                continue
            self._draw_mixed(
                draw, (self._pad_x, y), line,
                self._response_font, self._emoji_response, text_color,
                max_x=self._width - self._pad_x,
            )
            y += line_h

        if truncated:
            indicator = "\u2191"
            iw = self._battery_font.getlength(indicator)
            draw.text(
                (self._width - iw - self._pad_x, content_top),
                indicator, font=self._battery_font, fill=(80, 80, 80),
            )

        self._draw_battery(draw)
        self._draw(img)

    def flush_response(self):
        """Force a final redraw of buffered response text."""
        self._render_response(force=True)

    def update_text(self, text: str):
        """Legacy: draw centred text."""
        self.set_status(text, color=(255, 255, 255))

    def clear(self):
        with self._draw_lock:
            self.board.fill_screen(0x0000)

    def set_backlight(self, level: int):
        self.board.set_backlight(level)

    def cleanup(self):
        try:
            self.clear()
            self.board.set_backlight(0)
        except Exception:
            pass
        try:
            self.board.cleanup()
        except Exception:
            pass
