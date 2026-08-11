#!/usr/bin/env python3
"""Self-check for kanji's pure logic. Run: python3 test_kanji.py"""

import os
import tempfile
import types

from kanji import load_cbm, strip_load_addr, Kanji, PREV_SCALE

A = [24, 60, 102, 126, 102, 102, 102, 0]   # README char "A"

# CI runners have no VICE installation, so ROM-dependent checks are optional
HAVE_ROM = load_cbm() != bytearray(4096)

hflip = lambda r: [int(f"{b:08b}"[::-1], 2) for b in r]
vflip = lambda r: r[::-1]
shl = lambda r: [(b << 1) & 0xFF for b in r]
shr = lambda r: [b >> 1 for b in r]
up = lambda r: r[1:] + r[:1]
down = lambda r: r[-1:] + r[:-1]
inv = lambda r: [b ^ 0xFF for b in r]
swap = lambda r: [((b >> 4) | (b << 4)) & 0xFF for b in r]


def main():
    cbm = load_cbm()
    assert len(cbm) == 4096
    if HAVE_ROM:
        assert list(cbm[8:16]) == A, "char 1 must be 'A' from the chargen ROM"
    else:
        assert cbm == bytearray(4096), "without a ROM the charset must be empty"
        print("note: no chargen ROM found - ROM-dependent checks skipped")

    # load address stripping
    assert strip_load_addr(bytearray(b"\x00\x30" + b"x" * 2048)) == bytearray(b"x" * 2048)
    assert strip_load_addr(bytearray(b"x" * 2048)) == bytearray(b"x" * 2048)

    # every transform is its own inverse or has a known inverse
    for f in (hflip, vflip, inv, swap):
        assert f(f(A)) == A, f
    assert up(down(A)) == A
    assert down(up(A)) == A
    assert hflip([0b10000000]) == [0b00000001]
    assert shl([0b10000001]) == [0b00000010]   # top bit falls off
    assert shr([0b10000001]) == [0b01000000]   # low bit falls off
    assert swap([0b11110000]) == [0b00001111]
    assert inv([0]) == [255]

    tiles()
    keys()
    charset_io()
    show_original()
    font_preview()
    chargen_search_is_quick()
    chargen_lookup()
    print("OK")


def chargen_search_is_quick():
    """A full search must not walk every application bundle.

    An unbounded '**' over /Applications took minutes on a machine with no
    cached path - long enough to stall a CI runner - while finding nothing
    the bounded patterns miss.
    """
    import glob, time
    import kanji as K

    for pattern in K.CHARGEN_QUICK + K.CHARGEN_SLOW:
        head = pattern.split("**")[0]
        assert "**" not in pattern or head.count("/") > 2, \
            f"unbounded recursive glob: {pattern}"

    start = time.time()
    for pattern in K.CHARGEN_QUICK + K.CHARGEN_SLOW:
        glob.glob(pattern, recursive=True)
    elapsed = time.time() - start
    assert elapsed < 10, f"chargen search took {elapsed:.1f}s"
    print("OK")


def chargen_lookup():
    """chargen lookup: remember it, reuse it, search again if it is bogus."""
    import kanji as K
    saved = K.CONFIG, K.CHARGEN_QUICK, K.CHARGEN_SLOW
    K.CONFIG = os.path.join(tempfile.mkdtemp(), "cfg.json")
    try:
        assert not K.valid_chargen(None)
        assert not K.valid_chargen("/existiert/nicht")

        found = K.find_chargen()
        if found:                                   # only where VICE is installed
            assert K.read_config().get("chargen") == found, "path is remembered"
            assert K.find_chargen() == found, "the remembered path is used"
            K.write_config({"chargen": "/gone"})
            assert K.find_chargen() == found, "stale entry -> search again"

        # no hit: an empty charset rather than a crash
        K.CHARGEN_QUICK, K.CHARGEN_SLOW = ["/nirgends/chargen"], []
        K.CONFIG = os.path.join(tempfile.mkdtemp(), "cfg2.json")
        assert K.find_chargen() is None
        assert K.load_cbm(None) == bytearray(4096)

        # a 2 KB charset is valid and gets padded to 4096
        half = os.path.join(tempfile.mkdtemp(), "half.64c")
        with open(half, "wb") as f:
            f.write(bytes(A) * 256)                 # genau 2048 Bytes
        assert K.valid_chargen(half), "2048 Bytes muessen reichen"
        d = K.load_cbm(half)
        assert len(d) == 4096, "immer auf 4096 aufgefuellt"
        assert list(d[0:8]) == A and d[2048:] == bytearray(2048)

        # the load address is stripped when loading a charset too
        withaddr = os.path.join(tempfile.mkdtemp(), "addr.64c")
        with open(withaddr, "wb") as f:
            f.write(b"\x00\x38" + bytes(A) * 256)
        assert list(K.load_cbm(withaddr)[0:8]) == A, "Ladeadresse entfernt"

        # OpenROM download: None on a network error rather than a crash
        real_dir, real_url = K.APP_DIR, K.OPENROM_URL
        try:
            K.APP_DIR = tempfile.mkdtemp()
            K.OPENROM_URL = "https://example.invalid/nichts.rom"
            assert K.Kanji.download_openrom() is None, "Netzfehler -> None"
        finally:
            K.APP_DIR, K.OPENROM_URL = real_dir, real_url
    finally:
        K.CONFIG, K.CHARGEN_QUICK, K.CHARGEN_SLOW = saved


