#!/usr/bin/env bash
# Startet Claude Remote Control im Assistenten-Ordner (Auftrag 8).
# Beim ersten Mal von Hand ausführen, ggf. Anmeldung bestätigen.
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"
exec claude remote-control --name "Heimserver Assistent" --permission-mode default
