#!/usr/bin/env python3
"""Self-check for kanji's pure logic. Run: python3 test_kanji.py"""

import asyncio
import os
import tempfile
import types

from kanji import (load_cbm, strip_load_addr, Kanji, PREV_SCALE, MC_DEFAULT,
                   flood_fill, row_hflip)

A = [24, 60, 102, 126, 102, 102, 102, 0]   # README char "A"

# CI runners have no VICE installation, so ROM-dependent checks are optional
HAVE_ROM = load_cbm() != bytearray(4096)

hflip = lambda r: [int(f"{b:08b}"[::-1], 2) for b in r]
vflip = lambda r: r[::-1]
shl = lambda r: [(b << 1) & 0xFF for b in r]
shr = lambda r: [b >> 1 for b in r]
up = lambda r: r[1:] + [0]        # like shl/shr, the row that leaves is lost
down = lambda r: [0] + r[:-1]
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

    # load address stripping, also for partial fonts - a scene charset often
    # carries just the 64 characters it needs, not a full 2048-byte set
    for size in (2048, 4096, 512, 8):
        assert len(strip_load_addr(bytearray(b"\x00\x30" + b"x" * size))) == size
        assert len(strip_load_addr(bytearray(b"x" * size))) == size

    # every transform is its own inverse or has a known inverse
    for f in (hflip, vflip, inv, swap):
        assert f(f(A)) == A, f
    assert hflip([0b10000000]) == [0b00000001]
    # all four shifts drop what leaves the edge - nothing wraps around
    assert shl([0b10000001]) == [0b00000010]   # top bit falls off
    assert shr([0b10000001]) == [0b01000000]   # low bit falls off
    assert up([1, 2, 3]) == [2, 3, 0]          # first row falls off
    assert down([1, 2, 3]) == [0, 1, 2]        # last row falls off
    assert swap([0b11110000]) == [0b00001111]
    assert inv([0]) == [255]

    tiles()
    tile_edits()
    fill()
    drag()
    preview_pointing()
    multicolor()
    block_ops()
    layout()
    space_draw()
    key_repeat()
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
        assert not K.valid_chargen("/does/not/exist")

        found = K.find_chargen()
        if found:                                   # only where VICE is installed
            assert K.read_config().get("chargen") == found, "path is remembered"
            assert K.find_chargen() == found, "the remembered path is used"
            K.write_config({"chargen": "/gone"})
            assert K.find_chargen() == found, "stale entry -> search again"

        # no hit: an empty charset rather than a crash
        K.CHARGEN_QUICK, K.CHARGEN_SLOW = ["/nowhere/chargen"], []
        K.CONFIG = os.path.join(tempfile.mkdtemp(), "cfg2.json")
        assert K.find_chargen() is None
        assert K.load_cbm(None) == bytearray(4096)

        # a 2 KB charset is valid and gets padded to 4096
        half = os.path.join(tempfile.mkdtemp(), "half.64c")
        with open(half, "wb") as f:
            f.write(bytes(A) * 256)                 # exactly 2048 bytes
        assert K.valid_chargen(half), "2048 bytes must be enough"
        d = K.load_cbm(half)
        assert len(d) == 4096, "always padded to 4096"
        assert list(d[0:8]) == A and d[2048:] == bytearray(2048)

        # the load address is stripped when loading a charset too
        withaddr = os.path.join(tempfile.mkdtemp(), "addr.64c")
        with open(withaddr, "wb") as f:
            f.write(b"\x00\x38" + bytes(A) * 256)
        assert list(K.load_cbm(withaddr)[0:8]) == A, "load address stripped"

        # OpenROM download: None on a network error rather than a crash
        real_dir, real_url = K.APP_DIR, K.OPENROM_URL
        try:
            K.APP_DIR = tempfile.mkdtemp()
            K.OPENROM_URL = "https://example.invalid/nichts.rom"
            assert K.Kanji.download_openrom() is None, "a network error gives None"
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
    assert k.font_prev, "P turns the font preview on"
    k.on_key(ev("P"))
    assert not k.font_prev, "P again turns it back off"

    # navigation stays within base characters 0-63 in the preview
    k.font_prev = True
    k.focus_editor = False
    k.tile = 0
    k.cur = 63
    k.on_key(ev("Arrow Right"))
    assert k.cur == 0, f"63 wraps to 0, got {k.cur}"
    k.cur = 0
    k.on_key(ev("Arrow Left"))
    assert k.cur == 63, f"0 wraps back to 63, got {k.cur}"
    k.cur = 0
    k.on_key(ev("Arrow Down"))
    assert k.cur < 64, f"down stays below 64, got {k.cur}"

    # toggling brings a character >=64 into view
    k.font_prev = False
    k.cur = 200
    k.on_key(ev("P"))
    assert k.cur < 64, f"P clamps to 0-63, got {k.cur}"

    # a click in the tile view hits the right base character
    k.font_prev = True
    k.tile = 3                                   # 2x2 -> the tile is 17 px wide
    picked = []
    k.select = lambda c: picked.append(c)
    tw = 2 * 8 + 1
    k.preview_click(tap_at((1 + tw * 3) * PREV_SCALE, 1 * PREV_SCALE))
    assert picked == [3], f"4th tile of row 1 is char 3, got {picked}"

    # a click in the charset view: 2nd character of the 1st row
    k.font_prev = False
    k.cur = 0
    picked.clear()
    k.preview_click(tap_at((1 + 9) * PREV_SCALE, 1 * PREV_SCALE))
    assert picked == [1], f"2nd char of row 1, got {picked}"


