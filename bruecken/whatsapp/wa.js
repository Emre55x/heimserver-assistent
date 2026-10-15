// WhatsApp-Brücke (inoffiziell, als verknüpftes Gerät, Bibliothek Baileys).
//
// Liest Nachrichten und legt sie in state/wa_inbox.jsonl ab. Sendet NUR, was die
// Telegram-Brücke nach Emres Freigabe in state/wa_outbox.jsonl schreibt.
// Claude hat mit diesem Programm nichts zu tun und kann hier nichts senden.
//
// Regeln (CLAUDE.md 6a): nur Kontakte mit "Einwilligung: ja", nur Antworten auf
// Nachrichten dieser Kontakte, KI-Hinweis in der ersten Nachricht, Tageslimit,
// Mindestabstand 45 s.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import pino from "pino";
import qrcode from "qrcode-terminal";
import makeWASocket, {
  useMultiFileAuthState,
  DisconnectReason,
  fetchLatestBaileysVersion,
} from "@whiskeysockets/baileys";
import * as L from "./limits.js";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = process.env.BRIDGE_ROOT || path.resolve(HERE, "../..");
const STATE = path.join(ROOT, "state");
const AUTH = path.join(HERE, "auth");
const LOGIN_MODE = process.argv.includes("--login");
const EXIT_LOGGED_OUT = 2; // systemd: RestartPreventExitStatus=2

fs.mkdirSync(STATE, { recursive: true });
fs.mkdirSync(AUTH, { recursive: true, mode: 0o700 });

const F = {
  inbox: path.join(STATE, "wa_inbox.jsonl"),
  outbox: path.join(STATE, "wa_outbox.jsonl"),
  results: path.join(STATE, "wa_results.jsonl"),
  done: path.join(STATE, "wa_outbox_done.json"),
  seen: path.join(STATE, "wa_seen.json"), // { jid: nummer } bekannter Kontakte, die geschrieben haben
  sent: path.join(STATE, "wa_sent.json"), // Limit-Zähler, KI-Hinweis
  status: path.join(STATE, "wa_status.json"),
  contacts: path.join(ROOT, "kontakte.local.md"),
};

const log = (...a) => console.log(new Date().toISOString(), ...a);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function readJson(file, fallback) {
  try {
    return JSON.parse(fs.readFileSync(file, "utf8"));
  } catch {
    return fallback;
  }
}
function writeJson(file, data) {
  const tmp = file + ".tmp";
  fs.writeFileSync(tmp, JSON.stringify(data));
  fs.renameSync(tmp, file);
}
const appendLine = (file, obj) => fs.appendFileSync(file, JSON.stringify(obj) + "\n");
function readLines(file) {
  try {
    return fs
      .readFileSync(file, "utf8")
      .split("\n")
      .filter(Boolean)
      .map((l) => {
        try {
          return JSON.parse(l);
        } catch {
          return null;
        }
      })
      .filter(Boolean);
  } catch {
    return [];
  }
}
const readContacts = () => {
  try {
    return L.parseContacts(fs.readFileSync(F.contacts, "utf8"));
  } catch {
    return [];
  }
};

let sock = null;
let connected = false;
let busy = false;
let retries = 0;
const seenIds = new Set(readLines(F.inbox).slice(-500).map((r) => r.id));

function setStatus(connection) {
  const sent = readJson(F.sent, {});
  writeJson(F.status, {
    connection,
    ts: Date.now(),
    sentToday: sent.day === new Date().toLocaleDateString("sv-SE") ? sent.count ?? 0 : 0,
    dailyLimit: L.dailyLimit(sent, Date.now()),
  });
}

function extractText(message) {
  let m = message;
  if (m?.ephemeralMessage) m = m.ephemeralMessage.message;
  if (m?.viewOnceMessage) m = m.viewOnceMessage.message;
  if (!m) return "[leere Nachricht]";
  if (m.conversation) return m.conversation;
  if (m.extendedTextMessage?.text) return m.extendedTextMessage.text;
  if (m.imageMessage) return m.imageMessage.caption ? `[Bild] ${m.imageMessage.caption}` : "[Bild]";
  if (m.videoMessage) return m.videoMessage.caption ? `[Video] ${m.videoMessage.caption}` : "[Video]";
  if (m.audioMessage) return "[Sprachnachricht]";
  if (m.documentMessage) return `[Datei] ${m.documentMessage.fileName ?? ""}`.trim();
  return `[${Object.keys(m)[0] ?? "unbekannt"}]`;
}

