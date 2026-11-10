"""Optional lightweight on-screen chest-search ESTIMATOR for Fortnite.

This is *not* a game event reader. The locally captured search-prompt template
must be visible for multiple frames, the configured interaction key must be
pressed while the prompt is visible, and the prompt must then disappear shortly
afterwards. Looking away or a different search action may still be miscounted.

Nothing is injected into the game; no game memory/network is read, no global
keyboard hook is installed, and images / keystrokes are never transmitted.
"""
from __future__ import annotations
import ctypes
import os
import threading
import time
from pathlib import Path


class SearchInteraction:
    """Pure deterministic state machine; counts only prompt+key+disappearance."""
    def __init__(self, threshold: float = 0.86, min_visible_frames: int = 2,
                 min_absent_frames: int = 2, max_completion_delay: float = 1.8,
                 cooldown: float = 2.4):
        self.threshold = threshold
        self.min_visible_frames = min_visible_frames
        self.min_absent_frames = min_absent_frames
        self.max_completion_delay = max_completion_delay
        self.cooldown = cooldown
        self.reset()
        self.last_event = -1000.0

    def reset(self):
        self.visible = 0
        self.absent = 0
        self.armed = False
        self.pressed_at = None

    def update(self, score: float, pressed: bool, now: float) -> bool:
        if score >= self.threshold:
            self.visible += 1
            self.absent = 0
            if self.visible >= self.min_visible_frames:
                self.armed = True
            if self.armed and pressed:
                self.pressed_at = now
            return False

        self.visible = 0
        self.absent += 1
        if self.armed and pressed and self.pressed_at is None:
            self.pressed_at = now
        if self.armed and self.pressed_at is not None and self.absent >= self.min_absent_frames:
            valid = (0 <= now - self.pressed_at <= self.max_completion_delay and
                     now - self.last_event >= self.cooldown)
            self.reset()
            if valid:
                self.last_event = now
                return True
        if self.absent >= 5 or (self.pressed_at is not None and now - self.pressed_at > self.max_completion_delay):
            self.reset()
        return False


class WindowsInput:
    """Only checks one nominated key and whether Fortnite has focus."""
    def __init__(self):
        self.user32 = ctypes.windll.user32 if os.name == 'nt' else None

    def fortnite_focused(self):
        if not self.user32:
            return False
        h = self.user32.GetForegroundWindow()
        title = ctypes.create_unicode_buffer(512)
        self.user32.GetWindowTextW(h, title, 512)
        return 'fortnite' in title.value.lower()

    def key_pressed(self, key: str):
        if not self.user32:
            return False
        key = (key or 'E').strip().upper()
        if len(key) != 1 or not key.isalnum() or not key.isascii():
            return False
        # Passive GetAsyncKeyState polling, not a keyboard hook / keylogger.
        return bool(self.user32.GetAsyncKeyState(ord(key)) & 0x8001)


class VisionDetector:
    def __init__(self, core, template_path, threshold=0.86, key='E', interval=0.4):
        self.core = core
        self.template_path = Path(template_path)
        self.threshold = threshold
        self.key = key
        self.interval = max(0.35, min(1.5, float(interval)))
        self.stop = threading.Event()
        self.thread = None
        self.last_score = 0.0
        self.error = ''
        self.count = 0
        self.state = 'Aus'
        self.perf_ms = 0.0
        self.frames = 0
        # Surfaced by the UI so the user can judge how reliable the estimate is.
        self.last_event_at = None
        self.last_event_text = ''

    def start(self):
        if not self.template_path.is_file():
            raise ValueError('Zuerst ein PNG der Fortnite-Durchsuchen-Aufforderung auswählen.')
        if os.name != 'nt':
            raise RuntimeError('Die Live-Bildschirmerkennung wird nur unter Windows unterstützt.')
        try:
            import cv2  # noqa: F401
            import numpy  # noqa: F401
            from PIL import ImageGrab  # noqa: F401
        except ImportError as exc:
            raise RuntimeError('Für den Live-Bildschirmmodus SETUP_VISION.cmd ausführen (OpenCV, NumPy, Pillow).') from exc
        self.stop.clear()
        self.error = ''
        self.thread = threading.Thread(target=self.run, daemon=True, name='SquadLootScreenEstimator')
        self.thread.start()

    def stop_now(self):
        self.stop.set()
        self.state = 'Aus'
        self.last_score = 0.0

    def run(self):
        import cv2
        import numpy as np
        from PIL import ImageGrab
        try:
            template = cv2.imread(str(self.template_path), cv2.IMREAD_GRAYSCALE)
            if template is None or min(template.shape) < 8 or float(template.std()) < 8:
                raise ValueError('PNG zu klein oder kontrastarm. Such-Icon und Text knapp ausschneiden.')
            engine = SearchInteraction(self.threshold)
            input_state = WindowsInput()
            self.state = 'Warte auf Fortnite'
            while not self.stop.wait(self.interval):
                if not input_state.fortnite_focused():
                    engine.reset()
                    self.state = 'Fortnite nicht im Vordergrund'
                    continue
                started = time.perf_counter()
                # Only capture a central ROI, not the entire game frame. 2.5 FPS max.
                screen_w = input_state.user32.GetSystemMetrics(0)
                screen_h = input_state.user32.GetSystemMetrics(1)
                if screen_w < 400 or screen_h < 300:
                    self.state = 'Bildschirmauflösung zu klein'
                    continue
                bbox = (int(screen_w * .26), int(screen_h * .29),
                        int(screen_w * .74), int(screen_h * .72))
                image = ImageGrab.grab(bbox=bbox, all_screens=False)
                gray = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2GRAY)
                if template.shape[0] > gray.shape[0] or template.shape[1] > gray.shape[1]:
                    raise ValueError('Such-Vorlage ist größer als der überwachte mittlere Bildschirmbereich.')
                value = cv2.matchTemplate(gray, template, cv2.TM_CCOEFF_NORMED)
                score = float(cv2.minMaxLoc(value)[1])
                self.last_score = score
                pressed = input_state.key_pressed(self.key)
                self.state = f'Live-Beta · {self.key} · Treffer {score:.2f}'
                now = time.monotonic()
                self.frames += 1
                if engine.update(score, pressed, now):
                    self.core.adjust('vision', +1)
                    self.count += 1
                    self.last_event_at = now
                    self.last_event_text = (f'Suchhinweis + Taste {self.key} '
                                            f'(Treffer {score:.2f})')
                self.perf_ms = (time.perf_counter() - started) * 1000
        except Exception as exc:
            self.error = str(exc)[:180]
            self.state = 'Fehler'


