from __future__ import annotations

import asyncio
from pathlib import Path
import traceback

import omni.timeline
import omni.usd
from omni.kit.app import get_app
from pxr import Gf, Sdf, Usd, UsdGeom, UsdLux, UsdShade


VTU_PATH = Path(
    "D:/nvidia/fan-sim/runs/analysis/"
    "fan_mesh_streamlines_recheck_20260514/exporter_full_topology_smoke/prediction_preview.vtu"
)
FAN_MESH_USD = Path(
    "D:/nvidia/fan-sim/runs/analysis/"
    "fan_mesh_streamlines_recheck_20260514/exporter_full_topology_smoke/fan_mesh.usda"
)


def _find_dataset_prim(root: Usd.Prim):
    from omni.cae.schema import cae

    for prim in Usd.PrimRange(root):
        if prim.IsA(cae.DataSet):
            return prim
    return None


def _field_targets(stage: Usd.Stage, dataset_path: str, field_name: str) -> list[Sdf.Path]:
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


async def _wait_updates(count: int) -> None:
    app = get_app()
    for _ in range(count):
        await app.next_update_async()
        await asyncio.sleep(0.02)


async def main() -> None:
    try:
        print("FAN_SIM_DEBUG_NATIVE_START", flush=True)
        from omni.cae.data.commands import execute_command
        from omni.cae.importer.vtk import import_to_stage
        from omni.cae.schema import viz as cae_viz

        context = omni.usd.get_context()
        await context.new_stage_async()
        stage = context.get_stage()
        world = UsdGeom.Xform.Define(stage, "/World")
        stage.SetDefaultPrim(world.GetPrim())
        UsdGeom.Xform.Define(stage, "/World/CAE")
        UsdLux.DomeLight.Define(stage, "/World/FanSimDomeLight").CreateIntensityAttr(650.0)

        fan = UsdGeom.Xform.Define(stage, "/World/CAE/FanSimFanMesh").GetPrim()
        fan.GetReferences().AddReference(FAN_MESH_USD.as_posix(), "/OpenFOAMCase")
        mat = UsdShade.Material.Define(stage, "/World/Looks/FanSimFanMaterial")
        shader = UsdShade.Shader.Define(stage, "/World/Looks/FanSimFanMaterial/PreviewSurface")
        shader.CreateIdAttr("UsdPreviewSurface")
        shader.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(0.95, 0.62, 0.20))
        mat.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), "surface")

        root = await import_to_stage(VTU_PATH.as_posix(), "/World/CAE/FanSimPrediction")
        dataset = _find_dataset_prim(root)
        if dataset is None:
            raise RuntimeError("No dataset imported.")
        dataset_path = str(dataset.GetPath())
        print(f"FAN_SIM_DEBUG_NATIVE_DATASET {dataset_path}", flush=True)
        await _wait_updates(20)

        surface_path = "/World/CAE/FanSimSurface"
        await execute_command("CreateCaeVizFaces", dataset_path=dataset_path, prim_path=surface_path)
        surface = stage.GetPrimAtPath(surface_path)
        cae_viz.FieldSelectionAPI(surface, "colors").GetTargetRel().SetTargets(
            _field_targets(stage, dataset_path, "velocity_magnitude")
        )
        await _wait_updates(40)

        streamlines_path = "/World/CAE/FanSimStreamlines"
        seeds_path = "/World/CAE/FanSimStreamlineSeeds"
        await execute_command("CreateCaeVizStreamlines", dataset_path=dataset_path, prim_path=streamlines_path, type="standard")
        await execute_command("CreateCaeVizMeshPrim", prim_type="UnitSphere", prim_path=seeds_path, resolution=32)
        await execute_command(
            "TransformPrimSRT",
            path=seeds_path,
            new_translation=[0.0, 0.0, 0.06],
            new_scale=[0.035, 0.035, 0.012],
        )
        streamlines = stage.GetPrimAtPath(streamlines_path)
        seeds = stage.GetPrimAtPath(seeds_path)
        stream_api = cae_viz.StreamlinesAPI(streamlines)
        stream_api.GetDirectionAttr().Set(cae_viz.Tokens.forward)
        stream_api.GetMinStepSizeAttr().Set(0.0004)
        stream_api.GetInitialStepSizeAttr().Set(0.002)
        stream_api.GetMaxStepSizeAttr().Set(0.006)
        stream_api.GetMaxStepsAttr().Set(900)
        stream_api.GetWidthAttr().Set(0.0009)
        cae_viz.DatasetSelectionAPI(streamlines, "seeds").GetTargetRel().SetTargets([seeds.GetPath()])
        cae_viz.FieldSelectionAPI(streamlines, "velocities").GetTargetRel().SetTargets(
            _field_targets(stage, dataset_path, "U_pred")
        )
        cae_viz.FieldSelectionAPI(streamlines, "colors").GetTargetRel().SetTargets(
            _field_targets(stage, dataset_path, "velocity_magnitude")
        )
        UsdGeom.Imageable(seeds).CreateVisibilityAttr().Set(UsdGeom.Tokens.invisible)
        await _wait_updates(120)
        print("FAN_SIM_DEBUG_NATIVE_STREAMLINES_CONFIGURED", flush=True)

        flow_path = "/World/CAE/FanSimFlow"
        flow_emitter_path = "/World/CAE/FanSimFlow/DatasetInjector"
        await execute_command("CreateCaeVizFlowEnvironment", prim_path=flow_path, layer_number=0)
        flow = stage.GetPrimAtPath(flow_path)
        await execute_command(
            "CreateCaeVizFlowDataSetEmitter",
            dataset_path=dataset_path,
            prim_path=flow_emitter_path,
            layer_number=0,
            simulation_prim=flow,
        )
        emitter = stage.GetPrimAtPath(flow_emitter_path)
        cae_viz.DatasetVoxelizationAPI(emitter, "source").CreateMaxResolutionAttr().Set(96)
        cae_viz.DatasetVoxelizationAPI(emitter, "source").CreateInflateBoundsAttr().Set(2.0)
        cae_viz.FieldSelectionAPI(emitter, "velocities").GetTargetRel().SetTargets(
            _field_targets(stage, dataset_path, "U_pred")
        )
        cae_viz.FieldSelectionAPI(emitter, "temperatures").GetTargetRel().SetTargets(
            _field_targets(stage, dataset_path, "velocity_magnitude")
        )
        emitter.GetAttribute("velocityScale").Set(0.08)
        await _wait_updates(180)
        omni.timeline.get_timeline_interface().play()
        print("FAN_SIM_DEBUG_NATIVE_FLOW_CONFIGURED", flush=True)
    except Exception:
        print("FAN_SIM_DEBUG_NATIVE_EXCEPTION", flush=True)
        traceback.print_exc()
    finally:
        await _wait_updates(120)
        get_app().post_quit()


asyncio.ensure_future(main())
