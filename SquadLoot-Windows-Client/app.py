#!/usr/bin/env python3
"""SquadLoot desktop client.

A premium dark-mode gaming companion UI built on the Python standard library
only (Tkinter + Canvas).  No third-party GUI framework is required, so the
installer, the ZIP auto-updater and the startup/memory budget stay unchanged
while SquadLoot runs next to Fortnite.

Everything the user sees is drawn by the small design system in this module:
rounded surfaces, vector line icons, stateful controls and a six-section
navigation.  All network work happens on background threads; the Tk thread only
reads a thread-safe snapshot from client_core.Core.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import math
import os
import queue
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, font as tkfont, messagebox

from client_core import (Core, CONFIG, read_json, sync_once, validate_url)
from update_manager import current_version, check_and_stage, log_error
from vision import ManagedLiveEngine

# --------------------------------------------------------------------------
# Display scaling
# --------------------------------------------------------------------------
# Resolved before the first widget exists so every pixel constant below is
# already scaled.  Fonts use pixel sizes too, which keeps type and layout in
# step on 125 % / 150 % / 200 % Windows displays.


def detect_scale() -> float:
    if os.name == 'nt':
        for call in ('GetDpiForSystem', 'GetDpiForWindow'):
            try:
                dpi = getattr(ctypes.windll.user32, call)()
                if dpi:
                    return min(2.0, max(1.0, round(dpi / 96.0, 2)))
            except (AttributeError, OSError):
                continue
    try:
        override = float(os.getenv('SQUADLOOT_UI_SCALE', '') or 0)
        if override:
            return min(2.0, max(1.0, override))
    except ValueError:
        pass
    return 1.0


def enable_dpi_awareness() -> None:
    if os.name != 'nt':
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


enable_dpi_awareness()
SCALE = detect_scale()


def px(value: float) -> int:
    """Scale a design pixel to a device pixel."""
    return max(1, int(round(value * SCALE)))


# --------------------------------------------------------------------------
# Design tokens
# --------------------------------------------------------------------------
class T:
    """Single source of truth for colour, radius and spacing."""

    # Layered backgrounds, darkest to lightest.
    BG = '#080B12'
    RAIL = '#0B0F18'
    SURFACE = '#111724'
    SURFACE_2 = '#161E2E'
    SURFACE_3 = '#1C2638'
    FIELD = '#0C111B'

    # Hairlines.
    LINE = '#202B3D'
    LINE_SOFT = '#1A2333'
    LINE_STRONG = '#2B3850'

    # Type.
    TEXT = '#E9EEF8'
    DIM = '#97A3B8'
    MUTE = '#64718A'

    # Accents, used sparingly.
    ACCENT = '#5B78F0'
    ACCENT_HI = '#7A92FF'
    ACCENT_DEEP = '#38489C'
    CYAN = '#38BDF8'
    OK = '#34D399'
    WARN = '#F0B429'
    BAD = '#F2787C'
    VIOLET = '#A78BFA'

    # Translucent-looking tints (pre-blended against SURFACE).
    TINT_ACCENT = '#1B2444'
    TINT_CYAN = '#13293C'
    TINT_OK = '#12302A'
    TINT_WARN = '#2E2718'
    TINT_BAD = '#301C22'
    TINT_VIOLET = '#241F3D'

    # Radii.
    R_CARD = px(14)
    R_CTRL = px(10)
    R_CHIP = px(999)
    R_TILE = px(11)

    # Spacing scale.
    S1, S2, S3, S4, S5, S6, S7 = px(4), px(8), px(12), px(16), px(20), px(24), px(32)

    # Fixed metrics.
    SIDEBAR = px(236)
    TOPBAR = px(74)
    STATUSBAR = px(30)
    BTN_H = px(36)
    BTN_H_SM = px(30)
    FIELD_H = px(34)
    NAV_H = px(40)
    SCROLLW = px(10)


_FAMILY_CACHE: list[str] = []


def family() -> str:
    """Segoe UI on Windows; a close sans elsewhere so screenshots match."""
    if _FAMILY_CACHE:
        return _FAMILY_CACHE[0]
    chosen = 'Segoe UI'
    try:
        available = {name.lower() for name in tkfont.families()}
        for candidate in ('Segoe UI', 'Segoe UI Variable Text', 'Inter',
                          'Noto Sans', 'DejaVu Sans', 'Liberation Sans', 'Arial'):
            if candidate.lower() in available:
                chosen = candidate
                break
    except tk.TclError:
        pass
    _FAMILY_CACHE.append(chosen)
    return chosen


def font(size: int = 13, weight: str = 'normal'):
    """Pixel-sized font tuple; `size` is a design pixel."""
    return (family(), -px(size), weight)


# --------------------------------------------------------------------------
# Canvas primitives
# --------------------------------------------------------------------------
def round_points(x1, y1, x2, y2, radius, steps=7):
    """True rounded-rectangle outline (real quarter arcs, not a spline guess)."""
    r = max(0.0, min(float(radius), (x2 - x1) / 2.0, (y2 - y1) / 2.0))
    if r <= 0.5:
        return [x1, y1, x2, y1, x2, y2, x1, y2]
    pts = []
    corners = ((x2 - r, y2 - r, 0), (x1 + r, y2 - r, 90),
               (x1 + r, y1 + r, 180), (x2 - r, y1 + r, 270))
    for cx, cy, start in corners:
        for i in range(steps + 1):
            a = math.radians(start + 90.0 * i / steps)
            pts.extend((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def round_rect(canvas, x1, y1, x2, y2, radius, fill, outline=None, width=1, tags=None):
    pts = round_points(x1, y1, x2, y2, radius)
    return canvas.create_polygon(
        pts, fill=fill, outline=outline or fill, width=width,
        joinstyle='round', tags=tags or ())


def mix(color_a: str, color_b: str, amount: float) -> str:
    """Blend two #rrggbb colours; amount 0 -> a, 1 -> b."""
    a = [int(color_a[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(color_b[i:i + 2], 16) for i in (1, 3, 5)]
    out = [max(0, min(255, round(x + (y - x) * amount))) for x, y in zip(a, b)]
    return '#%02x%02x%02x' % tuple(out)


# --------------------------------------------------------------------------
# Vector icon set
# --------------------------------------------------------------------------
# Line art in a 24x24 design box, drawn with canvas primitives so the client
# needs no image files and stays crisp at any display scaling.
# Shapes: ('p', points, closed) polyline, ('o', bbox) ellipse outline,
#         ('d', bbox) filled dot, ('a', bbox+start+extent) arc.

ICONS: dict[str, list] = {
    'grid': [('p', [3.5, 3.5, 10.5, 3.5, 10.5, 10.5, 3.5, 10.5], True),
             ('p', [13.5, 3.5, 20.5, 3.5, 20.5, 10.5, 13.5, 10.5], True),
             ('p', [3.5, 13.5, 10.5, 13.5, 10.5, 20.5, 3.5, 20.5], True),
             ('p', [13.5, 13.5, 20.5, 13.5, 20.5, 20.5, 13.5, 20.5], True)],
    'target': [('o', [3, 3, 21, 21]), ('o', [8.5, 8.5, 15.5, 15.5]),
               ('d', [10.8, 10.8, 13.2, 13.2])],
    'clock': [('o', [3, 3, 21, 21]), ('p', [12, 6.8, 12, 12.4, 16.2, 14.6], False)],
    'users': [('o', [6.2, 3.4, 13.8, 11.0]),
              ('p', [3, 20.5, 3, 17.6, 5.6, 14.6, 14.4, 14.6, 17, 17.6, 17, 20.5], False),
              ('o', [15.6, 4.6, 21.2, 10.2]),
              ('p', [19, 14.6, 20.4, 14.6, 22, 16.6, 22, 20.5], False)],
    'gear': [('o', [5.2, 5.2, 18.8, 18.8]), ('o', [9.4, 9.4, 14.6, 14.6]),
             ('p', [12, 2.6, 12, 5.4], False), ('p', [12, 18.6, 12, 21.4], False),
             ('p', [2.6, 12, 5.4, 12], False), ('p', [18.6, 12, 21.4, 12], False),
             ('p', [5.6, 5.6, 7.6, 7.6], False), ('p', [16.4, 16.4, 18.4, 18.4], False),
             ('p', [18.4, 5.6, 16.4, 7.6], False), ('p', [7.6, 16.4, 5.6, 18.4], False)],
    'download': [('p', [12, 3, 12, 15.4], False), ('p', [7.6, 11, 12, 15.4, 16.4, 11], False),
                 ('p', [4, 15.8, 4, 20.4, 20, 20.4, 20, 15.8], False)],
    'chest': [('p', [4, 11, 4, 8.2, 6.4, 5.6, 17.6, 5.6, 20, 8.2, 20, 11], False),
              ('p', [4, 11, 20, 11, 20, 20, 4, 20], True),
              ('p', [4, 14.2, 20, 14.2], False),
              ('p', [10.4, 11, 13.6, 11, 13.6, 16, 10.4, 16], True)],
    'ammo': [('p', [4, 8, 12, 4, 20, 8, 20, 17, 12, 21, 4, 17], True),
             ('p', [4, 8, 12, 12.2, 20, 8], False), ('p', [12, 12.2, 12, 21], False)],
    'food': [('o', [5.6, 8.4, 18.4, 20.8]), ('p', [12, 8.4, 12, 4.6], False),
             ('p', [12, 6.0, 15.4, 3.4, 16.6, 6.4, 13.2, 7.6], True)],
    'burst': [('d', [10.4, 10.4, 13.6, 13.6]),
              ('p', [12, 2.6, 12, 7.2], False), ('p', [12, 16.8, 12, 21.4], False),
              ('p', [2.6, 12, 7.2, 12], False), ('p', [16.8, 12, 21.4, 12], False),
              ('p', [5.4, 5.4, 8.6, 8.6], False), ('p', [15.4, 15.4, 18.6, 18.6], False),
              ('p', [18.6, 5.4, 15.4, 8.6], False), ('p', [8.6, 15.4, 5.4, 18.6], False)],
    'gem': [('p', [12, 3, 20.4, 9.4, 12, 21, 3.6, 9.4], True),
            ('p', [3.6, 9.4, 20.4, 9.4], False),
            ('p', [12, 3, 8.4, 9.4, 12, 21], False), ('p', [12, 3, 15.6, 9.4, 12, 21], False)],
    'check': [('p', [5, 12.8, 9.8, 17.6, 19, 6.4], False)],
    'bolt': [('p', [13.4, 2.4, 5.4, 13.6, 11, 13.6, 10.2, 21.6, 18.6, 10, 13, 10], True)],
    'signal': [('d', [10.8, 17.4, 13.2, 19.8]),
               ('a', [7.6, 13.8, 16.4, 22.6, 30, 120]),
               ('a', [3.8, 10.0, 20.2, 26.4, 35, 110]),
               ('a', [0.2, 6.4, 23.8, 30.0, 40, 100])],
    'plus': [('p', [12, 5.4, 12, 18.6], False), ('p', [5.4, 12, 18.6, 12], False)],
    'minus': [('p', [5.4, 12, 18.6, 12], False)],
    'refresh': [('a', [4, 4, 20, 20, 35, 270]),
                ('d', [16.0, 2.4, 21.2, 7.6])],
    'folder': [('p', [3.2, 19.6, 3.2, 5.4, 9.4, 5.4, 11.6, 8.4, 20.8, 8.4, 20.8, 19.6], True)],
    'shield': [('p', [12, 2.8, 20, 6.0, 20, 12.0, 12, 21.2, 4, 12.0, 4, 6.0], True)],
    'eye': [('p', [2.4, 12, 7.2, 6.6, 16.8, 6.6, 21.6, 12, 16.8, 17.4, 7.2, 17.4], True),
            ('o', [9, 9, 15, 15])],
    'eye_off': [('p', [2.4, 12, 7.2, 6.6, 16.8, 6.6, 21.6, 12, 16.8, 17.4, 7.2, 17.4], True),
                ('p', [4, 20.4, 20, 3.6], False)],
    'external': [('p', [13.6, 3.6, 20.4, 3.6, 20.4, 10.4], False),
                 ('p', [20.4, 3.6, 11.2, 12.8], False),
                 ('p', [17, 13.6, 17, 20.4, 3.6, 20.4, 3.6, 7, 10.4, 7], False)],
    'key': [('o', [3, 8, 13, 18]), ('p', [11.4, 11.6, 21.4, 11.6], False),
            ('p', [17.4, 11.6, 17.4, 15.4], False), ('p', [20.4, 11.6, 20.4, 14.4], False)],
    'user': [('o', [8, 3.2, 16, 11.2]),
             ('p', [4, 21, 4, 18, 7, 14.8, 17, 14.8, 20, 18, 20, 21], False)],
    'cloud': [('p', [7, 18.4, 18, 18.4], False),
              ('a', [3.4, 10.0, 13.0, 19.6, 10, 200]),
              ('a', [9.6, 5.6, 20.6, 16.6, 320, 210])],
    'power': [('p', [12, 3.2, 12, 11.6], False), ('a', [4.6, 5.2, 19.4, 20.0, 230, 260])],
    'stop': [('p', [7.4, 7.4, 16.6, 7.4, 16.6, 16.6, 7.4, 16.6], True)],
    'play': [('p', [8.4, 5.6, 18.4, 12, 8.4, 18.4], True)],
    'sliders': [('p', [3.4, 7.4, 20.6, 7.4], False), ('p', [3.4, 16.6, 20.6, 16.6], False),
                ('d', [7.4, 4.8, 12.0, 9.4]), ('d', [13.6, 14.0, 18.2, 18.6])],
    'spark': [('p', [12, 3.2, 14.2, 9.8, 20.8, 12, 14.2, 14.2, 12, 20.8, 9.8, 14.2,
                     3.2, 12, 9.8, 9.8], True)],
    'lock': [('p', [4.6, 10.6, 19.4, 10.6, 19.4, 20.4, 4.6, 20.4], True),
             ('a', [7.4, 3.4, 16.6, 12.6, 0, 180]), ('d', [10.8, 14.2, 13.2, 16.6])],
    'unlock': [('p', [4.6, 10.6, 19.4, 10.6, 19.4, 20.4, 4.6, 20.4], True),
               ('a', [7.4, 3.4, 16.6, 12.6, 90, 90]), ('d', [10.8, 14.2, 13.2, 16.6])],
    'layout': [('p', [2.8, 4.6, 21.2, 4.6, 21.2, 19.4, 2.8, 19.4], True),
               ('p', [5.8, 8.0, 12.4, 8.0, 12.4, 11.4, 5.8, 11.4], True),
               ('p', [5.8, 14.6, 15.4, 14.6], False)],
    'film': [('p', [3.2, 5.6, 20.8, 5.6, 20.8, 18.4, 3.2, 18.4], True),
             ('p', [3.2, 10.0, 20.8, 10.0], False), ('p', [3.2, 14.0, 20.8, 14.0], False),
             ('p', [8.0, 5.6, 8.0, 18.4], False), ('p', [16.0, 5.6, 16.0, 18.4], False)],
}


# Names requested but not defined; the UI smoke test asserts this stays empty.
UNKNOWN_ICONS: set[str] = set()


def draw_icon(canvas, name, cx, cy, size, color, width=None, tags=None):
    """Render an icon centred on (cx, cy) inside a `size` box."""
    shapes = ICONS.get(name)
    if not shapes:
        UNKNOWN_ICONS.add(name)
        return
    k = size / 24.0
    stroke = width if width is not None else max(1.0, round(size / 13.0, 2))
    ox, oy = cx - size / 2.0, cy - size / 2.0
    tags = tags or ()

    def sx(v):
        return ox + v * k

    for shape in shapes:
        kind = shape[0]
        if kind == 'p':
            pts = [sx(v) if i % 2 == 0 else oy + v * k for i, v in enumerate(shape[1])]
            if shape[2]:
                pts = pts + pts[:2]
            canvas.create_line(*pts, fill=color, width=stroke, capstyle='round',
                               joinstyle='round', tags=tags)
        elif kind == 'o':
            x1, y1, x2, y2 = shape[1]
            canvas.create_oval(sx(x1), oy + y1 * k, sx(x2), oy + y2 * k,
                               outline=color, width=stroke, tags=tags)
        elif kind == 'd':
            x1, y1, x2, y2 = shape[1]
            canvas.create_oval(sx(x1), oy + y1 * k, sx(x2), oy + y2 * k,
                               fill=color, outline=color, tags=tags)
        elif kind == 'a':
            x1, y1, x2, y2, start, extent = shape[1]
            canvas.create_arc(sx(x1), oy + y1 * k, sx(x2), oy + y2 * k,
                              start=start, extent=extent, style='arc',
                              outline=color, width=stroke, tags=tags)


def draw_logo(canvas, cx, cy, size):
    """SquadLoot mark: a faceted loot crystal inside a soft accent plate."""
    half = size / 2.0
    round_rect(canvas, cx - half, cy - half, cx + half, cy + half,
               size * 0.30, T.TINT_ACCENT, T.ACCENT_DEEP, 1)
    s = size * 0.60
    draw_icon(canvas, 'gem', cx, cy, s, T.ACCENT_HI, width=max(1.2, s / 11.0))


# --------------------------------------------------------------------------
# Widgets
# --------------------------------------------------------------------------
class Card(tk.Frame):
    """Rounded surface. Put content into `.body`."""

    def __init__(self, parent, fill=T.SURFACE, border=T.LINE, pad=None,
                 radius=None, bg=None, accent=None):
        bg = bg or parent.cget('bg')
        super().__init__(parent, bg=bg, bd=0, highlightthickness=0)
        self.fill, self.border, self.accent = fill, border, accent
        self.radius = T.R_CARD if radius is None else radius
        self.back = tk.Canvas(self, bg=bg, bd=0, highlightthickness=0)
        self.back.place(x=0, y=0, relwidth=1, relheight=1)
        pad = T.S5 if pad is None else pad
        self.body = tk.Frame(self, bg=fill, bd=0, highlightthickness=0)
        self.body.pack(fill='both', expand=True, padx=max(pad, self.radius), pady=pad)
        self._size = (0, 0)
        self.bind('<Configure>', self._paint)

    def _paint(self, _event=None):
        w, h = self.winfo_width(), self.winfo_height()
        if (w, h) == self._size or w < 8 or h < 8:
            return
        self._size = (w, h)
        self.back.delete('all')
        round_rect(self.back, 1, 1, w - 1, h - 1, self.radius, self.fill, self.border)
        if self.accent:
            # A 2px accent cap along the top edge, clipped to the card radius.
            r = self.radius
            self.back.create_line(r + px(2), px(2.5), w - r - px(2), px(2.5),
                                  fill=self.accent, width=px(2), capstyle='round')


class Button(tk.Canvas):
    """Rounded action with icon support, hover / press / focus / disabled states."""

    VARIANTS = {
        'primary': (T.ACCENT, T.ACCENT_HI, T.ACCENT_DEEP, '#FFFFFF'),
        'secondary': (T.SURFACE_3, '#243049', T.LINE_STRONG, T.TEXT),
        'ghost': (None, T.SURFACE_2, T.LINE, T.DIM),
        'danger': (T.TINT_BAD, '#3B2229', '#51323A', T.BAD),
        'success': (T.TINT_OK, '#163A32', '#1F5347', T.OK),
    }

    def __init__(self, parent, label='', command=None, variant='secondary',
                 icon=None, width=None, height=None, bg=None, small=False, tip=''):
        bg = bg or parent.cget('bg')
        self._variant = variant
        self._label, self._icon, self._tip = label, icon, tip
        self._command = command or (lambda: None)
        self._hover = self._press = self._focus = False
        self._disabled = False
        self._h = height or (T.BTN_H_SM if small else T.BTN_H)
        self._fontsize = 12 if small else 13
        w = width or self._natural_width()
        super().__init__(parent, width=w, height=self._h, bg=bg, bd=0,
                         highlightthickness=0, cursor='hand2', takefocus=1)
        self.bind('<Configure>', lambda e: self._paint())
        self.bind('<Enter>', lambda e: self._set('_hover', True))
        self.bind('<Leave>', lambda e: (self._set('_press', False), self._set('_hover', False)))
        self.bind('<ButtonPress-1>', lambda e: self._set('_press', True))
        self.bind('<ButtonRelease-1>', self._release)
        self.bind('<FocusIn>', lambda e: self._set('_focus', True))
        self.bind('<FocusOut>', lambda e: self._set('_focus', False))
        self.bind('<Return>', lambda e: self.invoke())
        self.bind('<space>', lambda e: self.invoke())
        self._paint()

    def _natural_width(self):
        try:
            text_w = tkfont.Font(font=font(self._fontsize, 'bold')).measure(self._label)
        except tk.TclError:
            text_w = int(len(self._label) * px(7.2))
        pad = px(30 if not self._label else 26)
        return int(text_w + pad + (px(24) if self._icon else 0))

    def _set(self, attr, value):
        if getattr(self, attr) != value:
            setattr(self, attr, value)
            self._paint()

    def _release(self, event):
        was = self._press
        self._set('_press', False)
        if was and 0 <= event.x <= self.winfo_width() and 0 <= event.y <= self.winfo_height():
            self.invoke()

    def invoke(self):
        if not self._disabled:
            self.focus_set()
            self._command()

    def set_label(self, label, icon=False):
        self._label = label
        if icon is not False:
            self._icon = icon
        self._paint()

    def set_enabled(self, enabled: bool):
        self._set('_disabled', not enabled)
        self.configure(cursor='hand2' if enabled else 'arrow')

    def configure(self, cnf=None, **kw):
        if 'state' in kw:
            self._disabled = kw.pop('state') == 'disabled'
            self._paint()
        return super().configure(cnf, **kw)

    config = configure

    def _paint(self):
        self.delete('all')
        w, h = max(8, self.winfo_width()), max(8, self.winfo_height())
        base, hover, border, text = self.VARIANTS[self._variant]
        parent_bg = self.cget('bg')
        base = base or parent_bg
        fill = base
        if self._disabled:
            fill, text, border = mix(parent_bg, T.SURFACE_2, .6), T.MUTE, T.LINE_SOFT
        elif self._press:
            fill = mix(hover, '#000000', .18)
        elif self._hover:
            fill = hover
        round_rect(self, 1, 1, w - 1, h - 1, T.R_CTRL, fill, border)
        if self._focus and not self._disabled:
            round_rect(self, 2.5, 2.5, w - 2.5, h - 2.5, T.R_CTRL - px(1),
                       '', T.ACCENT_HI, px(1))
        isize = px(15)
        if self._icon and self._label:
            try:
                tw = tkfont.Font(font=font(self._fontsize, 'bold')).measure(self._label)
            except tk.TclError:
                tw = int(len(self._label) * px(7.2))
            total = isize + px(7) + tw
            x = (w - total) / 2
            draw_icon(self, self._icon, x + isize / 2, h / 2, isize, text)
            self.create_text(x + isize + px(7), h / 2 + px(.5), text=self._label,
                             anchor='w', fill=text, font=font(self._fontsize, 'bold'))
        elif self._icon:
            draw_icon(self, self._icon, w / 2, h / 2, isize, text)
        else:
            self.create_text(w / 2, h / 2 + px(.5), text=self._label, fill=text,
                             font=font(self._fontsize, 'bold'))


class IconButton(tk.Canvas):
    """Square, quiet control used in headers and field rows."""

    def __init__(self, parent, icon, command=None, size=None, bg=None,
                 tone=T.DIM, tip=''):
        bg = bg or parent.cget('bg')
        self.size = size or T.BTN_H
        self.icon, self.tone, self.tip = icon, tone, tip
        self._command = command or (lambda: None)
        self._hover = self._press = False
        super().__init__(parent, width=self.size, height=self.size, bg=bg, bd=0,
                         highlightthickness=0, cursor='hand2', takefocus=1)
        self.bind('<Enter>', lambda e: self._set(True, self._press))
        self.bind('<Leave>', lambda e: self._set(False, False))
        self.bind('<ButtonPress-1>', lambda e: self._set(self._hover, True))
        self.bind('<ButtonRelease-1>', self._release)
        self.bind('<Return>', lambda e: self._command())
        self._paint()

    def _set(self, hover, press):
        if (hover, press) != (self._hover, self._press):
            self._hover, self._press = hover, press
            self._paint()

    def _release(self, event):
        was = self._press
        self._set(self._hover, False)
        if was and 0 <= event.x <= self.winfo_width() and 0 <= event.y <= self.winfo_height():
            self._command()

    def set_icon(self, icon, tone=None):
        self.icon = icon
        if tone:
            self.tone = tone
        self._paint()

    def _paint(self):
        self.delete('all')
        s = self.size
        if self._hover or self._press:
            round_rect(self, 1, 1, s - 1, s - 1, T.R_CTRL,
                       T.SURFACE_3 if self._press else T.SURFACE_2, T.LINE)
        draw_icon(self, self.icon, s / 2, s / 2, px(16),
                  T.TEXT if self._hover else self.tone)


class Pill(tk.Canvas):
    """Compact status chip: optional leading dot or icon plus a short label."""

    def __init__(self, parent, text='', tone=T.DIM, tint=T.SURFACE_2, dot=True,
                 icon=None, bg=None, size=11):
        bg = bg or parent.cget('bg')
        self._text, self._tone, self._tint = text, tone, tint
        self._dot, self._icon, self._size = dot, icon, size
        super().__init__(parent, bg=bg, bd=0, highlightthickness=0, height=px(22))
        self._paint()

    def set(self, text, tone=None, tint=None, dot=None, icon=False):
        self._text = text
        if tone:
            self._tone = tone
        if tint:
            self._tint = tint
        if dot is not None:
            self._dot = dot
        if icon is not False:
            self._icon = icon
        self._paint()

    def _paint(self):
        self.delete('all')
        f = font(self._size, 'bold')
        try:
            tw = tkfont.Font(font=f).measure(self._text)
        except tk.TclError:
            tw = int(len(self._text) * px(6.4))
        lead = px(14) if (self._dot or self._icon) else 0
        h = px(22)
        w = int(tw + lead + px(20))
        self.configure(width=w, height=h)
        round_rect(self, .5, .5, w - .5, h - .5, h / 2, self._tint,
                   mix(self._tint, self._tone, .28))
        x = px(10)
        if self._icon:
            draw_icon(self, self._icon, x + px(5), h / 2, px(11), self._tone)
            x += px(14)
        elif self._dot:
            r = px(3)
            self.create_oval(x, h / 2 - r, x + 2 * r, h / 2 + r,
                             fill=self._tone, outline=self._tone)
            x += px(14)
        self.create_text(x, h / 2 + px(.5), text=self._text, anchor='w',
                         fill=self._tone, font=f)


class Meter(tk.Canvas):
    """Thin rounded progress track used for squad contribution and downloads."""

    def __init__(self, parent, tone=T.ACCENT, bg=None, height=None, track=T.SURFACE_3):
        bg = bg or parent.cget('bg')
        self.tone, self.track = tone, track
        self._value = 0.0
        h = height or px(6)
        super().__init__(parent, bg=bg, bd=0, highlightthickness=0, height=h)
        self.bind('<Configure>', lambda e: self._paint())

    def set(self, value, tone=None):
        value = 0.0 if value is None else max(0.0, min(1.0, float(value)))
        if tone and tone != self.tone:
            self.tone = tone
        elif abs(value - self._value) < 0.004:
            return
        self._value = value
        self._paint()

    def _paint(self):
        self.delete('all')
        w, h = self.winfo_width(), self.winfo_height()
        if w < 4:
            return
        round_rect(self, 0, 0, w, h, h / 2, self.track, self.track)
        filled = max(h, w * self._value)
        if self._value > 0:
            round_rect(self, 0, 0, filled, h, h / 2, self.tone, self.tone)


class Toggle(tk.Canvas):
    """Switch control; label sits to the right of the track."""

    def __init__(self, parent, label='', value=False, command=None, bg=None):
        bg = bg or parent.cget('bg')
        self._value = bool(value)
        self._label = label
        self._command = command or (lambda v: None)
        self._hover = False
        f = font(12)
        try:
            tw = tkfont.Font(font=f).measure(label)
        except tk.TclError:
            tw = int(len(label) * px(6.6))
        super().__init__(parent, bg=bg, bd=0, highlightthickness=0,
                         width=px(38) + px(10) + tw, height=px(22),
                         cursor='hand2', takefocus=1)
        self.bind('<Button-1>', lambda e: self.toggle())
        self.bind('<Return>', lambda e: self.toggle())
        self.bind('<space>', lambda e: self.toggle())
        self.bind('<Enter>', lambda e: self._set_hover(True))
        self.bind('<Leave>', lambda e: self._set_hover(False))
        self._paint()

    def _set_hover(self, value):
        self._hover = value
        self._paint()

    def get(self):
        return self._value

    def set(self, value):
        self._value = bool(value)
        self._paint()

    def toggle(self):
        self._value = not self._value
        self._paint()
        self._command(self._value)

    def _paint(self):
        self.delete('all')
        h = px(22)
        tw, th = px(38), px(20)
        y = (h - th) / 2
        on = self._value
        fill = T.ACCENT if on else T.SURFACE_3
        if self._hover:
            fill = mix(fill, '#FFFFFF', .08)
        round_rect(self, 1, y, tw - 1, y + th, th / 2, fill,
                   T.ACCENT_DEEP if on else T.LINE_STRONG)
        r = th / 2 - px(3)
        cx = (tw - px(5) - r) if on else (px(5) + r)
        cy = y + th / 2
        self.create_oval(cx - r, cy - r, cx + r, cy + r,
                         fill='#FFFFFF' if on else T.DIM, outline='')
        self.create_text(tw + px(10), h / 2 + px(.5), text=self._label, anchor='w',
                         fill=T.TEXT if on else T.DIM, font=font(12))


class Slider(tk.Canvas):
    """Rounded value slider: drag the knob, click the track, or use the arrows."""

    def __init__(self, parent, value=1.0, minimum=0.0, maximum=1.0, step=0.01,
                 command=None, commit=None, bg=None, tone=T.ACCENT, width=None):
        bg = bg or parent.cget('bg')
        self.minimum, self.maximum, self.step = float(minimum), float(maximum), float(step)
        self.tone = tone
        self._value = self._snap(value)
        self._command = command or (lambda v: None)
        self._commit = commit or (lambda v: None)
        self._hover = self._drag = False
        super().__init__(parent, bg=bg, bd=0, highlightthickness=0,
                         height=px(22), width=width or px(170),
                         cursor='hand2', takefocus=1)
        self.bind('<Configure>', lambda e: self._paint())
        self.bind('<ButtonPress-1>', self._press)
        self.bind('<B1-Motion>', self._motion)
        self.bind('<ButtonRelease-1>', self._release)
        self.bind('<Enter>', lambda e: self._set_hover(True))
        self.bind('<Leave>', lambda e: self._set_hover(False))
        self.bind('<Left>', lambda e: self._nudge(-1))
        self.bind('<Right>', lambda e: self._nudge(1))

    def _snap(self, value):
        value = max(self.minimum, min(self.maximum, float(value)))
        steps = round((value - self.minimum) / self.step)
        return round(self.minimum + steps * self.step, 4)

    def get(self):
        return self._value

    def set(self, value, notify=False):
        value = self._snap(value)
        if value != self._value:
            self._value = value
            self._paint()
            if notify:
                self._command(value)

    def _set_hover(self, hover):
        self._hover = hover
        self._paint()

    def _nudge(self, direction):
        self.set(self._value + direction * self.step, notify=True)
        self._commit(self._value)

    def _from_x(self, x):
        pad = px(9)
        span = max(1, self.winfo_width() - 2 * pad)
        return self.minimum + (self.maximum - self.minimum) * ((x - pad) / span)

    def _press(self, event):
        self._drag = True
        self.focus_set()
        self.set(self._from_x(event.x), notify=True)

    def _motion(self, event):
        if self._drag:
            self.set(self._from_x(event.x), notify=True)

    def _release(self, _event):
        if self._drag:
            self._drag = False
            self._commit(self._value)

    def _paint(self):
        self.delete('all')
        w, h = self.winfo_width(), self.winfo_height()
        if w < 12:
            return
        pad, cy = px(9), h / 2
        track = px(5)
        round_rect(self, pad, cy - track / 2, w - pad, cy + track / 2,
                   track / 2, T.SURFACE_3, T.SURFACE_3)
        span = (self._value - self.minimum) / max(1e-9, self.maximum - self.minimum)
        knob_x = pad + (w - 2 * pad) * span
        if span > 0:
            round_rect(self, pad, cy - track / 2, max(pad + track, knob_x),
                       cy + track / 2, track / 2, self.tone, self.tone)
        r = px(8 if (self._hover or self._drag) else 7)
        self.create_oval(knob_x - r, cy - r, knob_x + r, cy + r,
                         fill='#FFFFFF', outline=self.tone, width=px(2))


class SlimScrollbar(tk.Canvas):
    """Minimal rounded scrollbar that hides itself when everything fits."""

    def __init__(self, parent, command, bg=None):
        bg = bg or parent.cget('bg')
        super().__init__(parent, width=T.SCROLLW, bg=bg, bd=0, highlightthickness=0)
        self.command = command
        self.first, self.last = 0.0, 1.0
        self._drag = None
        self._hover = False
        self.bind('<Configure>', lambda e: self._paint())
        self.bind('<ButtonPress-1>', self._press)
        self.bind('<B1-Motion>', self._motion)
        self.bind('<ButtonRelease-1>', lambda e: setattr(self, '_drag', None))
        self.bind('<Enter>', lambda e: self._set_hover(True))
        self.bind('<Leave>', lambda e: self._set_hover(False))

    def _set_hover(self, value):
        self._hover = value
        self._paint()

    def set(self, first, last):
        self.first, self.last = float(first), float(last)
        self._paint()

    def _press(self, event):
        h = self.winfo_height()
        y1, y2 = self.first * h, self.last * h
        if y1 <= event.y <= y2:
            self._drag = event.y - y1
        else:
            self.command('moveto', max(0.0, (event.y - (y2 - y1) / 2) / max(1, h)))

    def _motion(self, event):
        if self._drag is None:
            return
        h = max(1, self.winfo_height())
        self.command('moveto', max(0.0, min(1.0, (event.y - self._drag) / h)))

    def _paint(self):
        self.delete('all')
        h, w = self.winfo_height(), self.winfo_width()
        if h < 10:
            return
        if self.last - self.first >= 0.999:
            return
        y1, y2 = self.first * h, self.last * h
        if y2 - y1 < px(28):
            y2 = y1 + px(28)
        pad = px(3)
        tone = T.LINE_STRONG if not (self._hover or self._drag is not None) else T.MUTE
        round_rect(self, pad, y1 + 1, w - pad, y2 - 1, (w - 2 * pad) / 2, tone, tone)


class ScrollArea(tk.Frame):
    """Vertical scroll container. Content goes into `.inner`."""

    def __init__(self, parent, bg=None):
        bg = bg or parent.cget('bg')
        super().__init__(parent, bg=bg, bd=0, highlightthickness=0)
        self.canvas = tk.Canvas(self, bg=bg, bd=0, highlightthickness=0, takefocus=0)
        self.bar = SlimScrollbar(self, self._yview, bg=bg)
        self.inner = tk.Frame(self.canvas, bg=bg, bd=0, highlightthickness=0)
        self.bar.pack(side='right', fill='y')
        self.canvas.pack(side='left', fill='both', expand=True)
        self._window = self.canvas.create_window(0, 0, anchor='nw', window=self.inner)
        self.canvas.configure(yscrollcommand=self.bar.set)
        self.inner.bind('<Configure>', self._sync)
        self.canvas.bind('<Configure>', self._resize)

    def _yview(self, *args):
        self.canvas.yview(*args)

    def _sync(self, _event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox('all'))

    def _resize(self, event):
        self.canvas.itemconfigure(self._window, width=event.width)
        self._sync()

    def on_wheel(self, event):
        """Routed from the toplevel so only the visible page scrolls."""
        first, last = self.canvas.yview()
        if last - first >= 0.999:
            return
        step = -1 if getattr(event, 'num', 0) == 4 or getattr(event, 'delta', 0) > 0 else 1
        self.canvas.yview_scroll(step * 3, 'units')


class NavItem(tk.Canvas):
    """Sidebar entry with icon, label and an active rail indicator."""

    def __init__(self, parent, key, label, icon, command, bg=None):
        bg = bg or parent.cget('bg')
        self.key, self.label, self.icon = key, label, icon
        self._command = command
        self._active = self._hover = False
        super().__init__(parent, bg=bg, height=T.NAV_H, bd=0, highlightthickness=0,
                         cursor='hand2', takefocus=1)
        self.bind('<Configure>', lambda e: self._paint())
        self.bind('<Button-1>', lambda e: self._command(self.key))
        self.bind('<Return>', lambda e: self._command(self.key))
        self.bind('<Enter>', lambda e: self._set('_hover', True))
        self.bind('<Leave>', lambda e: self._set('_hover', False))

    def _set(self, attr, value):
        if getattr(self, attr) != value:
            setattr(self, attr, value)
            self._paint()

    def set_active(self, active):
        self._set('_active', active)

    def _paint(self):
        self.delete('all')
        w, h = self.winfo_width(), self.winfo_height()
        if w < 10:
            return
        if self._active:
            round_rect(self, 0, 1, w, h - 1, T.R_CTRL, T.TINT_ACCENT, T.TINT_ACCENT)
            self.create_line(px(1.5), h * .26, px(1.5), h * .74, fill=T.ACCENT_HI,
                             width=px(3), capstyle='round')
        elif self._hover:
            round_rect(self, 0, 1, w, h - 1, T.R_CTRL, T.SURFACE, T.SURFACE)
        tone = T.TEXT if self._active else (T.DIM if not self._hover else T.TEXT)
        draw_icon(self, self.icon, px(22), h / 2, px(16),
                  T.ACCENT_HI if self._active else tone)
        self.create_text(px(40), h / 2 + px(.5), text=self.label, anchor='w',
                         fill=tone, font=font(13, 'bold' if self._active else 'normal'))


class StatCard(Card):
    """Headline metric: icon badge, label, value and a supporting caption."""

    def __init__(self, parent, label, icon, tone=T.ACCENT, tint=T.TINT_ACCENT,
                 caption='', big=True):
        super().__init__(parent, pad=T.S4, accent=None)
        self.tone = tone
        body = self.body
        head = tk.Frame(body, bg=T.SURFACE)
        head.pack(fill='x')
        badge = tk.Canvas(head, width=px(32), height=px(32), bg=T.SURFACE, bd=0,
                          highlightthickness=0)
        badge.pack(side='left')
        round_rect(badge, 0, 0, px(32), px(32), T.R_TILE, tint, mix(tint, tone, .22))
        draw_icon(badge, icon, px(16), px(16), px(17), tone)
        tk.Label(head, text=label.upper(), bg=T.SURFACE, fg=T.MUTE, anchor='w',
                 font=font(10, 'bold')).pack(side='left', fill='x', expand=True,
                                             padx=(T.S3, 0))
        self.value = tk.StringVar(value='–')
        tk.Label(body, textvariable=self.value, bg=T.SURFACE, fg=T.TEXT,
                 font=font(28 if big else 22, 'bold'), anchor='w').pack(
                     fill='x', pady=(T.S3, 0))
        self.caption = tk.StringVar(value=caption)
        tk.Label(body, textvariable=self.caption, bg=T.SURFACE, fg=T.MUTE,
                 font=font(11), anchor='w').pack(fill='x')

    def set(self, value, caption=None):
        if self.value.get() != str(value):
            self.value.set(str(value))
        if caption is not None and self.caption.get() != caption:
            self.caption.set(caption)


class MiniStat(tk.Frame):
    """Compact secondary metric tile used in dense rows."""

    def __init__(self, parent, label, icon, tone=T.CYAN, tint=T.TINT_CYAN, bg=T.SURFACE):
        super().__init__(parent, bg=bg, bd=0, highlightthickness=0)
        self.back = tk.Canvas(self, bg=bg, bd=0, highlightthickness=0)
        self.back.place(x=0, y=0, relwidth=1, relheight=1)
        self._size = (0, 0)
        self._fill, self._border = T.SURFACE_2, T.LINE_SOFT
        self.bind('<Configure>', self._paint)
        row = tk.Frame(self, bg=self._fill)
        row.pack(fill='both', expand=True, padx=T.R_TILE, pady=T.S3)
        badge = tk.Canvas(row, width=px(28), height=px(28), bg=self._fill, bd=0,
                          highlightthickness=0)
        badge.pack(side='left')
        round_rect(badge, 0, 0, px(28), px(28), px(9), tint, mix(tint, tone, .2))
        draw_icon(badge, icon, px(14), px(14), px(15), tone)
        text = tk.Frame(row, bg=self._fill)
        text.pack(side='left', fill='x', expand=True, padx=(T.S3, 0))
        self.value = tk.StringVar(value='0')
        tk.Label(text, textvariable=self.value, bg=self._fill, fg=T.TEXT,
                 font=font(17, 'bold'), anchor='w').pack(fill='x')
        tk.Label(text, text=label, bg=self._fill, fg=T.MUTE, font=font(11),
                 anchor='w').pack(fill='x')

    def set(self, value):
        if self.value.get() != str(value):
            self.value.set(str(value))

    def _paint(self, _event=None):
        w, h = self.winfo_width(), self.winfo_height()
        if (w, h) == self._size or w < 8 or h < 8:
            return
        self._size = (w, h)
        self.back.delete('all')
        round_rect(self.back, 1, 1, w - 1, h - 1, T.R_TILE, self._fill, self._border)


class Field(tk.Frame):
    """Labelled text input with focus ring, secret masking and a hint line."""

    def __init__(self, parent, label, value='', secret=False, hint='',
                 browse=None, bg=T.SURFACE, placeholder=''):
        super().__init__(parent, bg=bg)
        self.secret = secret
        self._revealed = False
        self.var = tk.StringVar(value=value)
        tk.Label(self, text=label, bg=bg, fg=T.DIM, font=font(12, 'bold'),
                 anchor='w').pack(fill='x', pady=(0, px(6)))
        shell = tk.Frame(self, bg=bg)
        shell.pack(fill='x')
        self.frame = tk.Frame(shell, bg=T.FIELD, bd=0, highlightthickness=1,
                              highlightbackground=T.LINE_STRONG, highlightcolor=T.ACCENT)
        self.frame.pack(side='left', fill='x', expand=True)
        self.entry = tk.Entry(self.frame, textvariable=self.var, bg=T.FIELD, fg=T.TEXT,
                              insertbackground=T.ACCENT_HI, relief='flat', bd=0,
                              font=font(13), show='*' if secret else '',
                              highlightthickness=0,
                              disabledbackground=T.FIELD, disabledforeground=T.MUTE)
        self.entry.pack(fill='x', expand=True, padx=T.S3, pady=px(8))
        if secret:
            self.reveal = IconButton(shell, 'eye', self.toggle_secret,
                                     size=T.FIELD_H, bg=bg, tip='Anzeigen')
            self.reveal.pack(side='left', padx=(px(6), 0))
        if browse:
            self.browse = IconButton(shell, 'folder', browse, size=T.FIELD_H, bg=bg)
            self.browse.pack(side='left', padx=(px(6), 0))
        self.hint_var = tk.StringVar(value=hint)
        self.hint = tk.Label(self, textvariable=self.hint_var, bg=bg, fg=T.MUTE,
                             font=font(11), anchor='w', justify='left')
        self.hint.pack(fill='x', pady=(px(5), 0))
        self._default_hint = hint

    def toggle_secret(self):
        self._revealed = not self._revealed
        self.entry.configure(show='' if self._revealed else '*')
        self.reveal.set_icon('eye_off' if self._revealed else 'eye')

    def hide_secret(self):
        if self.secret and self._revealed:
            self.toggle_secret()

    def get(self):
        return self.var.get().strip()

    def set(self, value):
        self.var.set(value)

    def mark(self, state='idle', message=None):
        colors = {'idle': T.MUTE, 'ok': T.OK, 'error': T.BAD, 'warn': T.WARN}
        self.hint.configure(fg=colors.get(state, T.MUTE))
        self.hint_var.set(self._default_hint if message is None else message)
        self.frame.configure(highlightbackground={'error': T.BAD, 'ok': T.LINE_STRONG}
                             .get(state, T.LINE_STRONG))


def label(parent, text='', size=13, weight='normal', fg=T.TEXT, bg=None, **kw):
    return tk.Label(parent, text=text, font=font(size, weight),
                    bg=bg or parent.cget('bg'), fg=fg, **kw)


def section_head(parent, title, subtitle='', bg=None):
    """Title row inside a card; returns the frame so actions can be added right."""
    bg = bg or parent.cget('bg')
    row = tk.Frame(parent, bg=bg)
    row.pack(fill='x', pady=(0, T.S4))
    text = tk.Frame(row, bg=bg)
    text.pack(side='left', fill='x', expand=True)
    label(text, title, 15, 'bold', bg=bg, anchor='w').pack(fill='x')
    if subtitle:
        label(text, subtitle, 11, fg=T.MUTE, bg=bg, anchor='w').pack(fill='x',
                                                                     pady=(px(2), 0))
    return row


def divider(parent, bg=None, pady=None):
    bg = bg or parent.cget('bg')
    line = tk.Frame(parent, bg=T.LINE_SOFT, height=1)
    line.pack(fill='x', pady=pady if pady is not None else T.S4)
    return line


# --------------------------------------------------------------------------
# In-game HUD
# --------------------------------------------------------------------------
# A small always-on-top card that sits over Fortnite in borderless/windowed
# mode. It is a plain Tk Toplevel plus a handful of documented Win32 window
# styles - no injection, no DirectX hook, no access to the game process.

HUD_DEFAULTS = {
    'hud_enabled': False,          # show the HUD at startup
    'hud_mode': 'compact',         # 'compact' | 'expanded'
    'hud_opacity': 0.92,           # 0.35 .. 1.0
    'hud_scale': 1.0,              # 0.8 .. 1.6, on top of the display scaling
    'hud_locked': True,            # locked = click-through, unlocked = draggable
    'hud_x': None,
    'hud_y': None,
    'hud_hotkey_toggle': 'Ctrl+Alt+H',
    'hud_hotkey_lock': 'Ctrl+Alt+L',
    'hud_hotkey_mode': 'Ctrl+Alt+E',
}

# Colour key for the transparent area around the card. Never used for content.
HUD_KEY = '#010203'

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 1, 2, 4, 8, 0x4000
HOTKEY_MODS = {'ctrl': MOD_CONTROL, 'control': MOD_CONTROL, 'strg': MOD_CONTROL,
               'alt': MOD_ALT, 'shift': MOD_SHIFT, 'umschalt': MOD_SHIFT,
               'win': MOD_WIN, 'super': MOD_WIN}
HOTKEY_KEYS = {'SPACE': 0x20, 'LEERTASTE': 0x20, 'INSERT': 0x2D, 'EINFG': 0x2D,
               'DELETE': 0x2E, 'ENTF': 0x2E, 'HOME': 0x24, 'POS1': 0x24,
               'END': 0x23, 'ENDE': 0x23, 'PAGEUP': 0x21, 'PAGEDOWN': 0x22,
               'TAB': 0x09, 'ESC': 0x1B, 'ESCAPE': 0x1B}
HOTKEY_KEYS.update({f'F{n}': 0x6F + n for n in range(1, 13)})


def parse_hotkey(text):
    """'Ctrl+Alt+H' -> (modifiers, virtual key). Empty text disables the hotkey.

    At least one modifier is required on purpose: a bare key would be swallowed
    system-wide and could break Fortnite or ChestCounter.
    """
    text = (text or '').strip()
    if not text:
        return None
    parts = [part.strip() for part in text.replace('-', '+').split('+') if part.strip()]
    if not parts:
        return None
    mods, key = 0, None
    for part in parts:
        lowered = part.lower()
        if lowered in HOTKEY_MODS:
            mods |= HOTKEY_MODS[lowered]
        elif key is None:
            key = part.upper()
        else:
            raise ValueError('Nur eine Taste plus Modifikatoren, z. B. Strg+Alt+H.')
    if key is None:
        raise ValueError('Es fehlt die eigentliche Taste, z. B. Strg+Alt+H.')
    if not mods:
        raise ValueError('Mindestens Strg, Alt oder Shift verwenden, damit die '
                         'Taste nicht im Spiel verloren geht.')
    if key in HOTKEY_KEYS:
        return mods | MOD_NOREPEAT, HOTKEY_KEYS[key]
    if len(key) == 1 and key.isascii() and key.isalnum():
        return mods | MOD_NOREPEAT, ord(key)
    raise ValueError(f'Unbekannte Taste "{key}".')


class Win32:
    """Thin ctypes wrapper. Every call is a no-op outside Windows."""

    GWL_EXSTYLE = -20
    WS_EX_LAYERED = 0x00080000
    WS_EX_TRANSPARENT = 0x00000020
    WS_EX_TOOLWINDOW = 0x00000080
    WS_EX_NOACTIVATE = 0x08000000
    HWND_TOPMOST = -1
    SWP_NOMOVE_NOSIZE_NOACTIVATE = 0x0002 | 0x0001 | 0x0010

    available = os.name == 'nt'

    @staticmethod
    def handle(window):
        """HWND of a Tk toplevel, following Tk's wrapper frame when present."""
        if not Win32.available:
            return 0
        try:
            # ctypes returns 32-bit int by default. HWND needs pointer-sized
            # WinAPI signatures on 64-bit Windows (most gaming PCs).
            import ctypes.wintypes as wintypes
            hwnd = int(window.winfo_id())
            fn = ctypes.windll.user32.GetParent
            fn.argtypes = [wintypes.HWND]
            fn.restype = wintypes.HWND
            return int(fn(wintypes.HWND(hwnd)) or hwnd)
        except (AttributeError, OSError, tk.TclError):
            return 0

    @staticmethod
    def set_overlay_styles(window, click_through):
        """Tool window (no taskbar button), never focus-stealing, optionally
        click-through so every mouse event lands in the game instead."""
        hwnd = Win32.handle(window)
        if not hwnd:
            return False
        try:
            user32 = ctypes.windll.user32
            import ctypes.wintypes as wintypes
            user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
            user32.GetWindowLongW.restype = ctypes.c_long
            user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int,
                                              ctypes.c_long]
            user32.SetWindowLongW.restype = ctypes.c_long
            style = user32.GetWindowLongW(hwnd, Win32.GWL_EXSTYLE)
            # Leave WS_EX_LAYERED to Tk's '-alpha' implementation. Manually
            # setting it can reset or conflict with Tk's transparency state.
            style |= (Win32.WS_EX_TOOLWINDOW | Win32.WS_EX_NOACTIVATE)
            if click_through:
                style |= Win32.WS_EX_TRANSPARENT
            else:
                style &= ~Win32.WS_EX_TRANSPARENT
            user32.SetWindowLongW(hwnd, Win32.GWL_EXSTYLE, style)
            return True
        except (AttributeError, OSError):
            return False

    @staticmethod
    def raise_topmost(window):
        hwnd = Win32.handle(window)
        if not hwnd:
            return False
        try:
            import ctypes.wintypes as wintypes
            user32 = ctypes.windll.user32
            user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND,
                                           ctypes.c_int, ctypes.c_int,
                                           ctypes.c_int, ctypes.c_int,
                                           ctypes.c_uint]
            user32.SetWindowPos.restype = wintypes.BOOL
            return bool(user32.SetWindowPos(
                hwnd, Win32.HWND_TOPMOST, 0, 0, 0, 0,
                Win32.SWP_NOMOVE_NOSIZE_NOACTIVATE))
        except (AttributeError, OSError):
            return False

    @staticmethod
    def primary_screen():
        """Windows primary display always starts at virtual position 0,0."""
        if not Win32.available:
            return None
        try:
            get = ctypes.windll.user32.GetSystemMetrics
            width, height = get(0), get(1)
            return (0, 0, width, height) if width > 0 and height > 0 else None
        except (AttributeError, OSError):
            return None

    @staticmethod
    def virtual_screen():
        """(x, y, width, height) across all monitors, or None."""
        if not Win32.available:
            return None
        try:
            metric = ctypes.windll.user32.GetSystemMetrics
            box = (metric(76), metric(77), metric(78), metric(79))
            return box if box[2] > 0 and box[3] > 0 else None
        except (AttributeError, OSError):
            return None


