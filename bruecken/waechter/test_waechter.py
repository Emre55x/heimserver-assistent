"""Tests für den Wächter mit Attrappen (kein Netz, kein systemd)."""
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

TMP = Path(tempfile.mkdtemp())
(TMP / "state").mkdir()
(TMP / ".env").write_text("TELEGRAM_BOT_TOKEN=123:SECRET\nTELEGRAM_OWNER_ID=42\nWHATSAPP_ENABLED=1\n")
BAT = TMP / "bat"
BAT.mkdir()
os.environ.update(BRIDGE_ROOT=str(TMP), WAECHTER_BAT=str(BAT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import waechter  # noqa: E402


class WaechterTest(unittest.TestCase):
    def setUp(self):
        for f in (TMP / "state").glob("*"):
            f.unlink()
        self.sent = []
        self.net = True
        self.active = {"assistent-telegram": True, "assistent-whatsapp": True}
        (BAT / "status").write_text("Charging")
        (BAT / "capacity").write_text("80")
        self.wa("open")
        patches = [
            mock.patch.object(waechter, "send", lambda env, text: self.sent.append(text)),
            mock.patch.object(waechter, "online", lambda: self.net),
            mock.patch.object(waechter, "service_active", lambda s: self.active[s]),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def wa(self, conn, ago=0):
        (TMP / "state" / "wa_status.json").write_text(
            json.dumps({"connection": conn, "ts": (time.time() - ago) * 1000}))

    def test_alles_ok_keine_meldung(self):
        waechter.main()
        self.assertEqual(self.sent, [])

    def test_dienst_aus_wird_einmal_gemeldet_und_wieder_ok(self):
        self.active["assistent-telegram"] = False
        waechter.main()
        waechter.main()
        self.assertEqual(len(self.sent), 1)
        self.assertIn("assistent-telegram", self.sent[0])
        self.active["assistent-telegram"] = True
        waechter.main()
        self.assertIn("Wieder ok", self.sent[1])

    def test_whatsapp_kurz_getrennt_ist_ok_lange_nicht(self):
        self.wa("close", ago=60)
        waechter.main()
        self.assertEqual(self.sent, [])
        self.wa("qr", ago=3600)
        waechter.main()
        self.assertIn("WhatsApp nicht verbunden", self.sent[0])

    def test_akku_ohne_netzteil(self):
        (BAT / "status").write_text("Discharging")
        (BAT / "capacity").write_text("20")
        waechter.main()
        self.assertIn("auf Akku", self.sent[0])
        self.assertIn("nur noch 20", self.sent[0])

    def test_internet_weg_wird_danach_gemeldet(self):
        self.net = False
        waechter.main()
        self.assertEqual(self.sent, [])
        st = json.loads((TMP / "state" / "waechter.json").read_text())
        st["offline_since"] -= 20 * 60
        (TMP / "state" / "waechter.json").write_text(json.dumps(st))
        self.net = True
        waechter.main()
        self.assertIn("Internet war ca. 20 Min weg", self.sent[0])


if __name__ == "__main__":
    unittest.main()
