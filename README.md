# Heimserver-Assistent

Persönlicher KI-Assistent für meinen IT-Support, gebaut auf [Claude Code](https://claude.com/claude-code). Er läuft rund um die Uhr auf einem alten Surface Pro 3 mit Ubuntu Server und wird über Telegram gesteuert.

**Grundsatz:** Die KI entwirft, der Mensch entscheidet. Nichts geht nach außen ohne Freigabe per Knopfdruck.

## Was er kann

- **Aufträge per Telegram** – Text oder Sprachnachricht (lokale Spracherkennung mit faster-whisper, keine Cloud).
- **Kalender und Google Drive** lesen, Dateien ablegen, Termine vorbereiten.
- **WhatsApp-Support:** Kunden schreiben an eine eigene Nummer, die KI entwirft eine Antwort, ich bekomme sie in Telegram mit den Knöpfen **[Senden] [Verwerfen] [Fall merken]**.
- **Wissensdatenbank:** gelöste Fälle werden – ohne Kundendaten – für spätere Antworten gesammelt.
- **Wächter:** prüft alle 5 Minuten Dienste, Speicherplatz, Akku und Internet und meldet Probleme – nur bei Änderungen, ohne KI.

## Aufbau

```
Telegram ──► bridge.py ──► Claude Code (eingeschränkte Werkzeuge) ──► Antwort / Entwurf
                │
WhatsApp ──► wa.js (Node) ──► Eingang ──► Entwurf ──► Freigabe in Telegram ──► Versand
                                                         (nur durch Code, nie durch die KI)
Wächter (systemd-Timer, ohne KI) ──► Meldung bei Problemen
```

| Ordner/Datei | Inhalt |
|---|---|
| `CLAUDE.md` | Regeln für die KI: Freigabepflicht, Datenschutz, sparsames Arbeiten |
| `helfer/` | Rollen: „Büro“ entwirft, „Prüfer“ kontrolliert vor der Ausgabe |
| `bruecken/telegram/` | Telegram-Brücke, Warteschlange, Freigabe-Knöpfe, Spracherkennung (Python, nur Standardbibliothek) |
| `bruecken/whatsapp/` | WhatsApp-Anbindung mit Versandlimits (Node.js, Baileys) |
| `bruecken/waechter/` | Überwachung per systemd-Timer |
| `setup*.sh` | Einrichtung von Diensten, Rechten und Bildschirm |

## Sicherheit

- **Nur eine Telegram-ID** darf Aufträge geben, alles andere wird ignoriert und gemeldet.
- **Kein Shell-Zugriff für die KI** bei Telegram-Aufträgen; Regeln, Code und Zugangsdaten sind für sie gesperrt (`--disallowedTools`).
- **Prompt-Injection-Schutz:** Nachrichten Dritter werden als Daten markiert, nie als Anweisung behandelt (mit Tests).
- **Versandlimits** gegen Sperrung: max. 30 Nachrichten pro Tag, mind. 45 s Abstand, nur Antworten.
- **Geheimnisse nur in `.env`**, Kontakte und Kundenkarten nur lokal (`.gitignore`).
- Server: verschlüsselte Festplatte (LUKS), Zugriff nur per SSH-Schlüssel.

## Tests

```bash
cd bruecken/telegram && python3 -m unittest test_wa_link     # 16 Tests
cd bruecken/waechter && python3 -m unittest test_waechter    # 5 Tests
cd bruecken/whatsapp && node --test limits.test.js           # 6 Tests
```

## Einrichtung (Kurzfassung)

1. Repository klonen, `cp .env.example .env`, Telegram-Bot-Token und eigene Telegram-ID eintragen.
2. `bash setup.sh` richtet die systemd-Benutzerdienste ein.
3. Optional: `bash setup-whatsapp.sh` und mit dem Handy den QR-Code scannen.

Details stehen in den READMEs der einzelnen Brücken.

## Hinweis

Die WhatsApp-Anbindung nutzt die inoffizielle Bibliothek Baileys. Das verstößt gegen die Nutzungsbedingungen von WhatsApp und kann zur Sperrung der Nummer führen – deshalb eine eigene Prepaid-Nummer und strenge Limits.
