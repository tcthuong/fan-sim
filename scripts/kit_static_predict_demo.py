from __future__ import annotations

import asyncio
import json
from pathlib import Path
import urllib.request

import omni.usd
from omni.cae.data.commands import execute_command
from omni.cae.importer.vtk import import_to_stage
from omni.cae.schema import cae
from omni.cae.schema import viz as cae_viz
from omni.kit.app import get_app
from pxr import Gf, Sdf, Usd, UsdGeom, UsdLux, UsdShade


SERVICE_URL = "http://127.0.0.1:8765"
DATASET_ROOT_PATH = "/World/CAE/FanSimPrediction"
FAN_MESH_PATH = "/World/CAE/FanSimFanMesh"
SURFACE_PATH = "/World/CAE/FanSimSurface"
STREAMLINES_PATH = "/World/CAE/FanSimStreamlines"
STREAMLINE_SEEDS_PATH = "/World/CAE/FanSimStreamlineSeeds"
FLOW_PATH = "/World/CAE/FanSimFlow"
FLOW_DATASET_EMITTER_PATH = "/World/CAE/FanSimFlow/DatasetInjector"
STREAMLINE_SEED_TRANSLATION = [0.0, 0.0, 0.0]
STREAMLINE_SEED_SCALE = [0.075, 0.075, 0.03]


def post_predict() -> dict:
    payload = {
        "case_id": "kit_static_demo",
        "rpm": 1500,
        "outlet_pressure": 0,
        "outputs": ["vtu", "usd", "streamlines", "particles"],
    }
    request = urllib.request.Request(
        f"{SERVICE_URL}/predict",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        return json.loads(response.read().decode("utf-8"))


def kit_path(path: str | None) -> str:
    if not path:
        return ""
    normalized = path.replace("\\", "/")
    if normalized.startswith("/mnt/") and len(normalized) > 6 and normalized[5].isalpha():
        return f"{normalized[5].upper()}:{normalized[6:]}"
    return Path(normalized).as_posix()


def ensure_world(stage: Usd.Stage) -> None:
    if not stage.GetPrimAtPath("/World").IsValid():
        world = UsdGeom.Xform.Define(stage, "/World")
        stage.SetDefaultPrim(world.GetPrim())
    if not stage.GetPrimAtPath("/World/CAE").IsValid():
        UsdGeom.Xform.Define(stage, "/World/CAE")


def find_dataset_prim(root_prim: Usd.Prim) -> Usd.Prim | None:
    for prim in Usd.PrimRange(root_prim):
        if prim.IsA(cae.DataSet):
            return prim
    return None


def field_targets(stage: Usd.Stage, dataset_path: str, field_name: str) -> list[Sdf.Path]:
    dataset_prim = stage.GetPrimAtPath(dataset_path)
    relationship = dataset_prim.GetRelationship(f"field:{field_name}")
    if relationship and relationship.IsValid():
        return list(relationship.GetTargets())
    root_path = Sdf.Path(dataset_path).GetParentPath()
    for scope_name in ("PointData", "CellData"):
        candidate = root_path.AppendChild(scope_name).AppendChild(field_name)
        if stage.GetPrimAtPath(candidate).IsValid():
            return [candidate]
    return []


def set_field_targets(stage: Usd.Stage, prim: Usd.Prim, instance_name: str, dataset_path: str, field_name: str) -> None:
    targets = field_targets(stage, dataset_path, field_name)
    if not targets:
        raise RuntimeError(f"Field {field_name!r} was not found under {dataset_path}")
    cae_viz.FieldSelectionAPI(prim, instance_name).GetTargetRel().SetTargets(targets)


def set_fixed_color_range(stage: Usd.Stage, prim: Usd.Prim, color_range: tuple[float, float] | None) -> None:
    if color_range is None:
        return
    if not prim.HasAPI(cae_viz.RescaleRangeAPI, "colors"):
        return
    rescale_api = cae_viz.RescaleRangeAPI(prim, "colors")
    rescale_api.GetRescaleModeAttr().Set(cae_viz.Tokens.disable)
    for target in rescale_api.GetIncludesRel().GetForwardedTargets():
        if not target.IsPrimPropertyPath():
            continue
        attr = stage.GetAttributeAtPath(target)
        if attr and attr.IsValid():
            attr.Set(color_range)


def reference_fan_mesh(stage: Usd.Stage, fan_mesh_usd: str) -> bool:
    if not fan_mesh_usd or not Path(fan_mesh_usd).exists():
        return False
    prim = UsdGeom.Xform.Define(stage, FAN_MESH_PATH).GetPrim()
    refs = prim.GetReferences()
    refs.ClearReferences()
    refs.AddReference(Path(fan_mesh_usd).as_posix(), "/OpenFOAMCase")
    style_fan_mesh(stage)
    return True


def style_fan_mesh(stage: Usd.Stage) -> None:
    mesh_prim = stage.GetPrimAtPath(f"{FAN_MESH_PATH}/FanMesh")
    if not mesh_prim.IsValid():
        return

    material = UsdShade.Material.Define(stage, "/World/Looks/FanSimFanMaterial")
    shader = UsdShade.Shader.Define(stage, "/World/Looks/FanSimFanMaterial/PreviewSurface")
    shader.CreateIdAttr("UsdPreviewSurface")
    shader.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(0.95, 0.62, 0.20))
    shader.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(0.42)
    material.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), "surface")
    UsdShade.MaterialBindingAPI(mesh_prim).Bind(material)

    mesh = UsdGeom.Mesh(mesh_prim)
    mesh.CreateDoubleSidedAttr(True)
    mesh.CreateDisplayColorPrimvar(UsdGeom.Tokens.constant).Set([Gf.Vec3f(0.95, 0.62, 0.20)])


