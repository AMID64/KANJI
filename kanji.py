#!/usr/bin/env python3
"""kanji - crossdev c64 font editor. drees / amid 2026"""

import asyncio
import base64
import glob
import io
import json
import os
import sys
import types
import urllib.request

import flet as ft
from PIL import Image

# The chargen ROM lives in a different place on every machine. On startup:
#   1. remembered path from the config, 2. search the usual locations.
#   A hit is written to kanji.json next to this file; if nothing is found
#   the app asks for the path and refuses to start without a valid ROM.
APP_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(APP_DIR, "kanji.json")

# free character set, offered when no emulator ROM is installed (LGPL-3.0)
OPENROM_URL = ("https://raw.githubusercontent.com/MEGA65/open-roms/master/"
               "bin/chargen_openroms.rom")
def _windows_roots():
    """Program folders on Windows, read from the environment.

    The folder name is localised ("Programme", "Programmes", ...), so
    hardcoding "Program Files" only works on English installs. These
    variables hold the real name whatever the system language is.
    """
    roots = []
    for var in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432",
                "LOCALAPPDATA", "APPDATA", "USERPROFILE"):
        v = os.environ.get(var)
        if v:
            roots.append(v.replace("\\", "/"))
    return roots


# VICE ships under several names; other emulators carry the same ROM
_EMUS = ("VICE*", "WinVICE*", "GTK3VICE*", "SDL*VICE*", "Vice*",
         "Hoxs64*", "CCS64*", "Denise*", "RetroDebugger*", "RetroArch*")


def _chargen_globs():
    """Search patterns, cheap and precise ones first.

    Split in two passes: the exact paths cost milliseconds, while a
    recursive '**' over /Applications or C:/ takes seconds. The slow ones
    only run if the quick pass found nothing.
    """
    quick = [os.path.join(APP_DIR, "chargen"),
             os.path.join(APP_DIR, "roms", "chargen")]
    slow = []

    if sys.platform == "darwin":
        quick += [
            "/Applications/VICE*/Roms/data/C64/chargen",
            "/Applications/VICE*/**/C64/chargen",
            "/opt/homebrew/share/vice/C64/chargen",
            "/usr/local/share/vice/C64/chargen",
            os.path.expanduser("~/Library/Application Support/RetroArch/system/**/chargen"),
        ]
        slow += [
            "/Applications/**/C64/chargen",
            os.path.expanduser("~/Applications/**/C64/chargen"),
        ]
    elif os.name == "nt":
        for root in _windows_roots():
            for app in _EMUS:
                quick.append(f"{root}/{app}/C64/chargen")
                quick.append(f"{root}/{app}/data/C64/chargen")
                slow.append(f"{root}/{app}/**/chargen")
                slow.append(f"{root}/{app}/**/chargen.bin")
        # portable installs live anywhere; only scanned in the slow pass and
        # only two levels deep, so a full drive is never walked
        for drive in ("C:", "D:", "E:"):
            for folder in ("", "/Emulatoren", "/Emulators", "/Games", "/Tools"):
                slow.append(f"{drive}{folder}/*/C64/chargen")
                slow.append(f"{drive}{folder}/*/*/C64/chargen")
    else:
        quick += [
            "/usr/share/vice/C64/chargen",
            "/usr/local/share/vice/C64/chargen",
            "/usr/lib/vice/C64/chargen",
            os.path.expanduser("~/.local/share/vice/C64/chargen"),
            os.path.expanduser("~/.config/retroarch/system/**/chargen"),
        ]
        slow += [
            "/snap/vice/current/**/C64/chargen",
            "/var/lib/flatpak/**/vice/**/C64/chargen",
            os.path.expanduser("~/.var/app/**/vice/**/C64/chargen"),
        ]

    quick.append(os.path.expanduser("~/.vice/C64/chargen"))
    return quick, slow


CHARGEN_QUICK, CHARGEN_SLOW = _chargen_globs()
CHARGEN_GLOBS = CHARGEN_QUICK + CHARGEN_SLOW       # kept for tests

