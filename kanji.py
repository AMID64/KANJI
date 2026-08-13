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

    Split in two passes: the exact paths cost milliseconds, the wider ones
    a fraction of a second. The slow ones only run if the quick pass found
    nothing.

    No pattern may use an unbounded '**' over a directory full of
    application bundles - that walk does not finish in reasonable time.
    Every wide pattern spells out its depth instead.
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
        # bounded depth, never '**': a recursive walk of /Applications
        # descends into every app bundle and takes minutes, not seconds
        for apps in ("/Applications", os.path.expanduser("~/Applications")):
            for depth in range(1, 5):
                slow.append(f"{apps}/{'*/' * depth}C64/chargen")
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
PT_RGB = (0x8b, 0x81, 0xe6)   # mouse pointer marker - visible, but clearly
                              # weaker than the white selection frame

# The C64 palette (VICE colodore). Index = the value written to the color
# registers, which is what a multicolor charset is defined in terms of.
C64_PALETTE = [
    (0x00, 0x00, 0x00), (0xff, 0xff, 0xff), (0x81, 0x33, 0x38),
    (0x75, 0xce, 0xc8), (0x8e, 0x3c, 0x97), (0x56, 0xac, 0x4d),
    (0x2e, 0x2c, 0x9b), (0xed, 0xf1, 0x71), (0x8e, 0x50, 0x29),
    (0x55, 0x38, 0x00), (0xc4, 0x6c, 0x71), (0x4a, 0x4a, 0x4a),
    (0x7b, 0x7b, 0x7b), (0xa9, 0xff, 0x9f), (0x70, 0x6d, 0xeb),
    (0xb2, 0xb2, 0xb2),
]
C64_NAMES = ["Black", "White", "Red", "Cyan", "Purple", "Green", "Blue",
             "Yellow", "Orange", "Brown", "Light Red", "Dark Grey",
             "Grey", "Light Green", "Light Blue", "Light Grey"]

# A multicolor char reads its bitmap in pairs, so each pair picks one of
# four colors. 00 is the screen background, 11 comes from color RAM; the
# defaults match what a fresh C64 shows.
# Slot 3 lives in colour RAM, which only stores four bits with bit 3 acting
# as the multicolor flag - so it has to stay within colors 0-7.
MC_DEFAULT = [6, 11, 1, 3]      # blue background, dark grey, white, cyan

# Shift+1..4 selects the color to draw with. A German keyboard reports the
# shifted digits as symbols, so both spellings map to the same slot.
MC_KEYS = {"1": 0, "2": 1, "3": 2, "4": 3,
           "!": 0, '"': 1, "§": 2, "$": 3,
           "@": 1, "#": 2}      # US layout sends @ and # for shift+2/3

def rgb_hex(rgb):
    return "#%02x%02x%02x" % rgb

# --- fixed layout: pane 3 is as wide as pane 1 + 2 -----------------------
PANE_GAP = 8                            # gap between panes
PAGE_PAD = 10                           # page margin
PANE_PAD = 10                           # inner padding of a pane
CHAR_W = 6.7                            # width of one char at HELP_SIZE
KEY_W = 86                              # column width for the key name;
                                        # fits the longest label ("Space hold",
                                        # "Shift 1-4") with the same gap in
                                        # every column
HELP_SIZE = 11                          # font size in the shortcut list -
                                        # pane 2 has a fixed width, so this
                                        # is what makes a longer list fit

PANE_HEAD = 43                          # pane title + spacing + padding
TITLEBAR = 28                           # macOS window title bar

EDITOR_W = 17 * (PIX + 1) + 140         # 16 pixel columns + ruler + tile preview
TOP_H = 17 * (PIX + 1) + PANE_HEAD      # 16 pixel rows + ruler + title
KEYS_PANE_H = TOP_H - PANE_HEAD         # usable height inside the key pane
KEYS_NUDGE = 4                          # optical centring, see keys()
STATUS_H = 26


# FUNC_W / TOTAL_W / WIN_* are computed below the HELP lists.

EXTS = ("64c", "bin")   # raw charset dump (2048 B, optional 2 B load address)

TILES = [(1, 1), (1, 2), (2, 1), (2, 2)]

# ruler labels: 0-9 then A-H, enough for a 2x2 tile (16 px)
RULER = "0123456789ABCDEFGH"

TITLE = "KANJI"
VERSION = "v1.40"
BYLINE = "by DREES/AMID"

COPYRIGHT = "DREES/AMID in 2026"   # shown in the app; the bundle metadata
                                   # in pyproject.toml stays terse
HOMEPAGE = "https://amid64.de/"


def credit_line(size=12):
    """The copyright with the homepage as a clickable link."""
    return ft.Text(spans=[
        ft.TextSpan(f"{COPYRIGHT} - "),
        ft.TextSpan(HOMEPAGE, url=HOMEPAGE),
    ], color=SEL, size=size, font_family="monospace")

LOGO = "kanji-logo.png"   # resolved against assets/, both from source and bundled
LOGO_W = 165              # in the key panel; the shortcut list has to fit
                          # below it without being clipped

# (key, function) - rendered in two columns, all formatted the same
#
# Never bind a hold-to-act shortcut to A, E, I, O or U: macOS press-and-hold
# opens its accent picker over the app after ~half a second. read_only,
# keyboard_type NONE/VISIBLE_PASSWORD and an input filter were all tried on
# the key sink below - the picker shows up regardless.
HELP_LEFT = [
    ("L / S", "Load / Save Charset"),
    ("C / V", "Copy / Paste Char"),
    ("H / M", "Hires / Multicolor"),
    ("P", "Preview Font"),
    ("T", "Set Tile Size"),
    ("Space", "Set / Unset"),
    ("Space hold", "Move to draw along"),
    ("Tab", "Editor / Charset"),
    ("Shift Tab", "Upper / Lowercase"),
]
HELP_RIGHT = [
    ("1 / 2", "Undo / Redo"),
    ("3 / 4", "Flip Horiz. / Vert."),
    ("5 / 6", "Shift Left / Right"),
    ("7 / 8", "Shift Up / Down"),
    ("9", "Invert Char"),
    ("0", "Reset to CBM Char"),
    ("B hold", "Show CBM Char"),
    ("F", "Fill Area"),
    ("Cursor/Mouse", "Move Around"),
]
HELP_BOTTOM = [
    ("Shift 1-4", "Pick Multicolor Drawing Color"),
    ("Bksp", "Clear Char"),
    ("Shift Bksp", "Clear whole 128-char Block"),
    ("R", "Make Reversed Block"),
    ("Shift R", "Make Normal Block from Reversed"),
]

