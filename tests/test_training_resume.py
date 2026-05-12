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


def test_induced_subgraph_remaps_edges():
    sample = {
        "schema_version": "fan-sim-graph-v1",
        "x": np.arange(12, dtype=np.float32).reshape(4, 3),
        "pos": np.arange(12, dtype=np.float32).reshape(4, 3),
        "y": np.arange(8, dtype=np.float32).reshape(4, 2),
        "edge_index": np.array([[0, 1, 1, 2, 2, 3], [1, 0, 2, 1, 3, 2]], dtype=np.int64),
        "edge_attr": np.arange(24, dtype=np.float32).reshape(6, 4),
    }

    sampled = training._induced_subgraph(sample, np.array([1, 2], dtype=np.int64))

    assert sampled["x"].shape == (2, 3)
    assert sampled["edge_index"].tolist() == [[0, 1], [1, 0]]
    assert sampled["edge_attr"].shape == (2, 4)


def test_completed_epochs_requires_matching_model_config(tmp_path: Path):
    cfg_path = tmp_path / "fan_sim.yaml"
    cfg_path.write_text(
        """
base_case: data/base_case
case_matrix:
  rpm: [600]
  outlet_pressure: [0]
model:
  backend: physicsnemo
  output_dir: artifacts/models/test_model
  processor_size: 3
  hidden_dim: 32
  max_nodes_per_graph: 1000
  sample_seed: 42
""",
        encoding="utf-8",
    )
    cfg = load_config(cfg_path)
    previous = {
        "backend": "physicsnemo",
        "graphs": ["a.graph.pt"],
        "processor_size": 3,
        "hidden_dim": 32,
        "max_nodes_per_graph": 1000,
        "sample_seed": 42,
        "completed_epochs": 7,
    }

    assert training._completed_epochs(previous, cfg, ["a.graph.pt"]) == 7
    assert training._completed_epochs({**previous, "hidden_dim": 16}, cfg, ["a.graph.pt"]) == 0