# ---------------------------------------------------------------------------
# Optional Fortnite Visual Chest Counter v0.2.x file bridge.
# The third-party visual detector runs separately, never in our process.
# Its OBS outputs are cumulative and persist between sessions: only POSITIVE
# deltas after starting this bridge are counted for the CURRENT SquadLoot round.
# This avoids importing a 155-MB video engine into every Windows update.
# No images, video, keyboard events, or detector logs leave this PC.
# ---------------------------------------------------------------------------
import re as _re


def _visual_file_count(path: Path) -> int:
    """Parse a single numeric OBS text file, e.g. 'APPROX. OPENED CHESTS: 1,234'."""
    path = Path(path)
    if path.stat().st_size > 4096:
        raise ValueError(f'{path.name}: Textdatei ist unerwartet groß.')
    text = path.read_text(encoding='utf-8-sig').strip()
    if '/' in text:
        raise ValueError(f'{path.name}: bitte keine Zählerwerte im Format 3/500 verwenden.')
    # The external app lets users customize labels; accept any label whose last
    # token is an unsigned decimal counter, with optional thousands commas.
    match = _re.search(r'(?<!\d)(\d[\d,]*)\s*$', text)
    if not match:
        raise ValueError(f'{path.name}: keine Zählerzahl am Textende. '
                         'Bitte in Visual Chest Counter die Standard-Anzeige einstellen.')
    number = match.group(1)
    if not (_re.fullmatch(r'\d+', number) or
            _re.fullmatch(r'\d{1,3}(?:,\d{3})+', number)):
        raise ValueError(f'{path.name}: ungültiges Zahlenformat.')
    value = int(number.replace(',', ''))
    if not 0 <= value <= 1000000:
        raise ValueError(f'{path.name}: Wert außerhalb des erwarteten Bereichs.')
    return value


def read_visual_counts(folder) -> tuple[int, int]:
    """Return (certain, approximate TOTAL); approx already includes certain."""
    folder = Path(folder)
    if not folder.is_dir():
        raise FileNotFoundError(f'OBS-Ordner nicht vorhanden: {folder}')
    certain = _visual_file_count(folder / 'certain_chests.txt')
    approximate = _visual_file_count(folder / 'approximate_chests.txt')
    if certain > approximate:
        raise ValueError('Visual Counter: CERTAIN ist größer als APPROX. '
                         'Bitte die Original-Anzeigeformate prüfen.')
    return certain, approximate


class VisualCounterBridge:
    """Opt-in read-only adapter for the external visual detector's OBS text files.

    Does not spawn or control the external executable. At start it snapshots the
    already existing cumulative totals as a baseline, ignoring old rounds. When
    SquadLoot begins a new round the baseline is reset, so no stale counts are
    attributed to the new round. At most one vision source should be active.
    """

    def __init__(self, core):
        self.core = core
        self.folder = None
        self.running = False
        self.last_raw = None
        self.last_round = None
        self.estimated = 0
        self.certain = 0
        self.error = ''
        self.state = 'Aus'
        self.last_event_at = None

    def start(self, folder):
        values = read_visual_counts(folder)
        self.folder = Path(folder)
        with self.core.lock:
            self.last_round = self.core.round_id
            self.core.vision = 0
            self.core.last_live = 0.0
        self.last_raw = values
        self.estimated = 0
        self.certain = 0
        self.error = ''
        self.running = True
        self.state = 'Aktiv · warte auf neue Kisten'

    def stop(self):
        self.running = False
        self.state = 'Aus'

    def reset_baseline(self):
        """Used when the user deliberately resets provisional local counts."""
        if not self.running:
            return
        try:
            self.last_raw = read_visual_counts(self.folder)
            with self.core.lock:
                self.last_round = self.core.round_id
            self.estimated = self.certain = 0
            self.error = ''
            self.state = 'Zähler für diese Runde zurückgesetzt'
        except (OSError, ValueError) as exc:
            self.error = str(exc)[:200]
            self.state = 'Quelldateien nicht lesbar'

    def poll(self):
        """Call from the existing 1s GUI refresh; never starts its own loop."""
        if not self.running:
            return False
        try:
            values = read_visual_counts(self.folder)
        except (OSError, ValueError) as exc:
            self.error = str(exc)[:200]
            self.state = 'Quelle nicht lesbar · keine neuen Werte'
            return False
        with self.core.lock:
            round_id = self.core.round_id
        if round_id != self.last_round:
            # The source is continuous, our match counter is not.
            self.last_round = round_id
            self.last_raw = values
            self.estimated = self.certain = 0
            with self.core.lock:
                self.core.vision = 0
                self.core.last_live = 0.0
            self.error = ''
            self.state = 'Neue Runde · Referenzwert übernommen'
            return False
        if self.last_raw is None:
            self.last_raw = values
            return False
        if values[0] < self.last_raw[0] or values[1] < self.last_raw[1]:
            # External Reset/Profile switch: never treat a smaller cumulative
            # value as new chests or negate previously counted events.
            self.last_raw = values
            self.error = ''
            self.state = 'Quellzähler zurückgesetzt · warte auf neue Kisten'
            return False
        new_certain = values[0] - self.last_raw[0]
        new_approx = values[1] - self.last_raw[1]
        self.last_raw = values
        if not new_certain and not new_approx:
            self.error = ''
            self.state = 'Aktiv · warte auf neue Kisten'
            return False
        self.certain = min(100000, self.certain + new_certain)
        self.estimated = min(100000, self.estimated + new_approx)
        with self.core.lock:
            self.core.vision = self.estimated
            self.core.last_live = 0.0
        self.last_event_at = time.monotonic()
        self.state = 'Aktiv · neuer visueller Kistenfund'
        self.error = ''
        return bool(new_approx)


# ---------------------------------------------------------------------------
# Optional German popup calibration for the MIT-licensed Visual Chest Counter.
# v0.2.3 uses language-specific pixel templates, not general-purpose OCR.
# The user explicitly installs the patch on a separate application after
# selecting one REAL German chest XP popup word. Never auto-patch on launch.
# No new dependencies and no Fortnite process/memory manipulation.
# ---------------------------------------------------------------------------
import shutil as _shutil
import struct as _struct
import subprocess as _subprocess
import tempfile as _tempfile

_GERMAN_MARKER = "# SquadLootGermanPopupBetaV1"
_FVCC_ORIGINAL_LANGUAGES = (
    'LANGUAGE_CHOICES = (("English", ["en"]), ("Portuguese (Brazil)", ["pt"]), '
    '("Both (English + Portuguese (Brazil))", ["en", "pt"]))'
)
_FVCC_VISUAL_ENTRY = (
    '    {"id": "de:TRUHE", "file": paths.TEMPLATES_DIR / "chest/de/truhe.npy",\n'
    '     "source_video": None, "source_time": 0, "box": (0, 0, 0, 0)},\n'
)
_FVCC_DE_CHOICES = (
    'LANGUAGE_CHOICES = (("English", ["en"]), ("Portuguese (Brazil)", ["pt"]), '
    '("Both (English + Portuguese (Brazil))", ["en", "pt"]), '
    '("Deutsch (SquadLoot Beta)", ["de"]))'
)


