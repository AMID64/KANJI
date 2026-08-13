# Examples

Small viewers that put a KANJI font on a real C64 screen — one per tile
format, in BASIC and in KickAssembler, hires and multicolor.

| | 1x1 | 1x2 | 2x1 | 2x2 |
|--|-----|-----|-----|-----|
| **hires** | `1x1view` | `1x2view` | `2x1view` | `2x2view` |
| **multicolor** | `1x1mcview` | `1x2mcview` | `2x1mcview` | `2x2mcview` |

All of them clear the screen, set border and background to black, and show
characters 0–63 in the same arrangement as KANJI's own font preview. Press
any key to return to the ROM charset.

## Fonts

`fonts/font.64c` (hires) and `fonts/fontmc.64c` (multicolor) are the charsets
the examples pull in. Replace them with your own saves from KANJI — the file
names are what the examples reference.

## KickAssembler

```sh
java -jar KickAss.jar 2x2view.asm
x64sc 2x2view.prg
```

The charset is assembled straight into the program at `$3000`, so the `.prg`
is self-contained.

## BASIC

The BASIC versions expect the charset to already sit at `$3000`. Load it
there first, for example:

```
POKE 43,1 : POKE 44,48 : POKE 45,1 : POKE 46,56
LOAD"FONT.64C",8,1
```

Then `LOAD` and `RUN` the viewer.

## Both charsets

A 4 KB save from KANJI holds the uppercase set first and the lowercase set
2048 bytes further on. Every example carries a commented-out line showing
which value to use for the second one — `$3800` instead of `$3000`.

## Multicolor

The multicolor viewers switch the VIC into MCM and set the three shared
color registers; the fourth color comes from colour RAM, which is why the
color byte has bit 3 set.

**Colour RAM only holds four bits, and bit 3 is the multicolor flag** — so
the fourth color can only be one of colors 0–7. Writing `15 + 8` there does
not give you light grey in multicolor: it is stored as `%0111`, the flag is
gone, and the character quietly renders as hires again. That one bit is the
most common reason a multicolor font shows up single-width and in the wrong
color.

The examples use black background, dark grey, white and cyan — KANJI's
defaults, with cyan standing in for light grey, which is out of range.

A hires font shown in multicolor looks wrong by definition — the VIC reads
its bitmap in pairs, so draw the font in KANJI's `M` mode first.