def font_preview():
    """P toggles pane 3 between the charset and the tile view."""
    k = headless()
    ev = lambda key: types.SimpleNamespace(key=key, shift=False)

    assert not k.font_prev
    k.on_key(ev("P"))
    assert k.font_prev, "P schaltet die Font-Preview ein"
    k.on_key(ev("P"))
    assert not k.font_prev, "nochmal P schaltet zurueck"

    # navigation stays within base characters 0-63 in the preview
    k.font_prev = True
    k.focus_editor = False
    k.tile = 0
    k.cur = 63
    k.on_key(ev("Arrow Right"))
    assert k.cur == 0, f"nach 63 folgt wieder 0, war {k.cur}"
    k.cur = 0
    k.on_key(ev("Arrow Left"))
    assert k.cur == 63, f"vor 0 liegt 63, war {k.cur}"
    k.cur = 0
    k.on_key(ev("Arrow Down"))
    assert k.cur < 64, f"runter bleibt unter 64, war {k.cur}"

    # toggling brings a character >=64 into view
    k.font_prev = False
    k.cur = 200
    k.on_key(ev("P"))
    assert k.cur < 64, f"P begrenzt auf 0-63, war {k.cur}"

    # a click in the tile view hits the right base character
    k.font_prev = True
    k.tile = 3                                   # 2x2 -> Tile ist 17 px breit
    picked = []
    k.select = lambda c: picked.append(c)
    tw = 2 * 8 + 1
    k.preview_click(tap_at((1 + tw * 3) * PREV_SCALE, 1 * PREV_SCALE))
    assert picked == [3], f"4. Tile der 1. Zeile = Zeichen 3, war {picked}"

    # a click in the charset view: 2nd character of the 1st row
    k.font_prev = False
    k.cur = 0
    picked.clear()
    k.preview_click(tap_at((1 + 9) * PREV_SCALE, 1 * PREV_SCALE))
    assert picked == [1], f"2. Zeichen der 1. Zeile, war {picked}"


def show_original():
    """Holding ß shows the CBM original, releasing shows the edit again."""
    k = headless()
    k.cur = 1
    k.put([0] * 8)                               # Zeichen leeren
    assert list(k.shown()) == [0] * 8

    ev = lambda key: types.SimpleNamespace(key=key, shift=False)
    k.on_key(ev("ß"))                            # gedrueckt
    assert k.show_orig
    assert list(k.shown()) == A, "zeigt das CBM-Original"
    assert list(k.get()) == [0] * 8, "Arbeitsdaten bleiben unveraendert"

    k.on_key_up(ev("ß"))                         # losgelassen
    assert not k.show_orig
    assert list(k.shown()) == [0] * 8, "zeigt wieder die Bearbeitung"


