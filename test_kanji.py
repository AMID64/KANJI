#!/usr/bin/env python3
"""Self-check for kanji's pure logic. Run: python3 test_kanji.py"""

import asyncio
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
    """Holding ß shows the CBM original, releasing shows the edit again."""
    k = headless()
    k.cur = 1
    k.put([0] * 8)                               # clear the character
    assert list(k.shown()) == [0] * 8

    ev = lambda key: types.SimpleNamespace(key=key, shift=False)
    k.on_key(ev("ß"))                            # held down
    assert k.show_orig
    assert list(k.shown()) == A, "shows the CBM original"
    assert list(k.get()) == [0] * 8, "the working data stays untouched"

    k.on_key_up(ev("ß"))                         # released
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
