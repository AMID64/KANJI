// KANJI 2x1 font viewer - characters 0-63 as tiles two wide, one tall:
//
//      n  n+64     (SHIFT)
//
// 8 tiles per row, eight rows - 64 characters, like the preview in KANJI.
//
// Build:  java -jar KickAss.jar 2x1view.asm
// Run:    x64sc 2x1view.prg

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

        ldx #8                  // eight rows of tiles
row:    ldy #0                  // screen column
tile:   lda char
        sta (scr), y            // left half
        lda #COLOR
        sta (col), y
        iny
        lda char
        clc
        adc #64                 // right half: SHIFT
        sta (scr), y
        lda #COLOR
        sta (col), y

        inc char
        iny
        iny                     // one blank column between the tiles
        cpy #24                 // eight tiles per row
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
