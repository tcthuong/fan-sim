from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any

import numpy as np


@dataclass
class ArrayStats:
    mean: list[float]
    scale: list[float]


@dataclass
class GraphNormalizer:
    x: ArrayStats
    edge_attr: ArrayStats
    y: ArrayStats

    @classmethod
    def fit(cls, samples: list[dict[str, Any]]) -> "GraphNormalizer":
        if not samples:
            raise ValueError("Cannot fit normalizer without samples.")
        return cls(
            x=_fit_stats(np.concatenate([np.asarray(sample["x"], dtype=np.float32) for sample in samples], axis=0)),
            edge_attr=_fit_stats(
                np.concatenate([np.asarray(sample["edge_attr"], dtype=np.float32) for sample in samples], axis=0)
                if any(np.asarray(sample["edge_attr"]).size for sample in samples)
                else np.zeros((1, 4), dtype=np.float32)
            ),
            y=_fit_stats(np.concatenate([np.asarray(sample["y"], dtype=np.float32) for sample in samples], axis=0)),
        )

    def transform(self, sample: dict[str, Any]) -> dict[str, Any]:
        transformed = _copy_sample(sample)
        transformed["x"] = _apply(np.asarray(sample["x"], dtype=np.float32), self.x)
        transformed["edge_attr"] = _apply(np.asarray(sample["edge_attr"], dtype=np.float32), self.edge_attr)
        if "y" in sample:
            transformed["y"] = _apply(np.asarray(sample["y"], dtype=np.float32), self.y)
        return transformed

    def inverse_transform_target(self, target: Any) -> np.ndarray:
        array = _to_numpy(target)
        return array * np.asarray(self.y.scale, dtype=np.float32) + np.asarray(self.y.mean, dtype=np.float32)

    def save(self, path: str | Path) -> None:
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "GraphNormalizer":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(
            x=ArrayStats(**raw["x"]),
            edge_attr=ArrayStats(**raw["edge_attr"]),
            y=ArrayStats(**raw["y"]),
        )


def _fit_stats(array: np.ndarray) -> ArrayStats:
    mean = array.mean(axis=0)
    scale = array.std(axis=0)
    scale = np.where(scale < 1e-12, 1.0, scale)
    return ArrayStats(mean=mean.astype(float).tolist(), scale=scale.astype(float).tolist())


def _apply(array: np.ndarray, stats: ArrayStats) -> np.ndarray:
    return (array - np.asarray(stats.mean, dtype=np.float32)) / np.asarray(stats.scale, dtype=np.float32)


def _copy_sample(sample: dict[str, Any]) -> dict[str, Any]:
    copied = dict(sample)
    copied["case_meta"] = dict(sample.get("case_meta", {}))
    return copied


def _to_numpy(value: Any) -> np.ndarray:
    if hasattr(value, "detach"):
        value = value.detach().cpu().numpy()
    return np.asarray(value, dtype=np.float32)