def ensure_lighting(stage: Usd.Stage) -> None:
    dome = UsdLux.DomeLight.Define(stage, "/World/FanSimDomeLight")
    dome.CreateIntensityAttr(650.0)
    distant = UsdLux.DistantLight.Define(stage, "/World/FanSimKeyLight")
    distant.CreateIntensityAttr(3500.0)
    UsdGeom.XformCommonAPI(distant.GetPrim()).SetRotate((-45.0, 0.0, -35.0), UsdGeom.XformCommonAPI.RotationOrderXYZ)


async def wait_updates(cycles: int = 20) -> None:
    for _ in range(cycles):
        await get_app().next_update_async()
        await asyncio.sleep(0.01)


async def frame_prim(stage: Usd.Stage, prim_path: str) -> None:
    try:
        from omni.kit.viewport.utility import get_active_viewport
    except Exception:
        return
    if not stage.GetPrimAtPath(prim_path).IsValid():
        return
    viewport = get_active_viewport()
    if viewport is None:
        return
    omni.usd.get_context().get_selection().set_selected_prim_paths([prim_path], True)
    await execute_command("FramePrimsCommand", prim_to_move=viewport.camera_path, prims_to_frame=[prim_path], zoom=0.9)


async def set_demo_camera(stage: Usd.Stage) -> None:
    try:
        from omni.kit.viewport.utility import get_active_viewport
    except Exception:
        return

    camera = UsdGeom.Camera.Define(stage, "/World/FanSimCamera")
    camera.CreateClippingRangeAttr(Gf.Vec2f(0.001, 100.0))
    camera.CreateFocalLengthAttr(38.0)

    view = Gf.Matrix4d(1.0)
    view.SetLookAt(Gf.Vec3d(0.48, -0.82, 0.36), Gf.Vec3d(0.0, 0.0, 0.0), Gf.Vec3d(0.0, 0.0, 1.0))
    xformable = UsdGeom.Xformable(camera.GetPrim())
    xformable.ClearXformOpOrder()
    xformable.AddTransformOp().Set(view.GetInverse())

    viewport = get_active_viewport()
    if viewport is not None:
        viewport.camera_path = str(camera.GetPath())


