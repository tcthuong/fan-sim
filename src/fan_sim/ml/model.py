from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np


class NumpyLinearSurrogate:
    """Small smoke-test backend used when PhysicsNeMo/PyTorch is unavailable."""

    backend = "numpy-linear"

    def __init__(self, weights: np.ndarray | None = None):
        self.weights = weights

    def fit(self, samples: list[dict[str, Any]]) -> None:
        x = np.concatenate([np.asarray(sample["x"], dtype=np.float32) for sample in samples], axis=0)
        y = np.concatenate([np.asarray(sample["y"], dtype=np.float32) for sample in samples], axis=0)
        x_aug = np.concatenate([x, np.ones((x.shape[0], 1), dtype=np.float32)], axis=1)
        self.weights = np.linalg.pinv(x_aug) @ y

    def predict(self, sample: dict[str, Any]) -> np.ndarray:
        if self.weights is None:
            raise RuntimeError("NumpyLinearSurrogate has not been fitted.")
        x = np.asarray(sample["x"], dtype=np.float32)
        x_aug = np.concatenate([x, np.ones((x.shape[0], 1), dtype=np.float32)], axis=1)
        return (x_aug @ self.weights).astype(np.float32)

    def save(self, path: str | Path) -> None:
        if self.weights is None:
            raise RuntimeError("Cannot save an unfitted model.")
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        np.savez(output, backend=self.backend, weights=self.weights)

    @classmethod
    def load(cls, path: str | Path) -> "NumpyLinearSurrogate":
        data = np.load(path, allow_pickle=False)
        return cls(weights=np.asarray(data["weights"], dtype=np.float32))


@dataclass
class PhysicsNeMoModelConfig:
    input_dim_nodes: int
    input_dim_edges: int
    output_dim: int = 4
    processor_size: int = 15
    hidden_dim: int = 128


def require_physicsnemo_meshgraphnet(config: PhysicsNeMoModelConfig):
    try:
        import torch
        from torch_geometric.data import Data
        from physicsnemo.models.meshgraphnet.meshgraphnet import MeshGraphNet
    except ImportError as exc:
        raise RuntimeError(
            "PhysicsNeMo training requires optional ML dependencies: "
            "pip install -e .[ml]. For smoke tests, use model.backend=numpy."
        ) from exc

    model = MeshGraphNet(
        input_dim_nodes=config.input_dim_nodes,
        input_dim_edges=config.input_dim_edges,
        output_dim=config.output_dim,
        processor_size=config.processor_size,
        hidden_dim_node_encoder=config.hidden_dim,
        hidden_dim_edge_encoder=config.hidden_dim,
        hidden_dim_node_decoder=config.hidden_dim,
    )
    return torch, Data, model