class HotkeyListener(threading.Thread):
    """Optional global shortcuts via RegisterHotKey (Windows only).

    Runs its own message loop because RegisterHotKey delivers WM_HOTKEY to the
    registering thread. Firing a hotkey only puts a name into a queue; the Tk
    thread acts on it in the normal refresh tick.
    """

    WM_HOTKEY = 0x0312
    WM_QUIT = 0x0012

    def __init__(self, bindings, sink):
        super().__init__(daemon=True, name='SquadLootHotkeys')
        self.bindings = list(bindings)       # [(name, (mods, vk)), ...]
        self.sink = sink
        self.thread_id = 0
        self.error = ''
        self.registered = []
        self._ready = threading.Event()

    def run(self):
        if not Win32.available or not self.bindings:
            self._ready.set()
            return
        try:
            import ctypes.wintypes as wintypes
            user32 = ctypes.windll.user32
            self.thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
            for index, (name, combo) in enumerate(self.bindings, start=1):
                if user32.RegisterHotKey(None, index, combo[0], combo[1]):
                    self.registered.append(name)
                else:
                    self.error = ('Mindestens ein Tastenkürzel ist bereits von '
                                  'einem anderen Programm belegt.')
            self._ready.set()
            message = wintypes.MSG()
            while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
                if message.message == self.WM_HOTKEY:
                    index = int(message.wParam) - 1
                    if 0 <= index < len(self.bindings):
                        self.sink(self.bindings[index][0])
        except Exception as exc:          # a broken hotkey must not kill the app
            self.error = str(exc)[:160]
        finally:
            self._ready.set()
            try:
                for index in range(1, len(self.bindings) + 1):
                    ctypes.windll.user32.UnregisterHotKey(None, index)
            except (AttributeError, OSError):
                pass

    def stop(self):
        if self.thread_id:
            try:
                ctypes.windll.user32.PostThreadMessageW(
                    self.thread_id, self.WM_QUIT, 0, 0)
            except (AttributeError, OSError):
                pass


