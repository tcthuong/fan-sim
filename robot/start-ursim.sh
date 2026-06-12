#!/bin/bash
# =====================================================================
#  Khoi dong URSim day du (PolyScope GUI + URControl RTDE) tren RunPod
# ---------------------------------------------------------------------
#  Kien truc: RunPod khong co Docker daemon, URControl la binary 32-bit.
#  Giai phap:
#    1) PolyScope (felix/java) start TRUOC - mo port 29919 (Dashboard)
#    2) URControl start SAU qua qemu-i386 + shim -> connect toi 29919
#    3) Robot len trang thai RUNNING -> RTDE + rtde_control kha dung
#  VNC GUI: x11vnc tren port 5900, noVNC tren port 6080 (browser)
# =====================================================================
set -u
ROOT=/root/.udocker/containers/b94e91f2-bfd0-3bb8-a65d-569a968f3137/ROOT
DYN=$ROOT/usr/local/urcontrol/dynlibs
SHIM=/root/mutexshim32.so
JAVA=$ROOT/usr/lib/jvm/jdk1.8.0_371/jre/bin/java
VER=5.25.2
ROBOT=${1:-UR5}
LOGDIR=/root/ursim-logs; mkdir -p $LOGDIR

ROBOT_DIR="$(cd "$(dirname "$0")" && pwd)"

# --- Symlinks ---
ln -sfn $ROOT/ursim /ursim
ln -sfn $ROOT/opt/urtool-3.0 /opt/urtool-3.0
mkdir -p /usr/local/urcontrol; ln -sfn $DYN /usr/local/urcontrol/dynlibs

# --- Config robot ---
ln -sf /ursim/.urcontrol/urcontrol.conf.$ROBOT /ursim/.urcontrol/urcontrol.conf 2>/dev/null
ln -sf /ursim/.urcontrol/safety.conf.$ROBOT   /ursim/.urcontrol/safety.conf   2>/dev/null

# --- Dung process cu ---
pkill -9 -f "qemu-i386-static /ursim/URControl" 2>/dev/null
pkill -9 -f "felix.jar" 2>/dev/null
pkill -9 x11vnc 2>/dev/null
for i in $(seq 1 8); do ss -ltn 2>/dev/null|grep -q ":30004" || break; sleep 1; done

# --- VNC: expose Xorg :10 qua port 5900 ---
if [ -n "${DISPLAY:-}" ] && [ "${DISPLAY}" = ":10.0" -o "${DISPLAY}" = ":10" ]; then
  x11vnc -bg -quiet -forever -shared \
    -display :10 -auth /root/.Xauthority \
    -rfbport 5900 -noxdamage \
    -logfile $LOGDIR/x11vnc.log 2>/dev/null
  echo "[*] x11vnc started (VNC port 5900, noVNC port 6080)"
fi

# --- BUOC 1: Start PolyScope (felix) TRUOC ---
echo "[*] Khoi dong PolyScope GUI ($ROBOT)..."
rm -rf /ursim/GUI/felix-cache 2>/dev/null
DISPLAY=${DISPLAY:-:10.0} XAUTHORITY=/root/.Xauthority \
  HOME=/ursim QEMU_LD_PREFIX=$ROOT \
  nohup $JAVA \
    -Duser.home=/ursim \
    -Dconfig.path=/ursim/.urcontrol \
    -DmockCybersecurityBackend=true \
    "-Djava.library.path=$ROOT/usr/lib/jni" \
    -Dorg.osgi.framework.storage.clean=onFirstInit \
    -jar /ursim/GUI/bin/felix.jar \
  > $LOGDIR/polyscope.log 2>&1 &
disown

# Cho Dashboard 29999 mo (felix khoi dong ~10-15s)
echo -n "[*] Cho PolyScope khoi dong"
for i in $(seq 1 30); do
  ss -ltn 2>/dev/null|grep -q ":29999" && break
  echo -n "."
  sleep 1
done
echo ""
if ! ss -ltn 2>/dev/null|grep -q ":29999"; then
  echo "[!] PolyScope khong khoi dong duoc - xem $LOGDIR/polyscope.log"
  exit 1
fi
echo "[OK] PolyScope dang chay (Dashboard 29999 mo)"

# --- BUOC 2: Start URControl SAU khi PolyScope da listen ---
echo "[*] Khoi dong URControl ($ROBOT) qua qemu-i386 + shim..."
export LD_LIBRARY_PATH=$DYN:/opt/urtool-3.0/lib:$ROOT/usr/lib/i386-linux-gnu:$ROOT/lib/i386-linux-gnu
nohup env HOME=/ursim LD_LIBRARY_PATH=$LD_LIBRARY_PATH QEMU_LD_PREFIX=$ROOT LD_PRELOAD=$SHIM \
  qemu-i386-static /ursim/URControl -m $VER -r > $LOGDIR/urcontrol.log 2>&1 &
disown

# Cho RTDE 30004 va Dashboard ket noi
echo -n "[*] Cho URControl khoi dong"
for i in $(seq 1 30); do
  ss -ltn 2>/dev/null|grep -q ":30004" && break
  echo -n "."
  sleep 1
done
echo ""

# --- BUOC 3: Power-on robot ---
sleep 3
MODE=$(printf "robotmode\n" | timeout 3 nc 127.0.0.1 29999 2>/dev/null | grep -i "Robotmode" | head -1)
echo "[*] Robot hien tai: $MODE"

if echo "$MODE" | grep -qi "POWER_OFF\|DISCONNECTED"; then
  printf "power on\n" | timeout 3 nc 127.0.0.1 29999 2>/dev/null | grep -v "^Connected" || true
  sleep 6
  printf "brake release\n" | timeout 3 nc 127.0.0.1 29999 2>/dev/null | grep -v "^Connected" || true
  sleep 5
fi

FINAL=$(printf "robotmode\n" | timeout 3 nc 127.0.0.1 29999 2>/dev/null | grep -i "Robotmode" | head -1)

echo "================================================================"
echo "  URSim day du. Trang thai: $FINAL"
echo "  RTDE: 127.0.0.1:30004  |  Dashboard: 127.0.0.1:29999"
echo "  VNC: port 5900  |  noVNC browser: port 6080"
echo ""
echo "  Dieu khien robot:"
echo "    python3 $ROBOT_DIR/control_ur3e.py"
echo ""
echo "  Dong bo Isaac Sim (GUI Script Editor):"
echo "    Dan noi dung $ROBOT_DIR/isaac_gui_sync.py vao Script Editor"
echo ""
echo "  Dung: bash $ROBOT_DIR/stop-ursim.sh"
echo "================================================================"
