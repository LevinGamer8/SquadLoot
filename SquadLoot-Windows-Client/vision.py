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
                if engine.update(score, pressed, time.monotonic()):
                    self.core.adjust('vision', +1)
                    self.count += 1
                self.perf_ms = (time.perf_counter() - started) * 1000
        except Exception as exc:
            self.error = str(exc)[:180]
            self.state = 'Fehler'
