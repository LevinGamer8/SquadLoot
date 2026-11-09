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

from client_core import (Core, CONFIG, chestcounter_exe, read_json, sync_once,
                         validate_url)
from update_manager import current_version, check_and_stage, log_error
from vision import VisionDetector

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
    'live': ('Live-Tracking', 'Manuell zählen oder die Beta-Bildschirmerkennung nutzen.'),
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
        self.overlay = None
        self.overlay_var = None
        self.vision = None
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
        self.dash_counts = tk.StringVar(value='0 manuell · 0 erkannt')
        tk.Label(status.body, textvariable=self.dash_counts, bg=T.SURFACE, fg=T.TEXT,
                 font=font(13), anchor='w').pack(fill='x', pady=(T.S3, 0))
        self.dash_event = tk.StringVar(value='Noch kein erkanntes Ereignis.')
        tk.Label(status.body, textvariable=self.dash_event, bg=T.SURFACE, fg=T.MUTE,
                 font=font(11), anchor='w', justify='left',
                 wraplength=px(300)).pack(fill='x', pady=(px(2), T.S3))
        row = tk.Frame(status.body, bg=T.SURFACE)
        row.pack(fill='x')
        Button(row, 'Truhe', lambda: self.core.adjust('manual', 1), 'primary',
               icon='plus', bg=T.SURFACE).pack(side='left')
        Button(row, '', lambda: self.core.adjust('manual', -1), 'secondary',
               icon='minus', width=T.BTN_H, bg=T.SURFACE).pack(side='left', padx=px(6))
        Button(row, 'Live-Tracking', lambda: self.show_page('live'), 'ghost',
               bg=T.SURFACE).pack(side='left')

        actions = Card(side)
        actions.pack(fill='x', pady=(T.S3, 0))
        section_head(actions.body, 'Schnellaktionen', 'Runde, Replay und Ansichten.')
        grid = tk.Frame(actions.body, bg=T.SURFACE)
        grid.pack(fill='x')
        quick = (
            ('Neue Squad-Runde', self.start_round, 'spark'),
            ('Replay auswerten', self.run_chestcounter, 'film'),
            ('Live-HUD', self.toggle_overlay, 'target'),
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
        page = self.page_body('live')

        banner = Card(page, fill=T.SURFACE, accent=T.ACCENT)
        banner.pack(fill='x', pady=(T.S4, T.S3))
        row = tk.Frame(banner.body, bg=T.SURFACE)
        row.pack(fill='x')
        text = tk.Frame(row, bg=T.SURFACE)
        text.pack(side='left', fill='x', expand=True)
        label(text, 'Aktueller Zählstand', 15, 'bold', bg=T.SURFACE,
              anchor='w').pack(fill='x')
        self.live_sub = tk.StringVar(value='Manuelle Zählung ist immer eine Schätzung.')
        tk.Label(text, textvariable=self.live_sub, bg=T.SURFACE, fg=T.MUTE,
                 font=font(11), anchor='w').pack(fill='x', pady=(px(2), 0))
        self.live_state = Pill(row, 'Tracking inaktiv', T.MUTE, T.SURFACE_2, bg=T.SURFACE)
        self.live_state.pack(side='right')

        counters = tk.Frame(banner.body, bg=T.SURFACE)
        counters.pack(fill='x', pady=(T.S4, 0))
        self.live_tiles = {}
        tiles = (
            ('manual', 'Manuell', 'chest', T.ACCENT, T.TINT_ACCENT),
            ('vision', 'Erkannt', 'bolt', T.WARN, T.TINT_WARN),
            ('destroyed', 'Zerstört', 'burst', T.BAD, T.TINT_BAD),
            ('ammo', 'Munition', 'ammo', T.CYAN, T.TINT_CYAN),
            ('food', 'Obst', 'food', T.OK, T.TINT_OK),
        )
        for i, (key, title, icon, tone, tint) in enumerate(tiles):
            tile = MiniStat(counters, title, icon, tone, tint, bg=T.SURFACE)
            tile.grid(row=0, column=i, sticky='nsew', padx=(0 if i == 0 else px(6), 0))
            counters.grid_columnconfigure(i, weight=1, uniform='live')
            self.live_tiles[key] = tile

        columns = tk.Frame(page, bg=T.BG)
        columns.pack(fill='both', expand=True)
        columns.grid_columnconfigure(0, weight=1, uniform='live2')
        columns.grid_columnconfigure(1, weight=1, uniform='live2')
        columns.grid_rowconfigure(0, weight=1)

        manual = Card(columns)
        manual.grid(row=0, column=0, sticky='new', padx=(0, T.S3))
        section_head(manual.body, 'Manuelle Steuerung',
                     'Zuverlässigste Zählung während der Runde.')
        pad = tk.Frame(manual.body, bg=T.SURFACE)
        pad.pack(fill='x')
        controls = (
            ('Truhe', lambda: self.core.adjust('manual', 1), 'plus', 'primary'),
            ('Truhe entfernen', lambda: self.core.adjust('manual', -1), 'minus', 'secondary'),
            ('Zerstört', self.destroyed, 'burst', 'secondary'),
            ('Munition', lambda: self.core.adjust('ammo', 1), 'ammo', 'secondary'),
            ('Obstbox', lambda: self.core.adjust('food', 1), 'food', 'secondary'),
            ('Zurücksetzen', self.confirm_reset, 'refresh', 'danger'),
        )
        for i, (title, callback, icon, variant) in enumerate(controls):
            Button(pad, title, callback, variant, icon=icon, bg=T.SURFACE).grid(
                row=i // 2, column=i % 2, sticky='ew',
                padx=(0 if i % 2 == 0 else px(6), 0), pady=px(3))
        pad.grid_columnconfigure(0, weight=1)
        pad.grid_columnconfigure(1, weight=1)
        divider(manual.body)
        label(manual.body, 'Runde & Replay', 12, 'bold', fg=T.DIM, bg=T.SURFACE,
              anchor='w').pack(fill='x', pady=(0, T.S3))
        ops = tk.Frame(manual.body, bg=T.SURFACE)
        ops.pack(fill='x')
        Button(ops, 'Neue Squad-Runde', self.start_round, 'secondary', icon='spark',
               bg=T.SURFACE).pack(side='left')
        Button(ops, 'Replay auswerten', self.run_chestcounter, 'secondary', icon='film',
               bg=T.SURFACE).pack(side='left', padx=(px(6), 0))

        vision = Card(columns)
        vision.grid(row=0, column=1, sticky='new')
        head = section_head(vision.body, 'Bildschirmerkennung',
                            'Opt-in · liest nur einen Bildausschnitt, nie das Spiel.')
        Pill(head, 'BETA', T.WARN, T.TINT_WARN, dot=False, bg=T.SURFACE).pack(side='right')
        self.vision_state = Pill(vision.body, 'Erkennung ist AUS', T.MUTE, T.SURFACE_2,
                                 bg=T.SURFACE)
        self.vision_state.pack(anchor='w')
        label(vision.body, 'Erkennungsqualität', 11, 'bold', fg=T.MUTE, bg=T.SURFACE,
              anchor='w').pack(fill='x', pady=(T.S4, px(5)))
        self.vision_meter = Meter(vision.body, tone=T.WARN, bg=T.SURFACE)
        self.vision_meter.pack(fill='x')
        self.vision_detail = tk.StringVar(value='Noch keine Messung. Vorlage wählen und starten.')
        tk.Label(vision.body, textvariable=self.vision_detail, bg=T.SURFACE, fg=T.MUTE,
                 font=font(11), anchor='w', justify='left',
                 wraplength=px(330)).pack(fill='x', pady=(px(6), 0))
        keyrow = tk.Frame(vision.body, bg=T.SURFACE)
        keyrow.pack(fill='x', pady=(T.S4, 0))
        label(keyrow, 'Interaktionstaste', 12, fg=T.DIM, bg=T.SURFACE).pack(side='left')
        self.vision_key = tk.StringVar(value=self.core.config.get('interact_key', 'E'))
        keybox = tk.Frame(keyrow, bg=T.FIELD, highlightthickness=1,
                          highlightbackground=T.LINE_STRONG, highlightcolor=T.ACCENT)
        keybox.pack(side='left', padx=(T.S3, T.S3))
        tk.Entry(keybox, textvariable=self.vision_key, width=3, justify='center',
                 bg=T.FIELD, fg=T.TEXT, insertbackground=T.ACCENT_HI, relief='flat',
                 bd=0, highlightthickness=0, font=font(13, 'bold')).pack(
                     padx=px(8), pady=px(6))
        label(keyrow, 'A–Z oder 0–9', 11, fg=T.MUTE, bg=T.SURFACE).pack(side='left')
        actions = tk.Frame(vision.body, bg=T.SURFACE)
        actions.pack(fill='x', pady=(T.S4, 0))
        Button(actions, 'PNG-Vorlage', self.select_vision_template, 'secondary',
               icon='folder', bg=T.SURFACE).pack(side='left')
        self.vision_button = Button(actions, 'Erkennung starten', self.toggle_vision,
                                    'primary', icon='play', bg=T.SURFACE)
        self.vision_button.pack(side='left', padx=(px(6), 0))
        divider(vision.body)
        label(vision.body,
              'Gezählt wird nur, wenn der Suchhinweis sichtbar war, du die Taste '
              'gedrückt hast und der Hinweis danach verschwindet. Das ist kein '
              'sicherer Nachweis für eine geöffnete Truhe — das Replay entscheidet.',
              11, fg=T.MUTE, bg=T.SURFACE, anchor='w', justify='left',
              wraplength=px(340)).pack(fill='x')
        label(vision.body,
              'Performance: nur der mittlere Bildausschnitt, maximal 2,5 Bilder pro '
              'Sekunde und nur bei aktivem Fortnite-Fenster. Bilder und Tastendrücke '
              'verlassen deinen PC nie.',
              11, fg=T.MUTE, bg=T.SURFACE, anchor='w', justify='left',
              wraplength=px(340)).pack(fill='x', pady=(px(8), 0))

        legend = Card(page)
        legend.pack(fill='x', pady=(T.S4, 0))
        section_head(legend.body, 'Geschätzt oder bestätigt?',
                     'So liest du jede Zahl in SquadLoot.')
        rows = tk.Frame(legend.body, bg=T.SURFACE)
        rows.pack(fill='x')
        items = (
            ('bolt', T.WARN, T.TINT_WARN, 'Geschätzt',
             'Manuelle Klicks und Bildschirmerkennung während der Runde.'),
            ('check', T.OK, T.TINT_OK, 'Replay bestätigt',
             'Von ChestCounter aus deinem Replay gelesen — verbindlich.'),
            ('signal', T.CYAN, T.TINT_CYAN, 'Live übertragen',
             'Wird gerade an deinen Pi gesendet, noch nicht bestätigt.'),
        )
        for i, (icon, tone, tint, title, text) in enumerate(items):
            cell = tk.Frame(rows, bg=T.SURFACE)
            cell.grid(row=0, column=i, sticky='nsew', padx=(0 if i == 0 else T.S4, 0))
            rows.grid_columnconfigure(i, weight=1, uniform='legend')
            badge = tk.Canvas(cell, width=px(28), height=px(28), bg=T.SURFACE, bd=0,
                              highlightthickness=0)
            badge.pack(anchor='w')
            round_rect(badge, 0, 0, px(28), px(28), px(9), tint, mix(tint, tone, .25))
            draw_icon(badge, icon, px(14), px(14), px(15), tone)
            label(cell, title, 12, 'bold', fg=tone, bg=T.SURFACE,
                  anchor='w').pack(fill='x', pady=(px(6), px(2)))
            label(cell, text, 11, fg=T.MUTE, bg=T.SURFACE, anchor='w', justify='left',
                  wraplength=px(230)).pack(fill='x')

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
        self.add_field(body, 'data_json', 'ChestCounter data.json',
                       'Die von ChestCounter erzeugte Auswertungsdatei.',
                       browse=lambda: self.pick_file('data_json', [('JSON', '*.json')]))
        self.add_field(body, 'chestcounter_exe', 'Pfad zur ChestCounter.exe',
                       'Optional. Leer lassen, wenn du ChestCounter selbst startest.',
                       browse=lambda: self.pick_file('chestcounter_exe',
                                                     [('Programm', '*.exe')]))

        body = self.settings_section(
            page, 'Live-Erkennung (Beta)', 'Experimentell. Liest nur einen '
            'Bildausschnitt und eine einzelne Taste.', 'bolt', T.WARN, T.TINT_WARN)
        self.template_var = tk.StringVar(value=self.template_caption())
        tk.Label(body, textvariable=self.template_var, bg=T.SURFACE, fg=T.DIM,
                 font=font(12), anchor='w', justify='left').pack(fill='x')
        row = tk.Frame(body, bg=T.SURFACE)
        row.pack(fill='x', pady=(T.S3, 0))
        Button(row, 'PNG-Vorlage wählen', self.select_vision_template, 'secondary',
               icon='folder', bg=T.SURFACE).pack(side='left')
        Button(row, 'Zur Live-Erkennung', lambda: self.show_page('live'), 'ghost',
               bg=T.SURFACE).pack(side='left', padx=(px(6), 0))

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

    def template_caption(self):
        path = self.core.config.get('vision_template', '')
        return ('Vorlage: ' + Path(path).name) if path else \
            'Noch keine PNG-Vorlage der Durchsuchen-Aufforderung gewählt.'

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
        exe = chestcounter_exe(self.core.config)
        if not exe:
            messagebox.showwarning('ChestCounter fehlt',
                                   'Bitte unter Einstellungen den Pfad zur '
                                   'ChestCounter.exe eintragen.')
            self.show_page('settings')
            return
        self.set_status('ChestCounter wertet vorhandene Replays aus …', T.DIM)

        def run():
            result = subprocess.run([str(exe), '--once'], capture_output=True,
                                    text=True, timeout=200, errors='replace')
            if result.returncode:
                raise RuntimeError('ChestCounter Exit ' + str(result.returncode) + ': '
                                   + result.stderr[-200:])
            count = self.core.sync_matches(self.core.credentials(), max_items=100000)
            return f'{count} Matches nach der Replay-Auswertung synchronisiert'

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
            self.set_status('Lokale Zähler zurückgesetzt.', T.DIM)

    def destroyed(self):
        self.core.adjust('manual', 1)
        self.core.adjust('destroyed', 1)

    # ---- vision --------------------------------------------------------
    def select_vision_template(self):
        name = filedialog.askopenfilename(
            title='PNG der Durchsuchen-Aufforderung',
            filetypes=[('PNG', '*.png'), ('Bilder', '*.png *.jpg *.jpeg')])
        if name:
            self.core.set_config({'vision_template': name})
            if hasattr(self, 'template_var'):
                self.template_var.set(self.template_caption())
            self.vision_detail.set('Vorlage: ' + Path(name).name
                                   + ' · Erkennung noch AUS')

    def vision_running(self):
        return bool(self.vision and self.vision.thread and self.vision.thread.is_alive())

    def toggle_vision(self):
        if self.vision_running():
            self.vision.stop_now()
            self.vision_state.set('Erkennung ist AUS', T.MUTE, T.SURFACE_2)
            self.vision_button.set_label('Erkennung starten', icon='play')
            self.vision_meter.set(0)
            return
        try:
            key = self.vision_key.get().strip().upper()
            if len(key) != 1 or not key.isascii() or not key.isalnum():
                raise ValueError('Bitte genau eine Interaktionstaste A–Z oder 0–9 '
                                 'eintragen.')
            self.core.set_config({'interact_key': key})
            self.vision = VisionDetector(self.core,
                                         self.core.config.get('vision_template', ''),
                                         key=key)
            self.vision.start()
            self.vision_button.set_label('Erkennung stoppen', icon='stop')
            self.vision_state.set('Aktiv · vorläufige Zählung', T.WARN, T.TINT_WARN)
        except (ValueError, RuntimeError) as exc:
            self.vision_state.set('Nicht gestartet', T.BAD, T.TINT_BAD)
            self.vision_detail.set(str(exc))
            messagebox.showwarning('Bildschirm-Erkennung', str(exc))

    # ---- overlay HUD ---------------------------------------------------
    def toggle_overlay(self):
        if self.overlay is not None:
            self.overlay.destroy()
            self.overlay = None
            self.overlay_var = None
            return
        win = tk.Toplevel(self.root)
        self.overlay = win
        win.title('SquadLoot HUD')
        win.geometry(f'{px(330)}x{px(220)}+{px(40)}+{px(120)}')
        win.configure(bg=T.BG)
        win.attributes('-topmost', True)
        win.resizable(False, False)
        win.protocol('WM_DELETE_WINDOW', self.toggle_overlay)
        card = Card(win, pad=T.S4)
        card.pack(fill='both', expand=True, padx=T.S2, pady=T.S2)
        head = tk.Frame(card.body, bg=T.SURFACE)
        head.pack(fill='x')
        mark = tk.Canvas(head, width=px(20), height=px(20), bg=T.SURFACE, bd=0,
                         highlightthickness=0)
        mark.pack(side='left')
        draw_logo(mark, px(10), px(10), px(19))
        label(head, 'SquadLoot HUD', 12, 'bold', bg=T.SURFACE).pack(side='left',
                                                                     padx=(px(6), 0))
        Pill(head, 'geschätzt', T.WARN, T.TINT_WARN, dot=False,
             bg=T.SURFACE).pack(side='right')
        self.overlay_var = tk.StringVar(value='Keine aktuelle Runde')
        tk.Label(card.body, textvariable=self.overlay_var, bg=T.SURFACE, fg=T.TEXT,
                 font=font(12), justify='left', anchor='nw').pack(fill='both',
                                                                   expand=True,
                                                                   pady=(T.S3, T.S3))
        row = tk.Frame(card.body, bg=T.SURFACE)
        row.pack(fill='x')
        Button(row, 'Truhe', lambda: self.core.adjust('manual', 1), 'primary',
               icon='plus', bg=T.SURFACE, small=True).pack(side='left')
        Button(row, '', lambda: self.core.adjust('manual', -1), 'secondary',
               icon='minus', width=T.BTN_H_SM, height=T.BTN_H_SM,
               bg=T.SURFACE, small=True).pack(side='left', padx=px(5))
        Button(row, 'Schließen', self.toggle_overlay, 'ghost', bg=T.SURFACE,
               small=True).pack(side='right')

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
            else f'{manual} manuell · {vision_count} erkannt')
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
        self.live_tiles['manual'].set(manual)
        self.live_tiles['vision'].set(vision_count)
        self.live_tiles['destroyed'].set(destroyed)
        self.live_tiles['ammo'].set(ammo)
        self.live_tiles['food'].set(food)
        running = self.vision_running()
        if current:
            tracking = ('Live + Bildschirm (Beta)' if running else 'Live-Tracking aktiv')
            tone, tint = (T.WARN, T.TINT_WARN) if running else (T.CYAN, T.TINT_CYAN)
        else:
            tracking, tone, tint = 'Tracking inaktiv', T.MUTE, T.SURFACE_2
        self.live_state.set(tracking, tone, tint)
        self.dash_state.set(tracking, tone, tint)
        self.dash_counts.set(f'{manual} manuell · {vision_count} erkannt'
                             + (f' · Squad {squad_total}' if members else ''))
        self.live_sub.set(
            f'Runde #{current} · {len(members)} Spieler · Squad {squad_total} Truhen'
            if current else 'Starte ein Match oder eine neue Squad-Runde.')
        self.update_vision_panel(running)

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

        # -- overlay ------------------------------------------------------
        if self.overlay is not None and self.overlay_var is not None:
            lines = [f'Squad    {squad_total} Truhen', f'Du       {personal}']
            for member in members[:4]:
                verified = member.get('verified_chests')
                value = verified if verified is not None else member.get('live_chests', 0)
                lines.append(f"{str(member.get('name', 'Spieler'))[:12]:<12} {value}")
            self.overlay_var.set('\n'.join(lines))

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

    def update_vision_panel(self, running):
        detector = self.vision
        if detector is None:
            self.vision_meter.set(0)
            return
        if getattr(detector, 'error', ''):
            self.vision_state.set('Fehler', T.BAD, T.TINT_BAD)
            self.vision_detail.set(detector.error)
            self.vision_meter.set(0, T.BAD)
            return
        if not running:
            self.vision_meter.set(0)
            return
        score = float(getattr(detector, 'last_score', 0.0) or 0.0)
        threshold = float(getattr(detector, 'threshold', 0.86) or 0.86)
        self.vision_meter.set(min(1.0, score / threshold) if threshold else 0,
                              T.OK if score >= threshold else T.WARN)
        last_at = getattr(detector, 'last_event_at', None)
        last_text = getattr(detector, 'last_event_text', '') or 'noch kein Ereignis'
        since = ago(None if not last_at else time.monotonic() - last_at)
        detail = (f'{detector.state}  ·  Treffer {score:.2f} / {threshold:.2f}  ·  '
                  f'{detector.count} vorläufige Truhen  ·  {detector.perf_ms:.0f} ms/Bild')
        self.vision_detail.set(detail + f'\nLetztes Ereignis: {last_text} ({since})')
        self.dash_event.set(f'Letztes erkanntes Ereignis: {last_text} ({since})')

    def handle_events(self, events):
        for kind, message in events:
            if kind == 'error':
                self.set_status('Fehler: ' + message[:220], T.BAD)
            elif kind == 'info':
                self.set_status(message, T.OK)
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
        if self.vision:
            self.vision.stop_now()
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
        exe = chestcounter_exe(config)
        if exe:
            result = subprocess.run([str(exe), '--once'], timeout=200)
            if result.returncode:
                raise SystemExit('ChestCounter Exit ' + str(result.returncode))
        count, state = sync_once(config)
        print('Fertig:', count, 'Replay-Datensaetze; Runde:',
              (state.get('round') or {}).get('id', '-'))
    else:
        Gui().run()


if __name__ == '__main__':
    main()
