from __future__ import annotations

import asyncio
import json
from pathlib import Path
import urllib.request

import omni.ext
import omni.ui as ui
import omni.usd
from omni.kit.async_engine import run_coroutine
from pxr import Sdf, Usd, UsdGeom

from .extension_config import build_predict_payload, default_config_path, load_rpm_values, rpm_slider_spec


class FanSimExtension(omni.ext.IExt):
    STREAMLINES_PATH = "/World/CAE/FanSimStreamlines"
    STREAMLINE_SEEDS_PATH = "/World/CAE/FanSimStreamlineSeeds"
    FLOW_PATH = "/World/CAE/FanSimFlow"
    FLOW_DATASET_EMITTER_PATH = "/World/CAE/FanSimFlow/DatasetInjector"
    FLOW_FUEL_INJECTOR_PATH = "/World/CAE/FanSimFlow/FuelInjectorSphere"
    DATASET_ROOT_PATH = "/World/CAE/FanSimPrediction"

    def on_startup(self, ext_id):
        self._window = ui.Window("Fan-Sim", width=420, height=320)
        self._service_url = "http://127.0.0.1:8765"
        self._case_id = "fan_base"
        self._outlet_pressure = 20.0
        self._dataset_path = ""

        self._config_path = default_config_path(__file__)
        try:
            rpm_values = load_rpm_values(self._config_path)
        except OSError:
            rpm_values = []
        self._rpm_spec = rpm_slider_spec(rpm_values)
        self._rpm_model = ui.SimpleFloatModel(self._rpm_spec.default)
        self._streamlines_model = ui.SimpleBoolModel(True)
        self._cae_flow_model = ui.SimpleBoolModel(False)
        self._streamlines_model.add_value_changed_fn(lambda _: self._on_visual_toggle())
        self._cae_flow_model.add_value_changed_fn(lambda _: self._on_visual_toggle())

        with self._window.frame:
            with ui.VStack(spacing=8):
                ui.Label("Fan-Sim Inference")
                ui.Label(f"RPM range: {self._rpm_spec.minimum:g} - {self._rpm_spec.maximum:g}")
                with ui.HStack(spacing=6):
                    ui.Label("Service", width=80)
                    self._service_field = ui.StringField()
                    self._service_field.model.set_value(self._service_url)
                with ui.HStack(spacing=6):
                    ui.Label("Case", width=80)
                    self._case_field = ui.StringField()
                    self._case_field.model.set_value(self._case_id)
                with ui.HStack(spacing=6):
                    ui.Label("RPM", width=80)
                    ui.FloatSlider(
                        model=self._rpm_model,
                        min=self._rpm_spec.minimum,
                        max=self._rpm_spec.maximum,
                    )
                    ui.FloatField(model=self._rpm_model, width=84)
                with ui.HStack(spacing=6):
                    ui.Label("Outlet Pa", width=80)
                    self._pout_field = ui.FloatField()
                    self._pout_field.model.set_value(self._outlet_pressure)
                with ui.HStack(spacing=12):
                    ui.CheckBox(model=self._streamlines_model)
                    ui.Label("Streamlines", width=120)
                    ui.CheckBox(model=self._cae_flow_model)
                    ui.Label("CAE Flow")
                ui.Button("Predict RPM And Visualize", clicked_fn=self._predict_clicked)
                self._status = ui.Label("")

    def on_shutdown(self):
        self._window = None

    def _predict_clicked(self):
        run_coroutine(self._predict_and_visualize())

    def _on_visual_toggle(self):
        stage = omni.usd.get_context().get_stage()
        if stage is None:
            return
        self._set_visibility(stage, self.STREAMLINES_PATH, self._streamlines_model.get_value_as_bool())
        self._set_visibility(stage, self.STREAMLINE_SEEDS_PATH, self._streamlines_model.get_value_as_bool())
        self._set_visibility(stage, self.FLOW_PATH, self._cae_flow_model.get_value_as_bool())
        if self._dataset_path and (self._streamlines_model.get_value_as_bool() or self._cae_flow_model.get_value_as_bool()):
            run_coroutine(self._ensure_requested_visuals(stage, self._dataset_path))

    async def _predict_and_visualize(self):
        self._service_url = self._service_field.model.get_value_as_string()
        self._case_id = self._case_field.model.get_value_as_string()
        self._outlet_pressure = self._pout_field.model.get_value_as_float()
        rpm = self._rpm_model.get_value_as_float()
        payload = build_predict_payload(
            case_id=self._case_id,
            rpm=rpm,
            outlet_pressure=self._outlet_pressure,
            show_streamlines=self._streamlines_model.get_value_as_bool(),
            show_cae_flow=self._cae_flow_model.get_value_as_bool(),
        )

        try:
            self._status.text = f"Predicting RPM {rpm:g}..."
            body = await asyncio.to_thread(self._post_predict, payload)
            prediction_usd = self._kit_path(body.get("prediction_usd", ""))
            prediction_vtu = self._kit_path(body.get("prediction_vtu", ""))
            if not prediction_vtu:
                raise RuntimeError("Inference response did not include prediction_vtu.")

            stage, dataset_prim = await self._load_prediction_dataset(prediction_usd, prediction_vtu)
            self._dataset_path = str(dataset_prim.GetPath())
            await self._ensure_requested_visuals(stage, self._dataset_path)
            self._status.text = f"Loaded RPM {rpm:g}: {self._dataset_path}"
        except Exception as exc:
            self._status.text = f"Fan-Sim error: {exc}"

    def _post_predict(self, payload: dict) -> dict:
        request = urllib.request.Request(
            f"{self._service_url.rstrip('/')}/predict",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=180) as response:
            return json.loads(response.read().decode("utf-8"))

    async def _load_prediction_dataset(self, prediction_usd: str, prediction_vtu: str) -> tuple[Usd.Stage, Usd.Prim]:
        from omni.cae.importer.vtk import import_to_stage

        context = omni.usd.get_context()
        if prediction_usd:
            await context.open_stage_async(prediction_usd)
        else:
            await context.new_stage_async()
        stage = context.get_stage()
        self._ensure_world_and_cae(stage)

        for path in [
            self.DATASET_ROOT_PATH,
            self.STREAMLINES_PATH,
            self.STREAMLINE_SEEDS_PATH,
            self.FLOW_PATH,
        ]:
            if stage.GetPrimAtPath(path).IsValid():
                stage.RemovePrim(Sdf.Path(path))

        root_prim = await import_to_stage(prediction_vtu, self.DATASET_ROOT_PATH)
        dataset_prim = self._find_dataset_prim(root_prim)
        if dataset_prim is None:
            raise RuntimeError(f"No CAE dataset prim was imported from {prediction_vtu}")
        return stage, dataset_prim

    async def _ensure_requested_visuals(self, stage: Usd.Stage, dataset_path: str):
        if self._streamlines_model.get_value_as_bool():
            await self._ensure_streamlines(stage, dataset_path)
        else:
            self._set_visibility(stage, self.STREAMLINES_PATH, False)
            self._set_visibility(stage, self.STREAMLINE_SEEDS_PATH, False)

        if self._cae_flow_model.get_value_as_bool():
            await self._ensure_cae_flow(stage, dataset_path)
        else:
            self._set_visibility(stage, self.FLOW_PATH, False)

    async def _ensure_streamlines(self, stage: Usd.Stage, dataset_path: str):
        from omni.cae.data.commands import execute_command
        from omni.cae.schema import viz as cae_viz

        if not stage.GetPrimAtPath(self.STREAMLINES_PATH).IsValid():
            await execute_command(
                "CreateCaeVizStreamlines",
                dataset_path=dataset_path,
                prim_path=self.STREAMLINES_PATH,
                type="standard",
            )
        if not stage.GetPrimAtPath(self.STREAMLINE_SEEDS_PATH).IsValid():
            await execute_command(
                "CreateCaeVizMeshPrim",
                prim_type="UnitSphere",
                prim_path=self.STREAMLINE_SEEDS_PATH,
                boundable_paths=[dataset_path],
            )

        streamlines_prim = stage.GetPrimAtPath(self.STREAMLINES_PATH)
        seed_prim = stage.GetPrimAtPath(self.STREAMLINE_SEEDS_PATH)
        cae_viz.DatasetSelectionAPI(streamlines_prim, "seeds").GetTargetRel().SetTargets([seed_prim.GetPath()])
        self._set_field_targets(cae_viz.FieldSelectionAPI(streamlines_prim, "velocities"), stage, dataset_path, "U_pred")
        self._set_field_targets(
            cae_viz.FieldSelectionAPI(streamlines_prim, "colors"), stage, dataset_path, "velocity_magnitude"
        )
        self._set_visibility(stage, self.STREAMLINES_PATH, True)
        self._set_visibility(stage, self.STREAMLINE_SEEDS_PATH, True)

    async def _ensure_cae_flow(self, stage: Usd.Stage, dataset_path: str):
        from omni.cae.data.commands import execute_command
        from omni.cae.schema import viz as cae_viz

        if not stage.GetPrimAtPath(self.FLOW_PATH).IsValid():
            await execute_command("CreateCaeVizFlowEnvironment", prim_path=self.FLOW_PATH, layer_number=0)

        simulation_prim = stage.GetPrimAtPath(self.FLOW_PATH)
        if not stage.GetPrimAtPath(self.FLOW_DATASET_EMITTER_PATH).IsValid():
            await execute_command(
                "CreateCaeVizFlowDataSetEmitter",
                dataset_path=dataset_path,
                prim_path=self.FLOW_DATASET_EMITTER_PATH,
                layer_number=0,
                simulation_prim=simulation_prim,
            )
        if not stage.GetPrimAtPath(self.FLOW_FUEL_INJECTOR_PATH).IsValid():
            await execute_command(
                "CreateCaeVizFlowSmokeInjector",
                boundable_paths=[dataset_path],
                prim_path=self.FLOW_FUEL_INJECTOR_PATH,
                layer_number=0,
                mode="sphere",
                simulation_prim=simulation_prim,
            )

        emitter_prim = stage.GetPrimAtPath(self.FLOW_DATASET_EMITTER_PATH)
        self._set_field_targets(cae_viz.FieldSelectionAPI(emitter_prim, "velocities"), stage, dataset_path, "U_pred")
        self._set_field_targets(
            cae_viz.FieldSelectionAPI(emitter_prim, "temperatures"), stage, dataset_path, "velocity_magnitude"
        )
        self._set_visibility(stage, self.FLOW_PATH, True)

    def _set_field_targets(self, field_selection_api, stage: Usd.Stage, dataset_path: str, field_name: str):
        targets = self._field_targets(stage, dataset_path, field_name)
        if not targets:
            raise RuntimeError(f"Field {field_name!r} was not found under {dataset_path}")
        field_selection_api.GetTargetRel().SetTargets(targets)

    def _field_targets(self, stage: Usd.Stage, dataset_path: str, field_name: str) -> list[Sdf.Path]:
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

    def _find_dataset_prim(self, root_prim: Usd.Prim) -> Usd.Prim | None:
        try:
            from omni.cae.schema import cae
        except Exception:
            return None

        for prim in Usd.PrimRange(root_prim):
            if prim.IsA(cae.DataSet):
                return prim
        return None

    def _ensure_world_and_cae(self, stage: Usd.Stage) -> None:
        if not stage.GetPrimAtPath("/World").IsValid():
            world = UsdGeom.Xform.Define(stage, "/World")
            stage.SetDefaultPrim(world.GetPrim())
        if not stage.GetPrimAtPath("/World/CAE").IsValid():
            UsdGeom.Xform.Define(stage, "/World/CAE")

    def _set_visibility(self, stage: Usd.Stage, path: str, visible: bool):
        prim = stage.GetPrimAtPath(path)
        if prim and prim.IsValid() and prim.IsA(UsdGeom.Imageable):
            UsdGeom.Imageable(prim).CreateVisibilityAttr().Set(
                UsdGeom.Tokens.inherited if visible else UsdGeom.Tokens.invisible
            )

    def _kit_path(self, path: str) -> str:
        if not path:
            return ""
        normalized = path.replace("\\", "/")
        if normalized.startswith("/mnt/") and len(normalized) > 6 and normalized[5].isalpha():
            drive = normalized[5].upper()
            return f"{drive}:{normalized[6:]}"
        return str(Path(normalized).as_posix())