def german_visual_counter_root(obs_output):
    """Find expected v0.2.3 extracted app from an existing OBS-output folder."""
    obs_output = Path(obs_output).expanduser().resolve()
    if obs_output.name.lower() != 'obs_output':
        raise ValueError('Bitte zuerst in SquadLoot den echten obs_output-Ordner auswählen.')
    root = obs_output.parent
    package = root / 'runtime' / 'lib' / 'fortnite_chest_counter'
    v = package / 'detection' / 'visual.py'
    cfg = package / 'settings.py'
    if not (v.is_file() and cfg.is_file() and
            (package / 'templates' / 'chest' / 'en' / 'chest.npy').is_file()):
        raise ValueError('Fortnite Visual Chest Counter v0.2.3 nicht am '
                         'erwarteten Ort gefunden. Bitte den Ordner der '
                         'Original-App mit obs_output verwenden.')
    return root, v, cfg, package / 'templates' / 'chest' / 'de' / 'truhe.npy'


def normalized_german_screenshot(obs_output, screenshot, destination):
    """Normalize a user-supplied 16:9 screenshot exactly like FVCC does: 1280x720."""
    root, _, _, _ = german_visual_counter_root(obs_output)
    source = Path(screenshot)
    if not source.is_file() or source.stat().st_size > 40 * 1024 * 1024:
        raise ValueError('Screenshot fehlt oder ist zu groß (maximal 40 MB).')
    if source.suffix.lower() not in ('.png', '.jpg', '.jpeg', '.webp', '.bmp'):
        raise ValueError('Bitte ein PNG-/JPG-Bild des echten deutschen Truhenpopups wählen.')
    ffmpeg_root = root / 'runtime' / 'ffmpeg'
    binaries = list(ffmpeg_root.rglob('ffmpeg.exe')) if ffmpeg_root.is_dir() else []
    if not binaries:
        raise FileNotFoundError('Das mit Visual Chest Counter gelieferte ffmpeg.exe fehlt.')
    target = Path(destination)
    proc = _subprocess.run(
        [str(binaries[0]), '-hide_banner', '-loglevel', 'error', '-y',
         '-i', str(source), '-vf', 'scale=1280:720',
         '-frames:v', '1', str(target)],
        capture_output=True, timeout=35,
    )
    if proc.returncode or not target.is_file():
        raise ValueError('Screenshot konnte nicht auf 1280x720 normalisiert werden: '
                         + proc.stderr.decode('utf-8', 'replace')[-250:])
    return target


def german_word_mask(photo, rectangle):
    """Extract only the lavender pixels of the selected *word* (not XP digits).

    PhotoImage is a normalized 1280x720 screenshot; narrow crop must isolate
    one word such as TRUHE, not the whole XP feed or a reward banner.
    Returns a list of rows of 0.0 / 1.0 values, ready for npy encoding.
    """
    if (photo.width(), photo.height()) != (1280, 720):
        raise ValueError('Kalibrierbild muss genau 1280x720 Pixel groß sein.')
    x0, y0, x1, y1 = (int(v) for v in rectangle)
    x0, x1 = sorted((x0, x1))
    y0, y1 = sorted((y0, y1))
    if not (500 <= x0 < x1 <= 1220 and 100 <= y0 < y1 <= 500
            and 6 <= x1 - x0 <= 100 and 4 <= y1 - y0 <= 33):
        raise ValueError('Bitte nur das Truhen-WORT neben dem Fadenkreuz markieren '
                         '(nicht XP-Zahl, ganze Zeile oder Bild).')
    pixels = []
    for y in range(y0, y1):
        row = []
        for x in range(x0, x1):
            rgb = photo.get(x, y)
            if isinstance(rgb, str):
                if rgb.startswith('#'):
                    rgb = tuple(int(rgb[i:i+2], 16) for i in (1, 3, 5))
                else:
                    rgb = tuple(int(p) for p in rgb.split())
            red, green, blue = (int(v) for v in rgb[:3])
            pale = min(red, blue)
            row.append(1.0 if pale > 170 and green < pale - 8 else 0.0)
        pixels.append(row)
    lit = [(y, x) for y, row in enumerate(pixels) for x, value in enumerate(row) if value]
    if not lit:
        raise ValueError('Keine violetten XP-Textpixel im Bereich gefunden. '
                         'Prüfe, ob das Popup im Screenshot sichtbar ist.')
    ylo, yhi = min(y for y, _ in lit), max(y for y, _ in lit)
    xlo, xhi = min(x for _, x in lit), max(x for _, x in lit)
    result = [row[xlo:xhi + 1] for row in pixels[ylo:yhi + 1]]
    h, w = len(result), len(result[0])
    density = sum(sum(row) for row in result) / (h * w)
    if not (6 <= w <= 100 and 4 <= h <= 25 and 0.05 < density < 0.79):
        raise ValueError('Auswahl ist kein brauchbares Wortmuster. '
                         'Markiere nur die violetten Buchstaben TRUHE, '
                         'nicht den gesamten Popup-Bereich.')
    return result


def german_numpy_template(rows):
    """Write a NumPy .npy v1.0 float32 C-order array without adding NumPy to SquadLoot."""
    if not rows or not rows[0] or len(rows) > 30 or len(rows[0]) > 120:
        raise ValueError('Leeres oder zu großes Wortmuster.')
    h, w = len(rows), len(rows[0])
    if any(len(row) != w for row in rows):
        raise ValueError('Nicht-rechteckige Wortvorlage.')
    header = "{'descr': '<f4', 'fortran_order': False, 'shape': (%d, %d), }" % (h, w)
    prefix = b'\x93NUMPY\x01\x00'
    # NPY v1 header including newline is aligned to 16 bytes.
    padding = (-len(prefix) - 2 - len(header.encode('latin1')) - 1) % 16
    header_bytes = (header + ' ' * padding + '\n').encode('latin1')
    raw = b''.join(_struct.pack('<f', float(v)) for row in rows for v in row)
    return prefix + _struct.pack('<H', len(header_bytes)) + header_bytes + raw


def _german_atomic_write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _tempfile.NamedTemporaryFile(dir=path.parent, prefix='.sl-german-',
                                      delete=False) as f:
        name = Path(f.name)
        f.write(data)
    try:
        os.replace(name, path)
    finally:
        name.unlink(missing_ok=True)


