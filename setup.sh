#!/usr/bin/env bash
# Einrichtung der Telegram-Brücke auf einem Linux-Rechner mit systemd.
# Aufruf im Repository-Ordner:  bash setup.sh
# Der Token wird verdeckt abgefragt und nur in .env (Rechte 600) gespeichert.
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

fail() { echo "FEHLER: $*" >&2; exit 1; }
ask()  { local a; read -r -p "$1 [j/N] " a; [[ "$a" =~ ^[jJyY]$ ]]; }

echo "== 1/5 Voraussetzungen"
command -v python3   >/dev/null || fail "python3 fehlt (sudo apt install python3)"
command -v systemctl >/dev/null || fail "systemd nicht gefunden"
CLAUDE_BIN="$(command -v claude || true)"
[ -n "$CLAUDE_BIN" ] || fail "Claude Code nicht gefunden. Erst installieren und einmal 'claude' starten, anmelden."
echo "Claude Code: $CLAUDE_BIN"

echo "== 2/5 .env"
[ -f .env ] || cp .env.example .env
chmod 600 .env
set_env() {  # set_env KEY WERT  (Wert läuft über die Umgebung, nicht über die Kommandozeile)
  KEY="$1" VAL="$2" python3 - <<'PY'
import os, pathlib
p = pathlib.Path(".env")
key, val = os.environ["KEY"], os.environ["VAL"]
lines = [l for l in p.read_text().splitlines() if not l.startswith(key + "=")]
lines.insert(0, f"{key}={val}")
p.write_text("\n".join(lines) + "\n")
PY
}
if ! grep -qE '^TELEGRAM_BOT_TOKEN=.+' .env; then
  read -r -s -p "Bot-Token von BotFather (wird nicht angezeigt): " TOKEN; echo
  [ -n "$TOKEN" ] || fail "Kein Token eingegeben."
  set_env TELEGRAM_BOT_TOKEN "$TOKEN"
  unset TOKEN
fi
if ! grep -qE '^TELEGRAM_OWNER_ID=[1-9][0-9]+' .env || grep -qE '^TELEGRAM_OWNER_ID=123456789$' .env; then
  read -r -p "Deine Telegram-ID (z. B. über @userinfobot): " OWNER
  [[ "$OWNER" =~ ^[0-9]+$ ]] || fail "Ungültige Telegram-ID."
  set_env TELEGRAM_OWNER_ID "$OWNER"
fi

echo "== 3/5 Token prüfen"
python3 - <<'PY'
import json, pathlib, urllib.request
env = dict(l.split("=", 1) for l in pathlib.Path(".env").read_text().splitlines() if "=" in l and not l.startswith("#"))
try:
    with urllib.request.urlopen(f"https://api.telegram.org/bot{env['TELEGRAM_BOT_TOKEN']}/getMe", timeout=15) as r:
        print("Bot gefunden: @" + json.load(r)["result"]["username"])
except Exception:
    raise SystemExit("FEHLER: Token ungültig oder Telegram nicht erreichbar. Bei @BotFather mit /mybots einen neuen Token erzeugen.")
PY

echo "== 4/5 Claude-Test (verbraucht ein kleines Stück Nutzungslimit)"
if ask "Jetzt 'claude -p' einmal testen?"; then
  "$CLAUDE_BIN" -p "Antworte nur mit dem Wort: ok" || fail "claude -p hat nicht funktioniert. Erst 'claude' interaktiv starten und anmelden."
fi

echo "== 5/5 Autostart (systemd-Benutzerdienst)"
UNIT_DIR="$HOME/.config/systemd/user"
mkdir -p "$UNIT_DIR"
sed -e "s|%h/assistent|$DIR|g" \
    -e "s|^Environment=PATH=.*|Environment=PATH=$(dirname "$CLAUDE_BIN"):%h/.local/bin:/usr/local/bin:/usr/bin:/bin|" \
    bruecken/telegram/assistent-telegram.service > "$UNIT_DIR/assistent-telegram.service"
systemctl --user daemon-reload
systemctl --user enable --now assistent-telegram
if ask "Dienst schon beim Hochfahren starten, auch ohne Login? (loginctl enable-linger)"; then
  loginctl enable-linger "$USER"
fi

echo
echo "Fertig. Schreib deinem Bot jetzt 'hallo'."
echo "Status: systemctl --user status assistent-telegram"
echo "Logs:   journalctl --user -u assistent-telegram -f"
