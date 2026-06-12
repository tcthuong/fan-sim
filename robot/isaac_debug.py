#!/usr/bin/env python3
# =====================================================================
#  Debug helper — dan vao Isaac Sim Script Editor de kiem tra trang thai
# =====================================================================
import omni.usd, omni.timeline
import numpy as np

PRIM_ROOT  = "/World/servo_indexed_belt_conveyor/Arm_Robot_02/ur3e_01/root_joint"
PRIM_BASE  = "/World/servo_indexed_belt_conveyor/Arm_Robot_02/ur3e_01"
URSIM_IP   = "127.0.0.1"

stage = omni.usd.get_context().get_stage()
print("[OK] Stage:", stage.GetRootLayer().identifier if stage else "NONE")

tl = omni.timeline.get_timeline_interface()
print("[*] Timeline playing:", tl.is_playing(), "| stopped:", tl.is_stopped())

p = stage.GetPrimAtPath(PRIM_ROOT) if stage else None
print("[*] root_joint:", "FOUND" if (p and p.IsValid()) else "NOT FOUND")

p2 = stage.GetPrimAtPath(PRIM_BASE) if stage else None
if p2 and p2.IsValid():
    children = [c.GetName() for c in p2.GetChildren()]
    print("[*] ur3e_01 children:", children)

from isaacsim.core.prims import SingleArticulation
try:
    r = SingleArticulation(prim_path=PRIM_ROOT, name="dbg_arm")
    r.initialize()
    q = r.get_joint_positions()
    print("[OK] DOF:", r.dof_names)
    print("[OK] Positions (deg):", [round(float(np.degrees(x)),1) for x in q])
except Exception as e:
    print("[FAIL] SingleArticulation:", e)

try:
    import rtde_receive
    rr = rtde_receive.RTDEReceiveInterface(URSIM_IP)
    print("[OK] RTDE connected:", rr.isConnected())
    if rr.isConnected():
        q2 = rr.getActualQ()
        print("     URSim joints (deg):", [round(float(np.degrees(x)),1) for x in q2])
    rr.disconnect()
except Exception as e:
    print("[FAIL] RTDE:", e)