def install_german_visual_template(obs_output, matrix):
    """Opt-in, backed-up v0.2.3 source patch, never an automatic upgrade action.

    Does not change the user's config.toml, counts, profiles, or game files.
    If either source file is not exactly recognizable, abort rather than making
    an incompatible partial patch. A subsequent upstream update may remove it.
    """
    root, visual, settings, template = german_visual_counter_root(obs_output)
    visual_text = visual.read_text(encoding='utf-8')
    settings_text = settings.read_text(encoding='utf-8')
    marker_visual = _GERMAN_MARKER in visual_text
    marker_settings = _GERMAN_MARKER in settings_text
    if marker_visual != marker_settings:
        raise ValueError('Nur ein Teil der Deutsch-Anpassung ist installiert. '
                         'Bitte zuerst den ursprünglichen App-Stand wiederherstellen.')
    fresh = not marker_visual
    if fresh:
        if (visual_text.count('CHEST_TEMPLATES = [') != 1 or
                settings_text.count(_FVCC_ORIGINAL_LANGUAGES) != 1 or
                '"id": "de:TRUHE"' in visual_text):
            raise ValueError('Diese Version des Visual Chest Counter wird noch '
                             'nicht unterstützt. Bitte v0.2.3 unverändert verwenden.')
        new_visual = visual_text.replace(
            'CHEST_TEMPLATES = [',
            'CHEST_TEMPLATES = [\n    ' + _GERMAN_MARKER + '\n' + _FVCC_VISUAL_ENTRY)
        new_settings = settings_text.replace(
            _FVCC_ORIGINAL_LANGUAGES, _GERMAN_MARKER + '\n' + _FVCC_DE_CHOICES)
        compile(new_visual, str(visual), 'exec')
        compile(new_settings, str(settings), 'exec')
    else:
        if ('"id": "de:TRUHE"' not in visual_text or
                '("Deutsch (SquadLoot Beta)", ["de"])' not in settings_text):
            raise ValueError('Die vorhandene Deutsch-Anpassung passt nicht zur '
                             'unterstützten Version. Bitte keine Dateien überschreiben.')
        new_visual, new_settings = visual_text, settings_text

    data = german_numpy_template(matrix)
    backup_dir = root / '.squadloot-german-backup'
    backup_visual = backup_dir / 'visual.py'
    backup_settings = backup_dir / 'settings.py'
    if fresh:
        if backup_dir.exists():
            raise ValueError('Es existiert bereits ein Deutsch-Backup. Bitte '
                             'zuerst die Wiederherstellung verwenden.')
        backup_dir.mkdir(mode=0o700)
        _german_atomic_write(backup_visual, visual_text.encode('utf-8'))
        _german_atomic_write(backup_settings, settings_text.encode('utf-8'))
    previous = template.read_bytes() if template.exists() else None
    try:
        _german_atomic_write(template, data)
        if fresh:
            _german_atomic_write(visual, new_visual.encode('utf-8'))
            _german_atomic_write(settings, new_settings.encode('utf-8'))
    except OSError:
        if fresh:
            _german_atomic_write(visual, visual_text.encode('utf-8'))
            _german_atomic_write(settings, settings_text.encode('utf-8'))
        if previous is None:
            template.unlink(missing_ok=True)
        else:
            _german_atomic_write(template, previous)
        raise
    return {'root': str(root), 'width': len(matrix[0]), 'height': len(matrix),
            'fresh': fresh}


def restore_german_visual_template(obs_output):
    """Restore our original v0.2.3 Python files without changing user state."""
    root, visual, settings, template = german_visual_counter_root(obs_output)
    backup_dir = root / '.squadloot-german-backup'
    bvisual = backup_dir / 'visual.py'
    bsettings = backup_dir / 'settings.py'
    if not bvisual.is_file() or not bsettings.is_file():
        raise ValueError('Kein vollständiges SquadLoot-Deutsch-Backup vorhanden.')
    now_visual = visual.read_text(encoding='utf-8')
    now_settings = settings.read_text(encoding='utf-8')
    if _GERMAN_MARKER not in now_visual or _GERMAN_MARKER not in now_settings:
        raise ValueError('Die externe Anwendung wurde inzwischen aktualisiert. '
                         'Alte Python-Dateien dürfen nicht zurückkopiert werden.')
    _german_atomic_write(visual, bvisual.read_bytes())
    _german_atomic_write(settings, bsettings.read_bytes())
    template.unlink(missing_ok=True)
    _shutil.rmtree(backup_dir)
    return str(root)


# ---------------------------------------------------------------------------
# SquadLoot v1.5.4: managed, headless analysis engines.
#
# The regular SquadLoot auto-update remains <4MB. The first Replay scan or
# user-triggered Live start downloads pinned upstream binaries into a PRIVATE
# app-data runtime, checks SHA256, and runs them WITHOUT their separate GUI.
# No player installation, custom executable path or additional app window.
#
# Replay engine: MIT LED-N/Fortnite-ChestCounter v1.4.0, --once --data --demos.
# Visual engine: MIT GabrielGzS/fortnite-visual-chest-counter v0.2.3,
# embedded Python worker, live --gui (machine-readable JSON lines).
# ---------------------------------------------------------------------------
import hashlib as _hashlib
import io as _io
import json as _json
import urllib.request as _urlrequest
import urllib.parse as _urlparse
import zipfile as _zipfile
import stat as _stat
import queue as _queue
import subprocess as _subprocess2
import tempfile as _tempfile2
import shutil as _shutil2

_MANAGED_ROOT = Path(os.environ.get('LOCALAPPDATA') or
                     str(Path.home() / '.local' / 'share')) / 'SquadLoot' / 'engines'
_REPLAY_NAME = 'ChestCounter-v1.4.0'
_VISUAL_NAME = 'VisualCounter-v0.2.3'
_REPLAY_URL = ('https://github.com/LED-N/Fortnite-ChestCounter/releases/'
               'download/v1.4.0/ChestCounter.exe')
_REPLAY_SHA256 = '9da628f09f8e1d8545ad7f34ecb65fee48acd856bcce8c809f1e0eb8a4e5c8c7'
_REPLAY_BYTES = 37959310
_VISUAL_URL = ('https://github.com/GabrielGzS/fortnite-visual-chest-counter/'
               'releases/download/v0.2.3/Fortnite-Visual-Chest-Counter-v0.2.3.zip')
_VISUAL_SHA256 = 'a8c54d53842f640121df6fcf6be331be2941469c80e7880aee6d37cfaafd7e3c'
_VISUAL_BYTES = 155755927
_ALLOWED_REDIRECT_HOSTS = frozenset({
    'github.com', 'release-assets.githubusercontent.com',
    'objects.githubusercontent.com', 'github-releases.githubusercontent.com'
})


