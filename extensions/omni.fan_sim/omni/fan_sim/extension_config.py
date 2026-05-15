from __future__ import annotations

import ast
from pathlib import Path
import re
from typing import NamedTuple


class RpmSliderSpec(NamedTuple):
    minimum: float
    maximum: float
    default: float


class StreamlineVisualSettings(NamedTuple):
    color_field: str
    color_range: tuple[float, float] | None
    min_step_size: float
    max_step_size: float
    initial_step_size: float
    max_steps: int
    direction: str
    threshold: float
    tolerance: float
    width: float
    seed_resolution: int
    seed_translation: tuple[float, float, float]
    seed_scale: tuple[float, float, float]


class FlowVisualSettings(NamedTuple):
    velocity_scale: float
    velocity_couple_rate: float
    voxel_max_resolution: int
    inflate_bounds: float
    density_cell_size: float
    ray_attenuation: float
    ray_color_scale: float
    source_radius: float
    source_offset: float
    source_z: float
    smoke_injector_names: tuple[str, ...]


class ExtensionRuntimeSettings(NamedTuple):
    auto_predict_on_startup: bool
    debounce_seconds: float
    pending_suffix: str


def default_streamline_settings() -> StreamlineVisualSettings:
    return StreamlineVisualSettings(
        color_field="velocity_magnitude",
        color_range=(0.0, 300.0),
        min_step_size=0.0008,
        max_step_size=0.015,
        initial_step_size=0.005,
        max_steps=900,
        direction="forward",
        threshold=1e-8,
        tolerance=5e-5,
        width=0.00028,
        seed_resolution=24,
        seed_translation=(0.0, 0.0, 0.085),
        seed_scale=(0.032, 0.032, 0.003),
    )


def default_flow_settings() -> FlowVisualSettings:
    return FlowVisualSettings(
        velocity_scale=0.12,
        velocity_couple_rate=80.0,
        voxel_max_resolution=128,
        inflate_bounds=2.0,
        density_cell_size=0.01,
        ray_attenuation=3.0,
        ray_color_scale=10.0,
        source_radius=0.0055,
        source_offset=0.010,
        source_z=0.085,
        smoke_injector_names=(
            "SmokeInjector_Center",
            "SmokeInjector_PosX",
            "SmokeInjector_NegX",
            "SmokeInjector_PosY",
            "SmokeInjector_NegY",
        ),
    )


def default_runtime_settings() -> ExtensionRuntimeSettings:
    return ExtensionRuntimeSettings(
        auto_predict_on_startup=True,
        debounce_seconds=0.65,
        pending_suffix="",
    )


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