FG = "#7b71d6"   # c64 light blue
BG = "#40318d"   # c64 blue
BORDER = "#6c5eb5"
CELL = "#352a78"  # unset pixel in the 8x8 editor grid
SEL = "#ffffff"   # highlight (key names, selection frame)

PIX = 22         # editor pixel size
COLS = 16        # chars per preview row
ROWS = 8         # rows per preview block (16x8 = 128 normal chars)
GAP = 8          # gap between the normal and reversed block (image px)

# The preview is rendered as a PNG: 9 px per char (8 + 1 separator).
# PAD = 1 px border so the selection frame of the first row/column fits.
PAD = 1
PREV_W = (COLS * 9) * 2 + GAP + PAD * 2
PREV_H = ROWS * 9 + PAD * 2 + 1         # +1: room for the last row's frame
BG_RGB = (0x40, 0x31, 0x8d)
FG_RGB = (0x7b, 0x71, 0xd6)
SEL_RGB = (0xff, 0xff, 0xff)

# --- fixed layout: pane 3 is as wide as pane 1 + 2 -----------------------
PANE_GAP = 8                            # gap between panes
PAGE_PAD = 10                           # page margin
PANE_PAD = 10                           # inner padding of a pane
CHAR_W = 7.3                            # width of one char in monospace 12px
KEY_W = 76                              # column width for the key name

PANE_HEAD = 43                          # pane title + spacing + padding
TITLEBAR = 28                           # macOS window title bar

EDITOR_W = 17 * (PIX + 1) + 140         # 16 pixel columns + ruler + tile preview
TOP_H = 17 * (PIX + 1) + PANE_HEAD      # 16 pixel rows + ruler + title
STATUS_H = 26


# FUNC_W / TOTAL_W / WIN_* are computed below the HELP lists.

EXTS = ("64c", "bin")   # raw charset dump (2048 B, optional 2 B load address)

TILES = [(1, 1), (1, 2), (2, 1), (2, 2)]

# ruler labels: 0-9 then A-H, enough for a 2x2 tile (16 px)
RULER = "0123456789ABCDEFGH"

TITLE = "KANJI"
VERSION = "v1.0"
BYLINE = "by DREES/AMID"

# (key, function) - rendered in two columns, all formatted the same
HELP_LEFT = [
    ("L", "Load Charset"),
    ("S", "Save Charset"),
    ("C", "Copy Char"),
    ("V", "Paste Char"),
    ("T", "Set Tile Size"),
    ("1", "Undo"),
    ("2", "Redo"),
    ("3", "Horizontal Flip"),
    ("4", "Perpendicular Flip"),
]
HELP_RIGHT = [
    ("5", "Shift Left"),
    ("6", "Shift Right"),
    ("7", "Shift Up"),
    ("8", "Shift Down"),
    ("9", "Invert Char"),
    ("0", "Reset to CBM Char"),
    ("ß", "Show CBM Char (hold)"),
    ("Backspace", "Clear Char"),
    ("P", "Preview Font"),
]
HELP_BOTTOM = [
    ("Space", "Set/Unset in Char Editor"),
    ("Tab", "Toggle between Char Editor/Preview Charset Window"),
    ("Shift Tab", "Toggle between Upper and lowercase Charset"),
    ("Cursor", "Select Char (Preview Charset) and Dot in Charset Editor"),
]

