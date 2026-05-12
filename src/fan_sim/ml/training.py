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
    output_dir = config.model.output_dir
    checkpoint = _checkpoint_path(config)
    train_config_path = output_dir / "train_config.yaml"
    graph_list = [str(p) for p in graph_paths]
    previous = _read_train_config(train_config_path)
    if (
        checkpoint.exists()
        and (output_dir / "normalizer.json").exists()
        and previous.get("backend") == config.model.backend
        and previous.get("graphs") == graph_list
        and previous.get("processor_size") == config.model.processor_size
        and previous.get("hidden_dim") == config.model.hidden_dim
        and previous.get("max_nodes_per_graph") == config.model.max_nodes_per_graph
        and previous.get("sample_seed") == config.model.sample_seed
        and int(previous.get("epochs", 0)) >= epochs
    ):
        print(f"{checkpoint}: existing checkpoint covers epochs={epochs}; skipping training.", flush=True)
        return checkpoint

    print(
        "Training setup: "
        f"backend={config.model.backend}, graphs={len(graph_paths)}, epochs={epochs}, "
        f"processor_size={config.model.processor_size}, hidden_dim={config.model.hidden_dim}, "
        f"max_nodes_per_graph={config.model.max_nodes_per_graph}",
        flush=True,
    )
    samples = [_sample_for_training(config, load_graph_sample(path), index) for index, path in enumerate(graph_paths)]
    _log_sample_summary(samples)
    normalizer = GraphNormalizer.fit(samples)
    normalized_samples = [normalizer.transform(sample) for sample in samples]

    output_dir.mkdir(parents=True, exist_ok=True)
    normalizer.save(output_dir / "normalizer.json")
    previous_epochs = _completed_epochs(previous, config, graph_list)
    epochs_to_run = max(epochs - previous_epochs, 0)
    _write_train_config(config, train_config_path, graph_list, requested_epochs=epochs, completed_epochs=previous_epochs)

    if config.model.backend == "numpy":
        model = NumpyLinearSurrogate()
        model.fit(normalized_samples)
        model.save(checkpoint)
    elif config.model.backend == "physicsnemo":
        checkpoint = _train_physicsnemo(
            config,
            normalized_samples,
            output_dir,
            train_config_path,
            graph_list,
            requested_epochs=epochs,
            completed_epochs=previous_epochs,
            epochs_to_run=epochs_to_run,
            resume=checkpoint.exists(),
        )
    else:
        raise ValueError(f"Unsupported model backend: {config.model.backend}")

    _write_train_config(config, train_config_path, graph_list, requested_epochs=epochs, completed_epochs=epochs)
    return checkpoint


def _log_sample_summary(samples: list[dict]) -> None:
    total_nodes = sum(int(np.asarray(sample["x"]).shape[0]) for sample in samples)
    total_edges = sum(int(np.asarray(sample["edge_index"]).shape[1]) for sample in samples)
    print(
        f"Training samples ready: samples={len(samples)}, total_nodes={total_nodes}, total_edges={total_edges}",
        flush=True,
    )


def _completed_epochs(previous: dict, config: FanSimConfig, graph_list: list[str]) -> int:
    if (
        previous.get("backend") == config.model.backend
        and previous.get("graphs") == graph_list
        and previous.get("processor_size") == config.model.processor_size
        and previous.get("hidden_dim") == config.model.hidden_dim
        and previous.get("max_nodes_per_graph") == config.model.max_nodes_per_graph
        and previous.get("sample_seed") == config.model.sample_seed
    ):
        return int(previous.get("completed_epochs", previous.get("epochs", 0)))
    return 0


def _write_train_config(
    config: FanSimConfig,
    path: Path,
    graph_list: list[str],
    *,
    requested_epochs: int,
    completed_epochs: int,
    last_loss: float | None = None,
) -> None:
    payload = {
        "backend": config.model.backend,
        "epochs": requested_epochs,
        "completed_epochs": completed_epochs,
        "graphs": graph_list,
        "processor_size": config.model.processor_size,
        "hidden_dim": config.model.hidden_dim,
        "max_nodes_per_graph": config.model.max_nodes_per_graph,
        "sample_seed": config.model.sample_seed,
    }
    if last_loss is not None:
        payload["last_loss"] = float(last_loss)
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")


