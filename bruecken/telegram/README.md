# Telegram-Brücke

`bridge.py` verbindet Emres Telegram-Bot mit Claude Code. Nur Standardbibliothek, Python 3.

## Ablauf
1. Wartet per Long-Polling auf Nachrichten (kostet kein Claude-Limit).
2. Nimmt nur Nachrichten aus dem **privaten Chat der Besitzer-ID** an. Alles andere wird ignoriert und Emre einmal pro Stunde gemeldet.
3. Legt Aufträge in `state/queue.jsonl` (bleibt nach Neustart erhalten) und wartet 4 Sekunden auf weitere Nachrichten.
4. Startet **einmal** `claude -p` im Assistenten-Ordner mit allen wartenden Nachrichten. Claude liest dabei `CLAUDE.md` selbst.
5. Schickt die Antwort an Telegram. Eine kurze Gesprächsfolge (bis 8 Runden, 6 Stunden) bleibt erhalten, damit "ok" auf eine Freigabeanfrage verstanden wird.

Nach einer Pause (Laptop war aus) holt die Brücke wartende Nachrichten ab. Telegram hebt sie nach meinem Kenntnisstand etwa 24 Stunden auf. Ältere Nachrichten als 10 Minuten werden Claude als "wartete X Min" gekennzeichnet, damit er bei Zeitkritischem nachfragt.

## Befehle in Telegram (ohne Claude, kostet kein Limit)
- `/status` Warteschlange, letzter Lauf, nächster Versuch
- `/neu` frischer Gesprächskontext
- `/hilfe`

## Sprachnachrichten
Werden lokal auf dem Server in Text umgewandelt (keine Cloud, kein Limit) und dann wie Text behandelt.
Einrichten (ohne sudo):
```
curl -LsSf https://astral.sh/uv/install.sh | sh
uv venv --python 3.12 ~/.local/share/assistent/whisper
VIRTUAL_ENV=~/.local/share/assistent/whisper uv pip install -r bruecken/telegram/whisper-requirements.txt
```
Modell wählbar mit `WHISPER_MODEL` (Standard `small`), Pfad mit `WHISPER_PYTHON` in `.env`.

## Wächter
`bruecken/waechter/` meldet Probleme (Dienste, WhatsApp, Speicher, Akku/Strom, Internet) per Telegram, ohne Claude.
```
cp bruecken/waechter/assistent-waechter.{service,timer} ~/.config/systemd/user/
systemctl --user daemon-reload && systemctl --user enable --now assistent-waechter.timer
```

## Nutzungslimit und Fehler
- Limit erreicht: Auftrag bleibt in der Warteschlange, Meldung an Emre, neuer Versuch nach 30 Minuten.
- Sonstiger Fehler: neuer Versuch nach 5 Minuten, nach 3 Fehlversuchen wird der Auftrag verworfen und Emre informiert.

## Sicherheit
- Claude darf in diesem Lauf standardmäßig nur `Read, Glob, Grep, Edit, Write, WebSearch, WebFetch`. **Kein Bash**, kein Senden. Änderbar mit `CLAUDE_ALLOWED_TOOLS` in der `.env`.
- Die Brücke sendet an niemanden außer an Emre.
- Der Token steht nur in `.env` und wird aus den Logs entfernt.

## Einrichten
**Kurzweg:** Repository nach `~/assistent` klonen, Claude Code installieren und anmelden, dann `bash setup.sh`. Das Skript fragt den Token verdeckt ab, prüft ihn, testet `claude -p` (optional) und richtet den Autostart ein. Die Einzelschritte stehen darunter.

