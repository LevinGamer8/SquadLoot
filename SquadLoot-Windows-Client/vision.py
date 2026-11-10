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
