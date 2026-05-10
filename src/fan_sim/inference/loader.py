from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from fan_sim.config import FanSimConfig
from fan_sim.inference.predictor import FanPredictor
from fan_sim.ml.dataset import load_graph_sample
from fan_sim.ml.model import NumpyLinearSurrogate, PhysicsNeMoModelConfig, require_physicsnemo_meshgraphnet
from fan_sim.ml.normalizer import GraphNormalizer


def load_predictor_from_artifacts(config: FanSimConfig, case_id: str) -> FanPredictor:
    template = _load_template_sample(config.root / "artifacts" / "graphs", case_id)
    normalizer = GraphNormalizer.load(config.model.output_dir / "normalizer.json")
    if config.model.backend == "numpy":
        model = NumpyLinearSurrogate.load(config.model.output_dir / "checkpoint.npz")
    elif config.model.backend == "physicsnemo":
        model = _load_physicsnemo_predict_model(config.model.output_dir / "checkpoint.pt", template)
    else:
        raise ValueError(f"Unsupported model backend: {config.model.backend}")
    return FanPredictor(model=model, template_sample=template, normalizer=normalizer)


def _load_template_sample(graph_dir: Path, case_id: str) -> dict[str, Any]:
    candidates = [
        graph_dir / f"{case_id}.graph.pt",
        graph_dir / f"{case_id}.pt",
        *sorted(graph_dir.glob(f"{case_id}*.graph.pt")),
    ]
    for candidate in candidates:
        if candidate.exists():
            return load_graph_sample(candidate)
    raise FileNotFoundError(f"No graph template found for case_id={case_id!r} under {graph_dir}")


class _PhysicsNeMoPredictModel:
    def __init__(self, checkpoint: Path, template: dict[str, Any]):
        import torch

        self.torch = torch
        torch_module, Data, model = require_physicsnemo_meshgraphnet(
            PhysicsNeMoModelConfig(
                input_dim_nodes=int(template["x"].shape[1]),
                input_dim_edges=int(template["edge_attr"].shape[1]),
                output_dim=4,
            )
        )
        self.Data = Data
        self.device = "cuda" if torch_module.cuda.is_available() else "cpu"
        payload = torch_module.load(checkpoint, map_location=self.device)
        model.load_state_dict(payload["state_dict"] if "state_dict" in payload else payload)
        self.model = model.to(self.device)
        self.model.eval()

    def predict(self, sample: dict[str, Any]) -> np.ndarray:
        torch = self.torch
        graph = self.Data(
            edge_index=torch.as_tensor(sample["edge_index"], dtype=torch.long, device=self.device),
            num_nodes=int(sample["x"].shape[0]),
        )
        x = torch.as_tensor(np.asarray(sample["x"]), dtype=torch.float32, device=self.device)
        edge_attr = torch.as_tensor(np.asarray(sample["edge_attr"]), dtype=torch.float32, device=self.device)
        with torch.no_grad():
            pred = self.model(x, edge_attr, graph)
        return pred.detach().cpu().numpy()


def _load_physicsnemo_predict_model(checkpoint: Path, template: dict[str, Any]) -> _PhysicsNeMoPredictModel:
    if not checkpoint.exists():
        raise FileNotFoundError(f"PhysicsNeMo checkpoint not found: {checkpoint}")
    return _PhysicsNeMoPredictModel(checkpoint, template)

