#!/bin/sh
# Descarga los efectos CC0 de BigSoundBank (https://bigsoundbank.com) usados en los videos.
# Licencia de BigSoundBank: CC0 / dominio público, uso comercial permitido, atribución no obligatoria.
set -e
cd "$(dirname "$0")/../audio/raw"
UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/126 Safari/537.36"
while read -r id slug; do
  [ -z "$id" ] && continue
  out="$id-$slug.wav"
  [ -s "$out" ] || curl -s -f -m 60 -A "$UA" -o "$out" "https://bigsoundbank.com/UPLOAD/bwf-en/$id.wav" || echo "FALLO $id $slug"
done <<LISTA
0612 small-dog-barking
0682 barking-of-a-spitz
2450 dog-singing-1
2451 dog-singing-2
1547 dogs-breathing
2352 old-dog-barking-1
0448 iphone-camera
1731 quick-imac-keyboard
2844 typewriter-bell
0007 clock
0572 whoosh-1
0573 whoosh-2
1795 whoosh-3
1796 whoosh-4
1797 whoosh-5
1798 whoosh-10
1799 whoosh-6
1800 whoosh-7
2063 notification-1
2064 notification-2
2065 notification-3
2066 notification-4
1111 message-1
1112 message-2
1398 idea-1
1399 idea-2
0447 iphone-touch
1074 bubbles-burst
0211 champagne-cork
1553 party-horn-1
1555 party-horn-3
0462 bubble-wrap
2087 chimes-butterfly-1
2088 chimes-butterfly-2
2089 chimes-butterfly-3
2079 chimes-dream-1
2080 chimes-dream-2
0920 glockenspiel
0275 bell-bike-2
3233 pencil-2
3236 pencil-signature-1
0807 whiteboard-marker
1416 sonar-1
1920 sonar-2
2196 kiss-1
2277 boing-cartoon-1
2278 boing-cartoon-2
2280 boing-cartoon-4
1414 scanner-fast
1417 beep-cash-register
0466 woodblock
0374 knock-light-door
0362 page-turn
0669 newspaper-page
0243 heartbeat-1
1384 drops-of-water-1
0313 crackling-radio
0879 squeaker-toy-2
3331 toy-squeak-1
3333 toy-squeak-3
1765 applause-1
LISTA
ls | wc -l
