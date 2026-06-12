#!/usr/bin/env python3
# =====================================================================
#  Dong bo URSim (RTDE) -> Isaac Sim 6.0  [headless standalone]
#
#  Chay trong terminal rieng (TAO RA INSTANCE HEADLESS MOI):
#    cd /root/isaacsim
#    OMNI_KIT_ALLOW_ROOT=1 ./python.sh \
#      /root/Downloads/fan-sim/robot/sync_ursim_isaac.py
#
#  Luu y: script nay chay Isaac Sim headless rieng biet — KHONG phai
#  cai dang hien thi tren VNC. De xem trong GUI hien tai, dung
#  isaac_gui_sync.py (dan vao Script Editor).
# =====================================================================
import numpy as np

from isaacsim import SimulationApp
simulation_app = SimulationApp({"headless": True})

from isaacsim.core.api import World
from isaacsim.core.utils.stage import open_stage
from isaacsim.core.prims import SingleArticulation

import rtde_receive

URSIM_IP  = "127.0.0.1"
STAGE_USD = "/root/Downloads/fan-sim/restored/proj/main.usda"

# Payload ur3e.usd load vao ur3e_01: root prim 'ur3e' merge voi 'ur3e_01'
# -> ArticulationRoot (root_joint) nam tai ur3e_01/root_joint
PRIM_PATH = "/World/servo_indexed_belt_conveyor/Arm_Robot_02/ur3e_01/root_joint"

print(f"[*] Mo stage: {STAGE_USD}")
open_stage(usd_path=STAGE_USD)

world = World(stage_units_in_meters=0.01)  # main.usda dung don vi cm
robot = SingleArticulation(prim_path=PRIM_PATH, name="ur3e_arm")
world.scene.add(robot)
world.reset()
robot.initialize()

print(f"[Isaac] DOF ({len(robot.dof_names)}): {robot.dof_names}")

print(f"[*] Ket noi RTDE {URSIM_IP}:30004 ...")
rtde_r = rtde_receive.RTDEReceiveInterface(URSIM_IP)
print(f"[RTDE] connected: {rtde_r.isConnected()}")

print("[*] Bat dau dong bo URSim -> Isaac Sim. Ctrl-C de dung.")
try:
    while simulation_app.is_running():
        if rtde_r.isConnected():
            q = np.asarray(rtde_r.getActualQ(), dtype=np.float32)
            robot.set_joint_positions(q)
        world.step(render=False)
except KeyboardInterrupt:
    pass
finally:
    rtde_r.disconnect()
    simulation_app.close()
    print("[*] Da dung.")
