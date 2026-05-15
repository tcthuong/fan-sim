import importlib.util
from pathlib import Path


def _load_helpers():
    helper_path = Path("extensions/omni.fan_sim/omni/fan_sim/extension_config.py")
    spec = importlib.util.spec_from_file_location("fan_sim_extension_config", helper_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_load_rpm_values_from_config(tmp_path: Path):
    helpers = _load_helpers()
    cfg = tmp_path / "fan_sim.yaml"
    cfg.write_text(
        """
base_case: data/base_case
case_matrix:
  rpm: [1, 300, 600, 1200]
  outlet_pressure: [0]
""",
        encoding="utf-8",
    )

    assert helpers.load_rpm_values(cfg) == [1.0, 300.0, 600.0, 1200.0]
    assert helpers.rpm_slider_spec([1.0, 300.0, 600.0, 1200.0]).minimum == 1.0
    assert helpers.rpm_slider_spec([1.0, 300.0, 600.0, 1200.0]).maximum == 1200.0


def test_predict_payload_tracks_visualization_toggles():
    helpers = _load_helpers()

    payload = helpers.build_predict_payload(
        case_id="fan_base",
        rpm=800.0,
        outlet_pressure=20.0,
        show_streamlines=True,
        show_cae_flow=False,
    )

    assert payload["rpm"] == 800.0
    assert payload["outputs"] == ["vtu", "usd", "streamlines"]

    payload = helpers.build_predict_payload(
        case_id="fan_base",
        rpm=800.0,
        outlet_pressure=20.0,
        show_streamlines=True,
        show_cae_flow=True,
    )

    assert payload["outputs"] == ["vtu", "usd", "streamlines", "particles"]


def test_default_kit_visual_settings_use_fan_scale_values():
    helpers = _load_helpers()

    streamlines = helpers.default_streamline_settings()
    flow = helpers.default_flow_settings()

    assert streamlines.color_field == "velocity_magnitude"
    assert streamlines.color_range == (0.0, 300.0)
    assert streamlines.initial_step_size == 0.005
    assert streamlines.max_step_size == 0.015
    assert streamlines.max_steps == 900
    assert streamlines.direction == "forward"
    assert streamlines.width == 0.00028
    assert streamlines.seed_resolution == 24
    assert streamlines.seed_translation == (0.0, 0.0, 0.085)
    assert streamlines.seed_scale == (0.032, 0.032, 0.003)

    assert flow.velocity_scale == 0.12
    assert flow.velocity_couple_rate == 80.0
    assert flow.voxel_max_resolution == 128
    assert flow.inflate_bounds == 2.0
    assert flow.density_cell_size == 0.01
    assert flow.ray_attenuation == 3.0
    assert flow.ray_color_scale == 10.0
    assert flow.source_radius == 0.0055
    assert flow.source_offset == 0.010
    assert len(flow.smoke_injector_names) == 5


def test_default_extension_runtime_settings_debounce_auto_predict():
    helpers = _load_helpers()

    runtime = helpers.default_runtime_settings()

    assert runtime.auto_predict_on_startup is True
    assert 0.5 <= runtime.debounce_seconds <= 0.8
    assert runtime.pending_suffix == ""


def test_extension_uses_usd_streamline_artifact_and_native_cae_flow():
    text = Path("extensions/omni.fan_sim/omni/fan_sim/extension.py").read_text(encoding="utf-8")

    assert "CreateCaeVizBoundingBox" in text
    assert "CreateCaeVizFlowSmokeInjector" in text
    assert "CreateCaeVizFlowBoundaryEmitter" in text
    assert "CreateCaeVizFlowDataSetEmitter" in text
    assert "coupleRateVelocity" in text
    assert "velocityIsWorldSpace" in text
    assert "applyPostPressure" in text
    assert "_set_flow_velocity_targets" in text
    assert 'for field_name in ("U", "U_pred")' in text
    assert "flowOffscreen/colormap" in text
    assert "CreateExternalOnlyAttr().Set(True)" not in text
    assert "FAN_SIM_FLOW_CONFIGURED" in text
    assert "prediction_streamlines_usd" in text
    assert "prediction_particles_usd" not in text
    assert "_reference_streamline_artifact" in text


def test_extension_loads_dataset_before_creating_native_cae_visuals():
    text = Path("extensions/omni.fan_sim/omni/fan_sim/extension.py").read_text(encoding="utf-8")

    load_dataset = text.index("stage, dataset_prim = await self._load_prediction_dataset")
    configure_visuals = text.index("await self._ensure_requested_visuals(")
    promote_paths = text.index("self._promote_prediction_paths(stage, suffix)")
    assert load_dataset < configure_visuals
    assert load_dataset < configure_visuals < promote_paths


def test_extension_keeps_cae_flow_prim_when_slider_reloads_dataset():
    text = Path("extensions/omni.fan_sim/omni/fan_sim/extension.py").read_text(encoding="utf-8")

    assert 'pending_suffix=""' in Path("extensions/omni.fan_sim/omni/fan_sim/extension_config.py").read_text(
        encoding="utf-8"
    )
    cleanup_start = text.index("def _prediction_top_level_paths")
    cleanup_end = text.index("def _remove_prediction_paths")
    cleanup_block = text[cleanup_start:cleanup_end]

    assert "self.FLOW_PATH" not in cleanup_block
    assert "self.FLOW_BOUNDING_BOX_PATH" in cleanup_block
    assert "self._ensure_static_fan_mesh(stage, fan_mesh_usd)" in text
    assert "self._ensure_static_fan_mesh(stage, fan_mesh_usd, path_suffix=path_suffix)" not in text


def test_extension_uses_reference_fan_case_paths_and_demo_scale():
    text = Path("extensions/omni.fan_sim/omni/fan_sim/extension.py").read_text(encoding="utf-8")

    assert 'DATASET_ROOT_PATH = "/World/FanCase"' in text
    assert 'FAN_ROOT_PATH = "/World/Fan"' in text
    assert 'FAN_MESH_PATH = "/World/Fan/FanMesh"' in text
    assert 'FAN_WIREFRAME_PATH = "/World/Fan/FanMeshWire"' in text
    assert 'FLOW_PATH = "/World/CAE/FlowSimulation_L0"' in text
    assert 'FLOW_DATASET_EMITTER_PATH = "/World/CAE/FlowSimulation_L0/DataSetInjector"' in text
    assert "DEMO_SCALE = 8.0" in text
    assert "SetScale((self.DEMO_SCALE, self.DEMO_SCALE, self.DEMO_SCALE))" in text


def test_extension_uses_point_fields_for_vector_advection_visuals():
    text = Path("extensions/omni.fan_sim/omni/fan_sim/extension.py").read_text(encoding="utf-8")

    assert "prefer_scope: str | None = None" in text
    assert text.count('prefer_scope="PointData"') >= 3


def test_extension_places_streamline_seed_directly_in_data_coordinates():
    text = Path("extensions/omni.fan_sim/omni/fan_sim/extension.py").read_text(encoding="utf-8")

    assert "new_translation=list(settings.seed_translation)" in text
    assert "new_scale=list(settings.seed_scale)" in text
    assert "_data_to_scaled_scene_tuple" not in text


def test_extension_keeps_fan_static_across_predictions():
    text = Path("extensions/omni.fan_sim/omni/fan_sim/extension.py").read_text(encoding="utf-8")

    cleanup_start = text.index("def _prediction_top_level_paths")
    cleanup_end = text.index("def _remove_prediction_paths")
    cleanup_block = text[cleanup_start:cleanup_end]

    assert "self.FAN_ROOT_PATH" not in cleanup_block
    assert "def _ensure_static_fan_mesh" in text


def test_extension_does_not_render_debug_domain_box():
    text = Path("extensions/omni.fan_sim/omni/fan_sim/extension.py").read_text(encoding="utf-8")

    assert "FanSimDomainBox" not in text
    assert "_ensure_domain_box" not in text


def test_extension_removes_prediction_visuals_but_not_fan():
    text = Path("extensions/omni.fan_sim/omni/fan_sim/extension.py").read_text(encoding="utf-8")

    cleanup_start = text.index("def _prediction_top_level_paths")
    cleanup_end = text.index("def _remove_prediction_paths")
    cleanup_block = text[cleanup_start:cleanup_end]

    assert "self.FAN_ROOT_PATH" not in cleanup_block


def test_extension_clears_selection_after_camera_frame():
    text = Path("extensions/omni.fan_sim/omni/fan_sim/extension.py").read_text(encoding="utf-8")

    frame_start = text.index("async def _frame_prediction")
    frame_end = text.index("def _frame_paths")
    frame_block = text[frame_start:frame_end]

    assert "set_selected_prim_paths([], True)" in frame_block


def test_extension_frames_cae_flow_when_flow_is_enabled():
    text = Path("extensions/omni.fan_sim/omni/fan_sim/extension.py").read_text(encoding="utf-8")

    frame_paths_start = text.index("def _frame_paths")
    frame_paths_end = text.index("async def _set_demo_camera")
    frame_paths_block = text[frame_paths_start:frame_paths_end]

    assert "self._cae_flow_model.get_value_as_bool()" in frame_paths_block
    assert "self.FLOW_PATH" in frame_paths_block


def test_streamline_defaults_avoid_reverse_column_and_white_overdraw():
    helpers = _load_helpers()

    settings = helpers.default_streamline_settings()

    assert settings.direction == "forward"
    assert settings.seed_resolution <= 24
    assert settings.seed_translation[2] > 0.0
    assert settings.seed_scale[2] < 0.01
    assert settings.width <= 0.00035
    assert settings.color_range == (0.0, 300.0)
