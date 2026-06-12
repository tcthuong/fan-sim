#!/usr/bin/env python3
# =====================================================================
#  Dong bo URSim -> Isaac Sim GUI (Script Editor)
#
#  Cach dung:
#    1) Mo Isaac Sim GUI, vao Window > Script Editor
#    2) Mo file nay, bam Run (hoac copy-paste noi dung)
#    3) Robot trong viewport se di chuyen theo URSim realtime
#
#  De dung dong bo:
#    Goi stop_sync() trong Script Editor
#
#  Yeu cau:
#    - URSim dang chay (bash fan-sim/robot/start-ursim.sh UR3)
#    - Stage main.usda da load (script tu dong load neu chua co)
# =====================================================================
import asyncio, math
import omni.usd, omni.kit.app, omni.timeline
import carb

STAGE_USD = "/root/Downloads/fan-sim/restored/proj/main.usda"
BASE      = "/World/servo_indexed_belt_conveyor/Arm_Robot_02/ur3e_01"
JOINTS    = ["shoulder_pan_joint","shoulder_lift_joint","elbow_joint",
             "wrist_1_joint","wrist_2_joint","wrist_3_joint"]
URSIM_IP  = "127.0.0.1"

_sub    = None
_rtde_r = None

async def _setup():
    global _sub, _rtde_r

    # 1) Mo stage (neu chua load)
    ctx = omni.usd.get_context()
    current = ctx.get_stage()
    if not current or not current.GetPrimAtPath(BASE).IsValid():
        print("[*] Mo stage ...")
        await ctx.open_stage_async(STAGE_USD)
        print("[OK] Stage loaded")

    app = omni.kit.app.get_app()
    tl  = omni.timeline.get_timeline_interface()
    stage = omni.usd.get_context().get_stage()

    # 2) Set stiffness TRUOC khi play (physics doc USD luc khoi tao)
    for jname in JOINTS:
        p = stage.GetPrimAtPath(f"{BASE}/joints/{jname}")
        if not p.IsValid():
            print(f"[!] Khong tim thay joint: {jname}")
            continue
        p.GetAttribute("drive:angular:physics:stiffness").Set(1e8)
        p.GetAttribute("drive:angular:physics:damping").Set(1e5)
        p.GetAttribute("drive:angular:physics:maxForce").Set(1e10)
    print("[OK] Drive stiffness set (snap mode)")

    # 3) Play de khoi tao physics
    if not tl.is_playing():
        tl.play()
    for _ in range(10):
        await app.next_update_async()

    # 4) Ket noi RTDE
    import rtde_receive
    _rtde_r = rtde_receive.RTDEReceiveInterface(URSIM_IP)
    print(f"[RTDE] connected: {_rtde_r.isConnected()}")

    # 5) Set vi tri ban dau
    if _rtde_r.isConnected():
        q0 = _rtde_r.getActualQ()
        for i, jname in enumerate(JOINTS):
            p = stage.GetPrimAtPath(f"{BASE}/joints/{jname}")
            if p.IsValid():
                p.GetAttribute("drive:angular:physics:targetPosition").Set(math.degrees(q0[i]))
        print(f"[*] Vi tri ban dau (deg): {[round(math.degrees(x),1) for x in q0]}")
        for _ in range(5):
            await app.next_update_async()

    # 6) Per-frame callback: cap nhat targetPosition (don vi DO) moi frame
    def on_update(e: carb.events.IEvent):
        if not (_rtde_r and _rtde_r.isConnected()):
            return
        q = _rtde_r.getActualQ()
        s = omni.usd.get_context().get_stage()
        for i, jname in enumerate(JOINTS):
            p = s.GetPrimAtPath(f"{BASE}/joints/{jname}")
            if p.IsValid():
                p.GetAttribute("drive:angular:physics:targetPosition").Set(math.degrees(q[i]))

    _sub = app.get_update_event_stream().create_subscription_to_pop(
        on_update, name="ursim_rtde_sync"
    )
    print("[*] Sync dang chay. De dung: goi stop_sync()")

def stop_sync():
    global _sub, _rtde_r
    if _sub:
        _sub.unsubscribe()
        _sub = None
    if _rtde_r:
        _rtde_r.disconnect()
        _rtde_r = None
    print("[*] Sync da dung.")

asyncio.ensure_future(_setup())
