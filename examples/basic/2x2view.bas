10 rem ---------------------------------------------------
20 rem kanji 2x2 font viewer
30 rem n n+64 over n+128 n+192, 8 per row
40 rem charset expected at $3000 (load it there first)
50 rem for the lowercase set use  or 14  instead of  or 12
60 rem ---------------------------------------------------
100 poke 53280,0 : poke 53281,0 : rem black border and background
110 print chr$(147);
120 poke 53272,(peek(53272)and240)or12 : rem chars at $3000
130 c=1 : rem white
200 for r=0 to 7
210 : for x=0 to 7
220 :   n=r*8+x : b=1024+r*120+x*3
230 :   poke b,n       : poke 55296+b-1024,c
240 :   poke b+1,n+64  : poke 55296+b-1024+1,c
250 :   poke b+40,n+128: poke 55296+b-1024+40,c
260 :   poke b+41,n+192: poke 55296+b-1024+41,c
270 : next x
280 next r
900 get k$:if k$="" then 900
910 poke 53272,21 : rem back to the rom charset
920 poke 53280,14 : poke 53281,6 : rem the usual blue back
930 end
