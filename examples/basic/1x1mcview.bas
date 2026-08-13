10 rem ---------------------------------------------------
20 rem kanji 1x1 multicolor font viewer
30 rem chars 0-63 as plain cells, 16 per row
40 rem charset expected at $3000 (load it there first)
50 rem for the lowercase set use  or 14  instead of  or 12
60 rem ---------------------------------------------------
100 poke 53280,0 : poke 53281,0 : rem black border and background
110 print chr$(147);
120 poke 53272,(peek(53272)and240)or12 : rem chars at $3000
130 poke 53270,peek(53270)or16 : rem multicolor mode on
140 poke 53282,11 : rem $d022 - pair 01, dark grey
150 poke 53283,1  : rem $d023 - pair 10, white
160 rem colour ram holds four bits and bit 3 is the multicolor flag,
170 rem so pair 11 can only be a colour from 0 to 7 - 15+8 would be
180 rem truncated to 7 and switch the character back to hires
190 c=3+8         : rem colour ram, pair 11 - cyan, plus the mc flag
200 for r=0 to 3
210 : for x=0 to 15
220 :   n=r*16+x : b=1024+r*80+x*2
230 :   poke b,n : poke 55296+b-1024,c
240 : next x
250 next r
900 get k$:if k$="" then 900
910 poke 53272,21 : rem back to the rom charset
915 poke 53270,peek(53270)and239 : rem multicolor off
920 poke 53280,14 : poke 53281,6 : rem the usual blue back
930 end
