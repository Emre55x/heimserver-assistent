#!/usr/bin/env python3
"""Telegram-Brücke für Emres Assistenten.

Nimmt Nachrichten von Emres Telegram-ID an, legt sie in eine dauerhafte
Warteschlange und übergibt sie gebündelt an Claude Code (`claude -p`) im
Assistenten-Ordner. Die Antwort geht 1:1 zurück an Telegram.

Spart Nutzungslimit: Das Warten auf Nachrichten ist reines Python. Claude
startet nur, wenn eine echte Nachricht von Emre vorliegt.

Nur Standardbibliothek, keine Abhängigkeiten.
"""
import fcntl
import json
import logging
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from wa_link import WaLink

ROOT = Path(os.environ.get("BRIDGE_ROOT") or Path(__file__).resolve().parents[2])
STATE = ROOT / "state"
QUEUE_FILE = STATE / "queue.jsonl"
OFFSET_FILE = STATE / "offset"
SESSION_FILE = STATE / "session.json"
STATUS_FILE = STATE / "status.json"
LOCK_FILE = STATE / "bridge.lock"

BATCH_WAIT = 4            # Sekunden warten, ob noch weitere Nachrichten kommen
POLL_TIMEOUT = 30         # Long-Polling bei Telegram
WA_POLL_TIMEOUT = 8       # kürzer, wenn WhatsApp aktiv ist (Eingang der Datei prüfen)
STALE_AFTER = 600         # Nachricht älter als 10 Min: Claude soll nachfragen
SESSION_MAX_TURNS = 8     # danach frischer Kontext (spart Limit)
SESSION_MAX_IDLE = 6 * 3600
RETRY_LIMIT_WAIT = 30 * 60   # Wartezeit nach Nutzungslimit
RETRY_ERROR_WAIT = 5 * 60    # Wartezeit nach sonstigem Fehler
MAX_ATTEMPTS = 3
TG_MAX = 4000
VOICE_MAX_S = 300         # längere Sprachnachrichten nicht umwandeln
WHISPER_PY = os.environ.get("WHISPER_PYTHON") or str(Path.home() / ".local/share/assistent/whisper/bin/python")
# Im Brücken-Lauf gesperrt, auch wenn CLAUDE_ALLOWED_TOOLS mehr erlaubt: Regeln, Helfer,
# Brücken-Code (erzwingt Freigaben/Limits), Geheimnisse und Zustand. Ändern nur am Laptop.
PROTECTED = [
    "Edit(./CLAUDE.md)", "Write(./CLAUDE.md)",
    "Edit(./helfer/**)", "Write(./helfer/**)",
    "Edit(./bruecken/**)", "Write(./bruecken/**)",
    "Edit(./.claude/**)", "Write(./.claude/**)",
    "Edit(./state/**)", "Write(./state/**)",
    "Edit(./.env)", "Write(./.env)", "Read(./.env)",
    "Read(./bruecken/whatsapp/auth/**)",
]

log = logging.getLogger("bridge")