def _safe_archive_member(name):
    """Reject archive traversal and dangerous files before unpacking."""
    if not isinstance(name, str) or '\\' in name or '\x00' in name:
        raise ValueError('Komponenten-Archiv: ungültiger Dateiname.')
    segments = name.split('/')
    if (name.startswith('/') or any(part in ('', '.', '..') for part in segments)
            or ':' in segments[0]):
        raise ValueError('Komponenten-Archiv: unsicherer Pfad.')
    return segments


def _managed_fetch(url, expected_sha, expected_size, destination, progress=None):
    """Pin a third-party binary to an exact, published SHA256 and expected size."""
    if os.name != 'nt':
        raise RuntimeError('Die verwalteten Analyse-Komponenten benötigen Windows 10/11.')
    if _urlparse.urlsplit(url).scheme != 'https' or _urlparse.urlsplit(url).hostname != 'github.com':
        raise RuntimeError('Komponenten-Download nur aus dem offiziellen GitHub-Release.')
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    h = _hashlib.sha256()
    written = 0
    try:
        request = _urlrequest.Request(url, headers={'User-Agent': 'SquadLoot/1.5.4'})
        with _urlrequest.urlopen(request, timeout=45) as response, open(destination, 'wb') as out:
            final = _urlparse.urlsplit(response.geturl())
            if final.scheme != 'https' or final.hostname not in _ALLOWED_REDIRECT_HOSTS:
                raise RuntimeError('Komponenten-Download: unerwartete Weiterleitung.')
            while True:
                part = response.read(1024 * 1024)
                if not part:
                    break
                written += len(part)
                if written > expected_size:
                    raise ValueError('Komponenten-Download ist unerwartet groß.')
                h.update(part)
                out.write(part)
                if progress:
                    progress(min(100, int(written * 100 / expected_size)))
        if written != expected_size or h.hexdigest() != expected_sha:
            raise ValueError('Download beschädigt oder SHA256-Prüfung fehlgeschlagen.')
        return destination
    except Exception:
        destination.unlink(missing_ok=True)
        raise