class Hud:
    """Compact in-game overlay: squad count, personal count, status dot.

    Everything is drawn on a single canvas and only repainted when a displayed
    value actually changes, so an idle HUD costs nothing while Fortnite runs.
    """

    MIN_W = 188
    HEAD_H = 60
    ROW_H = 20

    def __init__(self, master, core, on_change=None):
        self.master = master
        self.core = core
        self.on_change = on_change or (lambda: None)
        self.win = None
        self.canvas = None
        self.menu = None
        self._fonts = {}
        self._signature = None
        self._drag_from = None
        self._size = (0, 0)
        self._topmost_tick = 0
        self.data = {'squad': 0, 'personal': 0, 'round': None, 'connected': False,
                     'confirmed': 0, 'estimated': 0, 'members': [],
                     'personal_confirmed': False, 'error': False}

    # ---- configuration -------------------------------------------------
    def opt(self, key):
        return self.core.config.get(key, HUD_DEFAULTS[key])

    def save(self, **values):
        self.core.set_config(values)

    @property
    def visible(self):
        return self.win is not None

    def scale(self):
        try:
            user = float(self.opt('hud_scale'))
        except (TypeError, ValueError):
            user = 1.0
        return SCALE * max(0.8, min(1.6, user))

    def u(self, value):
        """Design pixel -> device pixel, including the user's HUD scale."""
        return max(1, int(round(value * self.scale())))

    def fnt(self, size, weight='normal'):
        key = (size, weight, round(self.scale(), 3))
        if key not in self._fonts:
            self._fonts[key] = (family(), -max(7, int(round(size * self.scale()))), weight)
        return self._fonts[key]

    def measure(self, text, size, weight='normal'):
        try:
            return tkfont.Font(font=self.fnt(size, weight)).measure(text)
        except tk.TclError:
            return int(len(text) * size * 0.62 * self.scale())

    # ---- geometry ------------------------------------------------------
    def screen_box(self):
        box = Win32.virtual_screen()
        if box:
            return box
        try:
            width = self.master.winfo_vrootwidth() or self.master.winfo_screenwidth()
            height = self.master.winfo_vrootheight() or self.master.winfo_screenheight()
        except tk.TclError:
            width, height = 1920, 1080
        return 0, 0, width, height

    def default_position(self, width, height):
        """Start on the PRIMARY display, never on an offscreen side monitor."""
        try:
            primary = Win32.primary_screen()
            if primary is None:
                primary = (0, 0, self.master.winfo_screenwidth(),
                           self.master.winfo_screenheight())
        except tk.TclError:
            primary = self.screen_box()
        x, y, box_w, box_h = primary
        margin_x = max(self.u(24), int(box_w * 0.02))
        margin_y = max(self.u(90), int(box_h * 0.1))
        return (x + min(margin_x, max(0, box_w - width)),
                y + min(margin_y, max(0, box_h - height)))

    def clamp(self, x, y, width, height):
        """Keep the card fully on a real monitor after a resolution change."""
        box_x, box_y, box_w, box_h = self.screen_box()
        x = int(min(max(x, box_x), box_x + box_w - width))
        y = int(min(max(y, box_y), box_y + box_h - height))
        return x, y

    def vision_region(self):
        """The area vision.py samples, in screen pixels (primary monitor)."""
        try:
            width = self.master.winfo_screenwidth()
            height = self.master.winfo_screenheight()
        except tk.TclError:
            return None
        return (int(width * .26), int(height * .29), int(width * .74), int(height * .72))

    def overlaps_vision_region(self):
        """True when the card sits inside the screen-recognition sample area."""
        if not self.visible:
            return False
        region = self.vision_region()
        if not region:
            return False
        left, top = self.win.winfo_x(), self.win.winfo_y()
        right, bottom = left + self._size[0], top + self._size[1]
        return not (right <= region[0] or left >= region[2]
                    or bottom <= region[1] or top >= region[3])

    # ---- window lifecycle ----------------------------------------------
    def show(self):
        if self.win is not None:
            self.bring_to_front()
            return
        win = tk.Toplevel(self.master)
        self.win = win
        win.withdraw()
        win.title('SquadLoot HUD')
        try:
            win.overrideredirect(True)      # no title bar, no taskbar button
        except tk.TclError:
            pass
        # Reliability fallback for Windows: a solid card with soft opacity.
        # '-transparentcolor' + '-alpha' + manual layered Win32 styles can
        # combine into a completely invisible window on some Windows setups.
        # Our HUD is only ~188x60px; prefer a visible card to invisible corners.
        win.configure(bg=T.SURFACE)
        win.resizable(False, False)
        try:
            win.attributes('-topmost', True)
        except tk.TclError:
            pass
        self.apply_opacity()
        self.canvas = tk.Canvas(win, bg=win.cget('bg'), bd=0, highlightthickness=0,
                                takefocus=0)
        self.canvas.pack(fill='both', expand=True)
        self.canvas.bind('<ButtonPress-1>', self._drag_start)
        self.canvas.bind('<B1-Motion>', self._drag_move)
        self.canvas.bind('<ButtonRelease-1>', self._drag_end)
        self.canvas.bind('<Button-3>', self._popup)
        win.protocol('WM_DELETE_WINDOW', self.hide)
        self._signature = None
        self._size = (0, 0)
        self.redraw(force=True)
        win.deiconify()
        win.update_idletasks()
        # Apply native styles only AFTER the native wrapper was mapped.
        self.bring_to_front()

    def bring_to_front(self):
        """Reassert visibility without activating or focusing Fortnite."""
        if self.win is None:
            return
        try:
            self.win.deiconify()
            self.win.attributes('-topmost', True)
            self.win.lift()
            self.apply_opacity()
            self.apply_click_through()
            Win32.raise_topmost(self.win)
        except tk.TclError:
            pass

    def hide(self):
        if self.win is None:
            return
        self.store_position()
        if self.menu is not None:
            try:
                self.menu.destroy()
            except tk.TclError:
                pass
            self.menu = None
        try:
            self.win.destroy()
        except tk.TclError:
            pass
        self.win = None
        self.canvas = None
        self._signature = None
        # Forget the geometry as well: resize() short-circuits on an unchanged
        # size, so a stale value would leave the next window unpositioned.
        self._size = (0, 0)

    def set_enabled(self, enabled):
        self.save(hud_enabled=bool(enabled))
        if enabled:
            self.show()
        else:
            self.hide()
        self.on_change()

    def toggle(self):
        self.set_enabled(not self.visible)

    def set_mode(self, mode):
        self.save(hud_mode='expanded' if mode == 'expanded' else 'compact')
        self.redraw(force=True)
        self.on_change()

    def toggle_mode(self):
        self.set_mode('compact' if self.opt('hud_mode') == 'expanded' else 'expanded')

    def set_locked(self, locked):
        self.save(hud_locked=bool(locked))
        self.apply_click_through()
        self.redraw(force=True)
        self.on_change()

    def toggle_lock(self):
        self.set_locked(not self.opt('hud_locked'))

    def apply_opacity(self):
        if self.win is None:
            return
        try:
            value = float(self.opt('hud_opacity'))
        except (TypeError, ValueError):
            value = HUD_DEFAULTS['hud_opacity']
        try:
            self.win.attributes('-alpha', max(0.35, min(1.0, value)))
        except tk.TclError:
            pass

    def apply_click_through(self):
        if self.win is not None:
            Win32.set_overlay_styles(self.win, bool(self.opt('hud_locked')))

    def reset_position(self):
        self.save(hud_x=None, hud_y=None)
        if self.win is not None:
            width, height = self._size
            x, y = self.default_position(width, height)
            self.win.geometry(f'+{x}+{y}')
            # Keep the saved coordinates null until the user deliberately drags
            # the overlay. Reading winfo_x/y here can return the OLD position.
            self.bring_to_front()
        self.on_change()

    def store_position(self):
        if self.win is None:
            return
        try:
            self.save(hud_x=int(self.win.winfo_x()), hud_y=int(self.win.winfo_y()))
        except tk.TclError:
            pass

    # ---- interaction ----------------------------------------------------
    def _drag_start(self, event):
        if self.opt('hud_locked'):
            return
        self._drag_from = (event.x_root - self.win.winfo_x(),
                           event.y_root - self.win.winfo_y())

    def _drag_move(self, event):
        if self._drag_from is None:
            return
        x = event.x_root - self._drag_from[0]
        y = event.y_root - self._drag_from[1]
        x, y = self.clamp(x, y, *self._size)
        self.win.geometry(f'+{x}+{y}')

    def _drag_end(self, _event):
        if self._drag_from is not None:
            self._drag_from = None
            self.store_position()
            self.on_change()

    def _popup(self, event):
        if self.win is None:
            return
        if self.menu is None:
            self.menu = tk.Menu(self.win, tearoff=0, bg=T.SURFACE_2, fg=T.TEXT,
                                activebackground=T.ACCENT, activeforeground='#FFFFFF',
                                bd=0, relief='flat', font=font(12))
        self.menu.delete(0, 'end')
        expanded = self.opt('hud_mode') == 'expanded'
        locked = bool(self.opt('hud_locked'))
        self.menu.add_command(label='Kompakt' if expanded else 'Erweitert',
                              command=self.toggle_mode)
        self.menu.add_command(label='Entsperren (verschiebbar)' if locked
                              else 'Sperren (klick-durchlässig)',
                              command=self.toggle_lock)
        self.menu.add_command(label='Position zurücksetzen', command=self.reset_position)
        self.menu.add_separator()
        self.menu.add_command(label='HUD ausblenden', command=lambda: self.set_enabled(False))
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()

    # ---- painting --------------------------------------------------------
    def update(self, data):
        """Called once per refresh tick; repaints only when something changed."""
        if self.win is None:
            return
        self.data = data
        self.redraw()
        self._topmost_tick += 1
        if self._topmost_tick % 10 == 0:
            Win32.raise_topmost(self.win)

    def signature(self):
        data = self.data
        base = (self.opt('hud_mode'), round(self.scale(), 3), bool(self.opt('hud_locked')),
                data['squad'], data['personal'], data['round'], data['connected'],
                data['error'], data['confirmed'], data['estimated'],
                data['personal_confirmed'])
        if self.opt('hud_mode') == 'expanded':
            base += tuple((m['name'], m['value'], m['confirmed'], m['online'])
                          for m in data['members'])
        return base

    def tones(self):
        data = self.data
        if data['round'] is None:
            squad = T.MUTE
        elif data['estimated'] == 0 and data['confirmed'] > 0:
            squad = T.OK
        else:
            squad = T.CYAN
        personal = T.OK if data['personal_confirmed'] else (
            T.CYAN if data['round'] is not None else T.MUTE)
        if data['error']:
            status = T.BAD
        elif data['connected']:
            status = T.OK
        else:
            status = T.MUTE
        return squad, personal, status

    def redraw(self, force=False):
        if self.win is None or self.canvas is None:
            return
        signature = self.signature()
        if not force and signature == self._signature:
            return
        self._signature = signature
        squad_tone, personal_tone, status_tone = self.tones()
        squad_text = str(self.data['squad'])
        personal_text = str(self.data['personal'])

        cursor = self.u(14)
        gap = self.u(9)
        icon_box = self.u(15)
        centre = self.u(24)
        chest_cx = cursor + icon_box / 2
        cursor += icon_box + gap
        squad_x = cursor
        squad_w = max(self.measure(squad_text, 25, 'bold'), self.measure('SQUAD', 9, 'bold'))
        cursor += squad_w + self.u(15)
        divider_x = cursor
        cursor += self.u(15)
        user_box = self.u(13)
        user_cx = cursor + user_box / 2
        cursor += user_box + self.u(8)
        personal_x = cursor
        personal_w = max(self.measure(personal_text, 18, 'bold'), self.measure('DU', 9, 'bold'))
        cursor += personal_w + self.u(18)

        width = max(self.u(self.MIN_W), int(cursor))
        height = self.u(self.HEAD_H)
        members = self.data['members'] if self.opt('hud_mode') == 'expanded' else []
        if self.opt('hud_mode') == 'expanded':
            rows = members or [None]
            name_w = max([self.measure(str(m['name'])[:14], 11) for m in members] or [self.u(70)])
            width = max(width, int(self.u(30) + name_w + self.u(26)
                                   + self.measure('999', 12, 'bold') + self.u(26)))
            width = min(width, self.u(320))
            height += self.u(4) + len(rows) * self.u(self.ROW_H) + self.u(8)

        self.resize(width, height)
        canvas = self.canvas
        canvas.delete('all')
        locked = bool(self.opt('hud_locked'))
        border = T.LINE_STRONG if locked else T.ACCENT
        round_rect(canvas, 0.5, 0.5, width - 0.5, height - 0.5, self.u(13),
                   T.SURFACE, border)
        if not locked:
            round_rect(canvas, self.u(3), self.u(3), width - self.u(3), height - self.u(3),
                       self.u(10), '', T.ACCENT_DEEP, 1)
            for index in range(3):
                dot_y = height / 2 - self.u(5) + index * self.u(5)
                canvas.create_oval(self.u(5.5), dot_y, self.u(8), dot_y + self.u(2.5),
                                   fill=T.ACCENT, outline='')

        draw_icon(canvas, 'chest', chest_cx, centre, icon_box, squad_tone,
                  width=max(1.0, icon_box / 11.0))
        canvas.create_text(squad_x, centre, text=squad_text, anchor='w',
                           fill=squad_tone, font=self.fnt(25, 'bold'))
        canvas.create_text(squad_x, self.u(43), text='SQUAD', anchor='w',
                           fill=T.MUTE, font=self.fnt(9, 'bold'))
        canvas.create_line(divider_x, self.u(16), divider_x, self.u(44),
                           fill=T.LINE, width=1)
        draw_icon(canvas, 'user', user_cx, centre, user_box, personal_tone,
                  width=max(1.0, user_box / 11.0))
        canvas.create_text(personal_x, centre, text=personal_text, anchor='w',
                           fill=personal_tone, font=self.fnt(18, 'bold'))
        canvas.create_text(personal_x, self.u(43), text='DU', anchor='w',
                           fill=T.MUTE, font=self.fnt(9, 'bold'))
        radius = self.u(4)
        dot_x, dot_y = width - self.u(13), self.u(13)
        canvas.create_oval(dot_x - radius - 1, dot_y - radius - 1,
                           dot_x + radius + 1, dot_y + radius + 1,
                           outline=mix(T.SURFACE, status_tone, .35), width=1)
        canvas.create_oval(dot_x - radius, dot_y - radius, dot_x + radius, dot_y + radius,
                           fill=status_tone, outline='')

        if self.opt('hud_mode') == 'expanded':
            top = self.u(self.HEAD_H)
            canvas.create_line(self.u(12), top, width - self.u(12), top,
                               fill=T.LINE_SOFT, width=1)
            top += self.u(4)
            if not members:
                canvas.create_text(width / 2, top + self.u(self.ROW_H) / 2,
                                   text='Keine aktive Runde', fill=T.MUTE,
                                   font=self.fnt(11))
            for index, member in enumerate(members):
                row_y = top + index * self.u(self.ROW_H) + self.u(self.ROW_H) / 2
                tone = T.OK if member['confirmed'] else (
                    T.CYAN if member['online'] else T.MUTE)
                mark = self.u(3.5)
                canvas.create_oval(self.u(18) - mark, row_y - mark,
                                   self.u(18) + mark, row_y + mark,
                                   fill=tone, outline='')
                canvas.create_text(self.u(30), row_y, text=str(member['name'])[:14],
                                   anchor='w', fill=T.DIM, font=self.fnt(11))
                canvas.create_text(width - self.u(28), row_y, text=str(member['value']),
                                   anchor='e', fill=tone, font=self.fnt(12, 'bold'))
                draw_icon(canvas, 'check' if member['confirmed'] else 'bolt',
                          width - self.u(15), row_y, self.u(9), tone, width=1.2)

    def resize(self, width, height):
        if (width, height) == self._size:
            return
        self._size = (width, height)
        stored_x, stored_y = self.opt('hud_x'), self.opt('hud_y')
        if stored_x is None or stored_y is None:
            x, y = self.default_position(width, height)
        else:
            x, y = self.clamp(int(stored_x), int(stored_y), width, height)
        self.win.geometry(f'{width}x{height}+{x}+{y}')
        self.canvas.configure(width=width, height=height)