function onMessage(m) {
  const key = m.key;
  if (!key || key.fromMe || !m.message) return;
  const jid = key.remoteJid;
  if (!jid || jid.endsWith("@g.us") || jid.endsWith("@broadcast") || jid.endsWith("@newsletter")) return;
  if (seenIds.has(key.id)) return;
  seenIds.add(key.id);

  // Neuere WhatsApp-Versionen nutzen teils @lid statt Telefonnummer; remoteJidAlt hilft, wenn vorhanden.
  const pnJid = [jid, key.remoteJidAlt].find((j) => j && j.endsWith("@s.whatsapp.net"));
  const number = pnJid ? pnJid.split("@")[0].split(":")[0] : null;
  const contact = number ? L.findContact(readContacts(), number) : null;
  const known = Boolean(contact?.consent);

  appendLine(F.inbox, {
    id: key.id,
    ts: Number(m.messageTimestamp) || Math.floor(Date.now() / 1000),
    jid,
    number,
    name: contact?.name ?? m.pushName ?? null,
    known,
    text: extractText(m.message),
  });
  // Auch Unbekannte dürfen eine Antwort bekommen (Emres Entscheidung 13.10.2026), aber nur wer selbst geschrieben hat.
  const seen = readJson(F.seen, {});
  seen[jid] = number;
  writeJson(F.seen, seen);
  log("Nachricht von", known ? contact.name : "unbekannt (nicht gespeichert)");
}

/** "wait" = später erneut versuchen, sonst Ergebnisobjekt. */
async function trySend(job) {
  const seen = readJson(F.seen, {});
  if (!(job.jid in seen)) return { status: "abgelehnt", reason: "Empfänger hat nicht zuerst geschrieben" };
  let text = String(job.text ?? "").trim().slice(0, 3500);
  if (!text) return { status: "abgelehnt", reason: "Leerer Text" };

  const state = readJson(F.sent, {});
  const check = L.checkSend(state, Date.now());
  if (!check.ok) {
    if (check.reason === "gap") return "wait";
    return { status: "limit", reason: check.message };
  }
  if (L.needsIntro(state, job.jid)) text = L.INTRO + text;

  try {
    await sock.sendPresenceUpdate("composing", job.jid);
    await sleep(2000 + Math.random() * 3000);
    await sock.sendMessage(job.jid, { text });
    await sock.sendPresenceUpdate("paused", job.jid);
  } catch (err) {
    return { status: "fehler", reason: String(err?.message ?? err) };
  }
  L.recordSend(state, Date.now());
  L.markIntroduced(state, job.jid);
  writeJson(F.sent, state);
  setStatus("open");
  return { status: "gesendet" };
}

async function pumpOutbox() {
  if (busy || !connected || !sock) return;
  busy = true;
  try {
    const done = new Set(readJson(F.done, []));
    for (const job of readLines(F.outbox)) {
      if (!job.id || done.has(job.id)) continue;
      const res = await trySend(job);
      if (res === "wait") break; // Reihenfolge behalten
      done.add(job.id);
      writeJson(F.done, [...done].slice(-2000));
      appendLine(F.results, { id: job.id, ts: Date.now(), ...res });
      log("Ausgang", job.id, res.status);
    }
  } catch (err) {
    log("Fehler im Ausgang:", err?.message ?? err);
  } finally {
    busy = false;
  }
}

async function start() {
  const { state, saveCreds } = await useMultiFileAuthState(AUTH);
  let version;
  try {
    ({ version } = await fetchLatestBaileysVersion());
  } catch {
    log("WhatsApp-Version nicht abrufbar, nutze Standard der Bibliothek");
  }
  sock = makeWASocket({
    auth: state,
    ...(version ? { version } : {}),
    logger: pino({ level: "silent" }),
    markOnlineOnConnect: false, // Handy soll weiter Benachrichtigungen zeigen
    syncFullHistory: false,
  });

  sock.ev.on("creds.update", saveCreds);
  sock.ev.on("messages.upsert", ({ messages, type }) => {
    if (type !== "notify") return;
    for (const m of messages) {
      try {
        onMessage(m);
      } catch (err) {
        log("Fehler bei Nachricht:", err?.message ?? err);
      }
    }
  });
  sock.ev.on("connection.update", (u) => {
    const { connection, lastDisconnect, qr } = u;
    if (qr) {
      setStatus("qr");
      console.log("\nIn WhatsApp: Einstellungen → Verknüpfte Geräte → Gerät hinzufügen, dann diesen Code scannen:\n");
      qrcode.generate(qr, { small: true });
    }
    if (connection === "open") {
      connected = true;
      retries = 0;
      setStatus("open");
      log("WhatsApp verbunden");
      if (LOGIN_MODE) {
        log("Anmeldung gespeichert. Beende in 8 Sekunden.");
        setTimeout(() => process.exit(0), 8000);
      }
    }
    if (connection === "close") {
      connected = false;
      setStatus("close");
      const code = lastDisconnect?.error?.output?.statusCode;
      if (code === DisconnectReason.loggedOut) {
        log("Abgemeldet. Ordner bruecken/whatsapp/auth löschen und neu verknüpfen.");
        process.exit(EXIT_LOGGED_OUT);
      }
      const delay = Math.min(300_000, 5000 * 2 ** Math.min(retries++, 6)); // 5 s … 5 min
      log("Verbindung getrennt (Code", code, `), neuer Versuch in ${Math.round(delay / 1000)} s`);
      setTimeout(() => start().catch((e) => log("Neustart fehlgeschlagen:", e?.message ?? e)), delay);
    }
  });
}

if (!LOGIN_MODE) setInterval(pumpOutbox, 3000);
start().catch((e) => {
  log("Start fehlgeschlagen:", e?.message ?? e);
  process.exit(1);
});