1. Repository nach `~/assistent` klonen, Claude Code installieren und einmal `claude` starten (anmelden).
2. `cp .env.example .env` und `TELEGRAM_BOT_TOKEN` eintragen. `TELEGRAM_OWNER_ID=<deine Telegram-ID>`.
3. Test im Vordergrund: `python3 bruecken/telegram/bridge.py`, dem Bot schreiben. Mit Strg+C beenden.
4. Autostart:
   ```
   mkdir -p ~/.config/systemd/user
   cp bruecken/telegram/assistent-telegram.service ~/.config/systemd/user/
   systemctl --user daemon-reload
   systemctl --user enable --now assistent-telegram
   ```
   Der Dienst startet beim Login. Soll er schon beim Hochfahren starten (ohne Login): `loginctl enable-linger $USER`.
5. Logs: `journalctl --user -u assistent-telegram -f` oder `logs/telegram.log`.

## Optionale Einstellungen in `.env`
`CLAUDE_BIN` (Pfad zu `claude`), `CLAUDE_MODEL` (z. B. kleineres Modell für Sparsamkeit), `CLAUDE_ALLOWED_TOOLS`, `CLAUDE_TIMEOUT` (Sekunden, Standard 900).

## Kalender und Drive (Konnektoren von claude.ai)
Voraussetzung: Konnektoren unter https://claude.ai/customize/connectors verbunden, auf dem Server in `claude` unter `/mcp` angemeldet. Im Hintergrundlauf (`claude -p`) ist kein Browser-Login möglich, nicht autorisierte Konnektoren fehlen dort einfach.

Nur diese Werkzeuge sind in `CLAUDE_ALLOWED_TOOLS` freigegeben (Kalender nur lesen, Drive lesen und neue Dateien speichern):

| Dienst | Werkzeuge |
|---|---|
| Google Calendar | `mcp__claude_ai_Google_Calendar__list_events`, `__get_event`, `__search_events`, `__list_calendars` |
| Google Drive | `mcp__claude_ai_Google_Drive__search_files`, `__read_file_content`, `__get_file_metadata`, `__list_recent_files`, `__download_file_content`, `__create_file` |

Absichtlich **nicht** freigegeben: Termine anlegen/ändern/löschen, Drive `update_file`, `trash_file`, `share_file`, `copy_file`. Das erzwingt die Regel aus `CLAUDE.md` Abschnitt 6 auch technisch.

Beispielzeile für die `.env` (eine Zeile):
```
CLAUDE_ALLOWED_TOOLS=Read,Glob,Grep,Edit,Write,WebSearch,WebFetch,mcp__claude_ai_Google_Calendar__list_events,mcp__claude_ai_Google_Calendar__get_event,mcp__claude_ai_Google_Calendar__search_events,mcp__claude_ai_Google_Calendar__list_calendars,mcp__claude_ai_Google_Drive__search_files,mcp__claude_ai_Google_Drive__read_file_content,mcp__claude_ai_Google_Drive__get_file_metadata,mcp__claude_ai_Google_Drive__list_recent_files,mcp__claude_ai_Google_Drive__download_file_content,mcp__claude_ai_Google_Drive__create_file
```
Nach Änderungen: `systemctl --user restart assistent-telegram`. Die Namen in `/mcp` gegenprüfen, falls ein Konnektor umbenannt wird.

## WhatsApp-Anteil (Weg C)
Mit `WHATSAPP_ENABLED=1` in der `.env` (setzt `setup-whatsapp.sh`) meldet die Brücke WhatsApp-Nachrichten freigegebener Kontakte mit Knöpfen und erzeugt Entwürfe erst nach Knopfdruck. `wa_link.py` enthält die Logik, `bruecken/whatsapp/` das Node-Programm. Ablauf und Schutzregeln: `bruecken/whatsapp/README.md`. Test: `python3 -m unittest bruecken/telegram/test_wa_link.py`.

## Bekannte Grenzen
- Während Claude arbeitet, reagiert auch `/status` erst danach.
- Ob `claude -p` mit deinem Pro-Abo ohne zusätzliche Anmeldung läuft, prüfst du am besten einmal mit `claude -p "sag hallo"` im Ordner.
- Getestet wurde bisher nur mit einer Attrappe für Telegram und Claude, noch nicht mit dem echten Bot.
