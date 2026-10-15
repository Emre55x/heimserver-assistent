#!/bin/bash
# Bildschirm nach 60 s ausschalten, Tastendruck weckt ihn. Start: sudo bash setup-bildschirm.sh
set -e
if [ "$(id -u)" != 0 ]; then
  echo "Bitte mit sudo starten."
  exit 1
fi
G=/etc/default/grub
if grep -q 'consoleblank=' "$G"; then
  echo "consoleblank ist schon gesetzt:"
  grep GRUB_CMDLINE_LINUX_DEFAULT "$G"
  exit 0
fi
cp "$G" "$G.bak"
sed -i 's/^\(GRUB_CMDLINE_LINUX_DEFAULT="[^"]*\)"/\1 consoleblank=60"/' "$G"
grep GRUB_CMDLINE_LINUX_DEFAULT "$G"
update-grub
echo "Fertig. Nach 'sudo reboot' gilt es. Sicherung: $G.bak"
echo "Test ohne Neustart: setterm -blank 1 -powerdown 1"