def show_original():
    """Holding B shows the CBM original, releasing shows the edit again."""
    k = headless()
    k.cur = 1
    k.put([0] * 8)                               # clear the character
    assert list(k.shown()) == [0] * 8

    ev = lambda key: types.SimpleNamespace(key=key, shift=False)
    k.on_key(ev("B"))                            # held down
    assert k.show_orig
    assert list(k.shown()) == A, "shows the CBM original"
    assert list(k.get()) == [0] * 8, "the working data stays untouched"

    k.on_key_up(ev("B"))                         # released
    assert not k.show_orig
    assert list(k.shown()) == [0] * 8, "shows the edit again"


async def _open_and_close(coro):
    """Run a dialog coroutine far enough to build it, then cancel it.

    sleep(0) is not enough here - the coroutine only gets to show_dialog
    once the loop actually yields.
    """
    task = asyncio.ensure_future(coro)
    await asyncio.sleep(0.05)
    task.cancel()


def charset_io():
    """Load and save operate on 2048-byte charsets (README)."""
    k = headless()

    # save writes exactly the ticked charsets, through the real do_save
    k.font[:2048] = bytes([0x11]) * 2048
    k.font[2048:4096] = bytes([0x22]) * 2048
    out = tempfile.mkdtemp()

    def saved(picked, name):
        path = os.path.join(out, name)
        k.ask_charsets = lambda: asyncio.sleep(0, result=picked)
        k.picker = types.SimpleNamespace(
            save_file=lambda *a, **kw: asyncio.sleep(0, result=path))
        k.note = lambda msg: None
        asyncio.run(k.do_save())
        return open(path, "rb").read() if os.path.exists(path) else None

    both = saved((True, True), "both.64c")
    assert len(both) == 4096 and both[0] == 0x11 and both[2048] == 0x22
    one = saved((True, False), "one.64c")
    assert len(one) == 2048 and set(one) == {0x11}, "charset 1 only"
    two = saved((False, True), "two.64c")
    assert len(two) == 2048 and set(two) == {0x22}, "charset 2 only"
    assert saved(None, "cancel.64c") is None, "cancelling writes nothing"

    # both boxes start ticked, and saving nothing must not be possible
    held = {}
    k.page = types.SimpleNamespace(
        update=lambda: None, pop_dialog=lambda: None,
        show_dialog=lambda d: held.setdefault("dlg", d))
    del k.ask_charsets                       # the stub above shadowed the real one
    asyncio.run(_open_and_close(k.ask_charsets()))

    dlg = held["dlg"]
    one, two = dlg.content.controls[2], dlg.content.controls[3]
    save = dlg.actions[1]
    assert one.value and two.value, "both charsets ticked by default"
    assert not save.disabled
    one.value = two.value = False
    one.on_change(None)
    assert save.disabled, "no tick means nothing to save"
    two.value = True
    two.on_change(None)
    assert not save.disabled

    # "ask_charsets": false in kanji.json skips the dialog and writes both
    import kanji as K
    saved_cfg = K.CONFIG
    K.CONFIG = os.path.join(tempfile.mkdtemp(), "cfg.json")
    try:
        K.write_config({"ask_charsets": False})
        path = os.path.join(out, "noask.64c")
        k.ask_charsets = lambda: (_ for _ in ()).throw(
            AssertionError("the dialog must not open when it is turned off"))
        k.picker = types.SimpleNamespace(
            save_file=lambda *a, **kw: asyncio.sleep(0, result=path))
        k.note = lambda msg: None
        asyncio.run(k.do_save())
        assert len(open(path, "rb").read()) == 4096, "writes both charsets"
    finally:
        K.CONFIG = saved_cfg

    k.font[:] = bytearray(4096)
    k.cur = 300                                  # second charset
    base = (k.cur // 256) * 256 * 8
    assert base == 2048

    # loading a 2048-byte dump replaces the active set only
    k.font[:] = bytearray(4096)
    data = bytearray(range(256)) * 8             # 2048 Bytes Testmuster
    n = min(len(data), 2048)
    k.font[base:base + n] = data[:n]
    assert k.font[2048:2048 + 8] == data[:8], "loaded into charset 2"
    assert k.font[0:8] == bytearray(8), "charset 1 stays untouched"

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
    assert k.tile_pixel(8, 0), "top right reads SHIFT A"
    k.put([0] * 8, 1)
    assert not k.tile_pixel(0, 0)

    # toggle writes into exactly that character
    k.cur = 1
    k.put([0] * 8, 129)
    k.toggle(0, 8)                              # links unten -> REVERSE A (129)
    assert k.font[129 * 8] & 0x80, "toggle must write into REVERSE A"
    assert not k.font[1 * 8] & 0x80, "the base character stays untouched"

    # second charset: the tile stays inside it
    k.cur = 257
    assert k.tile_char(1, 1) == 257 + 192


def tile_edits():
    """An edit covers the whole tile, and one undo takes all of it back.

    Clear used to wipe only the char under the cursor, leaving the other
    three of a 2x2 tile untouched.
    """
    ev = lambda key: types.SimpleNamespace(key=key, shift=False)
    k = headless()
    k.tile, k.cur = 3, 1                        # 2x2 on 'A'
    chars = k.tile_chars()
    assert chars == [1, 65, 129, 193], chars

    for i in chars:
        k.put([0xFF] * 8, i)
    k.on_key(ev("Backspace"))
    assert all(not any(k.get(i)) for i in chars), "clear must wipe every char"
    k.on_key(ev("1"))
    assert all(all(k.get(i)) for i in chars), "one undo must restore the tile"

    # a flip crosses the char boundary: top left pixel ends up in the neighbour
    for i in chars:
        k.put([0] * 8, i)
    k.put([0b10000000] + [0] * 7, chars[0])
    k.on_key(ev("3"))                           # horizontal flip
    assert not any(k.get(chars[0])) and k.get(chars[1])[0] == 1, "hflip"
    k.on_key(ev("1"))
    k.on_key(ev("4"))                           # vertical flip
    assert not any(k.get(chars[0])) and k.get(chars[2])[7] == 0x80, "vflip"

    # a single char behaves exactly as before: the bit falls off the edge
    k = headless()
    k.tile, k.cur = 0, 1
    k.put([0b10000001] * 8)
    k.on_key(ev("5"))
    assert list(k.get()) == [0b00000010] * 8, list(k.get())

    # all four shifts drop what leaves the tile - none of them wrap around
    for key, char, row, other in (("7", 0, 0, 2), ("8", 2, 7, 0)):
        k = headless()
        k.tile, k.cur = 3, 1
        chars = k.tile_chars()
        for i in chars:
            k.put([0] * 8, i)
        rows = [0] * 8
        rows[row] = 0xFF
        k.put(rows, chars[char])
        k.on_key(ev(key))
        assert not any(k.get(chars[other])), f"{key} must not wrap around"

    # copy and paste carry the whole tile, not just one char
    k = headless()
    k.tile, k.cur = 3, 1
    for n, i in enumerate(k.tile_chars()):
        k.put([n + 1] * 8, i)
    k.on_key(ev("C"))
    k.cur = 2
    target = k.tile_chars()
    for i in target:
        k.put([0] * 8, i)
    k.on_key(ev("V"))
    assert [k.get(i)[0] for i in target] == [1, 2, 3, 4], "paste fills the tile"
    k.on_key(ev("1"))
    assert all(not any(k.get(i)) for i in target), "one undo takes it back"

    # pasting between tile sizes crops or pads instead of failing
    k.tile, k.cur = 0, 5
    k.on_key(ev("V"))
    assert list(k.get()) == [1] * 8, "2x2 into 1x1 keeps the top left char"
    k.on_key(ev("C"))
    k.tile, k.cur = 3, 9
    for i in k.tile_chars():
        k.put([0] * 8, i)
    k.on_key(ev("V"))
    assert [k.get(i)[0] for i in k.tile_chars()] == [1, 0, 0, 0], \
        "1x1 into 2x2 leaves the rest empty"
    print("OK")


def fill():
    """F floods the connected area, across char boundaries, and stops at a wall."""
    ev = lambda key: types.SimpleNamespace(key=key, shift=False)

    # empty 1x1 char: the fill reaches every pixel
    k = headless()
    k.tile, k.cur = 0, 1
    k.put([0] * 8)
    k.cx = k.cy = 0
    k.on_key(ev("F"))
    assert list(k.get()) == [0xFF] * 8, list(k.get())
    k.on_key(ev("1"))
    assert list(k.get()) == [0] * 8, "one undo takes the fill back"

    # a wall confines it: row 3 set -> only the rows above it fill
    k.put([0, 0, 0, 0xFF, 0, 0, 0, 0])
    k.cx = k.cy = 0
    k.on_key(ev("F"))
    assert list(k.get()) == [0xFF, 0xFF, 0xFF, 0xFF, 0, 0, 0, 0], list(k.get())

    # 2x2 tile: the fill crosses into all four chars
    k = headless()
    k.tile, k.cur = 3, 1
    chars = k.tile_chars()
    for i in chars:
        k.put([0] * 8, i)
    k.cx = k.cy = 0
    k.on_key(ev("F"))
    assert all(list(k.get(i)) == [0xFF] * 8 for i in chars), "fill crosses chars"
    k.on_key(ev("1"))
    assert all(not any(k.get(i)) for i in chars), "one undo takes the whole tile back"

    # starting on a set pixel clears that area instead of filling it
    k.tile, k.cur = 0, 1
    k.put([0xFF] * 8)
    k.cx = k.cy = 4
    k.on_key(ev("F"))
    assert list(k.get()) == [0] * 8, "fill on a set pixel clears it"
    print("OK")


def at_pixel(x, y):
    """A pointer event over the centre of editor pixel (x,y).

    The grid is offset by one cell on both axes for the ruler labels - the
    same arithmetic grid_pixel() has to undo.
    """
    from kanji import PIX
    return tap_at((PIX + 1) + x * (PIX + 1) + PIX / 2, PIX + y * PIX + PIX / 2)


def drag():
    """A held mouse button paints across the pixels it runs over."""
    k = headless()
    k.tile, k.cur = 0, 1
    k.put([0] * 8)

    # the press maps to the pixel under the pointer
    assert k.grid_pixel(at_pixel(3, 5)) == (3, 5), k.grid_pixel(at_pixel(3, 5))
    # the ruler row and column are not part of the drawing area
    assert k.grid_pixel(tap_at(2, 2)) is None

    # Space is the draw modifier, for the mouse as well as the keyboard
    k.space = True
    k.grid_tap(at_pixel(0, 1))
    for x in range(1, 8):
        k.grid_drag(at_pixel(x, 1))
    assert k.get()[1] == 0xFF, "Space + drag paints the whole row"
    assert (k.cx, k.cy) == (7, 1), "and leaves the cursor where it ended"

    # re-entering a pixel of the same stroke does not flip it back
    k.grid_drag(at_pixel(3, 1))
    assert k.get()[1] == 0xFF, "a stroke touches each pixel once"

    # starting on a set pixel erases for the whole stroke, and a stroke that
    # runs over already-set pixels keeps setting them - it never toggles
    k.grid_release(None)
    k.put([0, 0b01010101, 0, 0, 0, 0, 0, 0])
    k.grid_tap(at_pixel(0, 1))              # pixel 0 is empty -> set mode
    for x in range(1, 8):
        k.grid_drag(at_pixel(x, 1))
    assert k.get()[1] == 0xFF, "drawing over set pixels keeps them set"

    k.grid_release(None)
    k.grid_tap(at_pixel(0, 1))              # pixel 0 is set now -> erase mode
    for x in range(1, 8):
        k.grid_drag(at_pixel(x, 1))
    assert k.get()[1] == 0, "starting on a set pixel erases the whole stroke"
    k.space = False

    # the whole erasing stroke is a single undo step
    k.on_key(types.SimpleNamespace(key="1", shift=False))
    assert k.get()[1] == 0xFF, "one undo takes the whole stroke back"

    # a plain click fires tap_down and pan_start on the same pixel; the
    # second is ignored, so the pixel ends up set, not set-then-cleared
    k.grid_release(None)
    k.grid_tap(at_pixel(0, 3))
    k.grid_press(at_pixel(0, 3))
    assert k.get()[3] == 0x80, "a click changes its pixel exactly once"

    # a stroke crossing into another char of a 2x2 tile still undoes as one
    k = headless()
    k.tile, k.cur, k.space = 3, 1, True
    chars = k.tile_chars()
    for i in chars:
        k.put([0] * 8, i)
    k.grid_tap(at_pixel(7, 0))          # last column of the left char
    k.grid_drag(at_pixel(8, 0))         # first column of the right char
    assert k.get(chars[0])[0] == 0x01 and k.get(chars[1])[0] == 0x80, "crosses chars"
    k.on_key(types.SimpleNamespace(key="1", shift=False))
    assert not any(k.get(chars[0])) and not any(k.get(chars[1])), \
        "one undo takes a stroke spanning two chars back"

    # after the button is released the next press opens a fresh step
    k.grid_release(None)
    assert k.stroke == set() and k.stroke_undo is None

    # the cursor follows the mouse without a button, changing nothing
    k = headless()
    k.tile, k.cur = 0, 1
    k.put([0] * 8)
    k.grid_hover(at_pixel(5, 6))
    assert (k.cx, k.cy) == (5, 6), "the cursor follows the mouse"
    assert list(k.get()) == [0] * 8, "hovering must not draw"
    assert k.focus_editor, "and it moves the focus into the editor"

    # moving the mouse across the whole editor must not paint a trail -
    # without a held key or button the cursor only follows
    for x in range(8):
        for y in range(8):
            k.grid_hover(at_pixel(x, y))
    assert list(k.get()) == [0] * 8, "hovering never draws on its own"

    # a click still acts on its own pixel, and only on that one
    k.put([0] * 8)
    k.grid_tap(at_pixel(3, 2))
    k.grid_release()
    assert k.get()[2] == (128 >> 3), "a click sets the pixel it lands on"
    for x in range(8):
        k.grid_hover(at_pixel(x, 2))
    assert k.get()[2] == (128 >> 3), "moving on after a click changes nothing"

    # pan updates keep arriving after the button was released - Flet sends
    # no end event for it - so they must not draw on their own either
    k.put([0] * 8)
    k.grid_tap(at_pixel(0, 5))
    for x in range(1, 8):
        k.grid_drag(at_pixel(x, 5))
    assert k.get()[5] == 0x80, f"only the press itself drew: {k.get()[5]:08b}"

    # a held Space makes mouse movement draw, over hover and pan alike
    k.put([0] * 8)
    k.space = True
    k.stroke, k.stroke_undo = set(), None
    for x in range(8):
        k.grid_hover(at_pixel(x, 5))
    assert k.get()[5] == 0xFF, f"Space + mouse move draws: {k.get()[5]:08b}"

    # letting Space go stops it again, even with the mouse still moving
    k.space = False
    k.stroke, k.stroke_undo = set(), None
    for x in range(8):
        k.grid_hover(at_pixel(x, 6))
    assert k.get()[6] == 0, "after Space is released hovering draws nothing"
    print("OK")


def space_draw():
    """Space held + cursor keys draws along the way, as one undo step."""
    k = headless()
    k.tile, k.cur, k.cx, k.cy = 0, 1, 0, 0
    k.focus_editor = True
    k.put([0] * 8)

    down = lambda key: k.on_key_down(types.SimpleNamespace(key=key))
    up = lambda key: k.on_key_up(types.SimpleNamespace(key=key))

    down("Space")                       # sets the pixel under the cursor
    assert k.get()[0] == 0x80, "Space still acts on its own"
    for _ in range(7):                  # walk right while it is held
        down("Arrow Right")
    assert k.get()[0] == 0xFF, f"Space + cursor draws a line: {k.get()[0]:08b}"
    up("Space")

    # the whole run collapses into one undo step
    k.on_key(types.SimpleNamespace(key="1", shift=False))
    assert k.get()[0] == 0, "one undo takes the drawn line back"

    # released again, moving no longer draws
    for _ in range(3):
        down("Arrow Down")
    assert list(k.get()) == [0] * 8, "moving without Space draws nothing"

    # the auto-repeat of a held Space must not act twice
    k.cx, k.cy = 0, 0
    down("Space")
    down("Space")
    assert k.get()[0] == 0x80, "held Space acts once, not on every repeat"
    up("Space")

    # starting on a set pixel erases along the way instead of setting
    k.put([0xFF] * 8)
    k.cx, k.cy = 0, 0
    down("Space")
    for _ in range(7):
        down("Arrow Right")
    assert k.get()[0] == 0, f"Space on a set pixel erases: {k.get()[0]:08b}"
    up("Space")
    print("OK")


def key_repeat():
    """A held cursor key keeps moving; other keys stay one-shot."""
    ev = lambda key: types.SimpleNamespace(key=key)
    k = headless()
    k.tile, k.cur, k.cx, k.cy = 0, 1, 0, 0
    k.focus_editor = True

    for _ in range(3):
        k.on_key_repeat(ev("Arrow Right"))
    assert k.cx == 3, f"a held cursor key keeps moving, cx={k.cx}"

    # a held Backspace must not clear tile after tile
    k.put([0xFF] * 8)
    k.on_key_repeat(ev("Backspace"))
    assert list(k.get()) == [0xFF] * 8, "Backspace does not repeat"

    # a repeat with Space held draws along, same as a real key press - the
    # pixel the cursor started on is not part of the run, only what it enters
    k = headless()
    k.tile, k.cur, k.cx, k.cy = 0, 1, 0, 0
    k.focus_editor, k.space = True, True
    k.put([0] * 8)
    for _ in range(3):
        k.on_key_repeat(ev("Arrow Right"))
    assert k.get()[0] == 0b01110000, f"repeat draws too: {k.get()[0]:08b}"
    print("OK")


def preview_pointing():
    """Hovering the charset pane marks a char; only a click loads it."""
    from kanji import PREV_SCALE
    k = headless()
    k.cur, k.point, k.font_prev = 1, None, False
    k.focus_editor = True

    at = lambda col, row: tap_at((1 + col * 9 + 4) * PREV_SCALE,
                                 (1 + row * 9 + 4) * PREV_SCALE)

    # hovering moves the marker, the edited char stays put
    k.preview_hover(at(3, 2))
    assert k.point == 35, k.point
    assert k.cur == 1, "hovering must not change the char being edited"
    assert k.focus_editor, "and it does not steal the focus either"

    # clicking the same spot is what actually picks it up
    k.preview_click(at(3, 2))
    assert k.cur == 35, k.cur
    assert not k.focus_editor, "a click moves the focus to the charset pane"

    # a click beside any char changes nothing
    k.preview_click(tap_at(0, 0))
    assert k.cur == 35, "a click on the padding is ignored"

    # never two frames at once: taking over with the keyboard drops the
    # mouse marker, whichever key it is
    for key in ("Arrow Right", "Tab", "9", "unknown-key"):
        k.point = 42
        k.on_key(types.SimpleNamespace(key=key, shift=False))
        assert k.point is None, f"{key} must drop the mouse marker"

    # and a click puts the white frame where the dim one was
    k.point, k.cur, k.focus_editor = 35, 1, True
    k.preview_click(at(3, 2))
    assert k.point is None and k.cur == 35, "click merges both frames into one"
    print("OK")


def multicolor():
    """Multicolor reads the same 8 bytes in pairs, four colors per row."""
    ev = lambda key: types.SimpleNamespace(key=key, shift=False)
    k = headless()
    k.tile, k.cur = 0, 1

    # M switches on, H switches back; the grid halves its columns
    assert k.cell_w() == 8
    k.on_key(ev("M")); assert k.mc and k.cell_w() == 4
    k.on_key(ev("H")); assert not k.mc and k.cell_w() == 8

    # the cursor keeps pointing at the same place on screen across a switch
    k.cx = 6
    k.on_key(ev("M")); assert k.cx == 3, k.cx
    k.on_key(ev("H")); assert k.cx == 6, k.cx

    # one byte holds four color indices, left to right
    k.on_key(ev("M"))
    k.put([0b00011011] + [0] * 7)
    assert [k.mc_pair(x, 0) for x in range(4)] == [0, 1, 2, 3]
    k.set_pair(0, 0, 3)
    assert k.get()[0] == 0b11011011, f"{k.get()[0]:08b}"

    # Space paints the selected color, and clears a cell that already has it
    k.put([0] * 8)
    k.cx = k.cy = 0
    k.mc_draw = 2
    k.toggle(0, 0); assert k.mc_pair(0, 0) == 2, "paints the chosen color"
    k.toggle(0, 0); assert k.mc_pair(0, 0) == 0, "again clears to background"

    # picking a color: by click and by Shift+digit, on both layouts
    k.set_draw_color(3); assert k.mc_draw == 3
    k.on_key(types.SimpleNamespace(key="2", shift=True)); assert k.mc_draw == 1
    k.on_key(types.SimpleNamespace(key='"', shift=True)); assert k.mc_draw == 1, \
        "a German layout sends the shifted symbol"
    # unshifted digits keep their normal function
    k.mc_draw = 3
    k.on_key(types.SimpleNamespace(key="2", shift=False))
    assert k.mc_draw == 3, "plain 2 is redo, not a color pick"

    # a stroke paints one color throughout, it does not step per cell
    k.put([0] * 8)
    k.mc_draw = 1
    k.stroke, k.stroke_undo = set(), None
    for x in range(4):
        k.stroke_draw(x, 0)
    assert k.get()[0] == 0b01010101, f"{k.get()[0]:08b}"
    k.on_key(ev("1"))
    assert k.get()[0] == 0, "one undo takes the whole multicolor stroke back"

    # a horizontal flip mirrors whole pairs, never single bits - otherwise
    # color 01 would come back as 10 and repaint the glyph
    assert row_hflip([0b00011011], mc=True) == [0b11100100], \
        format(row_hflip([0b00011011], mc=True)[0], "08b")
    assert row_hflip([0b00011011]) == [0b11011000], "hires still mirrors bits"

    # fill works on cells, not bits
    out = flood_fill([[0b00000000]], 0, 0, mc=True)
    assert out == [[0b01010101]], format(out[0][0], "08b")

    # navigation stays inside the four columns
    k.focus_editor, k.cx = True, 3
    k.on_key(ev("Arrow Right")); assert k.cx == 0, k.cx

    # the color registers survive a mode switch and default sanely
    assert len(k.mc_col) == 4 and all(0 <= c < 16 for c in k.mc_col)

    # Colour RAM holds four bits and bit 3 is the multicolor flag, so pair 11
    # can only be a color from 0-7. A value of 8-15 is stored as value & 7
    # with the flag cleared, and the character silently renders as hires on a
    # real C64 - which is exactly the bug this guards against.
    assert MC_DEFAULT[3] < 8, f"pair 11 must be 0-7, is {MC_DEFAULT[3]}"
    assert k.mc_col[3] < 8, f"pair 11 must be 0-7, is {k.mc_col[3]}"
    print("OK")


def layout():
    """The window keeps its original size, and the help list fits inside it.

    Pane 2 used to size itself to the longest help text, so every shortcut
    added made the whole window wider.
    """
    import kanji as K
    assert (K.WIN_W, K.WIN_H) == (1028, 800), (K.WIN_W, K.WIN_H)
    avail = K.FUNC_W - K.PANE_PAD * 2 - 4
    assert K._two_col <= avail, f"two-column rows need {K._two_col:.0f} of {avail}"
    assert K._one_col <= avail, f"bottom rows need {K._one_col:.0f} of {avail}"
    print("OK")


def block_ops():
    """R rebuilds the reversed block, Shift+Backspace clears a whole block."""
    ev = lambda key, shift=False: types.SimpleNamespace(key=key, shift=shift)
    k = headless()
    k.cur = 1

    # R: chars 0-127 land inverted in 128-255
    for i in range(128):
        k.put([i & 0xFF] * 8, i)
    k.on_key(ev("R"))
    assert list(k.get(128)) == [0xFF] * 8, list(k.get(128))
    assert list(k.get(129)) == [0xFE] * 8, list(k.get(129))
    assert list(k.get(1)) == [1] * 8, "the source block is untouched"

    # one undo takes all 128 chars back
    k.on_key(ev("1"))
    assert all(not any(k.get(128 + i)) for i in range(128)), \
        "one undo restores the whole block"

    # Shift+R goes the other way
    for i in range(128):
        k.put([0x0F] * 8, 128 + i)
    k.on_key(ev("R", shift=True))
    assert list(k.get(0)) == [0xF0] * 8, list(k.get(0))

    # it stays inside the active charset
    k.cur = 257
    for i in range(128):
        k.put([0xAA] * 8, 256 + i)
    before = list(k.get(1))
    k.on_key(ev("R"))
    assert list(k.get(384)) == [0x55] * 8, "charset 2 is rebuilt"
    assert list(k.get(1)) == before, "charset 1 is not touched"

    # Shift+Backspace clears the block the selection sits in
    k = headless()
    for i in range(256):
        k.put([0xFF] * 8, i)
    k.cur = 5                                   # normal block
    k.on_key(ev("Backspace", shift=True))
    assert all(not any(k.get(i)) for i in range(128)), "normal block cleared"
    assert all(all(k.get(128 + i)) for i in range(128)), "reversed one kept"

    k.cur = 200                                 # reversed block
    k.on_key(ev("Backspace", shift=True))
    assert all(not any(k.get(128 + i)) for i in range(128)), "reversed cleared"

    # plain Backspace still clears only the current char
    k.cur = 3
    k.put([0xFF] * 8, 3)
    k.put([0xFF] * 8, 4)
    k.on_key(ev("Backspace"))
    assert not any(k.get(3)) and all(k.get(4)), "plain Backspace is per char"
    print("OK")


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
    k.point = None
    k.mc = False
    k.mc_col, k.mc_draw = list(MC_DEFAULT), 1
    k.focus_editor, k.tile, k.clip = True, 0, None
    k.shift, k.show_orig, k.font_prev = False, False, False
    k.undo, k.redo = [], []
    k.space = False
    k.stroke, k.stroke_undo, k.stroke_set = set(), None, True
    async def _focus():
        pass
    k.sink = types.SimpleNamespace(focus=_focus, value="")
    k.keys = types.SimpleNamespace(focus=_focus)
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

    # The charset pane shows two blocks side by side, normal left (0-127)
    # and reversed right (128-255). The cursor moves on that visible grid,
    # not along the index: right of char 15 sits 128, not 16.
    k.cur = 15; k.on_key(ev("Arrow Right")); assert k.cur == 128, k.cur
    k.cur = 128; k.on_key(ev("Arrow Left")); assert k.cur == 15, k.cur
    # off the right edge of the reversed block the row wraps to its own
    # start, which is the normal block on the same row - not the next row
    k.cur = 143; k.on_key(ev("Arrow Right")); assert k.cur == 0, k.cur
    k.cur = 255; k.on_key(ev("Arrow Right")); assert k.cur == 112, k.cur
    # up and down stay in their block and wrap within it
    k.cur = 5; k.on_key(ev("Arrow Up")); assert k.cur == 117, k.cur
    k.cur = 133; k.on_key(ev("Arrow Up")); assert k.cur == 245, k.cur

    # and none of it ever crosses into the other charset
    for start in (0, 15, 128, 255):
        for key in ("Arrow Right", "Arrow Left", "Arrow Up", "Arrow Down"):
            k.cur = 256 + start
            k.on_key(ev(key))
            assert 256 <= k.cur < 512, f"{key} from {start} left the set: {k.cur}"

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
