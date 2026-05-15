from pathlib import Path

from scripts.static_predict_server import build_static_response


def test_static_predict_response_includes_precomputed_visual_usd_assets(tmp_path: Path):
    for name in (
        "prediction.vtu",
        "prediction.usda",
        "fan_mesh.usda",
        "prediction_streamlines.usda",
        "prediction_particles.usda",
    ):
        (tmp_path / name).write_text("", encoding="utf-8")

    body = build_static_response(tmp_path)

    assert body["prediction_vtu"].endswith("prediction.vtu")
    assert body["prediction_streamlines_usd"].endswith("prediction_streamlines.usda")
    assert body["prediction_particles_usd"].endswith("prediction_particles.usda")
    assert body["fan_mesh_usd"].endswith("fan_mesh.usda")


def test_static_predict_response_prefers_full_prediction_vtu_over_preview(tmp_path: Path):
    for name in ("prediction.vtu", "prediction_preview.vtu", "prediction.usda"):
        (tmp_path / name).write_text("", encoding="utf-8")

    body = build_static_response(tmp_path)

    assert body["prediction_vtu"].endswith("prediction.vtu")