# Size pane 2 so the longest help text fits and nothing gets clipped.
# Pane 3 is as wide as pane 1 + 2.
_two_col = 2 * (KEY_W + max(len(t) for _, t in HELP_LEFT + HELP_RIGHT) * CHAR_W) + 16
_one_col = KEY_W + max(len(t) for _, t in HELP_BOTTOM) * CHAR_W
FUNC_W = int(max(_two_col, _one_col)) + PANE_PAD * 2 + 4 - 50   # 10 px to pane 1, 40 px narrower
TOTAL_W = EDITOR_W + PANE_GAP + FUNC_W
# Scale the preview by an integer factor (otherwise it blurs) and absorb
# the remainder in the gap between the normal and reversed block, so the
# image ends up exactly as wide as pane 3.
PREV_SCALE = max(1, (TOTAL_W - PANE_PAD * 2 - 4) // PREV_W)
GAP += (TOTAL_W - PANE_PAD * 2 - 4) // PREV_SCALE - PREV_W
PREV_W = (COLS * 9) * 2 + GAP + PAD * 2
PREV_PANE_H = PREV_H * PREV_SCALE + PANE_HEAD + 8   # +8 slack, otherwise the
                                                    # last row's selection
                                                    # frame gets clipped
WIN_W = TOTAL_W + PAGE_PAD * 2
WIN_H = (TOP_H + PANE_GAP + PREV_PANE_H + PANE_GAP + STATUS_H
         + PAGE_PAD * 2 + TITLEBAR)


def read_config():
    try:
        with open(CONFIG) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def write_config(cfg):
    try:
        with open(CONFIG, "w") as f:
            json.dump(cfg, f, indent=2)
    except OSError:
        pass                    # not writable -> next start searches again


def valid_chargen(path):
    """True if the path points at something usable as a charset.

    Only the size is checked, deliberately: 2048 bytes is a single charset,
    4096 both, and custom or exotic fonts should be usable as a starting
    point too - so no test on the CBM bit pattern.
    """
    try:
        return bool(path) and os.path.getsize(path) >= 2048
    except OSError:
        return False


def find_chargen(deep=True):
    """Find the chargen ROM: remembered path, then the quick and slow passes.

    Set deep=False to skip the recursive patterns, which can take seconds.
    A hit is written to the config so later starts skip the search entirely.
    """
    remembered = read_config().get("chargen")
    if valid_chargen(remembered):
        return remembered

    passes = [CHARGEN_QUICK] + ([CHARGEN_SLOW] if deep else [])
    for patterns in passes:
        for pattern in patterns:
            try:
                hits = glob.glob(pattern, recursive=True)
            except OSError:                 # unreadable drive, permissions
                continue
            # newest version first: VICE-3.9 before VICE-3.6
            for hit in sorted(hits, reverse=True):
                if valid_chargen(hit):
                    write_config({**read_config(), "chargen": hit})
                    return hit
    return None


def load_cbm(path=None):
    """Load both CBM charsets (2x2048), padded to 4096 bytes.

    A file holding only one charset (2048 bytes) is accepted as well; the
    second charset then starts out empty.
    """
    out = bytearray(4096)
    path = path or find_chargen()
    if valid_chargen(path):
        with open(path, "rb") as f:
            data = strip_load_addr(bytearray(f.read(4098)))
        out[:len(data)] = data[:4096]
    return out


def strip_load_addr(data):
    """.64c files may carry a 2-byte load address."""
    return data[2:] if len(data) in (2050, 4098) else data


class Kanji:
    def __init__(self, page: ft.Page):
        self.page = page
        self.chargen = find_chargen()
        self.cbm = load_cbm(self.chargen)
        self.font = bytearray(self.cbm)
        self.cur = 1              # selected char index (0..511); >=256 = lowercase set
        self.cx = self.cy = 0     # cursor in char editor
        self.focus_editor = True
        self.tile = 0             # index into TILES
        self.clip = None
        self.undo, self.redo = [], []
        self.shift = False        # KeyboardListener reports Shift as its own key
        self.show_orig = False    # ß held -> show the CBM original instead of the edit
        self.font_prev = False    # P -> pane 3 shows the font as tiles
        self.picker = ft.FilePicker()
        page.services.append(self.picker)
        self.build()
        if not self.chargen:                # nothing found -> ask for it
            page.run_task(self.ask_chargen)

    # --- char access -------------------------------------------------
    def get(self, idx=None):
        """Char data for editing - always from the working charset."""
        i = (self.cur if idx is None else idx) * 8
        return self.font[i:i + 8]

    def shown(self, idx=None):
        """Char data for display - the CBM original while ß is held."""
        i = (self.cur if idx is None else idx) * 8
        src = self.cbm if self.show_orig else self.font
        return src[i:i + 8]

    def put(self, rows, idx=None):
        i = (self.cur if idx is None else idx) * 8
        self.font[i:i + 8] = bytes(rows)

    def snapshot(self, idx=None):
        idx = self.cur if idx is None else idx
        self.undo.append((idx, bytes(self.get(idx))))
        del self.undo[:-100]
        self.redo.clear()

    # --- ui ----------------------------------------------------------
    def build(self):
        self.titles = {}
        self.editor = ft.Column(spacing=0)
        self.preview = ft.Image(src="", width=PREV_W * PREV_SCALE, height=PREV_H * PREV_SCALE,
                                filter_quality=ft.FilterQuality.NONE,
                                gapless_playback=True)   # no blank frame while swapping
        self.tile_prev = ft.Column(spacing=0)
        self.status = ft.Text("", color=FG, size=13, font_family="monospace")

        top = ft.Container(
            ft.Row(
                [
                    ft.Container(
                        self.pane("EDITOR",
                                  ft.Row([self.editor, self.tile_prev], spacing=16,
                                         vertical_alignment=ft.CrossAxisAlignment.START)),
                        width=EDITOR_W),
                    ft.Container(self.pane(None, self.help_block()), width=FUNC_W),
                ],
                spacing=PANE_GAP,
                vertical_alignment=ft.CrossAxisAlignment.STRETCH,
            ),
            height=TOP_H,
        )
        self.prev_pane = ft.Container(
            self.pane("CHARSET",
                      ft.GestureDetector(self.preview, on_tap_down=self.preview_click),
                      expand=True),
            width=TOTAL_W,                        # as wide as pane 1 + 2
            height=PREV_PANE_H)
        # a page-level on_keyboard_event stops firing once a GestureDetector
        # takes focus, so the whole UI lives inside an autofocused listener
        self.keys = ft.KeyboardListener(
            content=ft.Column([top, self.prev_pane, self.status], spacing=PANE_GAP,
                              tight=True),
            autofocus=True,
            on_key_down=self.on_key_down,
            on_key_up=self.on_key_up,
        )
        self.page.add(self.keys)
        self.refresh()

    def help_block(self):
        """App name plus the two-column function list, uniformly formatted."""
        def entry(key, txt, kw=KEY_W):
            return ft.Row([
                ft.Container(ft.Text(key, color=SEL, size=12,
                                     font_family="monospace"), width=kw),
                ft.Text(txt, color=FG, size=12, font_family="monospace",
                        no_wrap=True),
            ], spacing=0)

        def column(items, kw=KEY_W):
            return ft.Column([entry(k, t, kw) for k, t in items], spacing=2)

        return ft.Container(
            ft.Column([
                ft.Row([
                    ft.Text(TITLE, color=SEL, size=20, weight=ft.FontWeight.BOLD,
                            font_family="monospace"),
                    ft.Text(VERSION, color=FG, size=12, font_family="monospace"),
                ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.END),
                ft.Text(BYLINE, color=FG, size=12, font_family="monospace"),
                ft.Container(height=8),
                ft.Row([column(HELP_LEFT), column(HELP_RIGHT)], spacing=16,
                       vertical_alignment=ft.CrossAxisAlignment.START),
                ft.Container(height=8),
                column(HELP_BOTTOM),
            ], spacing=2),
            padding=ft.Padding.only(left=10))      # keep the content off the border

    def pane(self, title, content, expand=True):
        inner = ft.Column([content], spacing=0, expand=expand,
                          scroll=ft.ScrollMode.AUTO)
        if title is None:                       # pane without a heading
            body = ft.Column([inner], spacing=8)
        else:
            label = ft.Text(title, color=FG, size=12, weight=ft.FontWeight.BOLD,
                            font_family="monospace")
            self.titles[title] = label
            body = ft.Column([label, inner], spacing=8)
        return ft.Container(
            body,
            bgcolor=BG, border=ft.Border.all(2, BORDER), border_radius=4,
            padding=10, expand=expand,
        )

    def dot(self, on, size, hi=False, grid=False):
        return ft.Container(
            width=size, height=size,
            bgcolor=FG if on else (CELL if grid else BG),
            border=ft.Border.all(1, "#ffffff") if hi else None,
        )

    def label(self, txt, size=PIX):
        return ft.Container(ft.Text(txt, color=BORDER, size=11, font_family="monospace",
                                    text_align=ft.TextAlign.CENTER),
                            width=size, height=size,
                            alignment=ft.Alignment.CENTER)

    def refresh(self):
        w, h = TILES[self.tile]
        px, py = w * 8, h * 8          # editable pixel extent of the tile
        rows = self.get()

        # Rebuild the grid on every refresh: Flet does not reliably send
        # property mutations on deeply nested controls.
        grid = [ft.Row([self.label("")] + [self.label(RULER[x]) for x in range(px)],
                       spacing=1)]
        for y in range(py):
            cells = [self.label(RULER[y])]
            for x in range(px):
                cells.append(ft.GestureDetector(
                    ft.Container(
                        width=PIX, height=PIX,
                        bgcolor=FG if self.tile_pixel(x, y) else CELL,
                        border=(ft.Border.all(1, "#ffffff")
                                if self.focus_editor and (x, y) == (self.cx, self.cy)
                                else None)),
                    on_tap=lambda e, x=x, y=y: self.toggle(x, y)))
            grid.append(ft.Row(cells, spacing=1))
        self.editor.controls = grid

        self.tile_prev.controls = self.render_tile()
        # only assign when actually different, otherwise Flet reloads the image -> flicker
        src = self.render_font_preview() if self.font_prev else self.render_preview()
        if src != self.preview.src:
            self.preview.src = src
        self.titles["CHARSET"].value = (
            f"FONT PREVIEW {w}x{h} - CHAR 0-63"
            if self.font_prev else
            f"CHARSET {self.cur // 256 + 1} - "
            f"{'UPPERCASE' if self.cur < 256 else 'LOWERCASE'}   (NORMAL | REVERSED)")
        self.status.value = (
            f"char {self.cur % 256:3d}  set {self.cur // 256 + 1}  tile {w}x{h}  "
            f"pixel {self.cx},{self.cy}  focus {'editor' if self.focus_editor else 'charset'}"
            + ("   [CBM ORIGINAL]" if self.show_orig else ""))
        self.page.update()

    def tile_char(self, tx, ty):
        """Char index at tile position (tx,ty).

        README FONT FORMAT - every part is a real char of the charset:
          1x2:  A            2x1:  A  SHIFT
                REVERSE
          2x2:  A            SHIFT
                REVERSE      SHIFT REVERSE
        Right = SHIFT (+64), below = REVERSE (+128).
        A = $01 -> SHIFT A = $41.
        """
        off = (64 if tx else 0) + (128 if ty else 0)
        base = (self.cur // 256) * 256
        return base + (self.cur - base + off) % 256

    def tile_pixel(self, x, y):
        """Bit at tile pixel (x,y), taken from the char it belongs to."""
        rows = self.shown(self.tile_char(x // 8, y // 8))
        return rows[y % 8] & (128 >> (x % 8))

    def render_tile(self):
        """1:1 preview of the tile, built from its individual chars."""
        w, h = TILES[self.tile]
        return [ft.Row([self.dot(self.tile_pixel(x, y), 6)
                        for x in range(w * 8)], spacing=0)
                for y in range(h * 8)]

    def prev_cols(self):
        """Number of tiles per row in the font preview."""
        w, _ = TILES[self.tile]
        return max(1, (PREV_W - PAD * 2) // (w * 8 + 1))

    def render_font_preview(self):
        """Chars 0-63 in the current tile format, assembled like in pane 1."""
        w, h = TILES[self.tile]
        tw, th = w * 8 + 1, h * 8 + 1          # tile + 1 px separator
        cols = self.prev_cols()
        im = Image.new("RGB", (PREV_W, PREV_H), BG_RGB)
        px = im.load()
        base = (self.cur // 256) * 256
        for i in range(64):
            r, col = divmod(i, cols)
            gx, gy = PAD + col * tw, PAD + r * th
            if gy + h * 8 > PREV_H:            # does not fit in the image any more
                break
            for ty in range(h):
                for tx in range(w):
                    off = (64 if tx else 0) + (128 if ty else 0)
                    glyph = self.shown(base + (i + off) % 256)
                    for y in range(8):
                        for x in range(8):
                            if glyph[y] & (128 >> x):
                                px[gx + tx * 8 + x, gy + ty * 8 + y] = FG_RGB
            if base + i == self.cur:           # mark the selection
                for x in range(-1, w * 8 + 1):
                    px[gx + x, gy - 1] = SEL_RGB
                    px[gx + x, min(gy + h * 8, PREV_H - 1)] = SEL_RGB
                for y in range(-1, h * 8 + 1):
                    px[gx - 1, gy + y] = SEL_RGB
                    px[gx + w * 8, gy + y] = SEL_RGB
        im = im.resize((PREV_W * PREV_SCALE, PREV_H * PREV_SCALE), Image.NEAREST)
        buf = io.BytesIO()
        im.save(buf, "PNG")
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()

    def render_preview(self):
        """Active charset as ONE image: 16x8 normal, reversed block next to it.

        As controls this would be ~19000 containers; Flet would have to
        serialise them on every keypress and the UI turns sluggish. A data-URI
        PNG is a single control and repaints instantly.
        """
        base = (self.cur // 256) * 256
        im = Image.new("RGB", (PREV_W, PREV_H), BG_RGB)
        px = im.load()
        for half in (0, 1):                    # 0 = normal, 1 = reversed
            ox = half * (COLS * 9 + GAP)
            for r in range(ROWS):
                for col in range(COLS):
                    c = base + r * COLS + col + half * 128
                    rows = self.shown(c)
                    gx, gy = PAD + ox + col * 9, PAD + r * 9
                    for y in range(8):
                        for x in range(8):
                            if rows[y] & (128 >> x):
                                px[gx + x, gy + y] = FG_RGB
                    if c == self.cur:          # mark the selection
                        for x in range(-1, 9):
                            px[gx + x, gy - 1] = SEL_RGB
                            px[gx + x, gy + 8] = SEL_RGB
                        for y in range(-1, 9):
                            px[gx - 1, gy + y] = SEL_RGB
                            px[gx + 8, gy + y] = SEL_RGB
        im = im.resize((PREV_W * PREV_SCALE, PREV_H * PREV_SCALE), Image.NEAREST)
        buf = io.BytesIO()
        im.save(buf, "PNG")
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()

    def preview_click(self, e):
        """Map a click in the preview image to a char index."""
        pos = e.local_position
        if pos is None:
            return
        ix = pos.x / PREV_SCALE - PAD                          # image coordinates
        iy = pos.y / PREV_SCALE - PAD
        if self.font_prev:                                     # tile view
            w, h = TILES[self.tile]
            tw, th = w * 8 + 1, h * 8 + 1
            i = int(iy // th) * self.prev_cols() + int(ix // tw)
            if 0 <= i < 64 and ix >= 0 and iy >= 0:
                self.select((self.cur // 256) * 256 + i)
            return
        if ix < 0 or iy < 0:
            return
        row = int(iy) // 9
        half = 0 if ix < COLS * 9 else 1                 # left/right block
        if half:
            ix -= COLS * 9 + GAP
        col = int(ix) // 9
        if not (0 <= row < ROWS and 0 <= col < COLS):
            return
        self.select((self.cur // 256) * 256 + row * COLS + col + half * 128)

    def toggle(self, x, y):
        """Toggle a pixel - writes into the char the tile cell belongs to."""
        self.cx, self.cy = x, y
        self.focus_editor = True
        idx = self.tile_char(x // 8, y // 8)
        self.snapshot(idx)
        rows = list(self.get(idx))
        rows[y % 8] ^= 128 >> (x % 8)
        self.put(rows, idx)
        self.refresh()

    def select(self, c):
        self.cur = c
        self.focus_editor = False
        self.refresh()

    # --- edits -------------------------------------------------------
    def edit(self, fn):
        self.snapshot()
        self.put(fn(list(self.get())))
        self.refresh()

    def on_key_down(self, e):
        if str(e.key).startswith("Shift"):
            self.shift = True
            return
        self.on_key(types.SimpleNamespace(key=str(e.key), shift=self.shift))

    def on_key_up(self, e):
        k = str(e.key)
        if k.startswith("Shift"):
            self.shift = False
        elif k == "ß" and self.show_orig:
            self.show_orig = False          # original only while the key is held
            self.refresh()

    def on_key(self, e):
        # the numeric keypad reports "Numpad 9" etc.; treat it as the digit
        k = e.key
        if k.startswith("Numpad "):
            k = k[7:]
        if k == "Tab" and e.shift:
            self.cur = (self.cur + 256) % 512          # upper <-> lowercase set
        elif k == "Tab":
            self.focus_editor = not self.focus_editor
        elif k in (" ", "Space"):
            self.toggle(self.cx, self.cy)
            return
        elif k in ("Arrow Left", "Arrow Right", "Arrow Up", "Arrow Down"):
            self.move(k)
        elif k == "L":
            self.page.run_task(self.do_load)
        elif k == "S":
            self.page.run_task(self.do_save)
        elif k == "C":
            self.clip = bytes(self.get())
        elif k == "V" and self.clip:
            self.snapshot()
            self.put(self.clip)
        elif k == "P":
            self.font_prev = not self.font_prev
            if self.font_prev:                  # preview only shows 0-63
                base = (self.cur // 256) * 256
                self.cur = base + (self.cur - base) % 64
        elif k == "T":
            self.tile = (self.tile + 1) % len(TILES)
            w, h = TILES[self.tile]
            self.cx, self.cy = min(self.cx, w * 8 - 1), min(self.cy, h * 8 - 1)
        elif k == "1":
            self.pop(self.undo, self.redo)
        elif k == "2":
            self.pop(self.redo, self.undo)
        elif k == "3":
            self.edit(lambda r: [int(f"{b:08b}"[::-1], 2) for b in r])
        elif k == "4":
            self.edit(lambda r: r[::-1])
        elif k == "5":
            self.edit(lambda r: [(b << 1) & 0xFF for b in r])
        elif k == "6":
            self.edit(lambda r: [b >> 1 for b in r])
        elif k == "7":
            self.edit(lambda r: r[1:] + r[:1])
        elif k == "8":
            self.edit(lambda r: r[-1:] + r[:-1])
        elif k == "9":
            self.edit(lambda r: [b ^ 0xFF for b in r])
        elif k == "0":
            self.edit(lambda r: list(self.cbm[self.cur * 8:self.cur * 8 + 8]))
        elif k == "Backspace":
            self.edit(lambda r: [0] * 8)
        elif k == "ß":
            if self.show_orig:              # ignore auto-repeat
                return
            self.show_orig = True
        else:
            return
        self.refresh()

    def move(self, k):
        d = {"Arrow Left": (-1, 0), "Arrow Right": (1, 0),
             "Arrow Up": (0, -1), "Arrow Down": (0, 1)}[k]
        w, h = TILES[self.tile]
        if self.focus_editor:
            self.cx = (self.cx + d[0]) % (w * 8)
            self.cy = (self.cy + d[1]) % (h * 8)
        else:
            base = (self.cur // 256) * 256          # stay inside the active set
            if self.font_prev:
                # the font preview only shows base chars 0-63 with that many
                # tiles per row -> keep navigation inside that range
                span, per_row = 64, self.prev_cols()
            else:
                span, per_row = 256, COLS
            self.cur = base + (self.cur - base + d[0] + d[1] * per_row) % span

    def pop(self, src, dst):
        if not src:
            return
        idx, rows = src.pop()
        dst.append((idx, bytes(self.get(idx))))
        self.cur = idx
        self.put(rows, idx)

    # --- io ----------------------------------------------------------
    async def ask_chargen(self):
        """Offer a choice when no chargen ROM was found: pick a file, or
        download the OpenROM one.

        Without a charset the editor is useless ('0' and 'ß' have no
        reference), so closing the dialog quits the app.
        """
        choice = asyncio.get_running_loop().create_future()

        def answer(what):
            if not choice.done():
                choice.set_result(what)

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("No character ROM found"),
            content=ft.Text(
                "KANJI needs a C64 character set to start.\n\n"
                "Select the chargen file of an emulator (VICE ships it as\n"
                "Roms/data/C64/chargen), or download the free OpenROM\n"
                "character set (4 KB, LGPL-3.0, github.com/MEGA65/open-roms).",
                font_family="monospace", size=12),
            actions=[
                ft.TextButton("Select file...", on_click=lambda e: answer("pick")),
                ft.TextButton("Download OpenROM", on_click=lambda e: answer("fetch")),
                ft.TextButton("Quit", on_click=lambda e: answer("quit")),
            ],
        )

        while True:
            self.page.show_dialog(dlg)
            what = await choice
            choice = asyncio.get_running_loop().create_future()
            self.page.pop_dialog()

            if what == "quit":
                await self.page.window.close()
                return
            if what == "fetch":
                path = await asyncio.to_thread(self.download_openrom)
                if not path:
                    self.note("download failed - check your connection")
                    continue
            else:
                files = await self.picker.pick_files(
                    "Select chargen ROM (VICE: Roms/data/C64/chargen)")
                if not files:
                    continue
                path = files[0].path
                if not valid_chargen(path):
                    self.note(f"{os.path.basename(path)} is too small for a "
                              f"charset (needs 2048 bytes) - try again")
                    continue
            break

        self.chargen = path
        write_config({**read_config(), "chargen": path})
        self.cbm = load_cbm(path)
        self.font = bytearray(self.cbm)
        self.undo.clear()
        self.redo.clear()
        self.refresh()
        self.note(f"chargen loaded: {path}")

    @staticmethod
    def download_openrom():
        """Fetch the OpenROM character set next to kanji.py. Returns the path.

        Not bundled with KANJI: OpenROM is LGPL-3.0 and stays a separate,
        replaceable file this way.
        """
        target = os.path.join(APP_DIR, "chargen_openroms.rom")
        try:
            with urllib.request.urlopen(OPENROM_URL, timeout=30) as r:
                data = r.read(8192)
            if len(data) < 2048:
                return None
            with open(target, "wb") as f:
                f.write(data)
            return target
        except (OSError, ValueError):
            return None

    async def do_load(self):
        files = await self.picker.pick_files("Load Charset",
                                             allowed_extensions=list(EXTS))
        if not files:
            return
        path = files[0].path
        with open(path, "rb") as f:
            data = strip_load_addr(bytearray(f.read()))
        if not data:
            self.note(f"{os.path.basename(path)}: empty file")
            return
        # 2048 bytes = one charset -> load into the active one,
        # 4096 bytes = both charsets
        base = (self.cur // 256) * 256 * 8
        if len(data) >= 4096:
            self.font[:4096] = data[:4096]
            what = "both charsets"
        else:
            n = min(len(data), 2048)
            self.font[base:base + n] = data[:n]
            what = f"charset {self.cur // 256 + 1}"
        self.undo.clear()
        self.redo.clear()
        self.refresh()          # rebuild editor and charset preview
        self.note(f"loaded: {os.path.basename(path)} ({len(data)} B, {what})")

    async def do_save(self):
        """Save the active charset as a 2048-byte raw dump (.64c/.bin)."""
        path = await self.picker.save_file("Save Charset", file_name="font.64c",
                                           allowed_extensions=list(EXTS))
        if not path:
            return
        if not path.lower().endswith(tuple("." + e for e in EXTS)):
            path += ".64c"
        base = (self.cur // 256) * 256 * 8
        with open(path, "wb") as f:
            f.write(self.font[base:base + 2048])
        self.note(f"saved: {os.path.basename(path)} (2048 B, "
                  f"charset {self.cur // 256 + 1})")

    def note(self, msg):
        """Show a message in the status line."""
        self.status.value = msg
        self.page.update()


async def main(page: ft.Page):
    page.title = (f"{TITLE} {VERSION} - crossdev c64 font editor"
                  f" - {BYLINE.removeprefix('by ')}")
    page.bgcolor = "#000000"
    page.padding = PAGE_PAD
    Kanji(page)
    # set the size after building, otherwise Flet keeps its default geometry
    page.window.width = WIN_W
    page.window.height = WIN_H
    page.window.min_width = WIN_W
    page.window.min_height = WIN_H
    page.window.resizable = False        # fixed size, no empty space
    page.update()
    await page.window.center()


if __name__ == "__main__":
    ft.run(main)
