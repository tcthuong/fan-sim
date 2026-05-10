from __future__ import annotations

from pathlib import Path
import pickle
from typing import Any

PICKLE_PROTOCOL_FOR_LARGE_GRAPHS = 4


def save_graph_sample(sample: dict[str, Any], path: str | Path) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    try:
        import torch

        torch.save(sample, temporary, pickle_protocol=PICKLE_PROTOCOL_FOR_LARGE_GRAPHS)
    except ImportError:
        with temporary.open("wb") as stream:
            pickle.dump(sample, stream, protocol=max(PICKLE_PROTOCOL_FOR_LARGE_GRAPHS, pickle.HIGHEST_PROTOCOL))
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    temporary.replace(output)


def load_graph_sample(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    try:
        import torch

        return torch.load(source, weights_only=False)
    except ImportError:
        with source.open("rb") as stream:
            return pickle.load(stream)
