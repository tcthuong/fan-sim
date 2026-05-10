from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient

from fan_sim.export.artifacts import export_prediction_artifacts
from fan_sim.config import FanSimConfig, CaseMatrix, ModelConfig
from fan_sim.inference.predictor import FanPredictor
from fan_sim.inference.loader import load_predictor_from_artifacts
from fan_sim.ml.dataset import save_graph_sample
from fan_sim.ml.model import NumpyLinearSurrogate
from fan_sim.ml.normalizer import GraphNormalizer
from fan_sim.service.app import create_app


class ConstantModel:
    def predict(self, sample):
        return np.array([[3.0, 0.0, 0.0, 30.0], [0.0, 4.0, 0.0, 40.0]], dtype=np.float32)


def _sample():
    return {
        "x": np.zeros((2, 10), dtype=np.float32),
        "edge_index": np.array([[0, 1], [1, 0]], dtype=np.int64),
        "edge_attr": np.ones((2, 4), dtype=np.float32),
        "pos": np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]], dtype=np.float32),
        "case_meta": {"case_id": "fan_base"},
        "schema_version": "fan-sim-graph-v1",
    }


def test_predictor_updates_operating_condition_and_returns_fields():
    predictor = FanPredictor(model=ConstantModel(), template_sample=_sample(), normalizer=None)

    result = predictor.predict(rpm=1500, inlet_pressure=0.0, outlet_pressure=25.0)

    assert result.prediction.shape == (2, 4)
    assert result.sample["case_meta"]["rpm"] == 1500
    assert result.sample["case_meta"]["outlet_pressure"] == 25.0
    assert result.fields == ["U_pred", "p_pred", "velocity_magnitude"]


def test_export_prediction_artifacts_writes_usd_and_seed_files(tmp_path: Path):
    predictor = FanPredictor(model=ConstantModel(), template_sample=_sample(), normalizer=None)
    result = predictor.predict(rpm=1500, inlet_pressure=0.0, outlet_pressure=25.0)

    artifacts = export_prediction_artifacts(result, output_dir=tmp_path, write_vtu=False)

    assert artifacts.prediction_usd.exists()
    assert artifacts.streamline_seeds_json.exists()
    assert artifacts.particle_seeds_json.exists()
    assert "rpm = 1500" in artifacts.prediction_usd.read_text(encoding="utf-8")


def test_service_predict_endpoint_returns_artifact_paths(tmp_path: Path):
    predictor = FanPredictor(model=ConstantModel(), template_sample=_sample(), normalizer=None)
    app = create_app(predictor=predictor, output_root=tmp_path, write_vtu=False)
    client = TestClient(app)

    response = client.post(
        "/predict",
        json={
            "case_id": "fan_base",
            "rpm": 1500,
            "inlet_pressure": 0,
            "outlet_pressure": 25,
            "outputs": ["usd", "streamlines", "particles"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["prediction_usd"].endswith("prediction.usda")
    assert body["fields"] == ["U_pred", "p_pred", "velocity_magnitude"]
    assert Path(body["prediction_usd"]).exists()


def test_load_predictor_from_artifacts_uses_saved_template_normalizer_and_numpy_checkpoint(tmp_path: Path):
    graph_dir = tmp_path / "artifacts" / "graphs"
    model_dir = tmp_path / "artifacts" / "models" / "fan_mgn"
    sample = _sample()
    sample["y"] = np.array([[3.0, 0.0, 0.0, 30.0], [0.0, 4.0, 0.0, 40.0]], dtype=np.float32)
    save_graph_sample(sample, graph_dir / "fan_base.graph.pt")
    normalizer = GraphNormalizer.fit([sample])
    normalizer.save(model_dir / "normalizer.json")
    normalized = normalizer.transform(sample)
    model = NumpyLinearSurrogate()
    model.fit([normalized])
    model.save(model_dir / "checkpoint.npz")
    cfg = FanSimConfig(
        base_case=tmp_path / "data" / "base_case",
        case_matrix=CaseMatrix(rpm=[1200], outlet_pressure=[20]),
        model=ModelConfig(backend="numpy", output_dir=model_dir),
        root=tmp_path,
    )

    predictor = load_predictor_from_artifacts(cfg, case_id="fan_base")
    result = predictor.predict(rpm=1500, inlet_pressure=0.0, outlet_pressure=25.0)

    assert result.prediction.shape == (2, 4)
    assert result.sample["case_meta"]["rpm"] == 1500
