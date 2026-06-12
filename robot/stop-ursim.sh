#!/bin/bash
# Dung URSim (URControl + PolyScope GUI + VNC)
for pat in "qemu-i386-static /ursim/URControl" "felix.jar" "x11vnc"; do
  pkill -9 -f "$pat" 2>/dev/null
done
echo "Da dung URSim (URControl + PolyScope + VNC)."
