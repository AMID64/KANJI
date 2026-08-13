// KANJI 1x1 font viewer - characters 0-63 as plain 8x8 cells,
// 16 per row, four rows - like the preview in KANJI itself.
//
// Build:  java -jar KickAss.jar 1x1view.asm
// Run:    x64sc 1x1view.prg
//
// Put your charset next to this file as font.64c. KANJI writes those
// without a load address, which is what the import at the bottom expects.

.const SCREEN  = $0400
.const COLRAM  = $d800
.const CHARSET = $3000
.const COLOR   = 1              // white

.const scr  = $fb               // pointer into the screen
.const col  = $fd               // and into colour RAM
.const char = $02               // character number being printed

BasicUpstart2(main)

main:
        sei                     // the examples own the screen from here
        lda #$93                // clear screen
        jsr $ffd2
        lda #0                  // black border and background
        sta $d020
        sta $d021

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
                                // repaint the screen and undo $d018

* = CHARSET "charset"
        .import binary "../fonts/font.64c"
