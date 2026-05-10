from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

import numpy as np

from fan_sim.inference.predictor import PredictionResult


@dataclass
class PredictionArtifacts:
    prediction_vtu: Path | None
    prediction_usd: Path
    streamline_seeds_json: Path
    particle_seeds_json: Path
    metrics_json: Path


def export_prediction_artifacts(
    result: PredictionResult,
    *,
    output_dir: str | Path,
    write_vtu: bool = True,
) -> PredictionArtifacts:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    prediction_vtu = output / "prediction.vtu" if write_vtu else None
    prediction_usd = output / "prediction.usda"
    streamline_seeds = output / "streamline_seeds.json"
    particle_seeds = output / "particle_seeds.json"
    metrics = output / "metrics.json"

    if prediction_vtu is not None:
        write_prediction_vtu(prediction_vtu, result)
    write_prediction_usd(prediction_usd, result, prediction_vtu)
    _write_seed_json(streamline_seeds, result, kind="streamlines")
    _write_seed_json(particle_seeds, result, kind="particles")
    metrics.write_text(json.dumps(compute_metrics(result), indent=2), encoding="utf-8")

    return PredictionArtifacts(prediction_vtu, prediction_usd, streamline_seeds, particle_seeds, metrics)


def write_prediction_vtu(path: str | Path, result: PredictionResult) -> None:
    pos = np.asarray(result.sample["pos"], dtype=np.float32)
    velocity = result.velocity
    pressure = result.pressure
    speed = result.velocity_magnitude
    n_points = pos.shape[0]
    connectivity = " ".join(str(i) for i in range(n_points))
    offsets = " ".join(str(i + 1) for i in range(n_points))
    types = " ".join("1" for _ in range(n_points))

    text = f"""<?xml version="1.0"?>
<VTKFile type="UnstructuredGrid" version="0.1" byte_order="LittleEndian">
  <UnstructuredGrid>
    <Piece NumberOfPoints="{n_points}" NumberOfCells="{n_points}">
      <Points>
        <DataArray type="Float32" NumberOfComponents="3" format="ascii">
          {_format_array(pos)}
        </DataArray>
      </Points>
      <Cells>
        <DataArray type="Int64" Name="connectivity" format="ascii">{connectivity}</DataArray>
        <DataArray type="Int64" Name="offsets" format="ascii">{offsets}</DataArray>
        <DataArray type="UInt8" Name="types" format="ascii">{types}</DataArray>
      </Cells>
      <PointData Vectors="U_pred" Scalars="p_pred">
        <DataArray type="Float32" Name="U_pred" NumberOfComponents="3" format="ascii">{_format_array(velocity)}</DataArray>
        <DataArray type="Float32" Name="p_pred" format="ascii">{_format_array(pressure.reshape(-1, 1))}</DataArray>
        <DataArray type="Float32" Name="velocity_magnitude" format="ascii">{_format_array(speed.reshape(-1, 1))}</DataArray>
      </PointData>
    </Piece>
  </UnstructuredGrid>
</VTKFile>
"""
    Path(path).write_text(text, encoding="utf-8")


def write_prediction_usd(path: str | Path, result: PredictionResult, prediction_vtu: Path | None) -> None:
    meta = result.sample.get("case_meta", {})
    vtu_asset = "" if prediction_vtu is None else prediction_vtu.as_posix()
    rpm = meta.get("rpm", 0.0)
    outlet_pressure = meta.get("outlet_pressure", 0.0)
    text = f"""#usda 1.0
(
    defaultPrim = "World"
)

def Xform "World"
{{
    custom string fanSim:predictionVtu = "{vtu_asset}"
    custom float rpm = {rpm:g}
    custom float outlet_pressure = {outlet_pressure:g}
    def Scope "FanSimPrediction"
    {{
        custom string[] fields = ["U_pred", "p_pred", "velocity_magnitude"]
    }}
}}
"""
    Path(path).write_text(text, encoding="utf-8")


def compute_metrics(result: PredictionResult) -> dict[str, float]:
    pressure = result.pressure
    return {
        "estimated_pressure_drop": float(pressure.max() - pressure.min()) if pressure.size else 0.0,
        "estimated_mass_flow": 0.0,
        "velocity_mean": float(result.velocity_magnitude.mean()) if result.velocity_magnitude.size else 0.0,
    }


def _write_seed_json(path: Path, result: PredictionResult, kind: str) -> None:
    pos = np.asarray(result.sample["pos"], dtype=float)
    seeds = pos[: min(16, len(pos))].tolist()
    path.write_text(json.dumps({"kind": kind, "seeds": seeds}, indent=2), encoding="utf-8")


def _format_array(array: np.ndarray) -> str:
    flat = np.asarray(array).reshape(-1)
    return " ".join(f"{float(value):.9g}" for value in flat)