async def main() -> None:
    print("FAN_SIM_AUTOPREDICT_START", flush=True)
    body = await asyncio.to_thread(post_predict)
    prediction_vtu = kit_path(body.get("prediction_vtu"))
    fan_mesh_usd = kit_path(body.get("fan_mesh_usd"))
    print(f"FAN_SIM_AUTOPREDICT_VTU={prediction_vtu}", flush=True)
    print(f"FAN_SIM_AUTOPREDICT_FAN_MESH={fan_mesh_usd}", flush=True)

    context = omni.usd.get_context()
    await context.new_stage_async()
    stage = context.get_stage()
    ensure_world(stage)
    ensure_lighting(stage)

    has_fan_mesh = reference_fan_mesh(stage, fan_mesh_usd)
    root_prim = await import_to_stage(prediction_vtu, DATASET_ROOT_PATH)
    dataset_prim = find_dataset_prim(root_prim)
    if dataset_prim is None:
        raise RuntimeError(f"No CAE dataset prim was imported from {prediction_vtu}")
    dataset_path = str(dataset_prim.GetPath())
    print(f"FAN_SIM_AUTOPREDICT_DATASET={dataset_path}", flush=True)

    await execute_command("CreateCaeVizFaces", dataset_path=dataset_path, prim_path=SURFACE_PATH)
    surface_prim = stage.GetPrimAtPath(SURFACE_PATH)
    set_field_targets(stage, surface_prim, "colors", dataset_path, "velocity_magnitude")
    set_fixed_color_range(stage, surface_prim, None)

    await execute_command("CreateCaeVizStreamlines", dataset_path=dataset_path, prim_path=STREAMLINES_PATH, type="standard")
    await execute_command(
        "CreateCaeVizMeshPrim",
        prim_type="UnitSphere",
        prim_path=STREAMLINE_SEEDS_PATH,
        resolution=64,
    )
    await execute_command(
        "TransformPrimSRT",
        path=STREAMLINE_SEEDS_PATH,
        new_translation=STREAMLINE_SEED_TRANSLATION,
        new_scale=STREAMLINE_SEED_SCALE,
    )
    streamlines_prim = stage.GetPrimAtPath(STREAMLINES_PATH)
    seed_prim = stage.GetPrimAtPath(STREAMLINE_SEEDS_PATH)
    streamlines_api = cae_viz.StreamlinesAPI(streamlines_prim)
    streamlines_api.GetMinStepSizeAttr().Set(0.0008)
    streamlines_api.GetInitialStepSizeAttr().Set(0.006)
    streamlines_api.GetMaxStepSizeAttr().Set(0.024)
    streamlines_api.GetMaxStepsAttr().Set(2200)
    streamlines_api.GetDirectionAttr().Set(cae_viz.Tokens.both)
    streamlines_api.GetThresholdAttr().Set(1e-8)
    streamlines_api.GetToleranceAttr().Set(5e-5)
    streamlines_api.GetWidthAttr().Set(0.0018)
    cae_viz.DatasetSelectionAPI(streamlines_prim, "seeds").GetTargetRel().SetTargets([seed_prim.GetPath()])
    set_field_targets(stage, streamlines_prim, "velocities", dataset_path, "U_pred")
    set_field_targets(stage, streamlines_prim, "colors", dataset_path, "velocity_magnitude")
    set_fixed_color_range(stage, streamlines_prim, None)
    UsdGeom.Imageable(seed_prim).CreateVisibilityAttr().Set(UsdGeom.Tokens.invisible)

    await execute_command("CreateCaeVizFlowEnvironment", prim_path=FLOW_PATH, layer_number=0)
    flow_prim = stage.GetPrimAtPath(FLOW_PATH)
    await execute_command(
        "CreateCaeVizFlowDataSetEmitter",
        dataset_path=dataset_path,
        prim_path=FLOW_DATASET_EMITTER_PATH,
        layer_number=0,
        simulation_prim=flow_prim,
    )
    flow_emitter = stage.GetPrimAtPath(FLOW_DATASET_EMITTER_PATH)
    voxel_api = cae_viz.DatasetVoxelizationAPI(flow_emitter, "source")
    voxel_api.CreateVoxelSizeModeAttr().Set(cae_viz.Tokens.maxResolution)
    voxel_api.CreateMaxResolutionAttr().Set(192)
    voxel_api.CreateInflateBoundsAttr().Set(4.0)
    set_field_targets(stage, flow_emitter, "velocities", dataset_path, "U_pred")
    set_field_targets(stage, flow_emitter, "temperatures", dataset_path, "velocity_magnitude")

    await wait_updates(80)
    await frame_prim(stage, FAN_MESH_PATH if has_fan_mesh else SURFACE_PATH)
    await set_demo_camera(stage)
    await wait_updates(20)
    print("FAN_SIM_AUTOPREDICT_DONE", flush=True)


asyncio.ensure_future(main())