def load_env(path):
    """Liest KEY=VALUE aus .env; bereits gesetzte Umgebungsvariablen gewinnen."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def setup_logging(token):
    class Scrub(logging.Filter):
        def filter(self, record):
            if token:
                record.msg = str(record.msg).replace(token, "***")
                if record.args:
                    record.args = tuple(
                        str(a).replace(token, "***") if isinstance(a, str) else a
                        for a in record.args
                    )
            return True

    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    (ROOT / "logs").mkdir(exist_ok=True)
    handlers = [
        RotatingFileHandler(ROOT / "logs" / "telegram.log", maxBytes=500_000, backupCount=3),
        logging.StreamHandler(sys.stderr),
    ]
    for h in handlers:
        h.setFormatter(fmt)
        h.addFilter(Scrub())
        log.addHandler(h)
    log.setLevel(logging.INFO)


class Bridge:
    def __init__(self):
        load_env(ROOT / ".env")
        self.token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        owner = os.environ.get("TELEGRAM_OWNER_ID", "")
        if not self.token or not owner.isdigit():
            sys.exit("TELEGRAM_BOT_TOKEN und TELEGRAM_OWNER_ID müssen in .env stehen.")
        self.owner = int(owner)
        self.claude_bin = os.environ.get("CLAUDE_BIN", "claude")
        self.model = os.environ.get("CLAUDE_MODEL", "")
        self.allowed_tools = os.environ.get(
            "CLAUDE_ALLOWED_TOOLS", "Read,Glob,Grep,Edit,Write,WebSearch,WebFetch"
        )
        self.claude_timeout = int(os.environ.get("CLAUDE_TIMEOUT", "900"))
        self.next_try = 0.0
        self.last_stranger_notice = 0.0
        STATE.mkdir(exist_ok=True)
        setup_logging(self.token)
        self.wa = WaLink(self, STATE) if os.environ.get("WHATSAPP_ENABLED") == "1" else None

    # ---------- Telegram ----------
    def api(self, method, params=None, timeout=60):
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{self.token}/{method}",
            data=json.dumps(params or {}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.load(resp)
        if not body.get("ok"):
            raise RuntimeError(body.get("description", "Telegram-Fehler"))
        return body["result"]

    def send(self, text):
        text = text.strip() or "(leere Antwort)"
        for i in range(0, len(text), TG_MAX):
            self.api("sendMessage", {"chat_id": self.owner, "text": text[i:i + TG_MAX]})

    def transcribe(self, voice):
        """Sprachnachricht lokal in Text umwandeln (transkript.py). None bei Fehler, Emre wird informiert."""
        if voice.get("duration", 0) > VOICE_MAX_S:
            self.send(f"Sprachnachricht zu lang (max. {VOICE_MAX_S // 60} Min). Bitte kürzer oder als Text.")
            return None
        if not Path(WHISPER_PY).exists():
            self.send("Sprachnachrichten sind auf diesem Gerät nicht eingerichtet. Bitte als Text schreiben.")
            return None
        path = STATE / "voice.ogg"
        try:
            info = self.api("getFile", {"file_id": voice["file_id"]})
            with urllib.request.urlopen(
                f"https://api.telegram.org/file/bot{self.token}/{info['file_path']}", timeout=60
            ) as resp:
                path.write_bytes(resp.read())
            proc = subprocess.run(
                [WHISPER_PY, str(Path(__file__).with_name("transkript.py")), str(path)],
                capture_output=True, text=True, timeout=600,
            )
            text = proc.stdout.strip()
            if proc.returncode != 0:
                raise RuntimeError(proc.stderr.strip()[-200:] or "Umwandlung fehlgeschlagen")
        except (urllib.error.URLError, TimeoutError, OSError):
            raise  # Telegram nicht erreichbar: Update später erneut
        except Exception as exc:
            log.warning("Sprachnachricht nicht umgewandelt: %s", exc)
            self.send("Sprachnachricht konnte nicht umgewandelt werden. Bitte als Text schreiben.")
            return None
        finally:
            path.unlink(missing_ok=True)
        if not text:
            self.send("In der Sprachnachricht wurde nichts verstanden.")
            return None
        self.send(f"🎤 Verstanden: {text}")
        return text

    # ---------- Zustand ----------
    @staticmethod
    def read_json(path, default):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return default

    @staticmethod
    def write_atomic(path, text):
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)

    def load_queue(self):
        if not QUEUE_FILE.exists():
            return []
        return [json.loads(l) for l in QUEUE_FILE.read_text(encoding="utf-8").splitlines() if l.strip()]

    def save_queue(self, items):
        self.write_atomic(QUEUE_FILE, "".join(json.dumps(i, ensure_ascii=False) + "\n" for i in items))

    def get_offset(self):
        try:
            return int(OFFSET_FILE.read_text().strip())
        except (OSError, ValueError):
            return 0

    def set_offset(self, value):
        self.write_atomic(OFFSET_FILE, str(value))

    # ---------- Nachrichten ----------
    def handle_update(self, upd):
        cq = upd.get("callback_query")
        if cq:
            if self.wa and (cq.get("from") or {}).get("id") == self.owner:
                self.wa.handle_callback(cq)
            else:
                log.warning("Fremder Knopfdruck von ID %s ignoriert", (cq.get("from") or {}).get("id"))
            return
        msg = upd.get("message")
        if not msg:
            return
        sender = (msg.get("from") or {}).get("id")
        private = (msg.get("chat") or {}).get("type") == "private"
        if sender != self.owner or not private:
            log.warning("Fremde Nachricht von ID %s ignoriert", sender)
            if time.time() - self.last_stranger_notice > 3600:
                self.last_stranger_notice = time.time()
                self.send(f"Hinweis: Fremde Nachricht von Telegram-ID {sender} wurde ignoriert.")
            return
        text = msg.get("text")
        if not text and msg.get("voice"):
            text = self.transcribe(msg["voice"])
            if not text:
                return
            msg["text"] = text  # damit auch eigene WhatsApp-Texte per Sprache gehen
        if not text:
            self.send("Ich nehme nur Text und Sprachnachrichten an.")
            return
        if self.wa and msg.get("reply_to_message") and self.wa.handle_reply(msg):
            return
        cmd = text.strip().split()[0].lower() if text.startswith("/") else ""
        if cmd in ("/status", "/hilfe", "/help", "/start", "/neu", "/push"):
            self.command(cmd)
            return
        items = self.load_queue()
        items.append({"id": upd["update_id"], "date": msg["date"], "text": text, "attempts": 0})
        self.save_queue(items)
        log.info("Auftrag in Warteschlange (%d offen)", len(items))

    def command(self, cmd):
        if cmd == "/push":
            self.git_push()
        elif cmd == "/neu":
            SESSION_FILE.unlink(missing_ok=True)
            self.send("Gesprächskontext zurückgesetzt.")
        elif cmd == "/status":
            session = self.read_json(SESSION_FILE, {})
            status = self.read_json(STATUS_FILE, {})
            wait = max(0, int(self.next_try - time.time()))
            self.send(
                f"Warteschlange: {len(self.load_queue())}\n"
                f"Letzter Lauf: {status.get('last_run', 'noch keiner')} ({status.get('result', '-')})\n"
                f"Kontext: {session.get('turns', 0)} Runden\n"
                f"Nächster Versuch in: {wait} s"
                + (f"\n{self.wa.status_line()}" if self.wa else "")
            )
        else:
            self.send("Schreib einfach deinen Auftrag (Text oder Sprache).\n/status – Stand\n"
                      "/neu – frischer Kontext\n/push – gespeicherte Änderungen auf GitHub hochladen")

    # ---------- Claude ----------
    def build_prompt(self, items):
        now = time.time()
        parts = [
            "Neue Nachrichten von Emre über Telegram. Arbeite sie nach den Regeln in CLAUDE.md ab. "
            "Trage echte Aufträge in auftraege.md ein. Alles mit Außenwirkung nur als Freigabeanfrage. "
            "Deine Antwort geht unverändert per Telegram an Emre, also kurz und auf Deutsch. "
            "Du hast keine Shell: Änderungen speichert die Brücke danach selbst per git commit, "
            "Pushen macht Emre mit /push.\n"
        ]
        for it in items:
            age = int(now - it["date"])
            when = datetime.fromtimestamp(it["date"]).strftime("%Y-%m-%d %H:%M")
            note = f", wartete {age // 60} Min" if age >= 60 else ""
            stale = " [ÄLTER ALS 10 MIN: bei Zeitkritischem erst nachfragen]" if age > STALE_AFTER else ""
            parts.append(f"[Eingang {when}{note}]{stale}\n{it['text']}\n")
        return "\n".join(parts)

    def session_id(self):
        s = self.read_json(SESSION_FILE, {})
        if not s.get("id"):
            return None
        if s.get("turns", 0) >= SESSION_MAX_TURNS or time.time() - s.get("last", 0) > SESSION_MAX_IDLE:
            return None
        return s["id"]

    def run_claude(self, prompt, tools=None, resume=True, model=None):
        """tools/resume: für Entwürfe aus fremden Nachrichten eingeschränkt und ohne Kontext."""
        cmd = [self.claude_bin, "-p", "--output-format", "json", "--allowedTools", tools or self.allowed_tools]
        cmd += ["--disallowedTools", *PROTECTED]
        if model or self.model:
            cmd += ["--model", model or self.model]
        sid = self.session_id() if resume else None
        if sid:
            cmd += ["--resume", sid]
        proc = subprocess.run(
            cmd, input=prompt, cwd=ROOT, capture_output=True, text=True, timeout=self.claude_timeout
        )
        try:
            data = json.loads(proc.stdout)
        except ValueError:
            raise RuntimeError((proc.stderr or proc.stdout or "keine Ausgabe").strip()[-500:])
        if proc.returncode != 0 or data.get("is_error"):
            raise RuntimeError(str(data.get("result") or proc.stderr)[-500:])
        return data

    def process_queue(self):
        items = self.load_queue()
        if not items or time.time() < self.next_try:
            return
        try:
            self.api("sendChatAction", {"chat_id": self.owner, "action": "typing"}, timeout=10)
        except Exception:
            pass
        started = datetime.now().strftime("%Y-%m-%d %H:%M")
        try:
            data = self.run_claude(self.build_prompt(items))
        except Exception as exc:  # Fehler, Limit oder Zeitüberschreitung
            self.on_failure(items, str(exc), started)
            return
        old = self.read_json(SESSION_FILE, {})
        turns = old.get("turns", 0) + 1 if old.get("id") == data.get("session_id") else 1
        self.write_atomic(SESSION_FILE, json.dumps(
            {"id": data.get("session_id"), "turns": turns, "last": time.time()}))
        self.write_atomic(STATUS_FILE, json.dumps({"last_run": started, "result": "ok"}))
        self.save_queue([])
        self.send(data.get("result") or "(keine Antwort)")
        self.git_commit(f"Telegram-Auftrag {started}")

    # ---------- Git (im Code, Claude hat keine Shell) ----------
    def git(self, *args, timeout=60):
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=timeout)

    def git_commit(self, message):
        """Änderungen des Laufs speichern (.gitignore schützt .env, state/, kunden/ usw.). Fehler nur ins Log."""
        try:
            if not (ROOT / ".git").exists():
                return
            self.git("add", "-A")
            if self.git("diff", "--cached", "--quiet").returncode == 0:
                return  # nichts geändert
            res = self.git("commit", "-q", "-m", message)
            if res.returncode != 0:
                log.warning("Commit fehlgeschlagen: %s", (res.stderr or res.stdout).strip()[-200:])
        except Exception as exc:
            log.warning("Commit fehlgeschlagen: %s", exc)

    def git_push(self):
        try:
            res = self.git("push", "-q", "origin", "HEAD", timeout=120)
        except Exception as exc:
            self.send(f"Push fehlgeschlagen: {exc}")
            return
        if res.returncode == 0:
            self.send("Auf GitHub hochgeladen.")
        else:
            self.send("Push fehlgeschlagen:\n" + (res.stderr or res.stdout).strip()[-400:])

    def on_failure(self, items, error, started):
        limit = any(w in error.lower() for w in ("limit", "usage", "quota", "rate"))
        for it in items:
            it["attempts"] = it.get("attempts", 0) + 1
        log.error("Claude-Lauf fehlgeschlagen: %s", error.replace("\n", " ")[:300])
        if "No conversation found" in error:
            SESSION_FILE.unlink(missing_ok=True)  # alte Sitzung (z. B. nach Umzug): frisch beginnen
        self.write_atomic(STATUS_FILE, json.dumps(
            {"last_run": started, "result": "Limit" if limit else "Fehler"}))
        if not limit and all(it["attempts"] >= MAX_ATTEMPTS for it in items):
            self.save_queue([])
            self.send("Das hat dreimal nicht geklappt, ich lasse es liegen. Bitte neu schicken oder /status prüfen.\n"
                      f"Fehler: {error.strip()[-200:]}")
            return
        wait = RETRY_LIMIT_WAIT if limit else RETRY_ERROR_WAIT
        self.next_try = time.time() + wait
        self.save_queue(items)
        if limit or items[0]["attempts"] == 1:
            what = "Nutzungslimit erreicht" if limit else "Fehler beim Bearbeiten"
            self.send(f"{what}. {len(items)} Auftrag/Aufträge bleiben in der Warteschlange, "
                      f"nächster Versuch in {wait // 60} Min.")

    # ---------- Hauptschleife ----------
    def run(self):
        lock = open(LOCK_FILE, "w")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            sys.exit("Die Brücke läuft schon.")
        log.info("Brücke gestartet, Besitzer-ID %s", self.owner)
        offset = self.get_offset()
        errors = 0
        while True:
            queued = bool(self.load_queue())
            wait_s = BATCH_WAIT if queued and time.time() >= self.next_try else POLL_TIMEOUT
            if queued and time.time() < self.next_try:
                wait_s = min(POLL_TIMEOUT, max(1, int(self.next_try - time.time())))
            if self.wa:
                wait_s = min(wait_s, WA_POLL_TIMEOUT)
            try:
                updates = self.api(
                    "getUpdates",
                    {"offset": offset, "timeout": wait_s, "allowed_updates": ["message", "callback_query"]},
                    timeout=wait_s + 15,
                )
                errors = 0
                for upd in updates:
                    try:
                        self.handle_update(upd)
                    except (urllib.error.URLError, TimeoutError, OSError):
                        raise
                    except Exception:  # ein defektes Update soll die Brücke nicht stoppen
                        log.exception("Update %s übersprungen", upd.get("update_id"))
                    offset = upd["update_id"] + 1
                    self.set_offset(offset)
                if self.wa:
                    try:
                        self.wa.poll()
                    except (urllib.error.URLError, TimeoutError, OSError):
                        raise
                    except Exception:
                        log.exception("WhatsApp-Verarbeitung fehlgeschlagen")
                if not updates:
                    self.process_queue()
            except (urllib.error.URLError, TimeoutError, RuntimeError, OSError) as exc:
                errors += 1
                delay = min(300, 5 * 2 ** min(errors, 6))
                log.warning("Telegram nicht erreichbar (%s), neuer Versuch in %d s", exc, delay)
                time.sleep(delay)


if __name__ == "__main__":
    try:
        Bridge().run()
    except KeyboardInterrupt:
        pass