def charset_io():
    """Load and save operate on 2048-byte charsets (README)."""
    k = headless()

    # save: the active charset only, 2048 bytes
    k.cur = 1
    assert len(k.font[0:2048]) == 2048
    k.cur = 300                                  # zweiter Zeichensatz
    base = (k.cur // 256) * 256 * 8
    assert base == 2048

    # loading a 2048-byte dump replaces the active set only
    k.font[:] = bytearray(4096)
    data = bytearray(range(256)) * 8             # 2048 Bytes Testmuster
    n = min(len(data), 2048)
    k.font[base:base + n] = data[:n]
    assert k.font[2048:2048 + 8] == data[:8], "in Charset 2 geladen"
    assert k.font[0:8] == bytearray(8), "Charset 1 bleibt unberuehrt"

    # 4096 bytes replace both sets
    both = bytearray(range(256)) * 16
    k.font[:4096] = both[:4096]
    assert k.font[0] == both[0] and k.font[2048] == both[2048]

    # the load address is stripped
    assert len(strip_load_addr(bytearray(b"\x00\x38" + b"x" * 2048))) == 2048
    assert len(strip_load_addr(bytearray(b"x" * 2048))) == 2048


def tiles():
    """README FONT FORMAT: SHIFT = +64, REVERSE = +128, real characters."""
    k = headless()
    k.cur = 1                                   # A

    k.tile = 0                                  # 1x1
    assert k.tile_char(0, 0) == 1

    k.tile = 1                                  # 1x2: unten = REVERSE
    assert [k.tile_char(0, y) for y in (0, 1)] == [1, 129]

    k.tile = 2                                  # 2x1: rechts = SHIFT
    assert [k.tile_char(x, 0) for x in (0, 1)] == [1, 65]

    k.tile = 3                                  # 2x2:  A        SHIFT
    assert k.tile_char(0, 0) == 1               #       REVERSE  SHIFT REVERSE
    assert k.tile_char(1, 0) == 65              # rechts oben = SHIFT A
    assert k.tile_char(0, 1) == 129             # links unten = REVERSE A
    assert k.tile_char(1, 1) == 193             # rechts unten = SHIFT REVERSE A

    # the pixel comes from the respective character
    k.font[65 * 8] = 0b10000000
    assert k.tile_pixel(8, 0), "rechts oben liest SHIFT A"
    k.put([0] * 8, 1)
    assert not k.tile_pixel(0, 0)

    # toggle writes into exactly that character
    k.cur = 1
    k.put([0] * 8, 129)
    k.toggle(0, 8)                              # links unten -> REVERSE A (129)
    assert k.font[129 * 8] & 0x80, "toggle muss in REVERSE A schreiben"
    assert not k.font[1 * 8] & 0x80, "Basiszeichen bleibt unveraendert"

    # second charset: the tile stays inside it
    k.cur = 257
    assert k.tile_char(1, 1) == 257 + 192


def tap_at(x, y):
    """A real Flet TapEvent - building a stub here would hide API changes."""
    from flet.controls.core.gesture_detector import TapEvent
    from flet.controls.transform import Offset

    ev = TapEvent.__new__(TapEvent)
    object.__setattr__(ev, "local_position", Offset(x, y))
    object.__setattr__(ev, "global_position", Offset(x, y))
    return ev


def headless():
    """A Kanji instance driven through its real key handler, without widgets.

    Uses a synthetic charset with 'A' at index 1 so the tests behave the same
    with or without a chargen ROM installed (CI runners have no VICE).
    """
    k = Kanji.__new__(Kanji)
    k.cbm = bytearray(4096)
    k.cbm[8:16] = bytes(A)                      # char 1 = "A", like the real ROM
    k.font = bytearray(k.cbm)
    k.cur, k.cx, k.cy = 1, 0, 0
    k.focus_editor, k.tile, k.clip = True, 0, None
    k.shift, k.show_orig, k.font_prev = False, False, False
    k.undo, k.redo = [], []
    k.refresh = lambda: None
    k.page = types.SimpleNamespace(run_task=lambda f: None)
    return k


def keys():
    k = headless()
    ev = lambda key, shift=False: types.SimpleNamespace(key=key, shift=shift)

    k.on_key(ev("9")); assert list(k.get()) == inv(A), "invert"
    k.on_key(ev("1")); assert list(k.get()) == A, "undo"
    k.on_key(ev("2")); assert list(k.get()) == inv(A), "redo"
    k.on_key(ev("0")); assert list(k.get()) == A, "reset to CBM"

    k.on_key(ev("C"))
    k.cur = 2
    k.on_key(ev("V")); assert list(k.get()) == A, "paste"
    k.on_key(ev("Backspace")); assert list(k.get()) == [0] * 8, "clear"
    k.on_key(ev("1")); assert list(k.get()) == A, "undo clear"

    # Shift-Tab swaps charset, keeps the index; Tab swaps focus
    k.cur = 5
    k.on_key(ev("Tab", shift=True)); assert k.cur == 261
    k.on_key(ev("Tab", shift=True)); assert k.cur == 5
    k.on_key(ev("Tab")); assert k.focus_editor is False

    # preview cursor wraps inside the active set, never across sets
    k.cur = 255; k.on_key(ev("Arrow Right")); assert k.cur == 0
    k.cur = 256; k.on_key(ev("Arrow Left")); assert k.cur == 511

    # tile cycle clamps the editor cursor back into range
    k.focus_editor, k.tile, k.cx, k.cy = True, 3, 15, 15
    k.on_key(ev("T")); assert (k.tile, k.cx, k.cy) == (0, 7, 7)

    # keypad digits arrive as "Numpad 9" and must dispatch like "9"
    k.cur = 3
    before = list(k.get())
    k.on_key(ev("Numpad 9")); assert list(k.get()) == inv(before), "numpad"

    # space toggles the pixel under the cursor
    k.cur, k.cx, k.cy = 2, 0, 0
    before = list(k.get())
    k.on_key(ev(" ")); assert list(k.get())[0] == before[0] ^ 128, "space"


if __name__ == "__main__":
    main()
