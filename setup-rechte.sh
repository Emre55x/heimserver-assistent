#!/usr/bin/env bash
# Schaltet Shell-Rechte (Bash) für Telegram-Aufträge an oder aus. Andere Werkzeuge (Kalender, Drive) bleiben.
# Stand 15.10.2026: Emre hat entschieden, die Shell AUS zu lassen.
# ACHTUNG beim Einschalten: Mit Bash greifen die Sperren in bridge.py (PROTECTED) nicht mehr. Claude könnte
# dann CLAUDE.md ändern, .env lesen oder WhatsApp-Nachrichten ohne Senden-Knopf in die Warteschlange legen.
# Start OHNE sudo:  bash setup-rechte.sh aus   |   bash setup-rechte.sh an
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"

if [ "$(id -u)" = 0 ]; then
  echo "Bitte ohne sudo starten (als normaler Benutzer)."; exit 1
fi

ENV=.env
MODUS="${1:-}"
[ "$MODUS" = an ] || [ "$MODUS" = aus ] || { echo "Aufruf: bash setup-rechte.sh an|aus"; exit 1; }

# Sicherheitsprüfung: WhatsApp-Entwürfe dürfen niemals Bash bekommen.
if ! grep -q '^DRAFT_TOOLS = "Read,Glob,Grep"$' bruecken/telegram/wa_link.py; then
  echo "ABBRUCH: DRAFT_TOOLS in wa_link.py ist nicht mehr nur Read,Glob,Grep. Erst prüfen."; exit 1
fi
if ! grep -q '^TELEGRAM_OWNER_ID=[0-9]\+' "$ENV"; then
  echo "ABBRUCH: TELEGRAM_OWNER_ID fehlt in .env (nur Emres Telegram-ID darf Aufträge geben)."; exit 1
fi

# Nur ",Bash" hinzufügen/entfernen, Rest der Liste (Kalender, Drive …) bleibt.
ALT="$(grep '^CLAUDE_ALLOWED_TOOLS=' "$ENV" | tail -1 | cut -d= -f2-)"
[ -n "$ALT" ] || ALT="Read,Glob,Grep,Edit,Write,WebSearch,WebFetch"
OHNE="$(echo "$ALT" | tr ',' '\n' | grep -vx 'Bash' | paste -sd,)"
WERT="$OHNE"
if [ "$MODUS" = an ]; then
  echo "WARNUNG: Mit Shell gelten die Sperren für CLAUDE.md, .env und den Brücken-Code nicht mehr."
  read -r -p "Wirklich einschalten? [j/N] " a; [[ "$a" =~ ^[jJ]$ ]] || exit 1
  WERT="$OHNE,Bash"
fi

cp "$ENV" "$ENV.bak"
if grep -q '^CLAUDE_ALLOWED_TOOLS=' "$ENV"; then
  sed -i "s|^CLAUDE_ALLOWED_TOOLS=.*|CLAUDE_ALLOWED_TOOLS=$WERT|" "$ENV"
else
  printf '\nCLAUDE_ALLOWED_TOOLS=%s\n' "$WERT" >> "$ENV"
fi
chmod 600 "$ENV"

systemctl --user restart assistent-telegram.service
sleep 2
systemctl --user is-active assistent-telegram.service

echo "Fertig: Shell $MODUS (Sicherung: $ENV.bak). WhatsApp-Entwürfe bleiben immer bei Read,Glob,Grep."
