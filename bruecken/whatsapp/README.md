# WhatsApp-Brücke (Weg C: Prepaid-Nummer, normales WhatsApp)

Verbindet die Prepaid-Nummer des Assistenten als **verknüpftes Gerät** mit dem Assistenten (inoffiziell, Bibliothek
[Baileys](https://github.com/WhiskeySockets/Baileys), Version 7.0.0-rc14 = Vorabversion). Kein WhatsApp Business nötig.

**Status: gebaut und mit Attrappen getestet, noch NICHT mit echtem WhatsApp ausprobiert.** Die Bibliothek ist
inoffiziell und eine Vorabversion; sie kann nach WhatsApp-Updates plötzlich nicht mehr funktionieren.

## Ablauf
1. Ein Kunde schreibt an die Prepaid-Nummer.
2. `wa.js` legt die Nachricht in `state/wa_inbox.jsonl`.
3. Die Telegram-Brücke meldet sie dir: *„WhatsApp von Müller: …“* mit Knöpfen **[Entwurf erstellen] [Ignorieren]**.
   Bis zum Knopfdruck läuft kein Claude (kostet kein Limit).
4. **Entwurf erstellen:** Claude schreibt einen Antwortvorschlag. Er hat dabei nur die Werkzeuge `Read, Glob, Grep`,
   kann nichts senden, und bekommt den Fremdtext ausdrücklich als Daten, nicht als Anweisung. Fehlt ihm sicheres Wissen
   (Preise, Termine, Zusagen), antwortet er mit `[ICH BRAUCHE EMRE]`, und du schreibst selbst.
5. Du siehst den Entwurf mit **[Senden] [Verwerfen]**. Eigener Text: einfach auf die Meldung **antworten**.
6. Erst **Senden** schreibt in `state/wa_outbox.jsonl`. Gesendet wird nur von `wa.js`.
7. Du bekommst eine Bestätigung („Gesendet an …“) oder den Grund, warum nicht.

Die Freigabe wird also im Programm erzwungen. Sie hängt nicht davon ab, dass Claude sich an Regeln hält.

## Schutzregeln im Code (`limits.js`, `wa.js`)
- Kontakte aus `kontakte.local.md` mit **Einwilligung: ja** werden normal bearbeitet. Unbekannte, die selbst geschrieben haben, bekommen
  ebenfalls die Knöpfe (markiert „nicht gespeichert“, vorsichtiger Entwurf).
- **Nur Antworten:** Gesendet wird nur an Kontakte, die selbst geschrieben haben. Neue Gespräche startet die Brücke nicht.
- Höchstens **30 pro Tag** (Nummer ist nicht neu, keine Aufwärmphase; Emres Entscheidung 13.10.2026).
- Mindestens **45 Sekunden** Abstand, vorher kurz „schreibt …“ als Zeichen für ein natürliches Verhalten.
- Vor der ersten Nachricht an einen Kontakt steht automatisch: *„Hallo, hier schreibt Emres KI-Assistent.“*
- Keine Gruppen, Status oder Broadcasts, nur Einzelchats. Nachrichten werden **nicht als gelesen markiert**, und das Handy
  bleibt für Benachrichtigungen aktiv (`markOnlineOnConnect: false`).
- Verbindungsabbruch: neuer Versuch mit wachsenden Pausen (5 s bis 5 min). Bei Abmeldung durch WhatsApp stoppt der Dienst
  (Exit-Code 2) und wartet auf neues Verknüpfen.

## Einrichten (auf dem Rechner der Zentrale)
Voraussetzungen: `bash setup.sh` (Telegram) läuft, Node.js 20 oder neuer, Prepaid-Nummer mit normalem WhatsApp auf einem Handy.
```
cd ~/assistent
git pull
bash setup-whatsapp.sh
```
Das Skript legt `kontakte.local.md` an, installiert die Pakete, führt die Tests aus, zeigt einen **QR-Code**
(WhatsApp auf dem Prepaid-Handy → Einstellungen → Verknüpfte Geräte → Gerät hinzufügen), schaltet `WHATSAPP_ENABLED=1`
in der `.env` ein und richtet den Autostart ein.

Node.js unter Ubuntu: Die Version aus `apt` ist oft zu alt. `node -v` muss mindestens 20 anzeigen.
Einfach: `sudo snap install node --classic --channel=22`.

## Wichtig
- **Das Prepaid-Handy** muss ab und zu online sein, sonst trennt WhatsApp die verknüpften Geräte (nach meinem Kenntnisstand
  nach etwa 14 Tagen). Die SIM aufgeladen halten.
- **Die Kundenliste** `kontakte.local.md` liegt nur lokal (steht in `.gitignore`). Kunden vorher informieren und um Okay bitten.
- **Datenschutz:** Der Text der Nachricht, für die du einen Entwurf anforderst, und bis zu 6 frühere Nachrichten dieses Kontakts
  (7 Tage, lokal in `state/wa_history.json`) gehen an Claude. Nachrichten ohne Knopfdruck gehen nicht an Claude.
  Das gilt auch für Kundendaten. Sensible Inhalte (Passwörter, Zugangsdaten) gar nicht erst per WhatsApp besprechen.
- **Sperrrisiko:** Inoffizielle Anbindung verstößt gegen die WhatsApp-Bedingungen. Es kann die Prepaid-Nummer treffen,
  nicht deine Hauptnummer. Ersatznummer einplanen.
- **Pfade:** `bruecken/whatsapp/auth/` enthält die WhatsApp-Sitzung (wie ein Passwort). Nicht kopieren oder hochladen.
- **Sprachnachrichten, Bilder, Dateien** werden nur als `[Sprachnachricht]`, `[Bild]` usw. gemeldet, nicht ausgewertet.

## Bekannte Grenzen
- Antworten gehen nur an die Absender-Kennung, von der die Nachricht kam. WhatsApp nutzt teils „LID“-Kennungen statt Nummern;
  kann die Brücke daraus keine Nummer bestimmen, gilt der Absender als unbekannt und wird nur gemeldet.
- Neue Gespräche beginnen, Gruppen und Anhänge senden gibt es nicht.
- Läuft die Brücke nicht, holt WhatsApp verpasste Nachrichten nach dem Start nach, soweit es sie noch vorhält.

## Test
```
cd bruecken/whatsapp && npm test          # Limits und Kontakte
cd ../.. && python3 -m unittest bruecken/telegram/test_wa_link.py   # Freigabe-Ablauf
```
