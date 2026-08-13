// KANJI 1x2 font viewer - characters 0-63 as tiles one wide, two tall:
//
//      n
//      n+128     (REVERSE)
//
// 16 tiles per row, four rows - 64 characters, like the preview in KANJI.
//
// Build:  java -jar KickAss.jar 1x2view.asm
// Run:    x64sc 1x2view.prg

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

        ldx #4                  // four rows of tiles
row:    ldy #0                  // screen column
tile:   lda char
        sta (scr), y            // top half
        lda #COLOR
        sta (col), y

        tya
        clc
        adc #40                 // one screen line down
        tay
        lda char
        clc
        adc #128                // bottom half: REVERSE
        sta (scr), y
        lda #COLOR
        sta (col), y
        tya
        sec
        sbc #40                 // back up to the top line
        tay

        inc char
        iny
        iny                     // one blank column between the tiles
        cpy #32                 // sixteen tiles per row
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
                                // repaint the screen and undo $d018

* = CHARSET "charset"
        .import binary "../fonts/font.64c"
