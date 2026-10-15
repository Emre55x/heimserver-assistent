# Brücken

Kleine Programme, die Nachrichten annehmen und an Claude Code weitergeben. Claude startet nur bei einem echten Auftrag (spart Nutzungslimit).

Brücken:
1. `telegram/` – Steuerkanal (läuft). Siehe `telegram/README.md`.
2. `whatsapp/` – Kunden/Freunde über eine eigene Prepaid-Nummer (läuft). Siehe `whatsapp/README.md`.
3. `waechter/` – prüft alle 5 Minuten, ob alles läuft, und meldet Probleme per Telegram.

Autostart auf dem Heimserver: systemd-Benutzerdienst, der die Brücken beim Hochfahren startet.
