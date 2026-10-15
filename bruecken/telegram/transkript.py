"""Sprachnachricht -> Text, lokal auf dem Server (faster-whisper, keine Cloud).

Läuft in eigener Umgebung (siehe README), Aufruf: <venv>/bin/python transkript.py datei.ogg
Gibt nur den erkannten Text auf stdout aus.
"""
import os
import sys

from faster_whisper import WhisperModel


def main():
    model = WhisperModel(os.environ.get("WHISPER_MODEL", "small"), device="cpu", compute_type="int8")
    segments, _ = model.transcribe(sys.argv[1], language="de", beam_size=1, vad_filter=True)
    print(" ".join(s.text.strip() for s in segments).strip())


if __name__ == "__main__":
    main()
