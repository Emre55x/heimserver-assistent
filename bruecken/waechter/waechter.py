#!/usr/bin/env python3
"""Wächter: prüft alle paar Minuten den Server und meldet Probleme per Telegram (ohne Claude).

Gemeldet wird nur bei Änderung: Problem neu -> Meldung, Problem weg -> "wieder ok".
Läuft als systemd-Timer (assistent-waechter.timer). Zustand: state/waechter.json.
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(os.environ.get("BRIDGE_ROOT") or Path(__file__).resolve().parents[2])
STATE_FILE = ROOT / "state" / "waechter.json"
BAT = Path(os.environ.get("WAECHTER_BAT", "/sys/class/power_supply/BAT0"))
SERVICES = ("assistent-telegram", "assistent-whatsapp")
WA_GRACE = 10 * 60        # WhatsApp darf kurz getrennt sein (Neuverbindung)
DISK_MAX = 90             # Prozent belegt
BAT_LOW = 25              # Prozent, nur relevant ohne Netzteil


def load_env(path):
    env = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return env


def read(path, default=""):
    try:
        return Path(path).read_text().strip()
    except OSError:
        return default


def online():
    try:
        socket.create_connection(("api.telegram.org", 443), timeout=10).close()
        return True
    except OSError:
        return False


def service_active(name):
    r = subprocess.run(["systemctl", "--user", "is-active", name], capture_output=True, text=True)
    return r.stdout.strip() == "active"


def checks(now, enabled_wa):
    """{schlüssel: Problemtext} für alle aktuellen Probleme."""
    problems = {}
    for s in SERVICES:
        if s == "assistent-whatsapp" and not enabled_wa:
            continue
        if not service_active(s):
            problems[f"dienst:{s}"] = f"Dienst {s} läuft nicht."
    if enabled_wa:
        try:
            st = json.loads(read(ROOT / "state" / "wa_status.json", "{}"))
        except ValueError:
            st = {}
        since = (st.get("ts") or 0) / 1000
        if st.get("connection") != "open" and now - since > WA_GRACE:
            problems["whatsapp"] = (
                f"WhatsApp nicht verbunden (Zustand: {st.get('connection', 'unbekannt')}). "
                "Bei 'QR-Code nötig' neu verknüpfen."
            )
    usage = shutil.disk_usage(ROOT)
    pct = round(usage.used * 100 / usage.total)
    if pct >= DISK_MAX:
        problems["platte"] = f"Speicher fast voll: {pct} % belegt."
    if BAT.exists():
        status = read(BAT / "status")
        cap = int(read(BAT / "capacity", "0") or 0)
        if status == "Discharging":
            problems["strom"] = f"Server läuft auf Akku ({cap} %). Netzteil oder Strom prüfen."
            if cap <= BAT_LOW:
                problems["akku"] = f"Akku nur noch {cap} %. Server geht bald aus."
    return problems


def send(env, text):
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{env['TELEGRAM_BOT_TOKEN']}/sendMessage",
        data=json.dumps({"chat_id": int(env["TELEGRAM_OWNER_ID"]), "text": text}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        json.load(resp)


def hm(ts):
    return datetime.fromtimestamp(ts).strftime("%d.%m. %H:%M")


def main():
    env = load_env(ROOT / ".env")
    if not env.get("TELEGRAM_BOT_TOKEN") or not env.get("TELEGRAM_OWNER_ID", "").isdigit():
        sys.exit("TELEGRAM_BOT_TOKEN/TELEGRAM_OWNER_ID fehlen in .env")
    now = time.time()
    try:
        state = json.loads(STATE_FILE.read_text())
    except (OSError, ValueError):
        state = {}
    known = state.get("problems", {})  # schlüssel -> {"text", "since"}

    if not online():
        state.setdefault("offline_since", now)
        STATE_FILE.write_text(json.dumps(state))
        return  # melden geht erst, wenn das Internet zurück ist

    lines = []
    if "offline_since" in state:
        mins = int((now - state.pop("offline_since")) // 60)
        if mins >= 5:
            lines.append(f"🌐 Internet war ca. {mins} Min weg (ab {hm(now - mins * 60)}), jetzt wieder da.")

    current = checks(now, env.get("WHATSAPP_ENABLED") == "1")
    for key, text in current.items():
        if key not in known:
            lines.append(f"⚠️ {text}")
            known[key] = {"text": text, "since": now}
    for key in [k for k in known if k not in current]:
        lines.append(f"✅ Wieder ok: {known.pop(key)['text']}")

    if lines:
        try:
            send(env, "Wächter:\n" + "\n".join(lines))
        except OSError:
            return  # nächster Lauf versucht es erneut (Zustand unverändert)
    state["problems"] = known
    state["last"] = now
    STATE_FILE.write_text(json.dumps(state))


if __name__ == "__main__":
    main()
