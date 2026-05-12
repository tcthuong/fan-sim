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
