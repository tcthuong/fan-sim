from __future__ import annotations

import asyncio
import json
from pathlib import Path
import urllib.request

import omni.ext
import omni.ui as ui
import omni.usd
from omni.kit.async_engine import run_coroutine
from pxr import Gf, Sdf, Usd, UsdGeom, UsdLux, UsdShade

from .extension_config import (
    build_predict_payload,
    default_config_path,
    default_flow_settings,
    default_runtime_settings,
    default_streamline_settings,
    load_rpm_values,
    rpm_slider_spec,
)


class FanSimExtension(omni.ext.IExt):
    DEMO_SCALE = 8.0
    FAN_ROOT_PATH = "/World/Fan"
    FAN_MESH_PATH = "/World/Fan/FanMesh"
    FAN_WIREFRAME_PATH = "/World/Fan/FanMeshWire"
    SURFACE_PATH = "/World/CAE/FanSimSurface"
    STREAMLINES_PATH = "/World/CAE/FanSimStreamlines"
    STREAMLINE_SEEDS_PATH = "/World/CAE/FanSimStreamlineSeeds"
    FLOW_PATH = "/World/CAE/FlowSimulation_L0"
    FLOW_BOUNDING_BOX_PATH = "/World/CAE/FanBoundingBox"
    FLOW_DATASET_EMITTER_PATH = "/World/CAE/FlowSimulation_L0/DataSetInjector"
    FLOW_BOUNDARY_EMITTER_PATH = "/World/CAE/FlowSimulation_L0/BoundaryEmitter"
    DATASET_ROOT_PATH = "/World/FanCase"

    def on_startup(self, ext_id):
        self._window = ui.Window("Fan-Sim", width=420, height=320)
        self._service_url = "http://127.0.0.1:8765"
        self._case_id = "fan_base"
        self._outlet_pressure = 20.0
        self._dataset_path = ""
        self._streamlines_usd = ""
        self._streamline_settings = default_streamline_settings()
        self._flow_settings = default_flow_settings()
        self._runtime_settings = default_runtime_settings()
        self._predict_revision = 0
        self._is_predicting = False
        self._rerun_after_predict = False
        self._active_payload_key = ""
        self._last_loaded_payload_key = ""
        self._last_scheduled_payload_key = ""
        self._pending_tasks = set()
        self._is_shutdown = False
        self._suspend_auto_predict = True
        self._has_framed_once = False

        self._config_path = default_config_path(__file__)
        try:
            rpm_values = load_rpm_values(self._config_path)
        except OSError:
            rpm_values = []
        self._rpm_spec = rpm_slider_spec(rpm_values)
        self._rpm_model = ui.SimpleFloatModel(self._rpm_spec.default)
        self._rpm_model.add_value_changed_fn(lambda _: self._schedule_auto_predict("rpm"))
        self._streamlines_model = ui.SimpleBoolModel(True)
        self._cae_flow_model = ui.SimpleBoolModel(True)
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
                    self._pout_field.model.add_value_changed_fn(lambda _: self._schedule_auto_predict("outlet_pressure"))
                with ui.HStack(spacing=12):
                    ui.CheckBox(model=self._streamlines_model)
                    ui.Label("Streamlines", width=120)
                    ui.CheckBox(model=self._cae_flow_model)
                    ui.Label("CAE Flow")
                ui.Button("Predict RPM And Visualize", clicked_fn=self._predict_clicked)
                self._status = ui.Label("")

        self._suspend_auto_predict = False
        if self._runtime_settings.auto_predict_on_startup:
            self._schedule_auto_predict("startup")

    def on_shutdown(self):
        self._is_shutdown = True
        self._predict_revision += 1
        for task in list(getattr(self, "_pending_tasks", ())):
            if hasattr(task, "cancel"):
                task.cancel()
        if hasattr(self, "_pending_tasks"):
            self._pending_tasks.clear()
        self._window = None

    def _predict_clicked(self):
        self._predict_revision += 1
        self._start_coroutine(self._predict_and_visualize("manual"))

    def _start_coroutine(self, coro):
        task = run_coroutine(coro)
        if not hasattr(self, "_pending_tasks"):
            self._pending_tasks = set()
        if hasattr(task, "add_done_callback"):
            self._pending_tasks.add(task)
            task.add_done_callback(lambda completed: self._pending_tasks.discard(completed))
        return task

    def _ensure_runtime_state(self) -> None:
        if not hasattr(self, "_streamline_settings"):
            self._streamline_settings = default_streamline_settings()
        if not hasattr(self, "_flow_settings"):
            self._flow_settings = default_flow_settings()
        if not hasattr(self, "_runtime_settings"):
            self._runtime_settings = default_runtime_settings()
        if not hasattr(self, "_predict_revision"):
            self._predict_revision = 0
        if not hasattr(self, "_is_predicting"):
            self._is_predicting = False
        if not hasattr(self, "_rerun_after_predict"):
            self._rerun_after_predict = False
        if not hasattr(self, "_active_payload_key"):
            self._active_payload_key = ""
        if not hasattr(self, "_last_loaded_payload_key"):
            self._last_loaded_payload_key = ""
        if not hasattr(self, "_last_scheduled_payload_key"):
            self._last_scheduled_payload_key = ""
        if not hasattr(self, "_pending_tasks"):
            self._pending_tasks = set()
        if not hasattr(self, "_is_shutdown"):
            self._is_shutdown = False
        if not hasattr(self, "_has_framed_once"):
            self._has_framed_once = False
        if not hasattr(self, "_streamlines_usd"):
            self._streamlines_usd = ""

    def _schedule_auto_predict(self, reason: str) -> None:
        self._ensure_runtime_state()
        if getattr(self, "_is_shutdown", False) or getattr(self, "_suspend_auto_predict", False):
            return
        payload_key = self._current_payload_key()
        if not payload_key or payload_key == self._last_scheduled_payload_key:
            return
        self._last_scheduled_payload_key = payload_key
        self._predict_revision += 1
        revision = self._predict_revision
        self._start_coroutine(self._debounced_predict(revision, reason))

    async def _debounced_predict(self, revision: int, reason: str) -> None:
        self._ensure_runtime_state()
        await asyncio.sleep(self._runtime_settings.debounce_seconds)
        if revision != self._predict_revision or getattr(self, "_is_shutdown", False) or getattr(self, "_window", None) is None:
            return
        await self._predict_and_visualize(reason)

    async def _wait_updates(self, count: int, sleep_seconds: float = 0.02) -> None:
        from omni.kit.app import get_app

        app = get_app()
        for _ in range(count):
            await app.next_update_async()
            await asyncio.sleep(sleep_seconds)

    def _on_visual_toggle(self):
        stage = omni.usd.get_context().get_stage()
        if stage is None:
            return
        self._set_visibility(stage, self.STREAMLINES_PATH, self._streamlines_model.get_value_as_bool())
        self._set_visibility(stage, self.STREAMLINE_SEEDS_PATH, False)
        self._set_visibility(stage, self.FLOW_PATH, self._cae_flow_model.get_value_as_bool())
        if self._dataset_path and (self._streamlines_model.get_value_as_bool() or self._cae_flow_model.get_value_as_bool()):
            self._start_coroutine(self._ensure_requested_visuals(stage, self._dataset_path, streamlines_usd=self._streamlines_usd))

    async def _predict_and_visualize(self, reason: str = "manual"):
        self._ensure_runtime_state()
        if getattr(self, "_is_shutdown", False) or getattr(self, "_window", None) is None:
            return
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
        payload_key = self._payload_key(payload)
        if reason != "manual" and payload_key == self._last_loaded_payload_key:
            self._last_scheduled_payload_key = payload_key
            print(f"FAN_SIM_PREDICT_SKIP_LOADED reason={reason}", flush=True)
            return

        if self._is_predicting:
            if payload_key != self._active_payload_key:
                self._rerun_after_predict = True
            print(f"FAN_SIM_PREDICT_SKIP_BUSY reason={reason}", flush=True)
            return

        self._is_predicting = True
        self._active_payload_key = payload_key
        try:
            print(f"FAN_SIM_PREDICT_START reason={reason} rpm={rpm:g}", flush=True)
            if hasattr(self, "_status"):
                self._status.text = f"Predicting RPM {rpm:g} ({reason})..."
            body = await asyncio.to_thread(self._post_predict, payload)
            prediction_usd = self._kit_path(body.get("prediction_usd", ""))
            prediction_vtu = self._kit_path(body.get("prediction_vtu", ""))
            fan_mesh_usd = self._kit_path(body.get("fan_mesh_usd", ""))
            streamlines_usd = self._kit_path(body.get("prediction_streamlines_usd", ""))
            if not prediction_vtu:
                raise RuntimeError("Inference response did not include prediction_vtu.")

            suffix = self._runtime_settings.pending_suffix
            stage, dataset_prim = await self._load_prediction_dataset(
                prediction_usd,
                prediction_vtu,
                fan_mesh_usd,
                path_suffix=suffix,
            )
            pending_dataset_path = str(dataset_prim.GetPath())
            pending_anchor = await self._ensure_visible_anchor(
                stage,
                pending_dataset_path,
                fan_mesh_usd,
                path_suffix=suffix,
            )
            self._streamlines_usd = streamlines_usd
            if suffix:
                await self._ensure_requested_visuals(
                    stage,
                    pending_dataset_path,
                    path_suffix=suffix,
                    streamlines_usd=streamlines_usd,
                    include_cae_flow=False,
                )
                self._promote_prediction_paths(stage, suffix)
                await self._wait_updates(120)
            self._dataset_path = self._finalized_path(pending_dataset_path, suffix)
            await self._ensure_requested_visuals(stage, self._dataset_path, streamlines_usd=streamlines_usd)
            if getattr(self, "_is_shutdown", False) or getattr(self, "_window", None) is None:
                return
            visible_anchor = self._finalized_path(pending_anchor, suffix) if pending_anchor else self.STREAMLINES_PATH
            if not self._has_framed_once:
                await self._frame_prediction(stage, self._frame_paths(visible_anchor))
                await self._set_demo_camera(stage)
                self._has_framed_once = True
            self._last_loaded_payload_key = payload_key
            self._last_scheduled_payload_key = payload_key
            if hasattr(self, "_status"):
                self._status.text = f"Loaded RPM {rpm:g}: {self._dataset_path}"
            print(f"FAN_SIM_PREDICT_LOADED rpm={rpm:g} dataset={self._dataset_path}", flush=True)
        except Exception as exc:
            stage = omni.usd.get_context().get_stage()
            if stage is not None:
                self._remove_prediction_paths(stage, self._runtime_settings.pending_suffix)
            if hasattr(self, "_status"):
                self._status.text = f"Fan-Sim error: {exc}"
            print(f"FAN_SIM_PREDICT_ERROR reason={reason} error={exc}", flush=True)
        finally:
            self._is_predicting = False
            self._active_payload_key = ""
            if getattr(self, "_rerun_after_predict", False) and not getattr(self, "_is_shutdown", False):
                self._rerun_after_predict = False
                self._schedule_auto_predict("queued")

    def _current_payload_key(self) -> str:
        if not all(
            hasattr(self, attr)
            for attr in ("_service_field", "_case_field", "_pout_field", "_rpm_model", "_streamlines_model", "_cae_flow_model")
        ):
            return ""
        payload = build_predict_payload(
            case_id=self._case_field.model.get_value_as_string(),
            rpm=self._rpm_model.get_value_as_float(),
            outlet_pressure=self._pout_field.model.get_value_as_float(),
            show_streamlines=self._streamlines_model.get_value_as_bool(),
            show_cae_flow=self._cae_flow_model.get_value_as_bool(),
        )
        return self._payload_key(payload)

    def _payload_key(self, payload: dict) -> str:
        normalized = dict(payload)
        normalized["rpm"] = round(float(normalized.get("rpm", 0.0)), 1)
        normalized["inlet_pressure"] = round(float(normalized.get("inlet_pressure", 0.0)), 3)
        normalized["outlet_pressure"] = round(float(normalized.get("outlet_pressure", 0.0)), 3)
        normalized["outputs"] = tuple(normalized.get("outputs", ()))
        return json.dumps(normalized, sort_keys=True)

    def _post_predict(self, payload: dict) -> dict:
        request = urllib.request.Request(
            f"{self._service_url.rstrip('/')}/predict",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=180) as response:
            return json.loads(response.read().decode("utf-8"))

    async def _load_prediction_dataset(
        self,
        prediction_usd: str,
        prediction_vtu: str,
        fan_mesh_usd: str = "",
        path_suffix: str = "",
    ) -> tuple[Usd.Stage, Usd.Prim]:
        from omni.cae.importer.vtk import import_to_stage

        context = omni.usd.get_context()
        if context.get_stage() is None:
            await context.new_stage_async()
        stage = context.get_stage()
        self._ensure_world_and_cae(stage)
        self._ensure_lighting(stage)

        self._remove_prediction_paths(stage, path_suffix)

        if fan_mesh_usd:
            self._ensure_static_fan_mesh(stage, fan_mesh_usd)

        root_prim = await import_to_stage(prediction_vtu, self._viz_path(self.DATASET_ROOT_PATH, path_suffix))
        dataset_prim = self._find_dataset_prim(root_prim)
        if dataset_prim is None:
            raise RuntimeError(f"No CAE dataset prim was imported from {prediction_vtu}")
        await self._wait_updates(20)
        return stage, dataset_prim

    async def _ensure_visible_anchor(
        self,
        stage: Usd.Stage,
        dataset_path: str,
        fan_mesh_usd: str = "",
        path_suffix: str = "",
    ) -> str:
        fan_mesh_path = self.FAN_MESH_PATH
        fan_root_path = self.FAN_ROOT_PATH
        if fan_mesh_usd and stage.GetPrimAtPath(fan_mesh_path).IsValid():
            self._set_visibility(stage, fan_mesh_path, True)
            return fan_mesh_path
        if fan_mesh_usd and stage.GetPrimAtPath(fan_root_path).IsValid():
            self._set_visibility(stage, fan_root_path, True)
            return fan_root_path
        await self._ensure_surface_preview(stage, dataset_path, path_suffix=path_suffix)
        surface_path = self._viz_path(self.SURFACE_PATH, path_suffix)
        return surface_path if stage.GetPrimAtPath(surface_path).IsValid() else ""

    async def _ensure_surface_preview(self, stage: Usd.Stage, dataset_path: str, path_suffix: str = ""):
        from omni.cae.data.commands import execute_command
        from omni.cae.schema import viz as cae_viz

        surface_path = self._viz_path(self.SURFACE_PATH, path_suffix)
        if not stage.GetPrimAtPath(surface_path).IsValid():
            await execute_command("CreateCaeVizFaces", dataset_path=dataset_path, prim_path=surface_path)

        surface_prim = stage.GetPrimAtPath(surface_path)
        if not surface_prim.IsValid():
            return
        cae_viz.FacesAPI(surface_prim).CreateExternalOnlyAttr().Set(False)
        self._set_field_targets(cae_viz.FieldSelectionAPI(surface_prim, "colors"), stage, dataset_path, "velocity_magnitude")
        self._set_fixed_color_range(cae_viz, stage, surface_prim, self._streamline_settings.color_range)
        if surface_prim.IsA(UsdGeom.Mesh):
            mesh = UsdGeom.Mesh(surface_prim)
            mesh.CreateDisplayOpacityAttr().Set([0.22])
        self._set_visibility(stage, surface_path, True)
        await self._wait_updates(40)

    async def _ensure_requested_visuals(
        self,
        stage: Usd.Stage,
        dataset_path: str,
        path_suffix: str = "",
        streamlines_usd: str = "",
        include_cae_flow: bool = True,
    ):
        if self._streamlines_model.get_value_as_bool():
            if streamlines_usd:
                self._reference_streamline_artifact(stage, streamlines_usd, path_suffix=path_suffix)
            else:
                await self._ensure_streamlines(stage, dataset_path, path_suffix=path_suffix)
        else:
            self._set_visibility(stage, self._viz_path(self.STREAMLINES_PATH, path_suffix), False)
            self._set_visibility(stage, self._viz_path(self.STREAMLINE_SEEDS_PATH, path_suffix), False)

        if not include_cae_flow:
            return

        if self._cae_flow_model.get_value_as_bool():
            await self._ensure_cae_flow(stage, dataset_path, path_suffix=path_suffix)
        else:
            self._set_visibility(stage, self._viz_path(self.FLOW_PATH, path_suffix), False)

    async def _ensure_streamlines(
        self,
        stage: Usd.Stage,
        dataset_path: str,
        path_suffix: str = "",
    ):
        from omni.cae.data.commands import execute_command
        from omni.cae.schema import viz as cae_viz

        streamlines_path = self._viz_path(self.STREAMLINES_PATH, path_suffix)
        seeds_path = self._viz_path(self.STREAMLINE_SEEDS_PATH, path_suffix)
        if not stage.GetPrimAtPath(streamlines_path).IsValid():
            await execute_command(
                "CreateCaeVizStreamlines",
                dataset_path=dataset_path,
                prim_path=streamlines_path,
                type="standard",
            )
        if not stage.GetPrimAtPath(seeds_path).IsValid():
            await execute_command(
                "CreateCaeVizMeshPrim",
                prim_type="UnitSphere",
                prim_path=seeds_path,
                resolution=self._streamline_settings.seed_resolution,
            )
        settings = self._streamline_settings
        await execute_command(
            "TransformPrimSRT",
            path=seeds_path,
            new_translation=list(settings.seed_translation),
            new_scale=list(settings.seed_scale),
        )

        streamlines_prim = stage.GetPrimAtPath(streamlines_path)
        seed_prim = stage.GetPrimAtPath(seeds_path)
        streamlines_api = cae_viz.StreamlinesAPI(streamlines_prim)
        streamlines_api.GetMinStepSizeAttr().Set(settings.min_step_size)
        streamlines_api.GetMaxStepSizeAttr().Set(settings.max_step_size)
        streamlines_api.GetInitialStepSizeAttr().Set(settings.initial_step_size)
        streamlines_api.GetMaxStepsAttr().Set(settings.max_steps)
        streamlines_api.GetDirectionAttr().Set(getattr(cae_viz.Tokens, settings.direction))
        streamlines_api.GetThresholdAttr().Set(settings.threshold)
        streamlines_api.GetToleranceAttr().Set(settings.tolerance)
        streamlines_api.GetWidthAttr().Set(settings.width)
        cae_viz.DatasetSelectionAPI(streamlines_prim, "seeds").GetTargetRel().SetTargets([seed_prim.GetPath()])
        self._set_field_targets(
            cae_viz.FieldSelectionAPI(streamlines_prim, "velocities"),
            stage,
            dataset_path,
            "U_pred",
            prefer_scope="PointData",
        )
        self._set_field_targets(
            cae_viz.FieldSelectionAPI(streamlines_prim, "colors"),
            stage,
            dataset_path,
            settings.color_field,
            prefer_scope="PointData",
        )
        self._set_fixed_color_range(cae_viz, stage, streamlines_prim, settings.color_range)
        self._set_visibility(stage, streamlines_path, True)
        self._set_visibility(stage, seeds_path, False)
        await self._wait_updates(520)

    async def _ensure_cae_flow(
        self,
        stage: Usd.Stage,
        dataset_path: str,
        path_suffix: str = "",
    ):
        from omni.cae.data.commands import execute_command
        from omni.cae.schema import viz as cae_viz

        flow_path = self._viz_path(self.FLOW_PATH, path_suffix)
        bbox_path = self._viz_path(self.FLOW_BOUNDING_BOX_PATH, path_suffix)
        dataset_emitter_path = self._viz_path(self.FLOW_DATASET_EMITTER_PATH, path_suffix)
        boundary_emitter_path = self._viz_path(self.FLOW_BOUNDARY_EMITTER_PATH, path_suffix)
        flow_exists = stage.GetPrimAtPath(flow_path).IsValid()

        if not flow_exists and not stage.GetPrimAtPath(bbox_path).IsValid():
            await execute_command("CreateCaeVizBoundingBox", dataset_paths=[dataset_path], prim_path=bbox_path)
        self._set_visibility(stage, bbox_path, False)

        if not flow_exists:
            await execute_command("CreateCaeVizFlowEnvironment", prim_path=flow_path, layer_number=0)

        settings = self._flow_settings
        simulation_prim = stage.GetPrimAtPath(flow_path)
        ray_march_prim = stage.GetPrimAtPath(f"{flow_path}/flowRender/rayMarch")
        self._set_attr_if_valid(ray_march_prim, "attenuation", settings.ray_attenuation)
        self._set_attr_if_valid(ray_march_prim, "shadowFactor", 0.45)
        colormap_prim = stage.GetPrimAtPath(f"{flow_path}/flowOffscreen/colormap")
        self._set_attr_if_valid(colormap_prim, "colorScale", settings.ray_color_scale)

        for index, (name, position) in enumerate(self._flow_smoke_specs()):
            smoke_path = f"{flow_path}/{name}"
            if not stage.GetPrimAtPath(smoke_path).IsValid():
                await execute_command(
                    "CreateCaeVizFlowSmokeInjector",
                    boundable_paths=[bbox_path],
                    prim_path=smoke_path,
                    layer_number=0,
                    mode="sphere",
                    simulation_prim=simulation_prim,
            )
            self._configure_smoke_injector(stage, smoke_path, position, pulse_phase=(index * 12) % 90)
            self._set_visibility(stage, smoke_path, False)

        if not stage.GetPrimAtPath(boundary_emitter_path).IsValid():
            await execute_command(
                "CreateCaeVizFlowBoundaryEmitter",
                boundable_paths=[bbox_path],
                prim_path=boundary_emitter_path,
                layer_number=0,
            )

        if not stage.GetPrimAtPath(dataset_emitter_path).IsValid():
            await execute_command(
                "CreateCaeVizFlowDataSetEmitter",
                dataset_path=dataset_path,
                prim_path=dataset_emitter_path,
                layer_number=0,
                simulation_prim=simulation_prim,
            )

        emitter_prim = stage.GetPrimAtPath(dataset_emitter_path)
        voxel_api = cae_viz.DatasetVoxelizationAPI(emitter_prim, "source")
        voxel_api.CreateVoxelSizeModeAttr().Set(cae_viz.Tokens.maxResolution)
        voxel_api.CreateMaxResolutionAttr().Set(settings.voxel_max_resolution)
        voxel_api.CreateInflateBoundsAttr().Set(settings.inflate_bounds)
        self._set_flow_velocity_targets(cae_viz.FieldSelectionAPI(emitter_prim, "velocities"), stage, dataset_path)
        self._set_attr_if_valid(emitter_prim, "velocityScale", settings.velocity_scale, lock=True)
        self._set_attr_if_valid(emitter_prim, "coupleRateVelocity", settings.velocity_couple_rate, lock=True)
        self._set_attr_if_valid(emitter_prim, "velocityIsWorldSpace", True, lock=True)
        self._set_attr_if_valid(emitter_prim, "applyPostPressure", True, lock=True)
        if stage.GetPrimAtPath(bbox_path).IsValid():
            stage.RemovePrim(Sdf.Path(bbox_path))
        self._set_visibility(stage, flow_path, True)
        print(
            "FAN_SIM_FLOW_CONFIGURED "
            f"voxelMaxResolution={settings.voxel_max_resolution} "
            f"inflateBounds={settings.inflate_bounds} "
            f"densityCellSize={settings.density_cell_size} "
            f"velocityScale={settings.velocity_scale} "
            f"velocityCoupleRate={settings.velocity_couple_rate} "
            f"sourceRadius={settings.source_radius} "
            f"sourceOffset={settings.source_offset} "
            f"rayAttenuation={settings.ray_attenuation} "
            f"rayColorScale={settings.ray_color_scale}",
            flush=True,
        )
        await self._wait_updates(180)
        try:
            import omni.timeline

            timeline = omni.timeline.get_timeline_interface()
            timeline.stop()
            timeline.set_start_time(0.0)
            timeline.set_end_time(20.0)
            timeline.set_current_time(0.0)
            timeline.set_time_codes_per_second(60.0)
            timeline.play()
        except Exception:
            pass

    def _reference_streamline_artifact(self, stage: Usd.Stage, streamlines_usd: str, path_suffix: str = "") -> None:
        streamlines_path = Path(streamlines_usd)
        if not streamlines_path.exists():
            raise RuntimeError(f"Streamline artifact was not found: {streamlines_usd}")
        stage_path = self._viz_path(self.STREAMLINES_PATH, path_suffix)
        prim = UsdGeom.Xform.Define(stage, stage_path).GetPrim()
        references = prim.GetReferences()
        references.ClearReferences()
        references.AddReference(streamlines_path.as_posix())
        self._set_visibility(stage, stage_path, True)
        self._set_visibility(stage, self._viz_path(self.STREAMLINE_SEEDS_PATH, path_suffix), False)
        print(f"FAN_SIM_STREAMLINES_USD {streamlines_path.as_posix()}", flush=True)

    def _create_flow_smoke_injector(self, stage: Usd.Stage, prim_path: str, layer_number: int) -> None:
        shape = UsdGeom.Sphere.Define(stage, prim_path).GetPrim()
        shape.GetAttribute("radius").Set(1.0)
        emitter = stage.DefinePrim(f"{prim_path}/EmitterSphere", "FlowEmitterSphere")
        self._set_attr_if_valid(emitter, "layer", layer_number)
        self._set_attr_if_valid(emitter, "radius", 1.0)
        self._set_attr_if_valid(emitter, "radiusIsWorldSpace", False)

    def _set_fixed_color_range(
        self, cae_viz, stage: Usd.Stage, prim: Usd.Prim, color_range: tuple[float, float] | None
    ) -> None:
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
            if not attr or not attr.IsValid():
                continue
            attr.Set(color_range)
            attr.SetCustomDataByKey("omni:kit:locked", True)

    def _flow_smoke_specs(self) -> list[tuple[str, tuple[float, float, float]]]:
        settings = self._flow_settings
        return [
            (settings.smoke_injector_names[0], (0.0, 0.0, settings.source_z)),
            (settings.smoke_injector_names[1], (settings.source_offset, 0.0, settings.source_z)),
            (settings.smoke_injector_names[2], (-settings.source_offset, 0.0, settings.source_z)),
            (settings.smoke_injector_names[3], (0.0, settings.source_offset, settings.source_z)),
            (settings.smoke_injector_names[4], (0.0, -settings.source_offset, settings.source_z)),
        ]

    def _configure_smoke_injector(
        self,
        stage: Usd.Stage,
        prim_path: str,
        position: tuple[float, float, float],
        pulse_phase: int,
    ) -> None:
        settings = self._flow_settings
        shape = stage.GetPrimAtPath(prim_path)
        if shape.IsValid():
            xform_api = UsdGeom.XformCommonAPI(shape)
            xform_api.SetTranslate(position)
            xform_api.SetScale((settings.source_radius, settings.source_radius, settings.source_radius))

        emitter = stage.GetPrimAtPath(f"{prim_path}/EmitterSphere")
        if not emitter.IsValid():
            return

        self._set_attr_if_valid(emitter, "radius", 1.0)
        self._set_attr_if_valid(emitter, "radiusIsWorldSpace", False)
        self._set_attr_if_valid(emitter, "smoke", 0.14)
        self._set_attr_if_valid(emitter, "fuel", 0.20)
        self._set_attr_if_valid(emitter, "temperature", 0.55)
        self._set_attr_if_valid(emitter, "burn", 0.46)
        self._set_attr_if_valid(emitter, "coupleRateSmoke", 38.0)
        self._set_attr_if_valid(emitter, "coupleRateFuel", 34.0)
        self._set_attr_if_valid(emitter, "coupleRateTemperature", 44.0)
        self._set_attr_if_valid(emitter, "coupleRateBurn", 42.0)
        self._set_attr_if_valid(emitter, "coupleRateVelocity", 0.0)
        self._set_soft_pulse_attr_if_valid(emitter, "smoke", 0.11, 0.18, pulse_phase)
        self._set_soft_pulse_attr_if_valid(emitter, "fuel", 0.12, 0.24, pulse_phase)
        self._set_soft_pulse_attr_if_valid(emitter, "temperature", 0.42, 0.60, pulse_phase)
        self._set_soft_pulse_attr_if_valid(emitter, "burn", 0.30, 0.50, pulse_phase)

    def _set_soft_pulse_attr_if_valid(
        self,
        prim: Usd.Prim,
        name: str,
        low_value: float,
        high_value: float,
        phase: int,
        period: int = 150,
        end_frame: int = 1200,
    ) -> None:
        attr = prim.GetAttribute(name)
        if not attr or not attr.IsValid():
            return

        mid_value = (low_value + high_value) * 0.5
        attr.Set(mid_value, 0)
        for cycle in range(-1, end_frame // period + 3):
            start = cycle * period + phase
            samples = [
                (start, low_value),
                (start + period * 0.25, mid_value),
                (start + period * 0.50, high_value),
                (start + period * 0.75, mid_value),
                (start + period, low_value),
            ]
            for frame, value in samples:
                frame_i = int(round(frame))
                if 0 <= frame_i <= end_frame:
                    attr.Set(value, frame_i)

    def _set_attr_if_valid(self, prim: Usd.Prim, name: str, value, lock: bool = False) -> bool:
        if not prim or not prim.IsValid():
            return False
        attr = prim.GetAttribute(name)
        if not attr or not attr.IsValid():
            return False
        if attr.GetCustomDataByKey("omni:kit:locked"):
            return False
        attr.Set(value)
        if lock:
            attr.SetCustomDataByKey("omni:kit:locked", True)
        return True

    def _set_field_targets(
        self,
        field_selection_api,
        stage: Usd.Stage,
        dataset_path: str,
        field_name: str,
        prefer_scope: str | None = None,
    ):
        targets = self._field_targets(stage, dataset_path, field_name, prefer_scope=prefer_scope)
        if not targets:
            raise RuntimeError(f"Field {field_name!r} was not found under {dataset_path}")
        field_selection_api.GetTargetRel().SetTargets(targets)

    def _set_flow_velocity_targets(self, field_selection_api, stage: Usd.Stage, dataset_path: str) -> None:
        for field_name in ("U", "U_pred"):
            targets = self._field_targets(stage, dataset_path, field_name, prefer_scope="PointData")
            if targets:
                field_selection_api.GetTargetRel().SetTargets(targets)
                print(f"FAN_SIM_FLOW_VELOCITY_FIELD {field_name}", flush=True)
                return
        raise RuntimeError(f"Field 'U' or 'U_pred' was not found under {dataset_path}")

    def _field_targets(
        self,
        stage: Usd.Stage,
        dataset_path: str,
        field_name: str,
        prefer_scope: str | None = None,
    ) -> list[Sdf.Path]:
        root_path = Sdf.Path(dataset_path).GetParentPath()
        if prefer_scope:
            candidate = root_path.AppendChild(prefer_scope).AppendChild(field_name)
            if stage.GetPrimAtPath(candidate).IsValid():
                return [candidate]

        dataset_prim = stage.GetPrimAtPath(dataset_path)
        relationship = dataset_prim.GetRelationship(f"field:{field_name}")
        if relationship and relationship.IsValid():
            return list(relationship.GetTargets())

        for scope_name in ("PointData", "CellData"):
            candidate = root_path.AppendChild(scope_name).AppendChild(field_name)
            if stage.GetPrimAtPath(candidate).IsValid():
                return [candidate]
        return []

    def _viz_path(self, base_path: str, path_suffix: str = "") -> str:
        if not path_suffix:
            return base_path
        if base_path.startswith(f"{self.FLOW_PATH}/"):
            return f"{self.FLOW_PATH}{path_suffix}{base_path[len(self.FLOW_PATH):]}"
        if base_path.startswith(f"{self.FAN_ROOT_PATH}/"):
            return f"{self.FAN_ROOT_PATH}{path_suffix}{base_path[len(self.FAN_ROOT_PATH):]}"
        return f"{base_path}{path_suffix}"

    def _finalized_path(self, path: str, path_suffix: str) -> str:
        if not path_suffix:
            return path
        replacements = [
            (self.FAN_ROOT_PATH, self._viz_path(self.FAN_ROOT_PATH, path_suffix)),
            (self.SURFACE_PATH, self._viz_path(self.SURFACE_PATH, path_suffix)),
            (self.DATASET_ROOT_PATH, self._viz_path(self.DATASET_ROOT_PATH, path_suffix)),
            (self.STREAMLINES_PATH, self._viz_path(self.STREAMLINES_PATH, path_suffix)),
            (self.STREAMLINE_SEEDS_PATH, self._viz_path(self.STREAMLINE_SEEDS_PATH, path_suffix)),
            (self.FLOW_BOUNDING_BOX_PATH, self._viz_path(self.FLOW_BOUNDING_BOX_PATH, path_suffix)),
            (self.FLOW_PATH, self._viz_path(self.FLOW_PATH, path_suffix)),
        ]
        for final_path, pending_path in replacements:
            if path == pending_path or path.startswith(f"{pending_path}/"):
                return f"{final_path}{path[len(pending_path):]}"
        return path

    def _prediction_top_level_paths(self) -> list[str]:
        return [
            self.SURFACE_PATH,
            self.DATASET_ROOT_PATH,
            self.STREAMLINES_PATH,
            self.STREAMLINE_SEEDS_PATH,
            self.FLOW_BOUNDING_BOX_PATH,
        ]

    def _remove_prediction_paths(self, stage: Usd.Stage, path_suffix: str = "") -> None:
        for base_path in self._prediction_top_level_paths():
            path = self._viz_path(base_path, path_suffix)
            if stage.GetPrimAtPath(path).IsValid():
                stage.RemovePrim(Sdf.Path(path))

    def _promote_prediction_paths(self, stage: Usd.Stage, path_suffix: str) -> None:
        if not path_suffix:
            return

        edits = Sdf.BatchNamespaceEdit()
        has_edits = False
        for base_path in self._prediction_top_level_paths():
            pending_path = self._viz_path(base_path, path_suffix)
            if not stage.GetPrimAtPath(pending_path).IsValid():
                continue
            if stage.GetPrimAtPath(base_path).IsValid():
                stage.RemovePrim(Sdf.Path(base_path))
            edits.Add(Sdf.NamespaceEdit.Rename(Sdf.Path(pending_path), Sdf.Path(base_path).name))
            has_edits = True

        if has_edits and not stage.GetRootLayer().Apply(edits):
            raise RuntimeError("Could not promote pending Fan-Sim prims into the active scene.")
        self._retarget_promoted_relationships(stage, path_suffix)

    def _retarget_promoted_relationships(self, stage: Usd.Stage, path_suffix: str) -> None:
        roots = [
            stage.GetPrimAtPath("/World/CAE"),
            stage.GetPrimAtPath(self.DATASET_ROOT_PATH),
            stage.GetPrimAtPath(self.FAN_ROOT_PATH),
        ]
        for root in roots:
            if not root.IsValid():
                continue
            for prim in Usd.PrimRange(root):
                for relationship in prim.GetRelationships():
                    targets = relationship.GetTargets()
                    if not targets:
                        continue
                    updated_targets = [Sdf.Path(self._finalized_path(str(target), path_suffix)) for target in targets]
                    if updated_targets != targets:
                        relationship.SetTargets(updated_targets)

    def _find_dataset_prim(self, root_prim: Usd.Prim) -> Usd.Prim | None:
        try:
            from omni.cae.schema import cae
        except Exception:
            return None

        for prim in Usd.PrimRange(root_prim):
            if prim.IsA(cae.DataSet):
                return prim
        return None

    def _ensure_static_fan_mesh(self, stage: Usd.Stage, fan_mesh_usd: str, path_suffix: str = "") -> None:
        if not fan_mesh_usd:
            return
        fan_mesh_path = Path(fan_mesh_usd)
        if not fan_mesh_path.exists():
            return
        stage_path = self._viz_path(self.FAN_ROOT_PATH, path_suffix)
        existing_fan = stage.GetPrimAtPath(stage_path)
        existing_mesh = stage.GetPrimAtPath(self._viz_path(self.FAN_MESH_PATH, path_suffix))
        if existing_fan.IsValid() and existing_mesh.IsValid():
            self._style_fan_mesh(stage, path_suffix=path_suffix)
            self._set_visibility(stage, stage_path, True)
            return

        prim = UsdGeom.Xform.Define(stage, stage_path).GetPrim()
        if not existing_fan.IsValid():
            UsdGeom.XformCommonAPI(prim).SetScale((self.DEMO_SCALE, self.DEMO_SCALE, self.DEMO_SCALE))
        references = prim.GetReferences()
        references.ClearReferences()
        references.AddReference(fan_mesh_path.as_posix(), "/OpenFOAMCase")
        self._style_fan_mesh(stage, path_suffix=path_suffix)
        self._set_visibility(stage, stage_path, True)

    def _style_fan_mesh(self, stage: Usd.Stage, path_suffix: str = "") -> None:
        mesh_prim = stage.GetPrimAtPath(self._viz_path(self.FAN_MESH_PATH, path_suffix))
        if not mesh_prim.IsValid():
            return

        material = UsdShade.Material.Define(stage, "/World/Looks/FanSimFanMaterial")
        shader = UsdShade.Shader.Define(stage, "/World/Looks/FanSimFanMaterial/PreviewSurface")
        shader.CreateIdAttr("UsdPreviewSurface")
        shader.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(0.76, 0.80, 0.78))
        shader.CreateInput("opacity", Sdf.ValueTypeNames.Float).Set(0.75)
        shader.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(0.82)
        material.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), "surface")
        UsdShade.MaterialBindingAPI(mesh_prim).Bind(material)

        mesh = UsdGeom.Mesh(mesh_prim)
        mesh.CreateDoubleSidedAttr(True)
        mesh.CreateDisplayColorPrimvar(UsdGeom.Tokens.constant).Set([Gf.Vec3f(0.76, 0.80, 0.78)])
        mesh.CreateDisplayOpacityAttr().Set([0.75])

        wire_prim = stage.GetPrimAtPath(self._viz_path(self.FAN_WIREFRAME_PATH, path_suffix))
        if wire_prim.IsValid():
            curves = UsdGeom.BasisCurves(wire_prim)
            curves.CreateDisplayColorAttr().Set([Gf.Vec3f(0.12, 0.15, 0.15)])
            curves.CreateDisplayOpacityAttr().Set([0.20])

    def _ensure_lighting(self, stage: Usd.Stage) -> None:
        dome = UsdLux.DomeLight.Define(stage, "/World/FanSimDomeLight")
        dome.CreateIntensityAttr(650.0)
        distant = UsdLux.DistantLight.Define(stage, "/World/FanSimKeyLight")
        distant.CreateIntensityAttr(3500.0)
        UsdGeom.XformCommonAPI(distant.GetPrim()).SetRotate(
            (-45.0, 0.0, -35.0),
            UsdGeom.XformCommonAPI.RotationOrderXYZ,
        )

    async def _frame_prediction(self, stage: Usd.Stage, prim_path: str | list[str]) -> None:
        prim_paths = [prim_path] if isinstance(prim_path, str) else list(prim_path)
        prim_paths = [path for path in prim_paths if path and stage.GetPrimAtPath(path).IsValid()]
        if not prim_paths:
            return
        try:
            from omni.cae.data.commands import execute_command
            from omni.kit.viewport.utility import get_active_viewport
        except Exception:
            return

        viewport = None
        for _ in range(60):
            viewport = get_active_viewport()
            if viewport is not None and viewport.camera_path:
                break
            await self._wait_updates(1)
        if viewport is None or not viewport.camera_path:
            print("FAN_SIM_FRAME_SKIP no_active_viewport", flush=True)
            return
        await execute_command("FramePrimsCommand", prim_to_move=viewport.camera_path, prims_to_frame=prim_paths, zoom=1.15)
        omni.usd.get_context().get_selection().set_selected_prim_paths([], True)
        await self._wait_updates(3)
        print(f"FAN_SIM_FRAME_OK paths={prim_paths}", flush=True)

    def _frame_paths(self, visible_anchor: str) -> list[str]:
        paths = []
        for path in (visible_anchor, self.FAN_MESH_PATH, self.FAN_WIREFRAME_PATH):
            if path and path not in paths:
                paths.append(path)
        if self._streamlines_model.get_value_as_bool():
            paths.append(self.STREAMLINES_PATH)
        if self._cae_flow_model.get_value_as_bool():
            paths.append(self.FLOW_PATH)
        return paths or [self.FAN_MESH_PATH]

    async def _set_demo_camera(self, stage: Usd.Stage) -> None:
        try:
            from omni.kit.viewport.utility import get_active_viewport
        except Exception:
            return

        camera = UsdGeom.Camera.Define(stage, "/World/FanSimCamera")
        camera.CreateClippingRangeAttr(Gf.Vec2f(0.001, 1000.0))
        camera.CreateFocalLengthAttr(32.0)

        view = Gf.Matrix4d(1.0)
        view.SetLookAt(Gf.Vec3d(3.0, -6.2, 2.0), Gf.Vec3d(0.0, 0.0, 0.0), Gf.Vec3d(0.0, 0.0, 1.0))
        xformable = UsdGeom.Xformable(camera.GetPrim())
        xformable.ClearXformOpOrder()
        xformable.AddTransformOp().Set(view.GetInverse())

        viewport = get_active_viewport()
        if viewport is not None:
            viewport.camera_path = str(camera.GetPath())

    def _ensure_world_and_cae(self, stage: Usd.Stage) -> None:
        if not stage.GetPrimAtPath("/World").IsValid():
            world = UsdGeom.Xform.Define(stage, "/World")
            stage.SetDefaultPrim(world.GetPrim())
        cae = UsdGeom.Xform.Define(stage, "/World/CAE")
        UsdGeom.XformCommonAPI(cae.GetPrim()).SetScale((self.DEMO_SCALE, self.DEMO_SCALE, self.DEMO_SCALE))
        if not stage.GetPrimAtPath(self.FAN_ROOT_PATH).IsValid():
            fan = UsdGeom.Xform.Define(stage, self.FAN_ROOT_PATH)
            UsdGeom.XformCommonAPI(fan.GetPrim()).SetScale((self.DEMO_SCALE, self.DEMO_SCALE, self.DEMO_SCALE))

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
