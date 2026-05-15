from __future__ import annotations

import asyncio

import omni.ui as ui
import omni.timeline
import omni.usd
from omni.kit.app import get_app
from pxr import UsdGeom


STREAMLINES_PATH = "/World/CAE/FanSimStreamlines"
FLOW_PATH = "/World/CAE/FlowSimulation_L0"


async def main() -> None:
    app = get_app()
    for _ in range(360):
        stage = omni.usd.get_context().get_stage()
        if (
            stage is not None
            and stage.GetPrimAtPath(FLOW_PATH).IsValid()
            and stage.GetPrimAtPath(f"{FLOW_PATH}/DataSetInjector").IsValid()
        ):
            break
        await app.next_update_async()
        await asyncio.sleep(0.25)
    for _ in range(60):
        await app.next_update_async()
        await asyncio.sleep(0.25)
    stage = omni.usd.get_context().get_stage()
    if stage is None:
        print("FAN_SIM_FLOW_ONLY_STAGE_MISSING", flush=True)
        return

    window = ui.Workspace.get_window("Fan-Sim")
    if window is not None:
        window.visible = False

    for _ in range(80):
        streamlines = stage.GetPrimAtPath(STREAMLINES_PATH)
        if streamlines.IsValid() and streamlines.IsA(UsdGeom.Imageable):
            UsdGeom.Imageable(streamlines).CreateVisibilityAttr().Set(UsdGeom.Tokens.invisible)

        flow = stage.GetPrimAtPath(FLOW_PATH)
        if flow.IsValid() and flow.IsA(UsdGeom.Imageable):
            UsdGeom.Imageable(flow).CreateVisibilityAttr().Set(UsdGeom.Tokens.inherited)

        await app.next_update_async()
        await asyncio.sleep(0.1)

    timeline = omni.timeline.get_timeline_interface()
    timeline.play()
    print("FAN_SIM_FLOW_ONLY_READY streamlines_hidden=true flow_visible=true", flush=True)


asyncio.ensure_future(main())
