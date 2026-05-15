from __future__ import annotations

import asyncio
import gc

import omni.usd
from omni.kit.app import get_app
from pxr import UsdGeom


FLOW_PATH = "/World/CAE/FlowSimulation_L0"
DATASET_PATH = "/World/FanCase/VTKUnstructuredGrid"
PENDING_FLOW_PATH = "/World/CAE/FlowSimulation_L0__pending"


def _find_extension():
    for obj in gc.get_objects():
        if obj.__class__.__name__ == "FanSimExtension":
            return obj
    return None


def _visible(stage, path: str) -> bool:
    prim = stage.GetPrimAtPath(path)
    if not prim.IsValid() or not prim.IsA(UsdGeom.Imageable):
        return False
    attr = UsdGeom.Imageable(prim).GetVisibilityAttr()
    return not attr.HasAuthoredValue() or attr.Get() != UsdGeom.Tokens.invisible


async def main() -> None:
    app = get_app()
    extension = None
    for _ in range(240):
        extension = _find_extension()
        stage = omni.usd.get_context().get_stage()
        if (
            extension is not None
            and stage is not None
            and stage.GetPrimAtPath(FLOW_PATH).IsValid()
            and stage.GetPrimAtPath(DATASET_PATH).IsValid()
        ):
            break
        await app.next_update_async()
        await asyncio.sleep(0.25)

    stage = omni.usd.get_context().get_stage()
    if extension is None or stage is None:
        print("FAN_SIM_SLIDER_VERIFY_FAILED reason=extension_or_stage_missing", flush=True)
        return

    before_valid = stage.GetPrimAtPath(FLOW_PATH).IsValid()
    before_visible = _visible(stage, FLOW_PATH)
    current_rpm = extension._rpm_model.get_value_as_float()
    target_rpm = 1039.0 if current_rpm < 900.0 else 600.0
    extension._rpm_model.set_value(target_rpm)

    await asyncio.sleep(1.0)
    await app.next_update_async()
    during_active_valid = stage.GetPrimAtPath(FLOW_PATH).IsValid()
    during_active_visible = _visible(stage, FLOW_PATH)
    during_pending_seen = stage.GetPrimAtPath(PENDING_FLOW_PATH).IsValid()

    expected_status = f"Loaded RPM {target_rpm:g}"
    for _ in range(480):
        status_text = getattr(getattr(extension, "_status", None), "text", "")
        if (
            expected_status in status_text
            and not getattr(extension, "_is_predicting", False)
            and stage.GetPrimAtPath(FLOW_PATH).IsValid()
            and stage.GetPrimAtPath(DATASET_PATH).IsValid()
        ):
            break
        await app.next_update_async()
        await asyncio.sleep(0.25)

    after_valid = stage.GetPrimAtPath(FLOW_PATH).IsValid()
    after_visible = _visible(stage, FLOW_PATH)
    pending_leftover = stage.GetPrimAtPath(PENDING_FLOW_PATH).IsValid()
    loaded = getattr(extension, "_dataset_path", "")
    status = getattr(getattr(extension, "_status", None), "text", "")

    print(
        "FAN_SIM_SLIDER_VERIFY "
        f"before_valid={before_valid} before_visible={before_visible} "
        f"during_active_valid={during_active_valid} during_active_visible={during_active_visible} "
        f"during_pending_seen={during_pending_seen} "
        f"after_valid={after_valid} after_visible={after_visible} "
        f"pending_leftover={pending_leftover} target_rpm={target_rpm:g} "
        f"dataset={loaded} status={status}",
        flush=True,
    )


asyncio.ensure_future(main())
