// KANJI 2x2 multicolor font viewer - characters 0-63 as tiles two wide, two tall:
//
//      n      n+64      (SHIFT)
//      n+128  n+192     (REVERSE, SHIFT REVERSE)
//
// 8 tiles per row, eight rows - 64 characters, like the preview in KANJI.
//
// Build:  java -jar KickAss.jar 2x2mcview.asm
// Run:    x64sc 2x2mcview.prg

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

        ldx #8                  // eight rows of tiles
row:    ldy #0                  // screen column
tile:   lda char
        sta (scr), y            // top left
        clc
        adc #128
        pha                     // bottom left, written after the colour
        lda #COLOR
        sta (col), y
        tya
        clc
        adc #40                 // one screen line down
        tay
        pla
        sta (scr), y            // bottom left: REVERSE
        lda #COLOR
        sta (col), y
        tya
        sec
        sbc #39                 // back up one line, one column to the right
        tay

        lda char
        clc
        adc #64
        sta (scr), y            // top right: SHIFT
        clc
        adc #128
        pha
        lda #COLOR
        sta (col), y
        tya
        clc
        adc #40
        tay
        pla
        sta (scr), y            // bottom right: SHIFT REVERSE
        lda #COLOR
        sta (col), y
        tya
        sec
        sbc #40
        tay

        inc char
        iny
        iny                     // one blank column between the tiles
        cpy #24                 // eight tiles per row
        bne tile

        lda scr                 // three screen lines to the next tile row
        clc
        adc #120
        sta scr
        bcc !+
        inc scr + 1
!:      lda col
        clc
        adc #120
        sta col
        bcc !+
        inc col + 1
!:      dex
        bne row

        jmp *                   // stop here - returning to BASIC would
                                // repaint the screen and undo $d016/$d018

* = CHARSET "charset"
        .import binary "../fonts/fontmc.64c"
