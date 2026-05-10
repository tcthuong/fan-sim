from __future__ import annotations

from pathlib import Path

import numpy as np
import yaml

from fan_sim.config import FanSimConfig
from fan_sim.ml.dataset import load_graph_sample
from fan_sim.ml.model import NumpyLinearSurrogate, PhysicsNeMoModelConfig, require_physicsnemo_meshgraphnet
from fan_sim.ml.normalizer import GraphNormalizer


def train_from_graphs(config: FanSimConfig, graph_paths: list[Path], epochs: int = 1) -> Path:
    if not graph_paths:
        raise ValueError("No graph paths supplied for training.")
    samples = [load_graph_sample(path) for path in graph_paths]
    normalizer = GraphNormalizer.fit(samples)
    normalized_samples = [normalizer.transform(sample) for sample in samples]

    output_dir = config.model.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    normalizer.save(output_dir / "normalizer.json")

    if config.model.backend == "numpy":
        model = NumpyLinearSurrogate()
        model.fit(normalized_samples)
        checkpoint = output_dir / "checkpoint.npz"
        model.save(checkpoint)
    elif config.model.backend == "physicsnemo":
        checkpoint = _train_physicsnemo(normalized_samples, output_dir, epochs)
    else:
        raise ValueError(f"Unsupported model backend: {config.model.backend}")

    (output_dir / "train_config.yaml").write_text(
        yaml.safe_dump({"backend": config.model.backend, "epochs": epochs, "graphs": [str(p) for p in graph_paths]}),
        encoding="utf-8",
    )
    return checkpoint


def _train_physicsnemo(samples: list[dict], output_dir: Path, epochs: int) -> Path:
    first = samples[0]
    torch, Data, model = require_physicsnemo_meshgraphnet(
        PhysicsNeMoModelConfig(
            input_dim_nodes=int(first["x"].shape[1]),
            input_dim_edges=int(first["edge_attr"].shape[1]),
            output_dim=int(first["y"].shape[1]),
        )
    )
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = model.to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-4)
    loss_fn = torch.nn.MSELoss()

    for _ in range(epochs):
        model.train()
        for sample in samples:
            graph = Data(
                edge_index=torch.as_tensor(sample["edge_index"], dtype=torch.long, device=device),
                num_nodes=int(sample["x"].shape[0]),
            )
            x = torch.as_tensor(np.asarray(sample["x"]), dtype=torch.float32, device=device)
            edge_attr = torch.as_tensor(np.asarray(sample["edge_attr"]), dtype=torch.float32, device=device)
            y = torch.as_tensor(np.asarray(sample["y"]), dtype=torch.float32, device=device)
            optimizer.zero_grad()
            pred = model(x, edge_attr, graph)
            loss = loss_fn(pred, y)
            loss.backward()
            optimizer.step()

    checkpoint = output_dir / "checkpoint.pt"
    torch.save({"backend": "physicsnemo", "state_dict": model.state_dict()}, checkpoint)
    return checkpoint

