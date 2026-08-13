// KANJI 1x1 multicolor font viewer - characters 0-63 as plain 8x8 cells,
// 16 per row, four rows - like the preview in KANJI itself.
//
// Build:  java -jar KickAss.jar 1x1mcview.asm
// Run:    x64sc 1x1mcview.prg
//
// Put your charset next to this file as font.64c. KANJI writes those
// without a load address, which is what the import at the bottom expects.

.const SCREEN  = $0400
.const COLRAM  = $d800
.const CHARSET = $3000
// Multicolor: the VIC reads the bitmap in pairs, so each pair picks one of
// four colors. 00 is the background ($d021), 01 and 10 come from $d022 and
// $d023, 11 comes from colour RAM - and the colour byte needs bit 3 set to
// put the character into multicolor mode at all.
//
// Colour RAM only holds four bits, and bit 3 is the multicolor flag - so
// the fourth colour can only be 0-7. Picking 8-15 there silently turns the
// character back into hires: 15 + 8 = 23, of which only %0111 survives.
//
// KANJI's defaults with a black background; light grey (15) is out of
// range for pair 11, so grey (12) stands in for it.
.const BG    = 0                // $d021, pair 00  (black)
.const MC1   = 11               // $d022, pair 01  (dark grey)
.const MC2   = 1                // $d023, pair 10  (white)
.const MC3   = 3                // colour RAM, 11  (cyan) - must be 0-7
.const COLOR = MC3 + 8          // bit 3 = this character is multicolor

.const scr  = $fb               // pointer into the screen
.const col  = $fd               // and into colour RAM
.const char = $02               // character number being printed

BasicUpstart2(main)

main:
        sei                     // the examples own the screen from here
        lda #$93                // clear screen
        jsr $ffd2
        lda #0                  // black border
        sta $d020
        lda #BG                 // the four multicolor registers
        sta $d021
        lda #MC1
        sta $d022
        lda #MC2
        sta $d023

        lda $d016               // multicolor mode on
        ora #%00010000
        sta $d016

        lda $d018               // screen $0400, charset $3000
        and #%11110000
        ora #%00001100
        sta $d018
        // A 4 KB font holds both charsets. The second one (lowercase) starts
        // 2048 bytes further on - swap the line above for this to show it:
        //      ora #%00001110          // charset at $3800

        lda #<SCREEN
        sta scr
        lda #>SCREEN
        sta scr + 1
        lda #<COLRAM
        sta col
        lda #>COLRAM
        sta col + 1
        lda #0
        sta char

        ldx #4                  // four rows
row:    ldy #0                  // screen column
tile:   lda char
        sta (scr), y
        lda #COLOR
        sta (col), y

        inc char
        iny
        iny                     // one blank column between the cells
        cpy #32                 // sixteen per row
        bne tile

        lda scr                 // two screen lines to the next row
        clc
        adc #80
        sta scr
        bcc !+
        inc scr + 1
!:      lda col
        clc
        adc #80
        sta col
        bcc !+
        inc col + 1
!:      dex
        bne row

        jmp *                   // stop here - returning to BASIC would
                                // repaint the screen and undo $d016/$d018

* = CHARSET "charset"
        .import binary "../fonts/fontmc.64c"
