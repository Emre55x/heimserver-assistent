#!/usr/bin/env bash
# Einrichtung der WhatsApp-Brücke (Weg C). Erst ausführen, wenn bash setup.sh (Telegram) läuft
# und die Prepaid-Nummer mit normalem WhatsApp auf einem Handy aktiviert ist.
# Aufruf im Repository-Ordner:  bash setup-whatsapp.sh
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

fail() { echo "FEHLER: $*" >&2; exit 1; }
ask()  { local a; read -r -p "$1 [j/N] " a; [[ "$a" =~ ^[jJyY]$ ]]; }

echo "== 1/6 Voraussetzungen"
[ -f .env ] || fail ".env fehlt. Erst 'bash setup.sh' ausführen."
command -v systemctl >/dev/null || fail "systemd nicht gefunden"
NODE_BIN="$(command -v node || true)"
[ -n "$NODE_BIN" ] || fail "Node.js fehlt. Version 20 oder neuer installieren (z. B. 'sudo snap install node --classic --channel=22')."
NODE_MAJOR="$("$NODE_BIN" -p 'process.versions.node.split(".")[0]')"
[ "$NODE_MAJOR" -ge 20 ] || fail "Node.js $NODE_MAJOR ist zu alt, es braucht Version 20 oder neuer."
command -v npm >/dev/null || fail "npm fehlt."
echo "Node.js $("$NODE_BIN" -v)"

echo "== 2/6 Kontaktliste"
if [ ! -f kontakte.local.md ]; then
  cp kontakte.beispiel.md kontakte.local.md
  echo "kontakte.local.md aus der Vorlage angelegt. Trag dort Kunden/Freunde ein (Einwilligung: ja),"
  echo "sonst werden alle Nachrichten nur gemeldet und nie beantwortet:  nano kontakte.local.md"
fi

echo "== 3/6 Pakete installieren"
( cd bruecken/whatsapp && npm ci --omit=dev --no-audit --no-fund )

echo "== 4/6 Tests"
( cd bruecken/whatsapp && "$NODE_BIN" --test ) || fail "Tests fehlgeschlagen."

echo "== 5/6 Mit WhatsApp verknüpfen"
if [ ! -f bruecken/whatsapp/auth/creds.json ]; then
  echo "Gleich erscheint ein QR-Code. Auf dem Handy mit der Prepaid-Nummer:"
  echo "WhatsApp → Einstellungen → Verknüpfte Geräte → Gerät hinzufügen → Code scannen."
  echo "Nutze NICHT deine private Hauptnummer."
  ask "Bereit?" || fail "Abgebrochen."
  ( cd bruecken/whatsapp && "$NODE_BIN" wa.js --login )
else
  echo "Schon verknüpft (bruecken/whatsapp/auth). Zum Neuverknüpfen den Ordner auth löschen."
fi
chmod -R go-rwx bruecken/whatsapp/auth 2>/dev/null || true

echo "== 6/6 Dienste"
grep -q '^WHATSAPP_ENABLED=1' .env || echo 'WHATSAPP_ENABLED=1' >> .env
UNIT_DIR="$HOME/.config/systemd/user"
mkdir -p "$UNIT_DIR"
sed -e "s|%h/assistent|$DIR|g" -e "s|/usr/bin/node|$NODE_BIN|" \
    bruecken/whatsapp/assistent-whatsapp.service > "$UNIT_DIR/assistent-whatsapp.service"
systemctl --user daemon-reload
systemctl --user enable --now assistent-whatsapp
systemctl --user restart assistent-telegram

echo
echo "Fertig. Schreib von einem anderen Handy an die Prepaid-Nummer (der Absender muss in kontakte.local.md stehen)."
echo "Dann kommt bei dir in Telegram die Meldung mit den Knöpfen."
echo "Status: Telegram-Bot /status   |   journalctl --user -u assistent-whatsapp -f"
