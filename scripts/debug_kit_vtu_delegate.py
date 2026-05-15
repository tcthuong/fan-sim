from __future__ import annotations

import asyncio
from pathlib import Path
import traceback

import omni.usd
from omni.kit.app import get_app
from pxr import Usd, UsdGeom


VTU_PATH = Path(
    "D:/nvidia/fan-sim/runs/analysis/"
    "fan_mesh_streamlines_recheck_20260514/exporter_full_topology_smoke/prediction_preview.vtu"
)


async def main() -> None:
    try:
        print("FAN_SIM_DEBUG_VTU_START", flush=True)
        from omni.cae.delegate.vtk.vtu_delegate import VTUMetadata, _read_array_from_file
        from omni.cae.importer.vtk import import_to_stage
        from omni.cae.schema import cae
        from omni.cae.schema import vtk as cae_vtk
        from omni.cae.data import get_data_delegate_registry

        meta = VTUMetadata.parse(str(VTU_PATH))
        piece = meta.pieces[0]
        print(
            "FAN_SIM_DEBUG_VTU_META "
            f"points={piece.num_points} cells={piece.num_cells} "
            f"compressor={meta.compressor} header={meta.header_dtype}",
            flush=True,
        )

        raw_points = _read_array_from_file(str(VTU_PATH), meta, piece.points)
        print(
            "FAN_SIM_DEBUG_VTU_DIRECT_POINTS "
            f"shape={raw_points.shape} dtype={raw_points.dtype} "
            f"first={raw_points[0].tolist()}",
            flush=True,
        )

        context = omni.usd.get_context()
        await context.new_stage_async()
        stage = context.get_stage()
        if not stage.GetPrimAtPath("/World").IsValid():
            world = UsdGeom.Xform.Define(stage, "/World")
            stage.SetDefaultPrim(world.GetPrim())
        if not stage.GetPrimAtPath("/World/CAE").IsValid():
            UsdGeom.Xform.Define(stage, "/World/CAE")

        root = await import_to_stage(str(VTU_PATH), "/World/CAE/DebugVTU")
        dataset = None
        for prim in Usd.PrimRange(root):
            if prim.IsA(cae.DataSet):
                dataset = prim
                break
        print(f"FAN_SIM_DEBUG_VTU_DATASET {dataset.GetPath() if dataset else None}", flush=True)
        if dataset is None:
            return

        targets = dataset.GetRelationship(cae_vtk.Tokens.caeVtkPoints).GetTargets()
        print(f"FAN_SIM_DEBUG_VTU_POINTS_TARGETS {targets}", flush=True)
        points_prim = stage.GetPrimAtPath(targets[0])
        registry = get_data_delegate_registry()
        field_array = await registry.get_field_array_async(points_prim, Usd.TimeCode.EarliestTime())
        print(
            "FAN_SIM_DEBUG_VTU_REGISTRY_POINTS "
            f"is_none={field_array is None} "
            f"shape={field_array.shape if field_array is not None else None} "
            f"dtype={field_array.dtype if field_array is not None else None} "
            f"device={field_array.device_id if field_array is not None else None}",
            flush=True,
        )
    except Exception:
        print("FAN_SIM_DEBUG_VTU_EXCEPTION", flush=True)
        traceback.print_exc()
    finally:
        get_app().post_quit()


asyncio.ensure_future(main())