# --------------------------------------------------------------------------
# Application shell
# --------------------------------------------------------------------------
NAV = (
    ('dashboard', 'Dashboard', 'grid'),
    ('live', 'Live-Tracking', 'target'),
    ('history', 'Match-Historie', 'clock'),
    ('squad', 'Squad', 'users'),
    ('settings', 'Einstellungen', 'gear'),
    ('updates', 'Updates', 'download'),
)

PAGE_META = {
    'dashboard': ('Dashboard', 'Dein Squad, deine Kisten, in Echtzeit.'),
    'live': ('Live-Tracking', 'Ein Klick zur Live-Erkennung.'),
    'history': ('Match-Historie', 'Alle vom Replay bestätigten Runden.'),
    'squad': ('Squad', 'Wer trägt wie viel zum Squad-Ergebnis bei.'),
    'settings': ('Einstellungen', 'Verbindung, Konten und Erkennung konfigurieren.'),
    'updates': ('Updates', 'Versionen kommen geschützt von deinem eigenen Pi.'),
}


def ago(seconds):
    """Short relative time for 'last event' and 'last check' captions."""
    if seconds is None:
        return 'nie'
    seconds = max(0, int(seconds))
    if seconds < 5:
        return 'gerade eben'
    if seconds < 60:
        return f'vor {seconds} s'
    if seconds < 3600:
        return f'vor {seconds // 60} min'
    if seconds < 86400:
        return f'vor {seconds // 3600} h'
    return f'vor {seconds // 86400} d'