class ManagedComponentStore:
    """Background-installable private runtimes; no changes to updater's file list."""

    def __init__(self, root=None):
        self.root = Path(root) if root else _MANAGED_ROOT
        self._lock = threading.RLock()

    def replay_path(self):
        return self.root / _REPLAY_NAME / 'ChestCounter.exe'

    def visual_root(self):
        return self.root / _VISUAL_NAME

    def visual_python(self):
        return self.visual_root() / 'runtime' / 'python' / 'python.exe'

    def ensure_replay(self, progress=None):
        target = self.replay_path()
        if target.is_file() and target.stat().st_size == _REPLAY_BYTES:
            with target.open('rb') as file:
                digest = _hashlib.file_digest(file, 'sha256').hexdigest()
            if digest == _REPLAY_SHA256:
                return target
        with self._lock:
            if target.is_file() and target.stat().st_size == _REPLAY_BYTES:
                with target.open('rb') as file:
                    digest = _hashlib.file_digest(file, 'sha256').hexdigest()
                if digest == _REPLAY_SHA256:
                    return target
            target.parent.mkdir(parents=True, exist_ok=True)
            with _tempfile2.TemporaryDirectory(prefix='.replay-download-', dir=target.parent) as tmp:
                staged = Path(tmp) / 'ChestCounter.exe'
                _managed_fetch(_REPLAY_URL, _REPLAY_SHA256, _REPLAY_BYTES, staged, progress)
                os.replace(staged, target)
        return target

    @staticmethod
    def unpack_visual_zip(archive, destination):
        """Only runtime/ paths from the verified release; no DLL/EXE outside it."""
        count = 0
        total = 0
        present = set()
        with _zipfile.ZipFile(archive) as z:
            for member in z.infolist():
                if member.is_dir():
                    continue
                name = member.filename
                parts = _safe_archive_member(name)
                # The *official* v0.2.3 GitHub ZIP has a fixed versioned
                # top-level folder; normalize it before applying the allowlist.
                if (parts[0] == 'Fortnite-Visual-Chest-Counter-v0.2.3' and
                        len(parts) > 1):
                    parts = parts[1:]
                if parts[0] != 'runtime':
                    continue
                mode = (member.external_attr >> 16) & 0o170000
                if mode not in (0, 0o100000):
                    raise ValueError('Komponentenarchiv enthält unerlaubten Dateityp.')
                if len(parts) < 3 or parts[1] not in ('python', 'lib', 'ffmpeg'):
                    continue
                normalized_name = '/'.join(parts)
                if normalized_name in present:
                    raise ValueError('Doppelte Datei im Komponentenarchiv.')
                count += 1
                total += member.file_size
                if count > 12000 or member.file_size > 180_000_000 or total > 1_500_000_000:
                    raise ValueError('Komponentenarchiv überschreitet Sicherheitsgrenzen.')
                target = Path(destination).joinpath(*parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                with z.open(member) as src, open(target, 'wb') as dst:
                    _shutil2.copyfileobj(src, dst, 1024 * 1024)
                present.add(normalized_name)
        required = (
            Path(destination) / 'runtime/python/python.exe',
            Path(destination) / 'runtime/lib/fortnite_chest_counter/counter.py',
            Path(destination) / 'runtime/ffmpeg/ffmpeg.exe',
        )
        if any(not p.is_file() for p in required):
            raise ValueError('Bildanalyse-Komponente unvollständig: Python/Detector/FFmpeg fehlt.')

    def ensure_visual(self, progress=None, previous_obs=None):
        root = self.visual_root()
        if self.visual_python().is_file() and (root / '.squadloot-sha256').is_file():
            return root
        with self._lock:
            if self.visual_python().is_file() and (root / '.squadloot-sha256').is_file():
                return root
            self.root.mkdir(parents=True, exist_ok=True)
            with _tempfile2.TemporaryDirectory(prefix='.visual-download-', dir=self.root) as tmp:
                archive = Path(tmp) / 'visual.zip'
                staging = Path(tmp) / 'files'
                staging.mkdir()
                _managed_fetch(_VISUAL_URL, _VISUAL_SHA256, _VISUAL_BYTES,
                               archive, progress)
                self.unpack_visual_zip(archive, staging)
                (staging / '.squadloot-sha256').write_text(_VISUAL_SHA256, encoding='ascii')
                if root.exists():
                    # Only our own runtime folder is ever removed.
                    _shutil2.rmtree(root)
                os.replace(staging, root)
            # Reuse an existing user's real German word template where available.
            if previous_obs:
                try:
                    self.adopt_german_template(previous_obs)
                except (OSError, ValueError):
                    pass  # English detection is still available; no fake German claims.
        return root

    def adopt_german_template(self, previous_obs):
        """Migrate an already user-calibrated DE template from 1.5.3 if valid."""
        previous_obs = Path(previous_obs)
        source = (previous_obs.parent / 'runtime' / 'lib' /
                  'fortnite_chest_counter' / 'templates' / 'chest' / 'de' / 'truhe.npy')
        if not source.is_file() or source.stat().st_size > 100_000:
            return False
        blob = source.read_bytes()
        if blob[:8] != b'\x93NUMPY\x01\x00':
            return False
        # Numpy's data header is deliberately parsed, never executed.
        import ast
        hl = _struct.unpack('<H', blob[8:10])[0]
        header = ast.literal_eval(blob[10:10 + hl].decode('latin1').strip())
        shape = header.get('shape')
        if (header.get('descr') != '<f4' or len(shape) != 2 or
                not (4 <= shape[0] <= 25 and 6 <= shape[1] <= 100) or
                len(blob) != 10 + hl + 4 * shape[0] * shape[1]):
            return False
        floats = _struct.unpack('<%df' % (shape[0] * shape[1]), blob[10 + hl:])
        if any(v not in (0.0, 1.0) for v in floats):
            return False
        matrix = [list(floats[i * shape[1]:(i + 1) * shape[1]])
                  for i in range(shape[0])]
        obs = self.visual_root() / 'obs_output'
        obs.mkdir(parents=True, exist_ok=True)
        install_german_visual_template(obs, matrix)
        return True

    def german_available(self):
        return (self.visual_root() / 'runtime/lib/fortnite_chest_counter/'
                'templates/chest/de/truhe.npy').is_file()


class ManagedReplayEngine:
    """Passive local replay analyzer; starts automatically, even without connection."""

    def __init__(self, core, store=None):
        self.core = core
        self.store = store or ManagedComponentStore()
        self.thread = None
        self._busy = threading.RLock()
        self.last_sig = None
        self.last_attempt = 0.0
        self.status = 'Replays werden automatisch ausgewertet'
        self.error = ''
        self.finished = 0

    def _signature(self):
        directory = Path(self.core.config.get('replay_dir', ''))
        if not directory.is_dir():
            return None
        files = []
        for path in directory.glob('*.replay'):
            try:
                st = path.stat()
                files.append((st.st_mtime_ns, path.name, st.st_size))
            except OSError:
                pass
        if not files:
            return None
        files.sort(reverse=True)
        return tuple(files[:100])

    def scan_once(self, force=False):
        """Run at most one CLI analyzer concurrently; never block GUI thread."""
        # Manual evaluation must wait for the background analyzer; otherwise
        # the UI uploads yesterday's JSON and incorrectly reports success.
        if force:
            acquired = self._busy.acquire(timeout=250)
        else:
            acquired = self._busy.acquire(blocking=False)
        if not acquired:
            if force:
                self.error = 'Replay-Analyse ist noch beschäftigt (Timeout).'
                self.status = self.error
            return False
        try:
            signature = self._signature()
            if not signature:
                self.status = 'Warte auf aufgezeichnete Fortnite-Replays'
                return False
            now = time.monotonic()
            latest_age = time.time() - signature[0][0] / 1e9
            if not force and (signature == self.last_sig or
                              latest_age < 12 or now - self.last_attempt < 25):
                return False
            self.last_attempt = now
            self.status = 'Replay-Analyse wird vorbereitet'
            exe = self.store.ensure_replay()
            datafile = Path(self.core.config.get('data_json') or
                            str(Path(os.getenv('APPDATA') or Path.home()) /
                                'ChestCounter' / 'data.json'))
            datafile.parent.mkdir(parents=True, exist_ok=True)
            cmd = [str(exe), '--once', '--data', str(datafile.parent),
                   '--demos', str(self.core.config.get('replay_dir')), '--lang', 'en']
            flags = getattr(_subprocess2, 'CREATE_NO_WINDOW', 0) if os.name == 'nt' else 0
            result = _subprocess2.run(cmd, stdout=_subprocess2.PIPE,
                                     stderr=_subprocess2.PIPE, timeout=240,
                                     creationflags=flags)
            if result.returncode != 0:
                hint = result.stderr.decode('utf-8', 'replace')[-180:]
                raise RuntimeError(f'Replay-Analyse Exit {result.returncode}: {hint}')
            output = result.stdout.decode('utf-8', 'replace').casefold()
            # ChestCounter exits with code 0 even if a second instance could
            # not acquire its data-folder mutex. In that case nothing was read.
            if any(message in output for message in
                   ('already open', 'déjà ouvert', 'ya está abierto')):
                raise RuntimeError('ChestCounter ist bereits geöffnet. '
                                   'Schließe die alte Instanz und versuche es erneut.')
            self.last_sig = signature
            self.finished += 1
            self.error = ''
            self.status = ('Replay-Scan abgeschlossen – Synchronisierung läuft'
                           if datafile.is_file() else
                           'Replay-Scan beendet – keine auswertbaren Matches exportiert')
            return True
        except Exception as exc:
            self.error = str(exc)[:240]
            self.status = 'Replay-Analyse: ' + self.error
            return False
        finally:
            self._busy.release()

    def loop(self):
        # First pass after startup; subsequent new replay files are picked up.
        while not self.core.stop.is_set():
            self.scan_once()
            self.core.stop.wait(10)

    def start(self):
        if os.name != 'nt':
            return
        if not self.thread or not self.thread.is_alive():
            self.thread = threading.Thread(target=self.loop, daemon=True,
                                           name='SquadLootReplayAnalyzer')
            self.thread.start()



def _best_monitor_for_windows(monitors, windows):
    """Pick upstream FFmpeg's EnumDisplayMonitors index by intersection area."""
    best_index, best_area = 1, 0
    for index, (x, y, width, height) in enumerate(monitors, 1):
        for left, top, right, bottom in windows:
            area = max(0, min(x + width, right) - max(x, left)) * max(
                0, min(y + height, bottom) - max(y, top))
            if area > best_area:
                best_area, best_index = area, index
    return best_index


def list_capture_monitors():
    """Return exactly the Win32 monitor order used by the visual FFmpeg source.

    Index 1..N is intentionally not reordered by primary monitor status.
    """
    if os.name != 'nt':
        return []
    from ctypes import wintypes
    monitors = []
    cb_type = ctypes.WINFUNCTYPE(
        ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p,
        ctypes.POINTER(wintypes.RECT), ctypes.c_void_p)

    @cb_type
    def callback(_monitor, _dc, rect, _data):
        r = rect.contents
        monitors.append((r.left, r.top, r.right - r.left, r.bottom - r.top))
        return 1

    if not ctypes.windll.user32.EnumDisplayMonitors(None, None, callback, None):
        raise OSError('Windows konnte die angeschlossenen Monitore nicht lesen.')
    return monitors


def detect_fortnite_monitor():
    """Use visible Fortnite window geometry only; never inspect game memory."""
    if os.name != 'nt':
        return 1
    try:
        from ctypes import wintypes
        monitors = list_capture_monitors()
        windows = []
        user32 = ctypes.windll.user32
        user32.IsWindowVisible.argtypes = [ctypes.c_void_p]
        user32.IsIconic.argtypes = [ctypes.c_void_p]
        user32.GetWindowTextW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
        user32.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.RECT)]
        cb_type = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)

        @cb_type
        def callback(hwnd, _data):
            if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
                return 1
            title = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, title, 256)
            name = title.value.strip().casefold()
            if name != 'fortnite' and not name.startswith('fortnite '):
                return 1
            rect = wintypes.RECT()
            if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                if rect.right - rect.left >= 480 and rect.bottom - rect.top >= 270:
                    windows.append((rect.left, rect.top, rect.right, rect.bottom))
            return 1

        user32.EnumWindows(callback, None)
        return _best_monitor_for_windows(monitors, windows)
    except (OSError, ValueError, AttributeError):
        return 1


