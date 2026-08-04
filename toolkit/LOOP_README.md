# Zolander loop daemon (F3)

One-shot tick spusteny launchd cez StartInterval (kazdych 1200s = 20 min) + RunAtLoad.
ZAMERNE NIE KeepAlive+while loop — launchd je scheduler, tick spravi jeden cyklus a
skonci. Robustne (ziaden zaseknuty loop), durable (prezije restart Macu).

## Co tick robi (zolander_loop.py)
1. integrity check (ak identita zmenena -> zaloguj a skonci)
2. heartbeat -> state/heartbeat.txt
3. sken dovolenych git projektov (zolo2.0, turiec-pod-lupou) -> nezacomitovane
   zmeny zapise do denniky/<datum>.md
4. zapis do logs/loop.log
ZAMERNE bez LLM volani (lacne). LLM obohacovanie pride vo F4 "sen".

## Ovladanie (launchctl, gui/501 domena; 501 = `id -u`)
- start/load:   launchctl bootstrap gui/501 ~/Library/LaunchAgents/pl.zolander.loop.plist
- stop/unload:  launchctl bootout gui/501/pl.zolander.loop
- stav:         launchctl print gui/501/pl.zolander.loop
- vynut tick:   launchctl kickstart -k gui/501/pl.zolander.loop
- po zmene plistu: bootout potom bootstrap (reload)

## Kontrola ze zije
- tail state/heartbeat.txt  (ts + pid posledneho ticku)
- tail logs/loop.log
- launchd stdout/stderr: logs/launchd.out.log, logs/launchd.err.log
