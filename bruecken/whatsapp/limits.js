// Reine Logik ohne WhatsApp-Verbindung: Kontakte, Sendelimits, KI-Hinweis.
// Regeln stammen aus CLAUDE.md Abschnitt 6a.

export const DAILY_LIMIT = 30; // Nachrichten pro Tag (Nummer ist nicht neu, keine Aufwärmphase)
export const MIN_GAP_MS = 45_000; // Mindestabstand zwischen zwei Nachrichten
export const INTRO = "Hallo, hier schreibt Emres KI-Assistent.\n\n";

/** "+49 176 123", "0176 123", "0049176123" -> "49176123" */
export function normalizeNumber(raw) {
  const s = String(raw ?? "").trim();
  const d = s.replace(/\D/g, "");
  if (s.startsWith("+")) return d;
  if (d.startsWith("00")) return d.slice(2);
  if (d.startsWith("0")) return "49" + d.slice(1);
  return d;
}

/** Liest die Tabelle aus kontakte.local.md. Spalten: Name | Nummer | Einwilligung | ... */
export function parseContacts(md) {
  const out = [];
  for (const line of String(md).split("\n")) {
    const t = line.trim();
    if (!t.startsWith("|")) continue;
    const cells = t.replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
    if (cells.length < 3) continue;
    const number = normalizeNumber(cells[1]);
    if (number.length < 8) continue; // Kopfzeile, Trennzeile, leere Vorlage
    out.push({ name: cells[0], number, consent: /^ja$/i.test(cells[2]) });
  }
  return out;
}

export function findContact(contacts, number) {
  if (!number) return null;
  return contacts.find((c) => c.number === number) ?? null;
}

const dayKey = (now) => new Date(now).toLocaleDateString("sv-SE"); // YYYY-MM-DD, lokale Zeit

export function dailyLimit(state, now) {
  return DAILY_LIMIT;
}

/** { ok: true } | { ok: false, reason: "limit" | "gap", ... } */
export function checkSend(state, now) {
  const count = state.day === dayKey(now) ? state.count : 0;
  const limit = dailyLimit(state, now);
  if (count >= limit) {
    return { ok: false, reason: "limit", message: `Tageslimit erreicht (${count}/${limit})` };
  }
  const waitMs = (state.lastSend ?? 0) + MIN_GAP_MS - now;
  if (waitMs > 0) return { ok: false, reason: "gap", waitMs };
  return { ok: true };
}

export function recordSend(state, now) {
  const today = dayKey(now);
  if (!state.firstSend) state.firstSend = new Date(now).toISOString();
  state.count = state.day === today ? (state.count ?? 0) + 1 : 1;
  state.day = today;
  state.lastSend = now;
  return state;
}

export const needsIntro = (state, jid) => !(state.introduced ?? []).includes(jid);

export function markIntroduced(state, jid) {
  state.introduced = [...new Set([...(state.introduced ?? []), jid])];
  return state;
}
