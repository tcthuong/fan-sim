#!/usr/bin/env python3
# =====================================================================
#  Dieu khien UR3e qua RTDE — moveJ / moveL
#
#  Yeu cau: URSim phai dang RUNNING truoc.
#    bash fan-sim/robot/start-ursim.sh UR3
#
#  Chay:
#    python3 fan-sim/robot/control_ur3e.py
#
#  Hoac voi Python cua Isaac Sim:
#    cd /root/isaacsim && OMNI_KIT_ALLOW_ROOT=1 \
#      ./python.sh /root/Downloads/fan-sim/robot/control_ur3e.py
# =====================================================================
import time
import math
import rtde_receive
import rtde_control

IP = "127.0.0.1"

print("[*] Ket noi RTDE ...")
rtde_r = rtde_receive.RTDEReceiveInterface(IP)
rtde_c = rtde_control.RTDEControlInterface(IP)
print(f"    receive: {rtde_r.isConnected()},  control: {rtde_c.isConnected()}")

def print_joints(label=""):
    q = rtde_r.getActualQ()
    deg = [round(math.degrees(x), 1) for x in q]
    print(f"  [{label}] joints (deg): {deg}")

# ---- Cac tu the mau (don vi rad) ----
HOME   = [0,       -1.5707,  0,       -1.5707,  0,       0]
PICK   = [0,       -1.2,     1.0,     -1.3707,  0,       0]
PLACE  = [1.5707,  -1.2,     1.0,     -1.3707,  0,       0]
SPEED  = 0.5   # rad/s
ACCEL  = 0.5   # rad/s^2

def movej(joints, speed=SPEED, accel=ACCEL):
    if not rtde_c.isConnected():
        rtde_c.reconnect()
    if not rtde_c.isProgramRunning():
        rtde_c.reuploadScript()
    return rtde_c.moveJ(joints, speed, accel)

print_joints("ban dau")

print("\n[1] Ve Home ...")
movej(HOME)
print_joints("home")

print("\n[2] Di toi PICK ...")
movej(PICK)
print_joints("pick")

print("\n[3] Di toi PLACE ...")
movej(PLACE)
print_joints("place")

print("\n[4] Ve Home ...")
movej(HOME)
print_joints("home lai")

# ---- Vi du moveL (Cartesian) ----
# tcp = rtde_r.getActualTCPPose()   # [x, y, z, rx, ry, rz]
# tcp[2] += 0.05                    # tinh tien 5cm theo Z
# rtde_c.moveL(tcp, speed=0.1, acceleration=0.5)

rtde_c.disconnect()
rtde_r.disconnect()
print("\n[*] Xong.")
