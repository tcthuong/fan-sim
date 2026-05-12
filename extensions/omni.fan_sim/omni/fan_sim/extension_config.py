from __future__ import annotations

import ast
from pathlib import Path
import re
from typing import NamedTuple


class RpmSliderSpec(NamedTuple):
    minimum: float
    maximum: float
    default: float


def default_project_root(extension_file: str | Path) -> Path:
    return Path(extension_file).resolve().parents[4]


def default_config_path(extension_file: str | Path) -> Path:
    return default_project_root(extension_file) / "configs" / "fan_sim.yaml"


def load_rpm_values(config_path: str | Path) -> list[float]:
    text = Path(config_path).read_text(encoding="utf-8")
    match = re.search(r"(?m)^\s*rpm\s*:\s*(\[[^\]]+\])", text)
    if not match:
        return []
    values = ast.literal_eval(match.group(1))
    return [float(value) for value in values]


def rpm_slider_spec(rpm_values: list[float], fallback: tuple[float, float] = (600.0, 1200.0)) -> RpmSliderSpec:
    values = sorted(float(value) for value in rpm_values)
    if not values:
        return RpmSliderSpec(minimum=fallback[0], maximum=fallback[1], default=fallback[0])
    return RpmSliderSpec(minimum=values[0], maximum=values[-1], default=values[len(values) // 2])


def build_predict_payload(
    *,
    case_id: str,
    rpm: float,
    outlet_pressure: float,
    show_streamlines: bool,
    show_cae_flow: bool,
    inlet_pressure: float = 0.0,
) -> dict:
    outputs = ["vtu", "usd"]
    if show_streamlines:
        outputs.append("streamlines")
    if show_cae_flow:
        outputs.append("particles")
    return {
        "case_id": case_id,
        "rpm": float(rpm),
        "inlet_pressure": float(inlet_pressure),
        "outlet_pressure": float(outlet_pressure),
        "outputs": outputs,
    }
