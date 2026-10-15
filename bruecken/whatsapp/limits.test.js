import test from "node:test";
import assert from "node:assert/strict";
import * as L from "./limits.js";

const NOW = Date.parse("2026-10-20T10:00:00");

test("Nummern werden normalisiert", () => {
  assert.equal(L.normalizeNumber("+49 176 123 456 78"), "4917612345678");
  assert.equal(L.normalizeNumber("0176 123 456 78"), "4917612345678");
  assert.equal(L.normalizeNumber("0049176 1234 5678"), "4917612345678");
});

test("kontakte.md wird gelesen, Kopf und leere Vorlage ignoriert", () => {
  const md = `# Kontakte
| Name | Nummer (lokal) | Einwilligung | Was darf der Assistent sagen | Notizen |
|---|---|---|---|---|
| | | nein | | |
| Müller GmbH | +49 711 1234567 | ja | Termine | Kunde |
| Max | 0176 12345678 | nein | | |
`;
  const c = L.parseContacts(md);
  assert.equal(c.length, 2);
  assert.deepEqual(c[0], { name: "Müller GmbH", number: "497111234567", consent: true });
  assert.equal(c[1].consent, false);
  assert.equal(L.findContact(c, "4917612345678").name, "Max");
  assert.equal(L.findContact(c, "123"), null);
  assert.equal(L.findContact(c, null), null);
});

test("Tageslimit: 30 pro Tag, am nächsten Tag wieder frei", () => {
  const s = {};
  for (let i = 0; i < 30; i++) {
    const t = NOW + i * 60_000;
    assert.equal(L.checkSend(s, t).ok, true, `Nachricht ${i + 1}`);
    L.recordSend(s, t);
  }
  const blocked = L.checkSend(s, NOW + 40 * 60_000);
  assert.equal(blocked.ok, false);
  assert.equal(blocked.reason, "limit");

  const later = NOW + 86_400_000; // nächster Tag
  assert.equal(L.dailyLimit(s, later), 30);
  assert.equal(L.checkSend(s, later).ok, true);
});

test("Mindestabstand 45 Sekunden", () => {
  const s = {};
  L.recordSend(s, NOW);
  const r = L.checkSend(s, NOW + 10_000);
  assert.equal(r.ok, false);
  assert.equal(r.reason, "gap");
  assert.equal(r.waitMs, 35_000);
  assert.equal(L.checkSend(s, NOW + 45_000).ok, true);
});

test("Zähler setzt sich am nächsten Tag zurück", () => {
  const s = {};
  for (let i = 0; i < 5; i++) L.recordSend(s, NOW + i * 60_000);
  assert.equal(L.checkSend(s, NOW + 86_400_000).ok, true);
});

test("KI-Hinweis nur einmal pro Kontakt", () => {
  const s = {};
  assert.equal(L.needsIntro(s, "a@s.whatsapp.net"), true);
  L.markIntroduced(s, "a@s.whatsapp.net");
  assert.equal(L.needsIntro(s, "a@s.whatsapp.net"), false);
  assert.equal(L.needsIntro(s, "b@s.whatsapp.net"), true);
});