def _sample_for_training(config: FanSimConfig, sample: dict, index: int) -> dict:
    max_nodes = config.model.max_nodes_per_graph
    if max_nodes is None:
        return sample
    n_nodes = int(np.asarray(sample["x"]).shape[0])
    if n_nodes <= max_nodes:
        return sample
    rng = np.random.default_rng(config.model.sample_seed + index)
    node_ids = np.sort(rng.choice(n_nodes, size=max_nodes, replace=False))
    sampled = _induced_subgraph(sample, node_ids)
    print(
        f"{sample.get('case_meta', {}).get('case_id', '<graph>')}: sampled nodes "
        f"{n_nodes} -> {sampled['x'].shape[0]}, edges {sample['edge_index'].shape[1]} -> {sampled['edge_index'].shape[1]}",
        flush=True,
    )
    return sampled


def _induced_subgraph(sample: dict, node_ids: np.ndarray) -> dict:
    node_ids = np.asarray(node_ids, dtype=np.int64)
    n_nodes = int(np.asarray(sample["x"]).shape[0])
    node_mask = np.zeros(n_nodes, dtype=bool)
    node_mask[node_ids] = True
    remap = np.full(n_nodes, -1, dtype=np.int64)
    remap[node_ids] = np.arange(node_ids.shape[0], dtype=np.int64)

    edge_index = np.asarray(sample["edge_index"], dtype=np.int64)
    edge_mask = node_mask[edge_index[0]] & node_mask[edge_index[1]]
    sampled_edges = edge_index[:, edge_mask]

    sampled = dict(sample)
    sampled["case_meta"] = dict(sample.get("case_meta", {}))
    sampled["x"] = np.asarray(sample["x"])[node_ids]
    sampled["y"] = np.asarray(sample["y"])[node_ids]
    if "pos" in sample:
        sampled["pos"] = np.asarray(sample["pos"])[node_ids]
    sampled["edge_index"] = remap[sampled_edges]
    sampled["edge_attr"] = np.asarray(sample["edge_attr"])[edge_mask]
    return sampled


def _checkpoint_path(config: FanSimConfig) -> Path:
    suffix = ".npz" if config.model.backend == "numpy" else ".pt"
    return config.model.output_dir / f"checkpoint{suffix}"


def _read_train_config(path: Path) -> dict:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _train_physicsnemo(
    config: FanSimConfig,
    samples: list[dict],
    output_dir: Path,
    train_config_path: Path,
    graph_list: list[str],
    *,
    requested_epochs: int,
    completed_epochs: int,
    epochs_to_run: int,
    resume: bool = False,
) -> Path:
    first = samples[0]
    torch, Data, model = require_physicsnemo_meshgraphnet(
        PhysicsNeMoModelConfig(
            input_dim_nodes=int(first["x"].shape[1]),
            input_dim_edges=int(first["edge_attr"].shape[1]),
            output_dim=int(first["y"].shape[1]),
            processor_size=config.model.processor_size,
            hidden_dim=config.model.hidden_dim,
        )
    )
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = model.to(device)
    checkpoint = output_dir / "checkpoint.pt"
    if resume:
        payload = torch.load(checkpoint, map_location=device)
        model.load_state_dict(payload["state_dict"])
        completed_epochs = int(payload.get("completed_epochs", completed_epochs))
        epochs_to_run = max(requested_epochs - completed_epochs, 0)
        print(f"{checkpoint}: loaded existing checkpoint at epoch {completed_epochs}.", flush=True)
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-4)
    loss_fn = torch.nn.MSELoss()

    if epochs_to_run == 0:
        print(f"{checkpoint}: no remaining epochs; skipping PhysicsNeMo training.", flush=True)
        return checkpoint

    for epoch_offset in range(epochs_to_run):
        epoch = completed_epochs + epoch_offset + 1
        model.train()
        epoch_loss = 0.0
        for sample_index, sample in enumerate(samples, start=1):
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
            loss_value = float(loss.detach().cpu())
            epoch_loss += loss_value
            print(
                f"epoch {epoch}/{requested_epochs} sample {sample_index}/{len(samples)} "
                f"nodes={x.shape[0]} edges={edge_attr.shape[0]} loss={loss_value:.6g}",
                flush=True,
            )
        avg_loss = epoch_loss / max(len(samples), 1)
        torch.save(
            {
                "backend": "physicsnemo",
                "state_dict": model.state_dict(),
                "completed_epochs": epoch,
                "last_loss": avg_loss,
            },
            checkpoint,
        )
        _write_train_config(
            config,
            train_config_path,
            graph_list,
            requested_epochs=requested_epochs,
            completed_epochs=epoch,
            last_loss=avg_loss,
        )
        print(f"epoch {epoch}/{requested_epochs} done avg_loss={avg_loss:.6g}; checkpoint={checkpoint}", flush=True)

    return checkpoint