def clock(stamp):
    if not stamp:
        return '–'
    try:
        return time.strftime('%d.%m.%Y  %H:%M', time.localtime(float(stamp)))
    except (TypeError, ValueError, OSError):
        return '–'


def aggregate(members):
    """Round totals, preferring replay-confirmed values over live estimates."""
    out = {'chests': 0, 'ammo': 0, 'food': 0, 'destroyed': 0, 'treasures': 0,
           'confirmed': 0, 'estimated': 0, 'online': 0}
    for m in members:
        verified = m.get('verified_chests')
        out['chests'] += verified if verified is not None else m.get('live_chests', 0)
        if verified is not None:
            out['confirmed'] += 1
        else:
            out['estimated'] += 1
        for key, live_key in (('ammo', 'ammo'), ('food', 'food'), ('destroyed', 'destroyed')):
            confirmed = m.get('verified_' + key)
            out[key] += confirmed if confirmed is not None else m.get(live_key, 0)
        out['treasures'] += m.get('verified_treasures') or 0
        out['online'] += 1 if m.get('online') else 0
    return out


class Gui:
    """Tk front end. Reads a snapshot from Core; never blocks on the network."""

    def __init__(self):
        self.core = Core()
        self.root = tk.Tk()
        self.root.title('SquadLoot  ·  Fortnite Squad Tracker ' + current_version())
        self.root.geometry(f'{px(1300)}x{px(840)}')
        self.root.minsize(px(1060), px(680))
        self.root.configure(bg=T.BG)
        self.root.protocol('WM_DELETE_WINDOW', self.close)
        try:
            self.root.option_add('*Font', font(13))
        except tk.TclError:
            pass

        self.events = queue.Queue()
        self.hud = Hud(self.root, self.core, on_change=self.sync_hud_controls)
        self.hotkeys = None
        self.hotkey_note = ''
        self.hud_fields = {}
        self.live_engine = ManagedLiveEngine(self.core)
        self.update_busy = False
        self.update_pending = False
        self.pending_version = ''
        self.last_check = None
        self.active = ''
        self.pages = {}
        self.nav = {}
        self.fields = {}
        self._hash = {}
        self._tick = 0
        self._idle = False

        self.build()
        start = 'dashboard' if self.core.config.get('server_url') else 'settings'
        self.show_page(start)
        self.root.bind_all('<MouseWheel>', self._wheel)
        self.root.bind_all('<Button-4>', self._wheel)
        self.root.bind_all('<Button-5>', self._wheel)
        self.root.bind('<Unmap>', lambda e: setattr(self, '_idle', True))
        self.root.bind('<Map>', lambda e: setattr(self, '_idle', False))
        self.root.after(500, self.refresh)
        self.root.after(9_000, self.periodic_update_check)
        self.start_hotkeys()
        self.core.replay_engine.start()  # automatic passive replay scan
        if self.hud.opt('hud_enabled'):
            self.root.after(250, self.restore_hud)
        if all(self.core.config.get(k) for k in ('server_url', 'token', 'name')):
            self.root.after(300, self.connect_automatically)

    # ---- shell ---------------------------------------------------------
    def build(self):
        shell = tk.Frame(self.root, bg=T.BG)
        shell.pack(fill='both', expand=True)
        self.build_sidebar(shell)
        main = tk.Frame(shell, bg=T.BG)
        main.pack(side='left', fill='both', expand=True)
        self.build_statusbar(main)
        self.build_topbar(main)
        holder = tk.Frame(main, bg=T.BG)
        holder.pack(fill='both', expand=True)
        for key, _title, _icon in NAV:
            self.pages[key] = ScrollArea(holder, bg=T.BG)
        self.build_dashboard()
        self.build_live()
        self.build_history()
        self.build_squad()
        self.build_settings()
        self.build_updates()

    def build_sidebar(self, parent):
        rail = tk.Frame(parent, bg=T.RAIL, width=T.SIDEBAR)
        rail.pack(side='left', fill='y')
        rail.pack_propagate(False)
        tk.Frame(parent, bg=T.LINE_SOFT, width=1).pack(side='left', fill='y')

        brand = tk.Frame(rail, bg=T.RAIL)
        brand.pack(fill='x', padx=T.S5, pady=(T.S5, T.S4))
        mark = tk.Canvas(brand, width=px(36), height=px(36), bg=T.RAIL, bd=0,
                         highlightthickness=0)
        mark.pack(side='left')
        draw_logo(mark, px(18), px(18), px(34))
        text = tk.Frame(brand, bg=T.RAIL)
        text.pack(side='left', padx=(T.S3, 0))
        label(text, 'SquadLoot', 17, 'bold', bg=T.RAIL, anchor='w').pack(fill='x')
        label(text, 'SQUAD TRACKER', 9, 'bold', fg=T.MUTE, bg=T.RAIL,
              anchor='w').pack(fill='x')

        label(rail, 'NAVIGATION', 10, 'bold', fg=T.MUTE, bg=T.RAIL,
              anchor='w').pack(fill='x', padx=T.S5, pady=(T.S3, T.S2))
        nav = tk.Frame(rail, bg=T.RAIL)
        nav.pack(fill='x', padx=px(14))
        for key, title, icon in NAV:
            item = NavItem(nav, key, title, icon, self.show_page, bg=T.RAIL)
            item.pack(fill='x', pady=px(2))
            self.nav[key] = item

        tk.Frame(rail, bg=T.RAIL).pack(fill='both', expand=True)

        foot = Card(rail, fill=T.SURFACE, border=T.LINE, pad=T.S3, bg=T.RAIL)
        foot.pack(fill='x', padx=px(14), pady=(0, T.S3))
        row = tk.Frame(foot.body, bg=T.SURFACE)
        row.pack(fill='x')
        label(row, 'INSTALLIERT', 9, 'bold', fg=T.MUTE, bg=T.SURFACE,
              anchor='w').pack(side='left')
        self.sidebar_update = Pill(row, 'aktuell', T.OK, T.TINT_OK, bg=T.SURFACE, size=10)
        self.sidebar_update.pack(side='right')
        label(foot.body, 'v' + current_version(), 15, 'bold', fg=T.ACCENT_HI,
              bg=T.SURFACE, anchor='w').pack(fill='x', pady=(px(2), 0))

        note = tk.Frame(rail, bg=T.RAIL)
        note.pack(fill='x', padx=px(18), pady=(0, T.S4))
        guard = tk.Canvas(note, width=px(14), height=px(14), bg=T.RAIL, bd=0,
                          highlightthickness=0)
        guard.pack(side='left', pady=(px(2), 0))
        draw_icon(guard, 'shield', px(7), px(7), px(13), T.MUTE)
        label(note, 'Keine Game-Mods · Daten nur auf deinem Pi', 10, fg=T.MUTE,
              bg=T.RAIL, anchor='w', justify='left',
              wraplength=T.SIDEBAR - px(56)).pack(side='left', padx=(px(6), 0))

    def build_topbar(self, parent):
        bar = tk.Frame(parent, bg=T.BG, height=T.TOPBAR)
        bar.pack(fill='x', side='top')
        bar.pack_propagate(False)
        left = tk.Frame(bar, bg=T.BG)
        left.pack(side='left', fill='y', padx=(T.S6, 0), pady=T.S3)
        self.page_title = tk.StringVar(value='Dashboard')
        self.page_sub = tk.StringVar(value='')
        tk.Label(left, textvariable=self.page_title, bg=T.BG, fg=T.TEXT,
                 font=font(20, 'bold'), anchor='w').pack(fill='x')
        tk.Label(left, textvariable=self.page_sub, bg=T.BG, fg=T.MUTE,
                 font=font(11), anchor='w').pack(fill='x')

        right = tk.Frame(bar, bg=T.BG)
        right.pack(side='right', fill='y', padx=(0, T.S6), pady=px(14))
        IconButton(right, 'gear', lambda: self.show_page('settings'),
                   bg=T.BG, tip='Einstellungen').pack(side='right')
        IconButton(right, 'external', self.open_dashboard, bg=T.BG,
                   tip='Web-Dashboard öffnen').pack(side='right', padx=(0, px(6)))
        self.round_pill = Pill(right, 'Keine Runde', T.DIM, T.SURFACE_2, icon='film',
                               bg=T.BG)
        self.round_pill.pack(side='right', padx=(0, T.S3))
        self.conn_pill = Pill(right, 'Nicht verbunden', T.MUTE, T.SURFACE_2, bg=T.BG)
        self.conn_pill.pack(side='right', padx=(0, T.S2))

    def build_statusbar(self, parent):
        tk.Frame(parent, bg=T.LINE_SOFT, height=1).pack(side='bottom', fill='x')
        bar = tk.Frame(parent, bg=T.BG, height=T.STATUSBAR)
        bar.pack(side='bottom', fill='x')
        bar.pack_propagate(False)
        dot = tk.Canvas(bar, width=px(10), height=px(10), bg=T.BG, bd=0,
                        highlightthickness=0)
        dot.pack(side='left', padx=(T.S6, px(8)))
        self.status_dot = dot
        self._paint_status_dot(T.MUTE)
        self.status_var = tk.StringVar(value='Bereit · trage unter Einstellungen deine Verbindung ein.')
        self.status_label = tk.Label(bar, textvariable=self.status_var, bg=T.BG,
                                     fg=T.DIM, font=font(11), anchor='w')
        self.status_label.pack(side='left', fill='x', expand=True)
        tk.Label(bar, text='Lokal ausgewertet · es werden nur Zählwerte synchronisiert.',
                 bg=T.BG, fg=T.MUTE, font=font(11)).pack(side='right', padx=(0, T.S6))

    def _paint_status_dot(self, color):
        self.status_dot.delete('all')
        r = px(4)
        self.status_dot.create_oval(px(5) - r, px(5) - r, px(5) + r, px(5) + r,
                                    fill=color, outline='')

    def _wheel(self, event):
        page = self.pages.get(self.active)
        if page is not None:
            page.on_wheel(event)

    def show_page(self, key):
        if key == self.active or key not in self.pages:
            return
        if self.active:
            self.pages[self.active].pack_forget()
        self.pages[key].pack(fill='both', expand=True)
        self.active = key
        title, subtitle = PAGE_META[key]
        self.page_title.set(title)
        self.page_sub.set(subtitle)
        for nav_key, item in self.nav.items():
            item.set_active(nav_key == key)
        if key != 'settings':
            for field in self.fields.values():
                field.hide_secret()

    def page_body(self, key, max_width=None):
        """Padded content column inside a page's scroll area.

        `max_width` keeps long form pages at a readable measure on wide screens
        instead of stretching inputs across the whole window.
        """
        page = self.pages[key]
        holder = tk.Frame(page.inner, bg=T.BG)
        holder.pack(fill='both', expand=True, padx=T.S6, pady=(T.S2, T.S6))
        if max_width:
            limit = px(max_width)

            def fit(event):
                extra = max(0, (event.width - 2 * T.S6 - limit)) // 2
                holder.pack_configure(padx=T.S6 + extra)

            page.canvas.bind('<Configure>', fit, add='+')
        return holder

    # ---- reusable rows -------------------------------------------------
    def member_row(self, parent, member, total, rank, compact=False):
        """One squad player: identity, reliability, count and contribution."""
        verified = member.get('verified_chests')
        count = verified if verified is not None else member.get('live_chests', 0)
        online = bool(member.get('online'))
        tone = T.OK if verified is not None else (T.CYAN if online else T.MUTE)
        card = Card(parent, fill=T.SURFACE_2, border=T.LINE_SOFT, pad=T.S3,
                    radius=T.R_TILE, bg=parent.cget('bg'))
        card.pack(fill='x', pady=(0, px(6)))
        body = card.body
        head = tk.Frame(body, bg=T.SURFACE_2)
        head.pack(fill='x')

        name = str(member.get('name', 'Spieler'))[:28] or 'Spieler'
        avatar = tk.Canvas(head, width=px(34), height=px(34), bg=T.SURFACE_2, bd=0,
                           highlightthickness=0)
        avatar.pack(side='left')
        tint = (T.TINT_ACCENT, T.TINT_CYAN, T.TINT_VIOLET, T.TINT_OK)[rank % 4]
        edge = (T.ACCENT, T.CYAN, T.VIOLET, T.OK)[rank % 4]
        if not online and verified is None:
            tint, edge = T.SURFACE_3, T.MUTE
        avatar.create_oval(px(1), px(1), px(33), px(33), fill=tint, outline=edge)
        avatar.create_text(px(17), px(17.5), text=name[:1].upper(), fill=edge,
                           font=font(14, 'bold'))
        if online:
            avatar.create_oval(px(24), px(24), px(33), px(33), fill=T.OK,
                               outline=T.SURFACE_2, width=px(2))

        ident = tk.Frame(head, bg=T.SURFACE_2)
        ident.pack(side='left', fill='x', expand=True, padx=(T.S3, T.S3))
        label(ident, name, 13, 'bold', bg=T.SURFACE_2, anchor='w').pack(fill='x')
        state = 'Replay bestätigt' if verified is not None else (
            'Live-Schätzung' if online else 'Offline · keine Daten')
        label(ident, state, 11, fg=tone, bg=T.SURFACE_2, anchor='w').pack(fill='x')

        numbers = tk.Frame(head, bg=T.SURFACE_2)
        numbers.pack(side='right')
        label(numbers, str(count), 22, 'bold', fg=tone, bg=T.SURFACE_2,
              anchor='e').pack(anchor='e')
        label(numbers, 'Kisten', 10, fg=T.MUTE, bg=T.SURFACE_2, anchor='e').pack(anchor='e')

        share = (count / total) if total else 0.0
        bottom = tk.Frame(body, bg=T.SURFACE_2)
        bottom.pack(fill='x', pady=(px(6) if compact else px(10), 0))
        meter = Meter(bottom, tone=edge, bg=T.SURFACE_2, track=T.SURFACE_3)
        meter.pack(side='left', fill='x', expand=True, pady=(px(5), 0))
        meter.set(share)
        label(bottom, f'{share * 100:.0f} %', 11, 'bold', fg=T.DIM, bg=T.SURFACE_2,
              width=6, anchor='e').pack(side='right', padx=(T.S3, 0))

        extras = []
        if compact:
            return card
        if member.get('ammo'):
            extras.append(f"{member['ammo']} Munition")
        if member.get('food'):
            extras.append(f"{member['food']} Obst")
        if member.get('destroyed'):
            extras.append(f"{member['destroyed']} zerstört")
        if member.get('verified_treasures'):
            extras.append(f"{member['verified_treasures']} Belohnungen")
        if extras:
            label(body, '  ·  '.join(extras), 11, fg=T.MUTE, bg=T.SURFACE_2,
                  anchor='w').pack(fill='x', pady=(px(8), 0))
        return card

    def render_members(self, container, members, key, limit=4, total=None,
                       compact=False):
        snapshot = json.dumps([members, limit, compact], ensure_ascii=False,
                              sort_keys=True, default=str)
        if self._hash.get(key) == snapshot:
            return
        self._hash[key] = snapshot
        for child in container.winfo_children():
            child.destroy()
        if not members:
            self.empty_state(container, 'users', 'Noch kein Spieler in dieser Runde',
                             'Sobald ein Squad-Mitglied ein Match startet oder SquadLoot '
                             'verbindet, erscheint es hier.')
            return
        if total is None:
            total = aggregate(members)['chests']
        for index, member in enumerate(members[:limit]):
            self.member_row(container, member, total, index, compact=compact)
        if len(members) > limit:
            label(container, f'+ {len(members) - limit} weitere im Squad-Tab', 11,
                  fg=T.MUTE, bg=container.cget('bg'), anchor='w').pack(fill='x',
                                                                       pady=(px(4), 0))

    def empty_state(self, parent, icon, title, text):
        bg = parent.cget('bg')
        holder = tk.Frame(parent, bg=bg)
        holder.pack(fill='x', pady=T.S5)
        art = tk.Canvas(holder, width=px(44), height=px(44), bg=bg, bd=0,
                        highlightthickness=0)
        art.pack()
        round_rect(art, px(2), px(2), px(42), px(42), px(14), T.SURFACE_2, T.LINE)
        draw_icon(art, icon, px(22), px(22), px(20), T.MUTE)
        label(holder, title, 13, 'bold', fg=T.DIM, bg=bg).pack(pady=(T.S3, px(4)))
        label(holder, text, 11, fg=T.MUTE, bg=bg, wraplength=px(420),
              justify='center').pack()
        return holder

    def metric_chip(self, parent, icon, value, caption, tone=T.DIM, bg=None):
        bg = bg or parent.cget('bg')
        chip = tk.Frame(parent, bg=bg)
        art = tk.Canvas(chip, width=px(15), height=px(15), bg=bg, bd=0,
                        highlightthickness=0)
        art.pack(side='left', pady=(px(2), 0))
        draw_icon(art, icon, px(7.5), px(7.5), px(14), tone)
        label(chip, f'{value}', 12, 'bold', bg=bg, anchor='w').pack(side='left',
                                                                    padx=(px(6), px(4)))
        label(chip, caption, 11, fg=T.MUTE, bg=bg, anchor='w').pack(side='left')
        return chip

    # ---- dashboard -----------------------------------------------------
    def build_dashboard(self):
        page = self.page_body('dashboard')

        top = tk.Frame(page, bg=T.BG)
        top.pack(fill='x', pady=(T.S4, T.S3))
        self.stats = {}
        cards = (
            ('mine', 'Deine Kisten', 'chest', T.ACCENT, T.TINT_ACCENT),
            ('squad', 'Squad gesamt', 'users', T.CYAN, T.TINT_CYAN),
            ('verified', 'Matches', 'check', T.OK, T.TINT_OK),
            ('round', 'Aktuelle Runde', 'film', T.VIOLET, T.TINT_VIOLET),
        )
        for i, (key, title, icon, tone, tint) in enumerate(cards):
            card = StatCard(top, title, icon, tone, tint)
            card.grid(row=0, column=i, sticky='nsew', padx=(0 if i == 0 else T.S3, 0))
            top.grid_columnconfigure(i, weight=1, uniform='stat')
            self.stats[key] = card

        mini = tk.Frame(page, bg=T.BG)
        mini.pack(fill='x', pady=(0, T.S4))
        self.minis = {}
        tiles = (
            ('ammo', 'Munitionskisten', 'ammo', T.WARN, T.TINT_WARN),
            ('food', 'Obstkisten', 'food', T.OK, T.TINT_OK),
            ('destroyed', 'Zerstörte Truhen', 'burst', T.BAD, T.TINT_BAD),
            ('treasures', 'Belohnungen', 'gem', T.VIOLET, T.TINT_VIOLET),
        )
        for i, (key, title, icon, tone, tint) in enumerate(tiles):
            tile = MiniStat(mini, title, icon, tone, tint, bg=T.BG)
            tile.grid(row=0, column=i, sticky='nsew', padx=(0 if i == 0 else T.S3, 0))
            mini.grid_columnconfigure(i, weight=1, uniform='mini')
            self.minis[key] = tile

        middle = tk.Frame(page, bg=T.BG)
        middle.pack(fill='both', expand=True)
        middle.grid_columnconfigure(0, weight=3, uniform='mid')
        middle.grid_columnconfigure(1, weight=2, uniform='mid')
        middle.grid_rowconfigure(0, weight=1)

        squad = Card(middle)
        squad.grid(row=0, column=0, sticky='nsew', padx=(0, T.S3))
        head = section_head(squad.body, 'Squad in dieser Runde',
                            'Bestätigte Replay-Werte ersetzen die Live-Schätzung.')
        self.squad_pill = Pill(head, 'wartet', T.MUTE, T.SURFACE_2, bg=T.SURFACE)
        self.squad_pill.pack(side='right')
        self.dash_members = tk.Frame(squad.body, bg=T.SURFACE)
        self.dash_members.pack(fill='both', expand=True)

        side = tk.Frame(middle, bg=T.BG)
        side.grid(row=0, column=1, sticky='nsew')

        status = Card(side)
        status.pack(fill='x')
        section_head(status.body, 'Live-Status', 'Was gerade gezählt wird.')
        self.dash_state = Pill(status.body, 'Tracking inaktiv', T.MUTE, T.SURFACE_2,
                               bg=T.SURFACE)
        self.dash_state.pack(anchor='w')
        self.dash_counts = tk.StringVar(value='0 automatisch erkannt')
        tk.Label(status.body, textvariable=self.dash_counts, bg=T.SURFACE, fg=T.TEXT,
                 font=font(13), anchor='w').pack(fill='x', pady=(T.S3, 0))
        self.dash_event = tk.StringVar(value='Noch kein erkanntes Ereignis.')
        tk.Label(status.body, textvariable=self.dash_event, bg=T.SURFACE, fg=T.MUTE,
                 font=font(11), anchor='w', justify='left',
                 wraplength=px(300)).pack(fill='x', pady=(px(2), T.S3))
        row = tk.Frame(status.body, bg=T.SURFACE)
        row.pack(fill='x')
        Button(row, 'Live-Tracking', lambda: self.show_page('live'), 'secondary',
               icon='target', bg=T.SURFACE).pack(side='left')

        actions = Card(side)
        actions.pack(fill='x', pady=(T.S3, 0))
        section_head(actions.body, 'Schnellaktionen', 'Runde, Replay und Ansichten.')
        grid = tk.Frame(actions.body, bg=T.SURFACE)
        grid.pack(fill='x')
        quick = (
            ('Neue Squad-Runde', self.start_round, 'spark'),
            ('Replay auswerten', self.run_chestcounter, 'film'),
            ('In-Game-HUD', self.toggle_overlay, 'layout'),
            ('Web-Dashboard', self.open_dashboard, 'external'),
        )
        for i, (title, callback, icon) in enumerate(quick):
            Button(grid, title, callback, 'secondary', icon=icon, bg=T.SURFACE).grid(
                row=i // 2, column=i % 2, sticky='ew', padx=(0 if i % 2 == 0 else px(6), 0),
                pady=px(3))
        grid.grid_columnconfigure(0, weight=1)
        grid.grid_columnconfigure(1, weight=1)

        recent = Card(side)
        recent.pack(fill='x', pady=(T.S3, 0))
        head = section_head(recent.body, 'Letzte Runden',
                            'Nach der Replay-Auswertung verbindlich.')
        Button(head, 'Alle ansehen', lambda: self.show_page('history'), 'ghost',
               small=True, bg=T.SURFACE).pack(side='right')
        self.dash_history = tk.Frame(recent.body, bg=T.SURFACE)
        self.dash_history.pack(fill='x')

    # ---- live tracking -------------------------------------------------
    def build_live(self):
        page = self.page_body('live', max_width=890)
        panel = Card(page, fill=T.SURFACE, accent=T.ACCENT)
        panel.pack(fill='x', pady=(T.S4, T.S3))
        header = tk.Frame(panel.body, bg=T.SURFACE)
        header.pack(fill='x')
        label(header, 'Live-Tracking', 18, 'bold', bg=T.SURFACE,
              anchor='w').pack(side='left')
        self.live_state = Pill(header, 'Replay automatisch', T.CYAN, T.TINT_CYAN,
                               bg=T.SURFACE)
        self.live_state.pack(side='right')
        bar = tk.Frame(panel.body, bg=T.SURFACE)
        bar.pack(fill='x', pady=(T.S4, T.S4))
        self.live_tiles = {}
        for i, (key, title, icon, tone, tint) in enumerate((
                ('vision', 'Deine Kisten', 'chest', T.ACCENT, T.TINT_ACCENT),
                ('squad', 'Squad gesamt', 'users', T.CYAN, T.TINT_CYAN),
                ('verified', 'Replay bestätigt', 'check', T.OK, T.TINT_OK))):
            tile = MiniStat(bar, title, icon, tone, tint, bg=T.SURFACE)
            tile.grid(row=0, column=i, sticky='nsew',
                      padx=(0 if i == 0 else px(6), 0))
            bar.grid_columnconfigure(i, weight=1, uniform='live')
            self.live_tiles[key] = tile
        self.live_button = Button(panel.body, 'Live-Test starten',
                                  self.toggle_integrated_live, 'primary',
                                  icon='play', bg=T.SURFACE)
        self.live_button.pack(anchor='w')
        self.live_info = tk.StringVar(value='Replays werden automatisch ausgewertet. Live ist optional.')
        tk.Label(panel.body, textvariable=self.live_info, bg=T.SURFACE,
                 fg=T.MUTE, font=font(11), anchor='w', justify='left',
                 wraplength=px(780)).pack(fill='x', pady=(T.S3, 0))

    # ---- match history -------------------------------------------------
    def build_history(self):
        page = self.page_body('history')
        summary = tk.Frame(page, bg=T.BG)
        summary.pack(fill='x', pady=(T.S4, T.S3))
        self.history_stats = {}
        tiles = (
            ('matches', 'Bestätigte Matches', 'check', T.OK, T.TINT_OK),
            ('chests', 'Truhen gesamt', 'chest', T.ACCENT, T.TINT_ACCENT),
            ('treasures', 'Belohnungen', 'gem', T.VIOLET, T.TINT_VIOLET),
            ('ammo', 'Munitionskisten', 'ammo', T.WARN, T.TINT_WARN),
        )
        for i, (key, title, icon, tone, tint) in enumerate(tiles):
            tile = MiniStat(summary, title, icon, tone, tint, bg=T.BG)
            tile.grid(row=0, column=i, sticky='nsew', padx=(0 if i == 0 else T.S3, 0))
            summary.grid_columnconfigure(i, weight=1, uniform='hist')
            self.history_stats[key] = tile

        card = Card(page)
        card.pack(fill='both', expand=True)
        head = section_head(card.body, 'Ausgewertete Runden',
                            'Die letzten 20 Runden, neueste zuerst.')
        Button(head, 'Replays synchronisieren', self.sync_all, 'secondary',
               icon='refresh', small=True, bg=T.SURFACE).pack(side='right')
        self.history_box = tk.Frame(card.body, bg=T.SURFACE)
        self.history_box.pack(fill='both', expand=True)

    def history_row(self, parent, row, compact=False):
        card = Card(parent, fill=T.SURFACE_2, border=T.LINE_SOFT, pad=T.S3,
                    radius=T.R_TILE, bg=parent.cget('bg'))
        card.pack(fill='x', pady=(0, px(6)))
        body = card.body
        head = tk.Frame(body, bg=T.SURFACE_2)
        head.pack(fill='x')
        left = tk.Frame(head, bg=T.SURFACE_2)
        left.pack(side='left', fill='x', expand=True)
        label(left, clock(row.get('started')), 12, 'bold', bg=T.SURFACE_2,
              anchor='w').pack(fill='x')
        names = str(row.get('breakdown') or 'Match')[:110]
        label(left, names, 11, fg=T.MUTE, bg=T.SURFACE_2, anchor='w',
              justify='left').pack(fill='x', pady=(px(2), 0))
        right = tk.Frame(head, bg=T.SURFACE_2)
        right.pack(side='right', padx=(T.S3, 0))
        label(right, str(row.get('chests', 0)), 20, 'bold', fg=T.ACCENT_HI,
              bg=T.SURFACE_2, anchor='e').pack(anchor='e')
        label(right, 'Truhen', 10, fg=T.MUTE, bg=T.SURFACE_2, anchor='e').pack(anchor='e')
        if compact:
            return card
        chips = tk.Frame(body, bg=T.SURFACE_2)
        chips.pack(fill='x', pady=(px(10), 0))
        data = (('users', row.get('players', 0), 'Spieler', T.CYAN),
                ('burst', row.get('destroyed', 0), 'zerstört', T.BAD),
                ('refresh', row.get('reopened', 0), 'erneut geöffnet', T.DIM),
                ('ammo', row.get('ammo', 0), 'Munition', T.WARN),
                ('food', row.get('food', 0), 'Obst', T.OK),
                ('gem', row.get('treasures', 0), 'Belohnungen', T.VIOLET))
        for icon, value, caption, tone in data:
            self.metric_chip(chips, icon, value, caption, tone,
                             bg=T.SURFACE_2).pack(side='left', padx=(0, px(14)))
        return card

    def render_history(self, container, history, key, limit=20, compact=False):
        snapshot = json.dumps(history[:limit], ensure_ascii=False, sort_keys=True,
                              default=str)
        if self._hash.get(key) == snapshot:
            return
        self._hash[key] = snapshot
        for child in container.winfo_children():
            child.destroy()
        if not history:
            self.empty_state(container, 'film', 'Noch keine ausgewertete Runde',
                             'Starte ChestCounter nach dem Match oder klicke auf '
                             '„Replay auswerten“. Danach erscheinen hier bestätigte Werte.')
            return
        for row in history[:limit]:
            self.history_row(container, row, compact=compact)

    # ---- squad ---------------------------------------------------------
    def build_squad(self):
        page = self.page_body('squad')
        card = Card(page)
        card.pack(fill='x', pady=(T.S4, T.S3))
        head = section_head(card.body, 'Aktuelle Runde',
                            'Beitrag jedes Spielers zum Squad-Ergebnis.')
        self.squad_total_pill = Pill(head, '0 Truhen', T.ACCENT, T.TINT_ACCENT,
                                     icon='chest', bg=T.SURFACE)
        self.squad_total_pill.pack(side='right')
        self.squad_members = tk.Frame(card.body, bg=T.SURFACE)
        self.squad_members.pack(fill='both', expand=True)

        accounts = Card(page)
        accounts.pack(fill='both', expand=True)
        section_head(accounts.body, 'Accounts & Gesamtstatistik',
                     'Jeder Epic-Account wird getrennt geführt.')
        self.account_box = tk.Frame(accounts.body, bg=T.SURFACE)
        self.account_box.pack(fill='both', expand=True)

    def render_accounts(self, accounts):
        snapshot = json.dumps(accounts, ensure_ascii=False, sort_keys=True, default=str)
        if self._hash.get('accounts') == snapshot:
            return
        self._hash['accounts'] = snapshot
        for child in self.account_box.winfo_children():
            child.destroy()
        if not accounts:
            self.empty_state(self.account_box, 'user', 'Noch keine Account-Statistik',
                             'Nach der ersten Replay-Auswertung erscheint hier jeder '
                             'Account mit Truhen, Munition und Belohnungen.')
            return
        best = max((a.get('chests') or 0) for a in accounts) or 1
        for index, account in enumerate(accounts[:12]):
            card = Card(self.account_box, fill=T.SURFACE_2, border=T.LINE_SOFT,
                        pad=T.S3, radius=T.R_TILE, bg=T.SURFACE)
            card.pack(fill='x', pady=(0, px(6)))
            head = tk.Frame(card.body, bg=T.SURFACE_2)
            head.pack(fill='x')
            art = tk.Canvas(head, width=px(28), height=px(28), bg=T.SURFACE_2, bd=0,
                            highlightthickness=0)
            art.pack(side='left')
            tone = (T.ACCENT, T.CYAN, T.VIOLET, T.OK)[index % 4]
            tint = (T.TINT_ACCENT, T.TINT_CYAN, T.TINT_VIOLET, T.TINT_OK)[index % 4]
            round_rect(art, 0, 0, px(28), px(28), px(9), tint, mix(tint, tone, .25))
            draw_icon(art, 'user', px(14), px(14), px(15), tone)
            label(head, str(account.get('name', '–'))[:28], 13, 'bold', bg=T.SURFACE_2,
                  anchor='w').pack(side='left', padx=(T.S3, 0))
            matches = account.get('matches') or 0
            chests = account.get('chests') or 0
            label(head, f'{chests}', 17, 'bold', fg=tone, bg=T.SURFACE_2,
                  anchor='e').pack(side='right')
            meter = Meter(card.body, tone=tone, bg=T.SURFACE_2, track=T.SURFACE_3)
            meter.pack(fill='x', pady=(px(10), px(8)))
            meter.set(chests / best if best else 0)
            chips = tk.Frame(card.body, bg=T.SURFACE_2)
            chips.pack(fill='x')
            average = (chests / matches) if matches else 0
            for icon, value, caption, chip_tone in (
                    ('film', matches, 'Matches', T.CYAN),
                    ('spark', f'{average:.1f}', 'Ø pro Match', T.ACCENT),
                    ('ammo', account.get('ammo') or 0, 'Munition', T.WARN),
                    ('food', account.get('food') or 0, 'Obst', T.OK),
                    ('gem', account.get('treasures') or 0, 'Belohnungen', T.VIOLET)):
                self.metric_chip(chips, icon, value, caption, chip_tone,
                                 bg=T.SURFACE_2).pack(side='left', padx=(0, px(14)))

    # ---- settings ------------------------------------------------------
    def settings_section(self, parent, title, subtitle, icon, tone, tint):
        card = Card(parent)
        card.pack(fill='x', pady=(0, T.S3))
        head = tk.Frame(card.body, bg=T.SURFACE)
        head.pack(fill='x', pady=(0, T.S4))
        badge = tk.Canvas(head, width=px(30), height=px(30), bg=T.SURFACE, bd=0,
                          highlightthickness=0)
        badge.pack(side='left')
        round_rect(badge, 0, 0, px(30), px(30), px(10), tint, mix(tint, tone, .25))
        draw_icon(badge, icon, px(15), px(15), px(16), tone)
        text = tk.Frame(head, bg=T.SURFACE)
        text.pack(side='left', fill='x', expand=True, padx=(T.S3, 0))
        label(text, title, 15, 'bold', bg=T.SURFACE, anchor='w').pack(fill='x')
        label(text, subtitle, 11, fg=T.MUTE, bg=T.SURFACE, anchor='w',
              justify='left').pack(fill='x', pady=(px(2), 0))
        return card.body

    def add_field(self, parent, key, title, hint='', secret=False, browse=None):
        field = Field(parent, title, self.core.config.get(key, ''), secret=secret,
                      hint=hint, browse=browse)
        field.pack(fill='x', pady=(0, T.S3))
        self.fields[key] = field
        return field

    def build_settings(self):
        page = self.page_body('settings', max_width=900)
        tk.Frame(page, bg=T.BG, height=T.S4).pack(fill='x')

        body = self.settings_section(
            page, 'Server-Verbindung', 'Deine eigene SquadLoot-Instanz auf dem Pi.',
            'cloud', T.CYAN, T.TINT_CYAN)
        self.add_field(body, 'server_url', 'Server-URL (HTTPS)',
                       'z. B. https://loot.example.net — HTTP nur für private IPs.')
        self.add_field(body, 'token', 'Squad-Token', 'Mindestens 24 Zeichen. '
                       'Identisch mit SQUAD_TOKEN auf dem Pi.', secret=True)
        row = tk.Frame(body, bg=T.SURFACE)
        row.pack(fill='x', pady=(px(4), 0))
        Button(row, 'Verbindung testen', self.test_connection, 'secondary',
               icon='signal', bg=T.SURFACE).pack(side='left')
        self.conn_test = Pill(row, 'nicht geprüft', T.MUTE, T.SURFACE_2, bg=T.SURFACE)
        self.conn_test.pack(side='left', padx=(T.S3, 0))

        body = self.settings_section(
            page, 'Cloudflare Access', 'Nur nötig, wenn dein Tunnel Access erzwingt. '
            'Beide Felder zusammen ausfüllen oder beide leer lassen.',
            'key', T.VIOLET, T.TINT_VIOLET)
        self.add_field(body, 'cf_access_client_id', 'Access Client-ID',
                       'Service-Token-ID aus dem Cloudflare-Dashboard.')
        self.add_field(body, 'cf_access_client_secret', 'Access Client-Secret',
                       'Wird maskiert gespeichert und nie protokolliert.', secret=True)

        body = self.settings_section(
            page, 'Epic-Account', 'Der Name, unter dem dich dein Squad live sieht.',
            'user', T.ACCENT, T.TINT_ACCENT)
        self.add_field(body, 'name', 'Live-Anzeigename',
                       'Beim Accountwechsel hier anpassen — Replays bringen den '
                       'echten Namen ohnehin mit.')

        body = self.settings_section(
            page, 'Replays & ChestCounter', 'Lokale Pfade. Replay-Dateien verlassen '
            'deinen PC nicht.', 'film', T.OK, T.TINT_OK)
        self.add_field(body, 'replay_dir', 'Fortnite Replay-Ordner',
                       'Standard: %LOCALAPPDATA%\\FortniteGame\\Saved\\Demos',
                       browse=lambda: self.pick_directory('replay_dir'))
        self.build_hud_settings(page)

        body = self.settings_section(
            page, 'Updates', 'Neue Versionen kommen ausschließlich von deinem Pi.',
            'download', T.CYAN, T.TINT_CYAN)
        self.autoupdate = Toggle(body, 'Automatisch nach Updates suchen',
                                 bool(self.core.config.get('auto_update', True)),
                                 self.toggle_autoupdate, bg=T.SURFACE)
        self.autoupdate.pack(anchor='w')

        actions = Card(page, fill=T.SURFACE, border=T.LINE_STRONG)
        actions.pack(fill='x', pady=(T.S2, 0))
        row = tk.Frame(actions.body, bg=T.SURFACE)
        row.pack(fill='x')
        Button(row, 'Speichern & verbinden', self.connect, 'primary', icon='check',
               bg=T.SURFACE).pack(side='left')
        Button(row, 'Alle Replays synchronisieren', self.sync_all, 'secondary',
               icon='refresh', bg=T.SURFACE).pack(side='left', padx=(px(6), 0))
        self.settings_note = tk.StringVar(
            value='Zugangsdaten bleiben auf diesem PC in %APPDATA%\\SquadLootClient.')
        tk.Label(actions.body, textvariable=self.settings_note, bg=T.SURFACE, fg=T.MUTE,
                 font=font(11), anchor='w', justify='left').pack(fill='x',
                                                                 pady=(T.S3, 0))

    def build_hud_settings(self, page):
        """Overlay configuration: visibility, mode, opacity, scale, lock, keys."""
        body = self.settings_section(
            page, 'In-Game-HUD', 'Kleines Overlay über Fortnite — nur die Zahlen, '
            'kein zweites Fenster. Für Vollbild im Fenstermodus spielen.',
            'layout', T.ACCENT, T.TINT_ACCENT)

        switches = tk.Frame(body, bg=T.SURFACE)
        switches.pack(fill='x')
        self.hud_toggle = Toggle(switches, 'HUD anzeigen', self.hud.visible,
                                 self.hud.set_enabled, bg=T.SURFACE)
        self.hud_toggle.pack(anchor='w')
        self.hud_expanded = Toggle(
            switches, 'Erweitert: Spieler einzeln anzeigen',
            self.hud.opt('hud_mode') == 'expanded',
            lambda value: self.hud.set_mode('expanded' if value else 'compact'),
            bg=T.SURFACE)
        self.hud_expanded.pack(anchor='w', pady=(T.S3, 0))
        self.hud_lock = Toggle(
            switches, 'Position gesperrt (Klicks gehen ins Spiel)',
            bool(self.hud.opt('hud_locked')), self.hud.set_locked, bg=T.SURFACE)
        self.hud_lock.pack(anchor='w', pady=(T.S3, 0))

        sliders = tk.Frame(body, bg=T.SURFACE)
        sliders.pack(fill='x', pady=(T.S4, 0))
        sliders.grid_columnconfigure(1, weight=1)
        self.hud_opacity_var = tk.StringVar()
        self.hud_scale_var = tk.StringVar()

        def opacity_changed(value):
            self.hud_opacity_var.set(f'{value * 100:.0f} %')
            self.core.config['hud_opacity'] = round(float(value), 2)
            self.hud.apply_opacity()

        def scale_changed(value):
            self.hud_scale_var.set(f'{value * 100:.0f} %')
            self.core.config['hud_scale'] = round(float(value), 2)
            self.hud.redraw(force=True)

        rows = (
            ('Deckkraft', 'hud_opacity', 0.35, 1.0, 0.01, opacity_changed,
             self.hud_opacity_var),
            ('Größe', 'hud_scale', 0.8, 1.6, 0.05, scale_changed, self.hud_scale_var),
        )
        for index, (title, key, low, high, step, handler, var) in enumerate(rows):
            label(sliders, title, 12, fg=T.DIM, bg=T.SURFACE, anchor='w',
                  width=10).grid(row=index, column=0, sticky='w', pady=px(4))
            slider = Slider(sliders, self.hud.opt(key), low, high, step,
                            command=handler,
                            commit=lambda value, k=key: self.core.set_config({k: round(float(value), 2)}),
                            bg=T.SURFACE)
            slider.grid(row=index, column=1, sticky='ew', padx=T.S3, pady=px(4))
            tk.Label(sliders, textvariable=var, bg=T.SURFACE, fg=T.TEXT,
                     font=font(12, 'bold'), width=6, anchor='e').grid(
                         row=index, column=2, sticky='e')
            handler(slider.get())

        actions = tk.Frame(body, bg=T.SURFACE)
        actions.pack(fill='x', pady=(T.S4, 0))
        Button(actions, 'Position zurücksetzen', self.hud.reset_position, 'secondary',
               icon='refresh', bg=T.SURFACE).pack(side='left')
        Button(actions, 'Vorschau', self.preview_hud, 'ghost', icon='eye',
               bg=T.SURFACE).pack(side='left', padx=(px(6), 0))
        Button(actions, 'HUD prüfen', self.diagnose_hud, 'ghost', icon='shield',
               bg=T.SURFACE).pack(side='left', padx=(px(6), 0))

        divider(body)
        label(body, 'Globale Tastenkürzel (optional)', 12, 'bold', fg=T.DIM,
              bg=T.SURFACE, anchor='w').pack(fill='x', pady=(0, T.S3))
        for key, title, hint in (
                ('hud_hotkey_toggle', 'HUD anzeigen / ausblenden',
                 'Leer lassen deaktiviert das Kürzel. Mindestens Strg, Alt oder Shift.'),
                ('hud_hotkey_lock', 'Sperren / entsperren',
                 'Zum Verschieben kurz entsperren.'),
                ('hud_hotkey_mode', 'Kompakt / erweitert',
                 'Wechselt zwischen beiden HUD-Modi.')):
            field = Field(body, title, self.hud.opt(key), hint=hint)
            field.pack(fill='x', pady=(0, T.S3))
            self.hud_fields[key] = field
        Button(body, 'Kürzel übernehmen', self.apply_hotkeys, 'secondary',
               icon='check', bg=T.SURFACE).pack(anchor='w')

        self.hud_note = tk.StringVar(value='')
        tk.Label(body, textvariable=self.hud_note, bg=T.SURFACE, fg=T.MUTE,
                 font=font(11), anchor='w', justify='left',
                 wraplength=px(780)).pack(fill='x', pady=(T.S3, 0))
        self.sync_hud_controls()

    def preview_hud(self):
        """Make a mapped HUD visible again; do not only repaint a hidden HWND."""
        if not self.hud.visible:
            self.hud.set_enabled(True)
        else:
            self.hud.redraw(force=True)
            self.hud.bring_to_front()

    def diagnose_hud(self):
        """Diagnose window mapping without displaying credentials or filenames."""
        self.preview_hud()
        win = self.hud.win
        if win is None:
            messagebox.showwarning('HUD-Diagnose', 'Kein HUD-Fenster vorhanden.')
            return
        try:
            self.root.update_idletasks()
            width, height = self.hud._size
            lines = [
                'SquadLoot ' + current_version(),
                'Fensterstatus: ' + str(win.state()),
                'Windows/Tk sichtbar: ' + str(bool(win.winfo_viewable())),
                'Gemappt: ' + str(bool(win.winfo_ismapped())),
                'Position: ' + str(win.winfo_x()) + ', ' + str(win.winfo_y()),
                'Groesse: ' + str(width) + ' x ' + str(height),
                'Deckkraft: ' + str(win.attributes('-alpha')),
                'Gesperrt: ' + str(bool(self.hud.opt('hud_locked'))),
                'Hauptmonitor: ' + str(Win32.primary_screen()),
                'Virtueller Bildschirm: ' + str(self.hud.screen_box()),
                'Win32 HWND: ' + str(Win32.handle(win)),
            ]
            messagebox.showinfo('SquadLoot HUD-Diagnose', '\n'.join(lines),
                                parent=self.root)
        except tk.TclError as exc:
            messagebox.showwarning('HUD-Diagnose',
                                   'HUD-Fenster kann nicht abgefragt werden: ' + str(exc))

    # ---- updates -------------------------------------------------------
    def build_updates(self):
        page = self.page_body('updates', max_width=1040)
        top = tk.Frame(page, bg=T.BG)
        top.pack(fill='x', pady=(T.S4, T.S3))

        installed = Card(top)
        installed.grid(row=0, column=0, sticky='nsew', padx=(0, T.S3))
        label(installed.body, 'INSTALLIERTE VERSION', 10, 'bold', fg=T.MUTE,
              bg=T.SURFACE, anchor='w').pack(fill='x')
        label(installed.body, 'v' + current_version(), 26, 'bold', fg=T.TEXT,
              bg=T.SURFACE, anchor='w').pack(fill='x', pady=(px(6), 0))
        label(installed.body, 'Läuft gerade', 11, fg=T.MUTE, bg=T.SURFACE,
              anchor='w').pack(fill='x')

        available = Card(top, accent=T.ACCENT)
        available.grid(row=0, column=1, sticky='nsew', padx=(0, T.S3))
        label(available.body, 'VERFÜGBARE VERSION', 10, 'bold', fg=T.MUTE,
              bg=T.SURFACE, anchor='w').pack(fill='x')
        self.available_var = tk.StringVar(value='–')
        tk.Label(available.body, textvariable=self.available_var, bg=T.SURFACE,
                 fg=T.ACCENT_HI, font=font(26, 'bold'), anchor='w').pack(fill='x',
                                                                         pady=(px(6), 0))
        self.available_sub = tk.StringVar(value='Noch nicht geprüft')
        tk.Label(available.body, textvariable=self.available_sub, bg=T.SURFACE,
                 fg=T.MUTE, font=font(11), anchor='w').pack(fill='x')

        check = Card(top)
        check.grid(row=0, column=2, sticky='nsew')
        label(check.body, 'LETZTE PRÜFUNG', 10, 'bold', fg=T.MUTE, bg=T.SURFACE,
              anchor='w').pack(fill='x')
        self.lastcheck_var = tk.StringVar(value='nie')
        tk.Label(check.body, textvariable=self.lastcheck_var, bg=T.SURFACE, fg=T.TEXT,
                 font=font(20, 'bold'), anchor='w').pack(fill='x', pady=(px(8), 0))
        label(check.body, 'Prüfung alle 20 Minuten', 11, fg=T.MUTE, bg=T.SURFACE,
              anchor='w').pack(fill='x')
        for i in range(3):
            top.grid_columnconfigure(i, weight=1, uniform='upd')

        status = Card(page)
        status.pack(fill='x', pady=(0, T.S3))
        head = section_head(status.body, 'Update-Status',
                            'Download, Prüfsumme und Installation.')
        self.update_pill = Pill(head, 'bereit', T.MUTE, T.SURFACE_2, bg=T.SURFACE)
        self.update_pill.pack(side='right')
        self.update_status = tk.StringVar(
            value='Noch kein Update heruntergeladen. Die Prüfung läuft im Hintergrund.')
        tk.Label(status.body, textvariable=self.update_status, bg=T.SURFACE, fg=T.TEXT,
                 font=font(12), anchor='w', justify='left',
                 wraplength=px(760)).pack(fill='x')
        self.update_meter = Meter(status.body, tone=T.ACCENT, bg=T.SURFACE)
        self.update_meter.pack(fill='x', pady=(T.S3, 0))
        self.release_notes = tk.StringVar(
            value='Release-Notizen erscheinen hier, sobald eine neue Version bereitliegt.')
        tk.Label(status.body, textvariable=self.release_notes, bg=T.SURFACE, fg=T.DIM,
                 font=font(11), anchor='w', justify='left',
                 wraplength=px(760)).pack(fill='x', pady=(T.S3, 0))
        row = tk.Frame(status.body, bg=T.SURFACE)
        row.pack(fill='x', pady=(T.S4, 0))
        Button(row, 'Jetzt prüfen', lambda: self.check_updates(manual=True), 'primary',
               icon='refresh', bg=T.SURFACE).pack(side='left')
        self.install_btn = Button(row, 'Neu starten & installieren',
                                  self.restart_and_install, 'secondary',
                                  icon='power', bg=T.SURFACE)
        self.install_btn.pack(side='left', padx=(px(6), 0))
        self.install_btn.set_enabled(False)

        info = Card(page)
        info.pack(fill='x')
        section_head(info.body, 'Wie SquadLoot aktualisiert',
                     'Sicher, nachvollziehbar und nie mitten im Match.')
        for icon, tone, tint, title, text in (
                ('shield', T.OK, T.TINT_OK, 'Nur über deine Verbindung',
                 'Updates werden ausschließlich über die konfigurierte HTTPS-/'
                 'Cloudflare-Verbindung zu deinem Pi geladen.'),
                ('check', T.CYAN, T.TINT_CYAN, 'SHA-256 geprüft',
                 'Manifest und Paket müssen übereinstimmen, sonst wird das Update '
                 'verworfen und die laufende Version bleibt aktiv.'),
                ('power', T.WARN, T.TINT_WARN, 'Installation beim nächsten Start',
                 'Heruntergeladene Updates werden erst beim nächsten Start '
                 'installiert. SquadLoot startet nie von selbst neu.')):
            row = tk.Frame(info.body, bg=T.SURFACE)
            row.pack(fill='x', pady=(0, T.S3))
            badge = tk.Canvas(row, width=px(28), height=px(28), bg=T.SURFACE, bd=0,
                              highlightthickness=0)
            badge.pack(side='left', anchor='n')
            round_rect(badge, 0, 0, px(28), px(28), px(9), tint, mix(tint, tone, .25))
            draw_icon(badge, icon, px(14), px(14), px(15), tone)
            text_box = tk.Frame(row, bg=T.SURFACE)
            text_box.pack(side='left', fill='x', expand=True, padx=(T.S3, 0))
            label(text_box, title, 12, 'bold', bg=T.SURFACE, anchor='w').pack(fill='x')
            label(text_box, text, 11, fg=T.MUTE, bg=T.SURFACE, anchor='w',
                  justify='left', wraplength=px(700)).pack(fill='x')

    # ---- settings actions ----------------------------------------------
    def pick_file(self, key, types):
        name = filedialog.askopenfilename(title='Datei wählen',
                                          filetypes=types + [('Alle Dateien', '*.*')])
        if name:
            self.fields[key].set(name)
            self.fields[key].mark('ok', 'Pfad übernommen — noch nicht gespeichert.')

    def pick_directory(self, key):
        name = filedialog.askdirectory(title='Ordner wählen')
        if name:
            self.fields[key].set(name)
            self.fields[key].mark('ok', 'Ordner übernommen — noch nicht gespeichert.')

    def collect_settings(self):
        """Validate every field inline and return the config patch, or None."""
        values = {key: field.get() for key, field in self.fields.items()}
        for field in self.fields.values():
            field.mark('idle')
        ok = True
        try:
            values['server_url'] = validate_url(values['server_url'])
            self.fields['server_url'].mark('ok', 'Gültige Server-Adresse.')
        except ValueError as exc:
            self.fields['server_url'].mark('error', str(exc))
            ok = False
        if len(values['token']) < 24:
            self.fields['token'].mark('error', 'Der Squad-Token ist zu kurz '
                                               '(mindestens 24 Zeichen).')
            ok = False
        if bool(values['cf_access_client_id']) != bool(values['cf_access_client_secret']):
            for key in ('cf_access_client_id', 'cf_access_client_secret'):
                self.fields[key].mark('error', 'Client-ID und Secret müssen beide '
                                               'ausgefüllt oder beide leer sein.')
            ok = False
        if not values['name']:
            self.fields['name'].mark('error', 'Bitte einen Live-Anzeigenamen eintragen.')
            ok = False
        for key, kind in (('replay_dir', 'dir'), ('data_json', 'file'),
                          ('chestcounter_exe', 'file')):
            path = values.get(key, '')
            if not path:
                continue
            exists = Path(path).is_dir() if kind == 'dir' else Path(path).is_file()
            if not exists:
                self.fields[key].mark('warn', 'Pfad existiert noch nicht — wird '
                                              'gespeichert und später erneut geprüft.')
        return values if ok else None

    def connect(self):
        values = self.collect_settings()
        if values is None:
            self.settings_note.set('Bitte die markierten Felder korrigieren.')
            self.set_status('Einstellungen unvollständig.', T.BAD)
            return
        try:
            self.core.set_config(values)
            self.core.start()
        except (ValueError, OSError) as exc:
            self.settings_note.set(str(exc))
            self.set_status('Fehler: ' + str(exc)[:200], T.BAD)
            return
        self.settings_note.set('Gespeichert. Verbindung zu deinem Pi wird aufgebaut …')
        self.set_status('Verbinde mit SquadLoot auf deinem Pi …', T.DIM)
        self.show_page('dashboard')
        self.check_updates()

    def test_connection(self):
        values = self.collect_settings()
        if values is None:
            self.conn_test.set('ungültig', T.BAD, T.TINT_BAD)
            return
        self.conn_test.set('prüfe …', T.DIM, T.SURFACE_2)

        def job():
            try:
                from client_core import Api
                api = Api(values['server_url'], values['token'],
                          values['cf_access_client_id'], values['cf_access_client_secret'])
                state = api.call('/api/state')
                members = ((state.get('round') or {}).get('members') or [])
                self.events.put(('conn_ok', f'{len(members)} Spieler in der Runde'))
            except Exception as exc:  # network/HTTP errors are reported, never raised
                self.events.put(('conn_bad', str(exc)[:180]))

        threading.Thread(target=job, daemon=True, name='SquadLootConnTest').start()

    def connect_automatically(self):
        try:
            self.core.start()
        except (ValueError, OSError) as exc:
            self.set_status(str(exc), T.BAD)

    def toggle_autoupdate(self, enabled):
        self.core.set_config({'auto_update': bool(enabled)})
        self.update_status.set('Automatische Updates sind aktiviert.' if enabled
                               else 'Automatische Updates sind deaktiviert. '
                                    'Du kannst jederzeit manuell prüfen.')
        if enabled:
            self.check_updates()

    # ---- updates -------------------------------------------------------
    def periodic_update_check(self):
        self.check_updates()
        self.root.after(20 * 60 * 1000, self.periodic_update_check)

    def check_updates(self, manual=False):
        if self.update_busy:
            return
        if not manual and not self.core.config.get('auto_update', True):
            return
        if not (self.core.config.get('server_url') and self.core.config.get('token')):
            if manual:
                self.update_status.set('Zuerst Server-URL und Squad-Token unter '
                                       'Einstellungen eintragen.')
                self.update_pill.set('nicht konfiguriert', T.WARN, T.TINT_WARN)
            return
        self.update_busy = True
        self.update_pill.set('prüfe …', T.CYAN, T.TINT_CYAN)
        self.update_status.set('Suche nach einer neuen Version auf deinem Pi …')

        def job():
            try:
                version = check_and_stage(self.core.config)
                self.events.put(('update', version or ''))
            except Exception as exc:  # offline/403: keep running the installed build
                log_error(exc)
                self.events.put(('update_error', str(exc)[:180]))

        threading.Thread(target=job, daemon=True, name='SquadLootUpdateCheck').start()

    def restart_and_install(self):
        if not self.update_pending:
            return
        if messagebox.askyesno('Update installieren',
                               'SquadLoot wird geschlossen und mit Version '
                               f'{self.pending_version} neu gestartet. Jetzt installieren?'):
            here = Path(__file__).resolve().parent
            subprocess.Popen([sys.executable, str(here / 'bootstrap.py')], cwd=str(here))
            self.close()

    # ---- round / replay actions ----------------------------------------
    def job(self, func):
        def runner():
            try:
                self.events.put(('info', str(func())))
            except Exception as exc:
                self.events.put(('error', str(exc)))

        threading.Thread(target=runner, daemon=True).start()

    def sync_all(self):
        self.set_status('Synchronisiere alle Replay-Daten …', T.DIM)
        self.job(lambda: str(self.core.sync_matches(self.core.credentials(),
                                                    max_items=100000))
                 + ' Matches synchronisiert')

    def start_round(self):
        if messagebox.askyesno('Neue Runde',
                               'Eine neue Squad-Runde für alle verbundenen Spieler '
                               'starten? Vorläufige Zähler werden zurückgesetzt.'):
            self.job(lambda: 'Neue Squad-Runde #' + str(self.core.new_round()))

    def run_chestcounter(self):
        self.set_status('Replays werden lokal ausgewertet …', T.DIM)

        def run():
            engine = self.core.replay_engine
            if not engine.scan_once(force=True) and engine.error:
                raise RuntimeError(engine.error)
            count = self.core.sync_matches(self.core.credentials(), max_items=100000)
            return f'{count} Replay-Matches synchronisiert'

        self.job(run)

    def open_dashboard(self):
        url = self.core.config.get('server_url', '')
        if url:
            webbrowser.open(url)
        else:
            messagebox.showwarning('Server fehlt',
                                   'Zuerst unter Einstellungen eine Server-URL eintragen.')
            self.show_page('settings')

    def confirm_reset(self):
        if messagebox.askyesno('Zähler zurücksetzen',
                               'Nur deine vorläufigen lokalen Zähler zurücksetzen?'):
            self.core.reset_local_counters()
            self.live_engine.reset_counts()
            self.set_status('Lokale Zähler zurückgesetzt.', T.DIM)

    # ---- one-click headless live tracking ------------------------------
    def toggle_integrated_live(self):
        if self.live_engine.running:
            self.live_engine.stop()
            self.live_button.set_label('Live-Test starten', icon='play')
            self.live_state.set('Replay automatisch', T.CYAN, T.TINT_CYAN)
            self.live_info.set('Live beendet. Replays werden weiter automatisch ausgewertet.')
            return
        try:
            self.live_engine.start()
            self.live_button.set_label('Live-Test stoppen', icon='stop')
            self.live_state.set('Startet …', T.WARN, T.TINT_WARN)
            self.live_info.set('Beim ersten Start wird der Erkennungs-Worker '
                               'automatisch heruntergeladen und geprüft.')
        except (OSError, ValueError, RuntimeError) as exc:
            self.live_state.set('Fehler', T.BAD, T.TINT_BAD)
            self.live_info.set(str(exc)[:240])

    # ---- in-game HUD ---------------------------------------------------
    def toggle_overlay(self):
        """Quick action and menu entry; keeps the historic method name."""
        self.hud.toggle()

    def restore_hud(self):
        """Bring the HUD back after a restart and mirror it into Settings."""
        self.hud.show()
        self.sync_hud_controls()

    def start_hotkeys(self):
        """(Re-)register the optional global shortcuts. Windows only."""
        self.stop_hotkeys()
        self.hotkey_note = ''
        bindings = []
        for name, key in (('toggle', 'hud_hotkey_toggle'), ('lock', 'hud_hotkey_lock'),
                          ('mode', 'hud_hotkey_mode')):
            try:
                combo = parse_hotkey(self.hud.opt(key))
            except ValueError as exc:
                self.hotkey_note = str(exc)
                continue
            if combo:
                bindings.append((name, combo))
        if not bindings:
            if not self.hotkey_note:
                self.hotkey_note = 'Keine Tastenkürzel aktiv.'
        elif not Win32.available:
            # The platform caveat is already stated once in sync_hud_controls.
            self.hotkey_note = f'{len(bindings)} Kürzel konfiguriert.'
        else:
            self.hotkeys = HotkeyListener(
                bindings, lambda name: self.events.put(('hotkey', name)))
            self.hotkeys.start()
            self.hotkey_note = f'{len(bindings)} Tastenkürzel registriert.'
        self.sync_hud_controls()

    def stop_hotkeys(self):
        if self.hotkeys is not None:
            self.hotkeys.stop()
            self.hotkeys = None

    def apply_hotkeys(self):
        values = {}
        for key, field in self.hud_fields.items():
            text = field.get()
            try:
                parse_hotkey(text)
            except ValueError as exc:
                field.mark('error', str(exc))
                return
            field.mark('ok' if text else 'idle',
                       'Übernommen.' if text else None)
            values[key] = text
        self.core.set_config(values)
        self.start_hotkeys()

    def sync_hud_controls(self):
        """Mirror the HUD state back into the settings panel."""
        if not hasattr(self, 'hud_toggle'):
            return
        self.hud_toggle.set(self.hud.visible)
        self.hud_expanded.set(self.hud.opt('hud_mode') == 'expanded')
        self.hud_lock.set(bool(self.hud.opt('hud_locked')))
        notes = []
        if not Win32.available:
            notes.append('Klick-durchlässig, Tool-Fenster und globale Kürzel sind '
                         'Windows-Funktionen und bleiben auf diesem System ohne Wirkung.')
        elif self.hud.opt('hud_locked'):
            notes.append('Gesperrt: Mausklicks gehen durch das HUD ins Spiel.')
        else:
            notes.append('Entsperrt: HUD mit der Maus verschieben, Rechtsklick öffnet '
                         'das Menü.')
        if self.hud.overlaps_vision_region():
            notes.append('Achtung: Das HUD liegt im Bereich, den die '
                         'Bildschirmerkennung abtastet. Bitte an den Rand ziehen.')
        if self.hotkey_note:
            notes.append(self.hotkey_note)
        if self.hotkeys is not None and self.hotkeys.error:
            notes.append(self.hotkeys.error)
        self.hud_note.set('  ·  '.join(notes))

    def hud_snapshot(self, members, squad_total, personal, own_verified,
                     current, connected, totals, failing):
        rows = []
        for member in members[:4]:
            verified = member.get('verified_chests')
            rows.append({'name': member.get('name', 'Spieler'),
                         'value': verified if verified is not None
                         else member.get('live_chests', 0),
                         'confirmed': verified is not None,
                         'online': bool(member.get('online'))})
        return {'squad': squad_total,
                'personal': own_verified if own_verified is not None else personal,
                'round': current, 'connected': connected,
                'confirmed': totals['confirmed'], 'estimated': totals['estimated'],
                'members': rows, 'personal_confirmed': own_verified is not None,
                'error': failing}

    # ---- live refresh --------------------------------------------------
    def set_status(self, message, tone=T.DIM):
        self.status_var.set(message)
        self.status_label.configure(fg=tone)
        self._paint_status_dot(tone)

    def refresh(self):
        self._tick += 1
        events = []
        while not self.events.empty():
            events.append(self.events.get_nowait())

        with self.core.lock:
            manual, vision_count = self.core.manual, self.core.vision
            ammo, food, destroyed = self.core.ammo, self.core.food, self.core.destroyed
            round_id, status = self.core.round_id, self.core.status
            connected = self.core.connected
            data = dict(self.core.current_state)

        rd = data.get('round') or {}
        members = rd.get('members') or []
        totals = aggregate(members)
        squad_total = rd.get('chests_total', totals['chests'])
        personal = max(manual, vision_count)
        accounts = data.get('accounts') or []
        history = data.get('history') or []

        # -- header ------------------------------------------------------
        if connected:
            self.conn_pill.set('Pi verbunden', T.OK, T.TINT_OK)
        elif self.core.config.get('server_url'):
            self.conn_pill.set('Keine Verbindung', T.BAD, T.TINT_BAD)
        else:
            self.conn_pill.set('Nicht eingerichtet', T.MUTE, T.SURFACE_2)
        current = rd.get('id') or round_id
        self.round_pill.set(f'Runde #{current}' if current else 'Keine Runde',
                            T.ACCENT_HI if current else T.DIM,
                            T.TINT_ACCENT if current else T.SURFACE_2)

        # -- dashboard ---------------------------------------------------
        own = next((m for m in members
                    if m.get('name') == self.core.config.get('name')), None)
        own_verified = own.get('verified_chests') if own else None
        self.stats['mine'].set(
            own_verified if own_verified is not None else personal,
            'Replay bestätigt' if own_verified is not None
            else f'{vision_count} visuell erkannt · vorläufig')
        self.stats['squad'].set(
            squad_total,
            f"{totals['confirmed']} bestätigt · {totals['estimated']} geschätzt"
            if members else 'Noch keine Spieler in der Runde')
        self.stats['verified'].set(
            data.get('total_matches', 0),
            f"bestätigt · {totals['online']}/{len(members)} online" if members
            else 'vom Replay bestätigt')
        self.stats['round'].set('#' + str(current) if current else '–',
                                clock(rd.get('created')) if rd.get('created')
                                else 'Noch nicht gestartet')
        for key in ('ammo', 'food', 'destroyed', 'treasures'):
            self.minis[key].set(totals[key])
        if not members:
            self.squad_pill.set('wartet auf Spieler', T.MUTE, T.SURFACE_2)
        elif totals['estimated']:
            self.squad_pill.set(f"{totals['estimated']} vorläufig", T.WARN, T.TINT_WARN)
        else:
            self.squad_pill.set('alle bestätigt', T.OK, T.TINT_OK)
        self.render_members(self.dash_members, members, 'dash_members', limit=4,
                            total=squad_total, compact=True)
        self.render_history(self.dash_history, history, 'dash_history', limit=3,
                            compact=True)

        # -- live tracking -----------------------------------------------
        self.live_tiles['vision'].set(own_verified if own_verified is not None else vision_count)
        self.live_tiles['squad'].set(squad_total)
        self.live_tiles['verified'].set(own_verified if own_verified is not None else '–')
        running = self.live_engine.running
        tracking, tone, tint = ('Live-Erkennung aktiv', T.WARN, T.TINT_WARN) if running else (
            'Replay automatisch', T.CYAN, T.TINT_CYAN)
        self.live_state.set(tracking, tone, tint)
        self.dash_state.set(tracking, tone, tint)
        self.dash_counts.set(f'{vision_count} visuell erkannt'
                             + (f' · Squad {squad_total}' if members else '')
                             + (' · vorläufig' if current else ''))
        engine = self.live_engine
        if running:
            self.live_state.set('Live aktiv', T.WARN, T.TINT_WARN)
            self.live_info.set(engine.state +
                               (f' · {engine.certain} sicher erkannt' if engine.count else ''))
        elif engine.error:
            self.live_state.set('Fehler', T.BAD, T.TINT_BAD)
            self.live_info.set(engine.error)
            self.live_button.set_label('Live-Test starten', icon='play')
        else:
            self.live_state.set('Replay automatisch', T.CYAN, T.TINT_CYAN)
            self.live_info.set(self.core.replay_engine.status)
            self.live_button.set_label('Live-Test starten', icon='play')

        self.dash_event.set(engine.state if running else self.core.replay_engine.status)

        # -- history / squad ----------------------------------------------
        self.history_stats['matches'].set(data.get('total_matches', 0))
        self.history_stats['chests'].set(sum(h.get('chests') or 0 for h in history))
        self.history_stats['treasures'].set(sum(a.get('treasures') or 0
                                                for a in accounts))
        self.history_stats['ammo'].set(sum(a.get('ammo') or 0 for a in accounts))
        self.render_history(self.history_box, history, 'history', limit=20)
        self.squad_total_pill.set(f'{squad_total} Truhen', T.ACCENT, T.TINT_ACCENT)
        self.render_members(self.squad_members, members, 'squad_members', limit=8,
                            total=squad_total)
        self.render_accounts(accounts)

        # -- in-game HUD --------------------------------------------------
        self.hud.update(self.hud_snapshot(members, squad_total, personal, own_verified,
                                          current, connected, totals,
                                          status.startswith('Fehler')))

        # -- updates ------------------------------------------------------
        self.lastcheck_var.set(ago(None if self.last_check is None
                                   else time.monotonic() - self.last_check))
        if self.update_busy:
            self.update_meter.set(0.15 + 0.2 * (self._tick % 4), T.ACCENT)
        elif self.update_pending:
            self.update_meter.set(1.0, T.OK)
        else:
            self.update_meter.set(0.0)

        # -- status bar ---------------------------------------------------
        if status.startswith('Fehler'):
            self.set_status(status, T.BAD)
        else:
            self.set_status(status, T.OK if connected else T.DIM)

        self.handle_events(events)
        self.root.after(2500 if self._idle else 1000, self.refresh)

    def handle_events(self, events):
        for kind, message in events:
            if kind == 'error':
                self.set_status('Fehler: ' + message[:220], T.BAD)
            elif kind == 'info':
                self.set_status(message, T.OK)
            elif kind == 'hotkey':
                if message == 'toggle':
                    self.hud.toggle()
                elif message == 'lock':
                    self.hud.toggle_lock()
                elif message == 'mode':
                    self.hud.toggle_mode()
            elif kind == 'conn_ok':
                self.conn_test.set('erreichbar · ' + message, T.OK, T.TINT_OK)
                self.settings_note.set('Server antwortet. Jetzt speichern und verbinden.')
            elif kind == 'conn_bad':
                self.conn_test.set('nicht erreichbar', T.BAD, T.TINT_BAD)
                self.settings_note.set(message)
            elif kind == 'update':
                self.update_busy = False
                self.last_check = time.monotonic()
                if message:
                    self.update_pending = True
                    self.pending_version = message
                    self.install_btn.set_enabled(True)
                    self.available_var.set('v' + message)
                    self.available_sub.set('Heruntergeladen und geprüft')
                    self.update_pill.set('bereit zur Installation', T.OK, T.TINT_OK)
                    self.update_status.set(
                        f'Version {message} wurde geladen und per SHA-256 geprüft. '
                        'Die Installation passiert beim nächsten Start — du kannst '
                        'normal weiterspielen.')
                    self.release_notes.set('SquadLoot startet nie von selbst neu.')
                    self.sidebar_update.set('Update', T.ACCENT_HI, T.TINT_ACCENT)
                else:
                    self.available_var.set('v' + current_version())
                    self.available_sub.set('Aktuellste Version')
                    self.update_pill.set('aktuell', T.OK, T.TINT_OK)
                    self.update_status.set('SquadLoot ist aktuell. Keine neue Version '
                                           'auf deinem Pi verfügbar.')
                    self.sidebar_update.set('aktuell', T.OK, T.TINT_OK)
            elif kind == 'update_error':
                self.update_busy = False
                self.last_check = time.monotonic()
                self.update_pill.set('Prüfung fehlgeschlagen', T.BAD, T.TINT_BAD)
                self.update_status.set('Update-Prüfung fehlgeschlagen — die '
                                       'installierte Version läuft unverändert weiter: '
                                       + message)
                self.sidebar_update.set('offline', T.MUTE, T.SURFACE_2)

    # ---- lifecycle -----------------------------------------------------
    def close(self):
        self.live_engine.stop()
        self.stop_hotkeys()
        self.hud.hide()
        self.core.shutdown()
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def run(self):
        self.root.mainloop()


def main():
    parser = argparse.ArgumentParser(description='SquadLoot Desktop')
    parser.add_argument('--once', action='store_true',
                        help='Replays auswerten und synchronisieren, ohne GUI')
    args = parser.parse_args()
    if args.once:
        config = read_json(CONFIG, {})
        if not config.get('server_url') or not config.get('token'):
            raise SystemExit('Zuerst STARTEN.cmd verwenden und verbinden.')
        count, state = sync_once(config)
        print('Fertig:', count, 'Replay-Datensaetze; Runde:',
              (state.get('round') or {}).get('id', '-'))
    else:
        Gui().run()


if __name__ == '__main__':
    main()
