from pathlib import Path

import numpy as np

from fan_sim.config import load_config
from fan_sim.ml import training
from fan_sim.ml.dataset import save_graph_sample


def _sample() -> dict:
    return {
        "schema_version": "fan-sim-graph-v1",
        "x": np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32),
        "edge_attr": np.array([[1.0, 0.0, 0.0, 1.0], [-1.0, 0.0, 0.0, 1.0]], dtype=np.float32),
        "edge_index": np.array([[0, 1], [1, 0]], dtype=np.int64),
        "y": np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float32),
    }


def test_train_from_graphs_skips_existing_complete_numpy_checkpoint(monkeypatch, tmp_path: Path):
    cfg_path = tmp_path / "fan_sim.yaml"
    cfg_path.write_text(
        """
base_case: data/base_case
case_matrix:
  rpm: [600]
  outlet_pressure: [0]
model:
  backend: numpy
  output_dir: artifacts/models/test_model
""",
        encoding="utf-8",
    )
    graph_path = tmp_path / "artifacts" / "graphs" / "case.graph.pt"
    save_graph_sample(_sample(), graph_path)
    cfg = load_config(cfg_path)

    checkpoint = training.train_from_graphs(cfg, [graph_path], epochs=1)

    def fail_fit(self, samples):
        raise AssertionError("fit should not run when checkpoint already covers requested epochs")

    monkeypatch.setattr(training.NumpyLinearSurrogate, "fit", fail_fit)

    assert training.train_from_graphs(cfg, [graph_path], epochs=1) == checkpoint