# Pane 2 keeps the width it had in v1.0 - deriving it from the longest help
# text made the window grow with every shortcut added. The list has to fit
# this width instead; HELP_SIZE below is what buys the room.
FUNC_W = 469
_two_col = 2 * (KEY_W + max(len(t) for _, t in HELP_LEFT + HELP_RIGHT) * CHAR_W) + 16
_one_col = KEY_W + max(len(t) for _, t in HELP_BOTTOM) * CHAR_W
TOTAL_W = EDITOR_W + PANE_GAP + FUNC_W
# Scale the preview by an integer factor (otherwise it blurs) and absorb
# the remainder in the gap between the normal and reversed block, so the
# image ends up exactly as wide as pane 3.
PREV_SCALE = max(1, (TOTAL_W - PANE_PAD * 2 - 4) // PREV_W)
GAP += (TOTAL_W - PANE_PAD * 2 - 4) // PREV_SCALE - PREV_W
# The reversed block should start on the same vertical line as the key
# column in pane 2. Without this it sits a few pixels to the right, which
# reads as a misalignment between the two panes.
_key_x = PAGE_PAD + EDITOR_W + PANE_GAP + 2 + PANE_PAD + 10
_rev_x = PAGE_PAD + 2 + PANE_PAD + (PAD + COLS * 9 + GAP) * PREV_SCALE
GAP -= round((_rev_x - _key_x) / PREV_SCALE)
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
    """.64c files may carry a 2-byte load address.

    Partial fonts are common - a scene charset often holds just the 64
    characters it needs - so the size is not fixed to a full charset. Two
    bytes on top of a multiple of 8 is the load address.
    """
    return data[2:] if len(data) % 8 == 2 else data


def row_hflip(row, mc=False):
    """Mirror one tile row. Wider than a char, so the bytes swap places too.

    Multicolor mirrors whole bit pairs: reversing single bits would turn
    color 01 into 10 and repaint the glyph in the wrong colors.
    """
    bits = "".join(f"{b:08b}" for b in row)
    if mc:
        pairs = [bits[i:i + 2] for i in range(0, len(bits), 2)]
        bits = "".join(reversed(pairs))
    else:
        bits = bits[::-1]
    return [int(bits[i:i + 8], 2) for i in range(0, len(bits), 8)]


def row_shift(row, step):
    """Shift one tile row by a pixel, dropping the bit that falls off the edge.

    step -1 shifts left, +1 right. Across a tile the bits move between the
    chars, so only the outermost pixel of the whole row is lost.
    """
    bits = "".join(f"{b:08b}" for b in row)
    bits = ("0" * step + bits[:-step]) if step > 0 else (bits[-step:] + "0" * -step)
    return [int(bits[i:i + 8], 2) for i in range(0, len(bits), 8)]


def flood_fill(rows, sx, sy, mc=False, new=None):
    """Fill the connected area around (sx,sy).

    Hires flips the area to the opposite value. Multicolor reads the row in
    pairs, so a cell is 2 bits wide and the area is filled with `new`
    (defaulting to the next color along).

    Works on the tile bitmap, so a fill crosses the char boundaries the same
    way the tile is drawn on screen. 4-neighbour scanline-free flood fill;
    a tile is at most 16x16 cells, so an explicit stack is plenty.
    """
    step = 2 if mc else 1                       # bits per cell
    h, w = len(rows), len(rows[0]) * 8 // step
    out = [list(r) for r in rows]

    def cell(x, y):
        byte, off = x // (8 // step), x % (8 // step)
        shift = 8 - step - off * step
        return (out[y][byte] >> shift) & (3 if mc else 1)

    def put(x, y, val):
        byte, off = x // (8 // step), x % (8 // step)
        shift = 8 - step - off * step
        mask = (3 if mc else 1) << shift
        out[y][byte] = (out[y][byte] & ~mask) | ((val << shift) & mask)

    start = cell(sx, sy)
    fill = (start ^ 1) if not mc else ((start + 1) % 4 if new is None else new)
    if fill == start:                           # nothing would change
        return out
    stack = [(sx, sy)]
    while stack:
        x, y = stack.pop()
        if not (0 <= x < w and 0 <= y < h) or cell(x, y) != start:
            continue
        put(x, y, fill)
        stack += [(x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)]
    return out


def fit_tile(rows, w, h):
    """Crop or pad a copied tile so it fits a tile of w bytes by h*8 rows.

    Copying a 2x2 and pasting into a 1x1 keeps the top left corner; the
    other way round the missing part stays empty.
    """
    out = [list(r[:w]) + [0] * max(0, w - len(r)) for r in rows[:h * 8]]
    return out + [[0] * w for _ in range(h * 8 - len(out))]


class Kanji:
    def __init__(self, page: ft.Page):
        self.page = page
        self.chargen = find_chargen()
        self.cbm = load_cbm(self.chargen)
        self.font = bytearray(self.cbm)
        self.cur = 1              # selected char index (0..511); >=256 = lowercase set
        self.point = None         # char the mouse points at in the preview,
                                  # marked but not loaded into the editor
        self.mc = False           # multicolor: pixels read in pairs
        self.mc_draw = 1          # which of the four colors Space paints
        stored = read_config()
        # "mc_colours" was the key up to v1.31 - keep reading it so an
        # existing kanji.json does not silently lose its colors
        cfg = stored.get("mc_colors", stored.get("mc_colours"))
        if isinstance(cfg, list) and len(cfg) == 4:
            cfg = list(cfg)
            if isinstance(cfg[3], int):
                cfg[3] &= 7         # older configs may hold 8-15 here
        self.mc_col = list(cfg) if (isinstance(cfg, list) and len(cfg) == 4
                                    and all(isinstance(c, int) and 0 <= c < 16
                                            for c in cfg)) else list(MC_DEFAULT)
        self.cx = self.cy = 0     # cursor in char editor
        self.focus_editor = True
        self.tile = 0             # index into TILES
        self.clip = None
        self.space = False        # Space is held -> moving draws
        self.stroke = set()       # pixels the running stroke already hit
        self.stroke_undo = None   # its undo step, extended as the stroke grows
        self.stroke_set = True    # what the stroke writes - decided by its
                                  # first pixel, so a line does not switch
                                  # itself back off halfway through
        self.undo, self.redo = [], []
        self.shift = False        # KeyboardListener reports Shift as its own key
        self.show_orig = False    # B held -> show the CBM original instead of the edit
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
        """Char data for display - the CBM original while B is held."""
        i = (self.cur if idx is None else idx) * 8
        src = self.cbm if self.show_orig else self.font
        return src[i:i + 8]

    def put(self, rows, idx=None):
        i = (self.cur if idx is None else idx) * 8
        self.font[i:i + 8] = bytes(rows)

    def tile_chars(self):
        """Every char index the current tile is built from, in reading order."""
        w, h = TILES[self.tile]
        return [self.tile_char(tx, ty) for ty in range(h) for tx in range(w)]

    def snapshot(self, idxs=None):
        """Remember the chars an edit is about to change, as one undo step.

        Takes a single char index or a list of them - a tile-wide edit is
        one step, so one undo takes all of it back.
        """
        if idxs is None:
            idxs = [self.cur]
        elif isinstance(idxs, int):
            idxs = [idxs]
        self.undo.append([(i, bytes(self.get(i))) for i in idxs])
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
                    ft.Container(self.pane(None, self.help_block(), scroll=False),
                                 width=FUNC_W),
                ],
                spacing=PANE_GAP,
                vertical_alignment=ft.CrossAxisAlignment.STRETCH,
            ),
            height=TOP_H,
        )
        self.prev_pane = ft.Container(
            self.pane("CHARSET",
                      ft.GestureDetector(self.preview,
                                         # a click picks the char up, a drag
                                         # keeps picking while it moves;
                                         # hovering only marks it
                                         on_tap_down=self.preview_click,
                                         on_pan_start=self.preview_click,
                                         on_pan_update=self.preview_click,
                                         on_hover=self.preview_hover,
                                         hover_interval=30),
                      expand=True),
            width=TOTAL_W,                        # as wide as pane 1 + 2
            height=PREV_PANE_H)
        # KeyboardListener reads a keystroke but never reports it to Flutter
        # as handled, so macOS answers every key with an alert beep. A focused
        # TextField accepts the key and silences it; the listener still sees
        # it. The field is one pixel and painted in the background color, and
        # its value is dropped on every change so nothing accumulates in it.
        self.sink = ft.TextField(
            autofocus=True, width=1, height=1, text_size=1,
            border=ft.InputBorder.NONE, filled=False, content_padding=0,
            cursor_color=BG, text_style=ft.TextStyle(color=BG),
            on_change=self.drop_sink)
        # a page-level on_keyboard_event stops firing once a GestureDetector
        # takes focus, so the whole UI lives inside the listener
        self.keys = ft.KeyboardListener(
            # the sink sits in a Stack on top of the layout, not in the
            # column: as a column child it would add its own row plus a
            # PANE_GAP and push the status line out of the fixed window
            content=ft.Stack([
                ft.Column([top, self.prev_pane, self.status],
                          spacing=PANE_GAP, tight=True),
                self.sink,
            ]),
            autofocus=False,      # the sink holds the focus, see above
            on_key_down=self.on_key_down,
            on_key_repeat=self.on_key_repeat,
            on_key_up=self.on_key_up,
        )
        self.page.add(self.keys)
        self.refresh()

    def help_block(self):
        """App name plus the two-column function list, uniformly formatted."""
        def entry(key, txt, kw=KEY_W):
            return ft.Row([
                ft.Container(ft.Text(key, color=SEL, size=HELP_SIZE,
                                     font_family="monospace"), width=kw),
                ft.Text(txt, color=FG, size=HELP_SIZE, font_family="monospace",
                        no_wrap=True),
            ], spacing=0)

        def column(items, kw=KEY_W):
            return ft.Column([entry(k, t, kw) for k, t in items], spacing=2)

        return ft.Container(
            ft.Column([
                # logo over its subline, centred
                ft.Image(src=LOGO, width=LOGO_W, fit=ft.BoxFit.CONTAIN),
                ft.Text(f"crossdev c64 font editor {VERSION}",
                        color=FG, size=12, font_family="monospace"),
                credit_line(),
                ft.Container(height=20),        # blank line above the columns
                ft.Row([column(HELP_LEFT), column(HELP_RIGHT)], spacing=16,
                       vertical_alignment=ft.CrossAxisAlignment.START),
                ft.Container(height=6),
                # the bottom rows spell out combinations ("Shift 1-4"), which
                # need more room than a single key name - widened by the same
                # amount the columns above leave free, so the gap matches
                column(HELP_BOTTOM),
            ], spacing=2,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                alignment=ft.MainAxisAlignment.CENTER,
                # no fixed height: the list grows with every new shortcut,
                # and a hardcoded one cuts the last rows off
                tight=True),
            # this pane carries no heading, but pane() still reserves the room
            # for one, which pushes the optical centre up
            padding=ft.Padding.only(left=10, top=KEYS_NUDGE * 2))

    def pane(self, title, content, expand=True, scroll=True):
        # the key pane sizes itself to its content, so a scrollbar there is
        # only ever a stripe over the layout - never something to drag
        inner = ft.Column([content], spacing=0, expand=expand,
                          scroll=ft.ScrollMode.AUTO if scroll else None)
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
                            width=size, height=PIX,
                            alignment=ft.Alignment.CENTER)

    def refresh(self):
        w, h = TILES[self.tile]
        # editable extent: multicolor halves the columns and doubles their
        # width, so the tile keeps the same size on screen
        px, py = w * self.cell_w(), h * 8
        cw = PIX * 2 + 1 if self.mc else PIX

        # Rebuild the grid on every refresh: Flet does not reliably send
        # property mutations on deeply nested controls.
        grid = [ft.Row([self.label("")]
                       + [self.label(RULER[x], cw) for x in range(px)],
                       spacing=1)]
        for y in range(py):
            cells = [self.label(RULER[y])]
            for x in range(px):
                cells.append(ft.Container(
                    width=cw, height=PIX,
                    bgcolor=(rgb_hex(self.tile_cell(x, y)) if self.mc else
                             (FG if self.tile_pixel(x, y) else CELL)),
                    border=(ft.Border.all(1, "#ffffff")
                            if self.focus_editor and (x, y) == (self.cx, self.cy)
                            else None)))
            grid.append(ft.Row(cells, spacing=1))
        # One detector over the whole grid, not one per pixel: a drag that
        # crosses a cell border sends no events to the neighbour, so per-pixel
        # detectors can only ever toggle the cell the press started in.
        self.editor.controls = [ft.GestureDetector(
            ft.Column(grid, spacing=0),
            on_tap_down=self.grid_tap,
            on_pan_start=self.grid_press,
            on_pan_update=self.grid_drag,
            on_pan_end=self.grid_release,
            # a click without movement never sends pan_end; during a drag
            # the release belongs to pan_end instead
            on_tap_up=self.grid_release,
            on_tap_cancel=self.grid_release,
            on_hover=self.grid_hover,
            hover_interval=30)]      # ms; unthrottled hover repaints the grid
                                     # far more often than the eye can follow

        self.tile_prev.controls = self.render_tile() + self.render_mc_colors()
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
            f"{'multicolor' if self.mc else 'hires'}  "
            f"pixel {self.cx},{self.cy}  focus {'editor' if self.focus_editor else 'charset'}"
            + ("   [CBM ORIGINAL]" if self.show_orig else ""))
        self.page.update()
        # the grid is rebuilt above, GestureDetector included; whatever that
        # does to the focus, the key listener has to end up holding it again
        # or macOS beeps at every keypress
        self.grab_keys()

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

    def cell_w(self):
        """Editable cells per char row: 8 in hires, 4 double-wide in MC."""
        return 4 if self.mc else 8

    def row_rgb(self, byte):
        """One char row as 8 rgb values, in whichever mode is active.

        Multicolor reads the same byte in pairs, each picking one of the
        four colors, and every pair covers two screen pixels - so the
        result is still 8 wide and lines up with the hires case.
        """
        if not self.mc:
            return [FG_RGB if byte & (128 >> x) else BG_RGB for x in range(8)]
        out = []
        for pair in range(4):
            rgb = C64_PALETTE[self.mc_col[(byte >> (6 - pair * 2)) & 3]]
            out += [rgb, rgb]
        return out

    def mc_pair(self, x, y, idx=None):
        """Color index 0-3 of multicolor cell x (0-3) in row y.

        A multicolor char is the same 8 bytes; it is only read differently.
        Bits 7+6 are the leftmost cell, 5+4 the next, and so on.
        """
        rows = self.shown(idx)
        return (rows[y] >> (6 - x * 2)) & 3

    def set_pair(self, x, y, val, idx=None):
        """Write a color index 0-3 into multicolor cell x of row y."""
        rows = list(self.get(idx))
        shift = 6 - x * 2
        rows[y] = (rows[y] & ~(3 << shift)) | ((val & 3) << shift)
        self.put(rows, idx)

    def tile_cell(self, x, y):
        """Color of tile cell (x,y) as an rgb tuple, honouring the mode.

        In hires a set bit is the foreground; in multicolor the bit pair
        picks one of the four colors.
        """
        if not self.mc:
            return FG_RGB if self.tile_pixel(x, y) else BG_RGB
        idx = self.tile_char(x // 4, y // 8)
        return C64_PALETTE[self.mc_col[self.mc_pair(x % 4, y % 8, idx)]]

    def render_tile(self):
        """1:1 preview of the tile, built from its individual chars.

        Multicolor cells are twice as wide, so the preview keeps the same
        proportions as the real thing.
        """
        w, h = TILES[self.tile]
        size = 12 if self.mc else 6
        return [ft.Row([self.swatch(self.tile_cell(x, y), size, 6)
                        for x in range(w * self.cell_w())], spacing=0)
                for y in range(h * 8)]

    def swatch(self, rgb, width, height):
        """One preview cell in a fixed color."""
        return ft.Container(width=width, height=height, bgcolor=rgb_hex(rgb))

    def render_mc_colors(self):
        """The four multicolor registers, as 2x2 blocks under the preview.

        Slot 0 is the screen background - it is the one color a char cannot
        set for itself, so it carries a "BG" mark. The slot being drawn with
        has a white frame; clicking picks it, double-clicking opens the
        palette. Picking is the frequent action, so it gets the single click.
        """
        if not self.mc:
            return []
        blocks = []
        for i in range(4):
            c = self.mc_col[i]
            active = i == self.mc_draw
            blocks.append(ft.GestureDetector(
                ft.Container(
                    ft.Text("BG" if i == 0 else "", size=9, color=SEL,
                            font_family="monospace",
                            text_align=ft.TextAlign.CENTER),
                    width=26, height=26,
                    bgcolor=rgb_hex(C64_PALETTE[c]),
                    alignment=ft.Alignment.CENTER,
                    border=ft.Border.all(2 if active else 1,
                                         SEL if active else BORDER),
                    tooltip=f"{'background' if i == 0 else f'color {i}'}: "
                            f"{C64_NAMES[c]} ({c})"
                            f"\nclick = draw with it, double-click = change"),
                on_tap=lambda e, i=i: self.set_draw_color(i),
                on_double_tap=lambda e, i=i: self.page.run_task(
                    self.pick_color, i)))
        return [ft.Container(height=8),
                ft.Row(blocks[:2], spacing=2), ft.Row(blocks[2:], spacing=2)]

    def set_draw_color(self, i):
        """Pick which of the four colors Space and the mouse paint with."""
        self.mc_draw = i
        self.refresh()
        self.grab_keys()

    async def pick_color(self, slot):
        """Pick a C64 color for one of the four multicolor registers.

        Slot 3 comes from colour RAM, which only stores four bits - and bit 3
        is the flag that puts the character into multicolor at all. So that
        slot can only hold colors 0-7; offering 8-15 would look right here
        and come out as hires in the wrong color on a real C64.
        """
        top = 8 if slot == 3 else 16
        choice = asyncio.get_running_loop().create_future()

        def answer(c):
            if not choice.done():
                choice.set_result(c)

        swatches = [
            ft.GestureDetector(
                ft.Container(width=30, height=30, bgcolor=rgb_hex(C64_PALETTE[c]),
                             tooltip=f"{C64_NAMES[c]} ({c})",
                             border=ft.Border.all(
                                 2, SEL if c == self.mc_col[slot] else BORDER)),
                on_tap=lambda e, c=c: answer(c))
            for c in range(top)
        ]
        rows = [ft.Row(swatches[i:i + 8], spacing=4) for i in range(0, top, 8)]
        if slot == 3:
            rows.append(ft.Container(
                ft.Text("colour RAM stores 4 bits, and bit 3 selects\n"
                        "multicolor - so this one is limited to 0-7",
                        size=11, font_family="monospace"),
                padding=ft.Padding.only(top=6)))
        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("Background color" if slot == 0
                          else f"Multicolor {slot}"),
            content=ft.Column(rows, tight=True, spacing=4),
            actions=[ft.TextButton("Cancel", on_click=lambda e: answer(None))],
        )
        self.page.show_dialog(dlg)
        col = await choice
        self.page.pop_dialog()
        if col is not None:
            self.mc_col[slot] = col
            write_config({**read_config(), "mc_colors": self.mc_col})
        self.refresh()
        self.grab_keys()

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
                        for x, rgb in enumerate(self.row_rgb(glyph[y])):
                            # in MC the background is a chosen color, so it
                            # is painted rather than left as the pane blue
                            if self.mc or rgb != BG_RGB:
                                px[gx + tx * 8 + x, gy + ty * 8 + y] = rgb
            if base + i == self.cur or base + i == self.point:
                col_rgb = SEL_RGB if base + i == self.cur else PT_RGB
                for x in range(-1, w * 8 + 1):
                    px[gx + x, gy - 1] = col_rgb
                    px[gx + x, min(gy + h * 8, PREV_H - 1)] = col_rgb
                for y in range(-1, h * 8 + 1):
                    px[gx - 1, gy + y] = col_rgb
                    px[gx + w * 8, gy + y] = col_rgb
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
                        for x, rgb in enumerate(self.row_rgb(rows[y])):
                            if self.mc or rgb != BG_RGB:
                                px[gx + x, gy + y] = rgb
                    # white frame = the char in the editor, dim frame = the
                    # one the mouse is pointing at
                    if c == self.cur or c == self.point:
                        col_rgb = SEL_RGB if c == self.cur else PT_RGB
                        for x in range(-1, 9):
                            px[gx + x, gy - 1] = col_rgb
                            px[gx + x, gy + 8] = col_rgb
                        for y in range(-1, 9):
                            px[gx - 1, gy + y] = col_rgb
                            px[gx + 8, gy + y] = col_rgb
        im = im.resize((PREV_W * PREV_SCALE, PREV_H * PREV_SCALE), Image.NEAREST)
        buf = io.BytesIO()
        im.save(buf, "PNG")
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()

    def preview_char(self, e):
        """Char index under the pointer in the preview, or None beside one."""
        pos = e.local_position
        if pos is None:
            return None
        ix = pos.x / PREV_SCALE - PAD                          # image coordinates
        iy = pos.y / PREV_SCALE - PAD
        base = (self.cur // 256) * 256
        if self.font_prev:                                     # tile view
            w, h = TILES[self.tile]
            tw, th = w * 8 + 1, h * 8 + 1
            i = int(iy // th) * self.prev_cols() + int(ix // tw)
            return base + i if (0 <= i < 64 and ix >= 0 and iy >= 0) else None
        if ix < 0 or iy < 0:
            return None
        row = int(iy) // 9
        half = 0 if ix < COLS * 9 else 1                 # left/right block
        if half:
            ix -= COLS * 9 + GAP
        col = int(ix) // 9
        if not (0 <= row < ROWS and 0 <= col < COLS):
            return None
        return base + row * COLS + col + half * 128

    def preview_click(self, e):
        """Click in the preview: this char becomes the one being edited."""
        c = self.preview_char(e)
        if c is not None:
            self.select(c)

    def preview_hover(self, e):
        """Pointer moved over the preview - move the marker, nothing else.

        Hovering only points at a char; it does not load it into the editor.
        That takes a click, so passing over the pane on the way somewhere
        else cannot replace what is being worked on.
        """
        c = self.preview_char(e)
        if c is None or c == self.point:
            return
        self.point = c
        self.refresh()

    def drop_point(self):
        """Forget where the mouse pointed.

        Called whenever the keyboard takes over, so the pane never shows the
        white selection frame and the dim mouse frame at the same time.
        """
        if self.point is not None:
            self.point = None
            return True
        return False

    def cell_char(self, x, y):
        """Char index the editor cell (x,y) belongs to, in either mode."""
        return self.tile_char(x // self.cell_w(), y // 8)

    def toggle(self, x, y, snapshot=True):
        """Change the cell under the cursor.

        Hires flips the bit. Multicolor steps through the four colors, so
        one key reaches all of them the way Space reaches both hires states.
        """
        self.cx, self.cy = x, y
        self.focus_editor = True
        idx = self.cell_char(x, y)
        if snapshot:
            self.snapshot(idx)
        if self.mc:
            # paint the selected color; on a cell that already has it, fall
            # back to the background so one key still clears
            have = self.mc_pair(x % 4, y % 8, idx)
            self.set_pair(x % 4, y % 8,
                          0 if have == self.mc_draw else self.mc_draw, idx)
        else:
            rows = list(self.get(idx))
            rows[y % 8] ^= 128 >> (x % 8)
            self.put(rows, idx)
        self.refresh()

    def grid_pixel(self, e):
        """Tile cell under a pointer event, or None outside the drawing area.

        The grid starts one cell in on both axes - that row and column hold
        the ruler labels. Multicolor cells are twice as wide.
        """
        pos = e.local_position
        if pos is None:
            return None
        w, h = TILES[self.tile]
        cw = (PIX * 2 + 1 if self.mc else PIX) + 1
        x = int(pos.x - (PIX + 1)) // cw
        y = int(pos.y - PIX) // PIX
        if pos.x < PIX + 1 or pos.y < PIX:
            return None
        return (x, y) if 0 <= x < w * self.cell_w() and 0 <= y < h * 8 else None

    def grid_tap(self, e):
        """Press on the grid - always the start of a fresh stroke.

        on_tap_down arrives before on_pan_start, so this is where a stroke
        begins; the pan handlers only ever extend it.
        """
        self.stroke = set()
        self.stroke_undo = None
        self.grid_press(e)
        self.grab_keys()

    def grid_press(self, e):
        """Invert the pressed pixel and open a stroke.

        The mouse button is the draw modifier, the same role Space plays for
        the cursor keys. A plain click fires both on_tap_down and
        on_pan_start; the second lands on a pixel the stroke already holds
        and is ignored, so it never draws twice.
        """
        p = self.grid_pixel(e)
        if p is None or p in self.stroke:
            return
        self.stroke.add(p)
        self.stroke_draw(*p)

    def grid_hover(self, e):
        """Mouse moved over the grid: follow with the cursor, draw if Space.

        Space is the draw modifier, not the mouse button. Flet reports no
        usable end for a button press here: releasing it mid-move sends
        neither tap_up nor pan_end, and pan updates simply keep coming, so
        "button is down" cannot be tracked without getting stuck on. Space
        arrives as a clean down/up pair and holds through a drag.
        """
        p = self.grid_pixel(e)
        if p is None:
            return
        if self.space:
            if p not in self.stroke:
                self.stroke.add(p)
                self.stroke_draw(*p)
            return
        if p == (self.cx, self.cy) and self.focus_editor:
            return                  # nothing moved - repainting would only flicker
        self.cx, self.cy = p
        self.focus_editor = True
        self.refresh()

    def grid_release(self, e=None):
        """End of a stroke - the next press starts a fresh undo step."""
        self.stroke = set()
        self.stroke_undo = None
        self.grab_keys()

    def drop_sink(self, e=None):
        """Throw away whatever landed in the key sink - it is not an input."""
        self.sink.value = ""

    def grab_keys(self):
        """Put the focus back on the key sink.

        Clicking the grid moves the focus to the GestureDetector, after
        which the sink no longer swallows keystrokes: macOS starts beeping
        again and Space never reaches on_key_down, so the set/erase mode
        stops engaging.

        focus() is a coroutine: calling it without awaiting builds a
        coroutine object that never runs, which is exactly as broken as not
        calling it at all - only quieter.
        """
        self.page.run_task(self.sink.focus)

    def grid_drag(self, e):
        """Pan update - same rule as hover: only Space draws.

        Pan updates keep arriving after the button was released (Flet sends
        no end event for it), so acting on them unconditionally would paint
        on long after the drag is over.
        """
        self.grid_hover(e)


    def stroke_draw(self, x, y):
        """Draw one pixel of the current stroke, extending its undo step.

        The first pixel decides what the whole stroke does: starting on an
        empty pixel sets, starting on a set one erases. Toggling each pixel
        individually would switch already-set pixels back off halfway
        through a line, which makes drawing a solid shape impossible.
        """
        idx = self.cell_char(x, y)
        if self.stroke_undo is None:            # first cell opens the step
            self.snapshot(idx)
            self.stroke_undo = self.undo[-1]
            # from the working charset, not shown() - while B is held that
            # would read the CBM original and pick the wrong direction
            if self.mc:
                # the selected color, unless the stroke starts on a cell
                # that already has it - then it erases, mirroring hires
                cur = (self.get(idx)[y % 8] >> (6 - (x % 4) * 2)) & 3
                self.stroke_set = 0 if cur == self.mc_draw else self.mc_draw
            else:
                self.stroke_set = not (self.get(idx)[y % 8] & (128 >> (x % 8)))
        elif not any(i == idx for i, _ in self.stroke_undo):
            # the stroke ran into another char of the tile - fold its previous
            # state into the same step so one undo takes the whole stroke back
            self.stroke_undo.append((idx, bytes(self.get(idx))))
        self.cx, self.cy = x, y
        self.focus_editor = True
        if self.mc:
            self.set_pair(x % 4, y % 8, self.stroke_set, idx)
        else:
            rows = list(self.get(idx))
            bit = 128 >> (x % 8)
            rows[y % 8] = ((rows[y % 8] | bit) if self.stroke_set
                           else (rows[y % 8] & ~bit))
            self.put(rows, idx)
        self.refresh()

    def select(self, c):
        # a drag reports many events per char - repainting for a selection
        # that did not move would re-render the preview PNG for nothing
        if c == self.cur and not self.focus_editor and self.point is None:
            return
        self.point = None           # the white frame marks it from here on
        self.cur = c
        self.focus_editor = False
        self.refresh()

    # --- edits -------------------------------------------------------
    def tile_rows(self):
        """The tile as one bitmap: h*8 rows of w bytes, left to right."""
        w, h = TILES[self.tile]
        chars = [[self.get(self.tile_char(tx, ty)) for tx in range(w)]
                 for ty in range(h)]
        return [[chars[y // 8][tx][y % 8] for tx in range(w)]
                for y in range(h * 8)]

    def cbm_tile_rows(self):
        """The tile bitmap as it looks in the untouched CBM charset."""
        w, h = TILES[self.tile]
        return [[self.cbm[self.tile_char(tx, ty) * 8 + y % 8] for tx in range(w)]
                for ty in range(h) for y in range(8)]

    def put_tile_rows(self, rows):
        """Write a tile bitmap back into the chars it is made of."""
        w, h = TILES[self.tile]
        for ty in range(h):
            for tx in range(w):
                self.put([rows[ty * 8 + y][tx] for y in range(8)],
                         self.tile_char(tx, ty))

    def edit(self, fn):
        """Apply fn to the whole tile, not just the char under the cursor.

        fn works on a single char (8 rows of one byte). For a tile it is
        applied to the tile bitmap instead, so a flip or a shift crosses
        the char boundaries the way the tile is drawn on screen.
        """
        self.snapshot(self.tile_chars())
        self.put_tile_rows(fn(self.tile_rows()))
        self.refresh()

    def on_key_down(self, e):
        if str(e.key).startswith("Shift"):
            self.shift = True
            return
        k = str(e.key)
        if k in (" ", "Space"):
            # Space is a held key: while it is down, moving draws. The stroke
            # it opens spans every pixel the cursor crosses, as one undo step.
            if self.space:
                return                      # ignore the OS auto-repeat
            self.space = True
            self.stroke, self.stroke_undo = set(), None
        self.on_key(types.SimpleNamespace(key=k, shift=self.shift))

    # Keys that may fire on auto-repeat while held. Everything else stays a
    # one-shot: a held Backspace would clear tile after tile, a held T would
    # spin through the tile sizes. Space is not in here either - it is a
    # modifier while held, and the movement it draws along comes from the
    # cursor keys, which do repeat.
    REPEATABLE = ("Arrow Left", "Arrow Right", "Arrow Up", "Arrow Down")

    def on_key_repeat(self, e):
        """The OS repeats a held key - move on, instead of one step per press."""
        k = str(e.key)
        if k.startswith("Numpad "):
            k = k[7:]
        if k in self.REPEATABLE:
            self.on_key(types.SimpleNamespace(key=k, shift=self.shift))

    def on_key_up(self, e):
        k = str(e.key)
        if k.startswith("Shift"):
            self.shift = False
        elif k in (" ", "Space"):
            self.space = False
            self.stroke, self.stroke_undo = set(), None
        elif k == "B" and self.show_orig:
            self.show_orig = False          # original only while the key is held
            self.refresh()

    def on_key(self, e):
        # the numeric keypad reports "Numpad 9" etc.; treat it as the digit
        k = e.key
        if k.startswith("Numpad "):
            k = k[7:]
        # any key means the keyboard is driving now - the mouse marker goes,
        # otherwise the charset pane shows two frames at once
        dropped = self.drop_point()
        # Shift+1..4 picks the drawing color. A German layout reports the
        # shifted digits as their symbols, so both spellings are accepted.
        if self.mc and e.shift and k in MC_KEYS:
            self.mc_draw = MC_KEYS[k]
        elif k == "Tab" and e.shift:
            self.cur = (self.cur + 256) % 512          # upper <-> lowercase set
        elif k == "Tab":
            self.focus_editor = not self.focus_editor
        elif k in (" ", "Space"):
            if self.focus_editor:
                self.stroke.add((self.cx, self.cy))
                self.stroke_draw(self.cx, self.cy)   # repaints on its own
            elif dropped:
                self.refresh()
            return
        elif k in ("Arrow Left", "Arrow Right", "Arrow Up", "Arrow Down"):
            self.move(k)
            if self.space and self.focus_editor:
                # Space held: the cursor draws as it goes, the whole run
                # collapsing into the single undo step Space opened
                p = (self.cx, self.cy)
                if p not in self.stroke:
                    self.stroke.add(p)
                    self.stroke_draw(*p)
        elif k == "L":
            self.page.run_task(self.do_load)
        elif k == "S":
            self.page.run_task(self.do_save)
        elif k == "C":
            self.clip = self.tile_rows()
        elif k == "V" and self.clip:
            self.edit(lambda t: fit_tile(self.clip, len(t[0]), len(t)))
        elif k == "P":
            self.font_prev = not self.font_prev
            if self.font_prev:                  # preview only shows 0-63
                base = (self.cur // 256) * 256
                self.cur = base + (self.cur - base) % 64
        elif k in ("M", "H"):
            was = self.mc
            self.mc = (k == "M")
            if self.mc != was:
                # the column count changes with the mode - keep the cursor
                # on the cell it visually sat on, and inside the tile
                self.cx = self.cx // 2 if self.mc else self.cx * 2
                w, _ = TILES[self.tile]
                self.cx = min(self.cx, w * self.cell_w() - 1)
        elif k == "T":
            self.tile = (self.tile + 1) % len(TILES)
            w, h = TILES[self.tile]
            self.cx = min(self.cx, w * self.cell_w() - 1)
            self.cy = min(self.cy, h * 8 - 1)
        elif k == "1":
            self.pop(self.undo, self.redo)
        elif k == "2":
            self.pop(self.redo, self.undo)
        elif k == "3":
            self.edit(lambda t: [row_hflip(r, self.mc) for r in t])
        elif k == "4":
            self.edit(lambda t: t[::-1])
        elif k == "5":
            # multicolor shifts by a whole cell, so colors stay intact
            self.edit(lambda t: [row_shift(r, -2 if self.mc else -1) for r in t])
        elif k == "6":
            self.edit(lambda t: [row_shift(r, 2 if self.mc else 1) for r in t])
        elif k == "7":
            self.edit(lambda t: t[1:] + [[0] * len(t[0])])
        elif k == "8":
            self.edit(lambda t: [[0] * len(t[0])] + t[:-1])
        elif k == "9":
            self.edit(lambda t: [[b ^ 0xFF for b in r] for r in t])
        elif k == "0":
            self.edit(lambda t: self.cbm_tile_rows())
        elif k == "R":
            self.make_reversed(back=e.shift)
        elif k == "F":
            self.edit(lambda t: flood_fill(t, self.cx, self.cy, self.mc))
        elif k == "Backspace" and e.shift:
            self.clear_block()
        elif k == "Backspace":
            self.edit(lambda t: [[0] * len(t[0]) for _ in t])
        elif k == "B":
            if self.show_orig:              # ignore auto-repeat
                return
            self.show_orig = True
        else:
            if dropped:             # nothing to do but the marker went away
                self.refresh()
            return
        self.refresh()

    def move(self, k):
        d = {"Arrow Left": (-1, 0), "Arrow Right": (1, 0),
             "Arrow Up": (0, -1), "Arrow Down": (0, 1)}[k]
        w, h = TILES[self.tile]
        if self.focus_editor:
            self.cx = (self.cx + d[0]) % (w * self.cell_w())
            self.cy = (self.cy + d[1]) % (h * 8)
        else:
            base = (self.cur // 256) * 256          # stay inside the active set
            if self.font_prev:
                # the font preview only shows base chars 0-63 with that many
                # tiles per row -> keep navigation inside that range
                span, per_row = 64, self.prev_cols()
                self.cur = base + (self.cur - base + d[0] + d[1] * per_row) % span
                return
            # The charset pane draws two blocks side by side: 0-127 normal on
            # the left, 128-255 reversed on the right. Moving by index alone
            # would wrap char 15 to char 16 - the start of the next line -
            # while on screen the char to its right is 128. So move on the
            # grid the eye sees: 32 columns wide, the right half offset by
            # 128, and let a step off one edge continue into the other block.
            i = self.cur - base
            col = i % COLS + (COLS if i >= 128 else 0)
            row = (i % 128) // COLS
            col = (col + d[0]) % (COLS * 2)
            row = (row + d[1]) % ROWS
            self.cur = base + (col % COLS) + row * COLS + (128 if col >= COLS else 0)

    def make_reversed(self, back=False):
        """Fill one half of the active charset with the inverted other half.

        R takes chars 0-127 into 128-255, Shift+R goes the other way. The
        whole run is a single undo step - 128 separate ones would be
        unusable.
        """
        base = (self.cur // 256) * 256
        src, dst = (128, 0) if back else (0, 128)
        idxs = [base + dst + i for i in range(128)]
        self.snapshot(idxs)
        for i in range(128):
            rows = self.get(base + src + i)
            self.put([b ^ 0xFF for b in rows], base + dst + i)
        # no status message: on_key refreshes right after this and would
        # overwrite it - the result is visible in pane 3 anyway

    def clear_block(self):
        """Wipe the 128-char block the selected char sits in, as one step.

        Which block that is follows the selection: chars 0-127 are the
        normal one, 128-255 the reversed one.
        """
        base = (self.cur // 256) * 256 + (128 if self.cur % 256 >= 128 else 0)
        idxs = [base + i for i in range(128)]
        self.snapshot(idxs)
        for i in idxs:
            self.put([0] * 8, i)

    def pop(self, src, dst):
        """Undo or redo one step - a step may span several chars of a tile."""
        if not src:
            return
        step = src.pop()
        dst.append([(i, bytes(self.get(i))) for i, _ in step])
        for idx, rows in step:
            self.put(rows, idx)
        self.cur = step[0][0]

    # --- io ----------------------------------------------------------
    async def ask_chargen(self):
        """Offer a choice when no chargen ROM was found: pick a file, or
        download the OpenROM one.

        Without a charset the editor is useless ('0' and 'B' have no
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

    async def ask_charsets(self):
        """Which charsets to save. Both are ticked by default.

        Returns (lower, upper) or None if the dialog was cancelled. Save is
        blocked while neither is ticked - there would be nothing to write.
        """
        choice = asyncio.get_running_loop().create_future()

        def answer(ok):
            if not choice.done():
                choice.set_result(ok)

        lower = ft.Checkbox(label="Charset 1 - uppercase", value=True)
        upper = ft.Checkbox(label="Charset 2 - lowercase", value=True)
        save = ft.TextButton("Save", on_click=lambda e: answer(True))

        def tick(e):
            save.disabled = not (lower.value or upper.value)
            self.page.update()

        lower.on_change = upper.on_change = tick

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("Save charsets"),
            content=ft.Column([
                ft.Text("Both charsets go into one 4096-byte file, a single "
                        "one into 2048 bytes.", font_family="monospace", size=12),
                ft.Container(height=8),
                lower, upper,
            ], tight=True),
            actions=[
                ft.TextButton("Cancel", on_click=lambda e: answer(False)),
                save,
            ],
        )
        self.page.show_dialog(dlg)
        ok = await choice
        self.page.pop_dialog()
        return (lower.value, upper.value) if ok else None

    async def do_save(self):
        """Save the picked charsets as a raw dump (.64c/.bin).

        The "which charsets" dialog can be turned off by putting
        "ask_charsets": false in kanji.json - then both are always written.
        """
        if read_config().get("ask_charsets", True):
            picked = await self.ask_charsets()
            if picked is None:
                return
        else:
            picked = (True, True)
        lower, upper = picked

        # no extension in the suggested name: the macOS dialog appends the
        # allowed one itself, which turned "font.64c" into "font.64c.64c"
        path = await self.picker.save_file("Save Charset", file_name="font",
                                           allowed_extensions=list(EXTS))
        if not path:
            return
        if not path.lower().endswith(tuple("." + e for e in EXTS)):
            path += ".64c"

        if lower and upper:
            data, what = self.font[:4096], "both charsets"
        elif lower:
            data, what = self.font[:2048], "charset 1"
        else:
            data, what = self.font[2048:4096], "charset 2"
        with open(path, "wb") as f:
            f.write(data)
        self.note(f"saved: {os.path.basename(path)} "
                  f"({len(data)} B, {what})")

    def note(self, msg):
        """Show a message in the status line."""
        self.status.value = msg
        self.page.update()


async def main(page: ft.Page):
    page.title = (f"{TITLE} {VERSION} - crossdev c64 font editor"
                  f" - {BYLINE.removeprefix('by ')}")
    page.bgcolor = "#000000"
    page.padding = PAGE_PAD
    page.window.width = page.window.min_width = WIN_W
    page.window.height = page.window.min_height = WIN_H
    page.window.resizable = False        # fixed size, no empty space
    Kanji(page)
    page.update()
    await page.window.center()


if __name__ == "__main__":
    ft.run(main)