def _ppm_from_bgra(pixels, width, height):
    """Small local-only PPM image for Tkinter; no Pillow/third-party download."""
    width, height = int(width), int(height)
    if not (0 < width <= 1200 and 0 < height <= 800):
        raise ValueError('Ungültige Größe für die Monitorvorschau.')
    if len(pixels) != width * height * 4:
        raise ValueError('Die Bildschirmaufnahme ist unvollständig.')
    result = bytearray(width * height * 3)
    for src in range(0, len(pixels), 4):
        dst = (src // 4) * 3
        result[dst:dst + 3] = pixels[src + 2:src + 3] + pixels[src + 1:src + 2] + pixels[src:src + 1]
    return ('P6\n%d %d\n255\n' % (width, height)).encode('ascii') + result


def capture_monitor_preview(index, max_width=520, max_height=292):
    """Take one manually requested *local* Win32 thumbnail.

    Uses a GDI snapshot, never sends or stores screenshots. Exclusive DirectX
    fullscreen may show black: windowed fullscreen is recommended.
    """
    if os.name != 'nt':
        raise RuntimeError('Die Bildschirmvorschau ist nur unter Windows verfügbar.')
    monitors = list_capture_monitors()
    index = int(index)
    if not 1 <= index <= len(monitors):
        raise ValueError('Ausgewählter Monitor ist nicht mehr angeschlossen.')
    x, y, width, height = monitors[index - 1]
    scale = min(float(max_width) / width, float(max_height) / height, 1.0)
    out_w, out_h = max(1, int(width * scale)), max(1, int(height * scale))
    user32, gdi = ctypes.windll.user32, ctypes.windll.gdi32
    ptr = ctypes.c_void_p
    user32.GetDC.argtypes, user32.GetDC.restype = [ptr], ptr
    user32.ReleaseDC.argtypes = [ptr, ptr]
    gdi.CreateCompatibleDC.argtypes, gdi.CreateCompatibleDC.restype = [ptr], ptr
    gdi.CreateCompatibleBitmap.argtypes = [ptr, ctypes.c_int, ctypes.c_int]
    gdi.CreateCompatibleBitmap.restype = ptr
    gdi.SelectObject.argtypes, gdi.SelectObject.restype = [ptr, ptr], ptr
    gdi.SetStretchBltMode.argtypes = [ptr, ctypes.c_int]
    gdi.StretchBlt.argtypes = [ptr, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        ctypes.c_int, ptr, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        ctypes.c_int, ctypes.c_uint]
    gdi.GetDIBits.argtypes = [ptr, ptr, ctypes.c_uint, ctypes.c_uint,
        ptr, ptr, ctypes.c_uint]
    gdi.DeleteDC.argtypes, gdi.DeleteObject.argtypes = [ptr], [ptr]

    class BitmapInfoHeader(ctypes.Structure):
        _fields_ = [
            ('size', ctypes.c_uint32), ('width', ctypes.c_int32),
            ('height', ctypes.c_int32), ('planes', ctypes.c_uint16),
            ('bits', ctypes.c_uint16), ('compression', ctypes.c_uint32),
            ('image_size', ctypes.c_uint32), ('xres', ctypes.c_int32),
            ('yres', ctypes.c_int32), ('colors', ctypes.c_uint32),
            ('important_colors', ctypes.c_uint32),
        ]

    src_dc = user32.GetDC(None)
    if not src_dc:
        raise OSError('Bildschirmaufnahme: Desktop-Kontext nicht verfügbar.')
    mem_dc = bitmap = old = None
    try:
        mem_dc = gdi.CreateCompatibleDC(src_dc)
        bitmap = gdi.CreateCompatibleBitmap(src_dc, out_w, out_h)
        if not mem_dc or not bitmap:
            raise OSError('Bildschirmaufnahme: Speicherbild konnte nicht angelegt werden.')
        old = gdi.SelectObject(mem_dc, bitmap)
        if not old:
            raise OSError('Bildschirmaufnahme: Grafikobjekt nicht auswählbar.')
        gdi.SetStretchBltMode(mem_dc, 3)
        if not gdi.StretchBlt(mem_dc, 0, 0, out_w, out_h,
                             src_dc, x, y, width, height, 0x00CC0020):
            raise OSError('Windows konnte die Monitorvorschau nicht aufnehmen.')
        # GetDIBits requires the bitmap to be deselected from its memory DC.
        gdi.SelectObject(mem_dc, old)
        old = None
        header = BitmapInfoHeader(
            ctypes.sizeof(BitmapInfoHeader), out_w, -out_h, 1, 32, 0,
            out_w * out_h * 4, 0, 0, 0, 0)
        pixels = ctypes.create_string_buffer(out_w * out_h * 4)
        if not gdi.GetDIBits(src_dc, bitmap, 0, out_h,
                             pixels, ctypes.byref(header), 0):
            raise OSError('Windows konnte das Vorschaubild nicht auslesen.')
        return _ppm_from_bgra(pixels.raw, out_w, out_h)
    finally:
        if old and mem_dc:
            gdi.SelectObject(mem_dc, old)
        if bitmap:
            gdi.DeleteObject(bitmap)
        if mem_dc:
            gdi.DeleteDC(mem_dc)
        user32.ReleaseDC(None, src_dc)


class ManagedLiveEngine:
    """One button controls a private, headless visual detector subprocess."""

    def __init__(self, core, store=None):
        self.core = core
        self.store = store or ManagedComponentStore()
        self._stop = threading.Event()
        self.thread = None
        self.process = None
        self.state = 'Aus'
        self.error = ''
        self.started = False
        self.count = 0
        self.certain = 0
        self.last_raw = 0
        self.round_id = None
        self.last_event_at = None
        self._lock = threading.RLock()
        self.legacy_obs = core.config.get('visual_counter_dir', '')
        self.monitor = 1
        self.last_source = ''
        self.warning = ''

    @property
    def running(self):
        return self.state not in ('Aus', 'Fehler', 'Beendet')

    def feed_message(self, event):
        """Pure counter policy: APPROX includes CERTAIN, never double-count."""
        if not isinstance(event, dict) or event.get('type') not in ('counts', 'event'):
            return False
        if event.get('type') == 'event' and event.get('verdict') == 'rejected':
            return False
        approx = event.get('approx')
        certain = event.get('certain', 0)
        if type(approx) is not int or type(certain) is not int:
            return False
        if not (0 <= certain <= approx <= 1000000):
            return False
        with self._lock, self.core.lock:
            if self.round_id != self.core.round_id:
                self.round_id = self.core.round_id
                # Preserve the last raw total: the first event after the
                # round boundary can already be the NEW round's first chest.
                # Discarding that event would silently miss one chest.
                self.count = self.certain = 0
                self.core.vision = 0
                self.core.last_live = 0.0
            if approx < self.last_raw:
                self.last_raw = approx  # external reset, never subtract counted chests
                return False
            delta = approx - self.last_raw
            self.last_raw = approx
            if delta:
                self.count += delta
                self.core.vision = self.count
                self.core.last_live = 0.0
                self.last_event_at = time.monotonic()
            self.certain = max(self.certain, certain)
            return bool(delta)

    def start(self):
        if self.running:
            return
        if os.name != 'nt':
            raise RuntimeError('Live-Bildanalyse benötigt Windows.')
        self._stop.clear()
        self.state = 'Einrichtung'
        self.error = ''
        self.count = self.certain = self.last_raw = 0
        self.round_id = self.core.round_id
        with self.core.lock:
            self.core.vision = 0
            self.core.last_live = 0.0
        self.thread = threading.Thread(target=self._run, daemon=True,
                                       name='SquadLootManagedLive')
        self.thread.start()

    def _run(self):
        try:
            def progress(value):
                self.state = 'Live-Modul wird eingerichtet · %d %%' % value

            root = self.store.ensure_visual(progress=progress,
                                            previous_obs=self.legacy_obs)
            if self._stop.is_set():
                return
            german = self.store.german_available()
            # EN is always supported by the pinned upstream templates. DE
            # additionally needs an actual calibrated TRUHE image; without
            # one only its language-independent object cue can contribute.
            languages = '["en", "de"]' if german else '["en"]'
            config = root / 'squadloot-live.toml'
            config.write_text(
                '[detector]\n'
                'languages = ' + languages + '\n'
                'process_fps = 15\n'
                'count_interaction_object_as_approx = true\n'
                '[logging]\n'
                'enabled = false\n'
                '[capture]\n'
                'mode = "off"\n', encoding='utf-8')
            python = self.store.visual_python()
            env = os.environ.copy()
            env['PATH'] = (str(root / 'runtime' / 'ffmpeg') + os.pathsep +
                           env.get('PATH', ''))
            env['PYTHONUNBUFFERED'] = '1'
            flags = getattr(_subprocess2, 'CREATE_NO_WINDOW', 0) if os.name == 'nt' else 0
            override = self.core.config.get('live_monitor', 'auto')
            try:
                monitor = int(override)
                if not 1 <= monitor <= 8:
                    raise ValueError('Monitor außerhalb von 1..8')
            except (TypeError, ValueError):
                monitor = detect_fortnite_monitor()
            self.monitor = monitor
            cmd = [str(python), '-m', 'fortnite_chest_counter',
                   'live', '--config', str(config),
                   '--source', 'desktop', '--monitor', str(monitor),
                   '--gui', '--reset',
                   '--state', str(root / 'state' / 'squadloot-live.json'),
                   '--obs-dir', str(root / 'obs_output')]
            self.state = f'Bildanalyse verbindet Monitor {monitor}'
            error_log = root / 'squadloot-live-errors.log'
            connected = False
            # Save stderr instead of discarding the only actionable reason
            # for missing FFmpeg, an invalid monitor or a runtime crash.
            with error_log.open('wb') as stderr:
                self.process = _subprocess2.Popen(
                    cmd, stdin=_subprocess2.PIPE, stdout=_subprocess2.PIPE,
                    stderr=stderr, cwd=str(root), env=env, creationflags=flags)
                self.started = True
                for raw in self.process.stdout:
                    if self._stop.is_set():
                        break
                    if len(raw) > 20000:
                        continue
                    try:
                        event = _json.loads(raw.decode('utf-8', 'replace'))
                    except ValueError:
                        continue
                    if not isinstance(event, dict):
                        continue
                    kind = event.get('type')
                    if kind in ('event', 'counts'):
                        self.feed_message(event)
                    elif kind == 'error':
                        self.error = str(event.get('text', ''))[:200]
                        self.state = 'Live-Erkennungsfehler'
                    elif kind == 'warn':
                        self.warning = str(event.get('text', ''))[:200]
                    elif kind == 'connected':
                        connected = True
                        self.last_source = str(event.get('source', ''))[:120]
                        self.state = f'Live-Tracking aktiv · Monitor {monitor}'
                exit_code = self.process.wait(timeout=10)
            if not self._stop.is_set():
                if exit_code or not connected:
                    detail = error_log.read_bytes()[-1200:].decode(
                        'utf-8', 'replace').strip()[-250:]
                    reason = (f'Bildanalyse beendet (Code {exit_code})'
                              if exit_code else
                              'Bildanalyse ohne Monitor-Verbindung beendet')
                    raise RuntimeError(reason + (': ' + detail if detail else '.'))
                self.state = 'Beendet'
        except Exception as exc:
            self.error = str(exc)[:240]
            self.state = 'Fehler'
        finally:
            if self.process is not None and self.process.poll() is None:
                try:
                    self.process.terminate()
                    self.process.wait(timeout=3)
                except (OSError, _subprocess2.TimeoutExpired):
                    try:
                        self.process.kill()
                    except OSError:
                        pass
            self.process = None
            self.started = False
            if self._stop.is_set():
                self.state = 'Aus'

    def reset_counts(self):
        """Reset SquadLoot's provisional totals, not the external process."""
        with self._lock, self.core.lock:
            self.count = self.certain = 0
            self.core.vision = 0
            self.core.last_live = 0.0

    def stop(self):
        self._stop.set()
        p = self.process
        if p and p.poll() is None:
            try:
                p.stdin.write(b'stop\n')
                p.stdin.flush()
            except (BrokenPipeError, OSError):
                pass
        self.state = 'Aus'
