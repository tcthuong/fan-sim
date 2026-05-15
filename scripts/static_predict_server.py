from __future__ import annotations

import argparse
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path


@lru_cache(maxsize=16)
def _metrics_for_prediction(vtu_path: str, modified_ns: int) -> dict[str, float]:
    del modified_ns
    defaults = {
        "estimated_pressure_drop": 0.0,
        "estimated_mass_flow": 0.0,
        "velocity_mean": 0.0,
    }
    try:
        import numpy as np
        import pyvista as pv

        mesh = pv.read(vtu_path)
        values = None
        if "velocity_magnitude" in mesh.point_data:
            values = mesh.point_data["velocity_magnitude"]
        elif "velocity_magnitude" in mesh.cell_data:
            values = mesh.cell_data["velocity_magnitude"]
        elif "U_pred" in mesh.point_data:
            values = np.linalg.norm(np.asarray(mesh.point_data["U_pred"]), axis=1)
        elif "U_pred" in mesh.cell_data:
            values = np.linalg.norm(np.asarray(mesh.cell_data["U_pred"]), axis=1)
        if values is None:
            return defaults
        return {
            **defaults,
            "velocity_mean": float(np.nanmean(np.asarray(values, dtype=float))),
        }
    except Exception:
        return defaults


def build_static_response(prediction_dir: Path) -> dict:
    prediction_vtu = prediction_dir / "prediction.vtu"
    if not prediction_vtu.exists():
        prediction_vtu = prediction_dir / "prediction_preview.vtu"
    prediction_usd = prediction_dir / "prediction.usda"
    fan_mesh_usd = prediction_dir / "fan_mesh.usda"
    streamlines_usd = prediction_dir / "prediction_streamlines.usda"
    particles_usd = prediction_dir / "prediction_particles.usda"
    metrics = {
        "estimated_pressure_drop": 0.0,
        "estimated_mass_flow": 0.0,
        "velocity_mean": 0.0,
    }
    if prediction_vtu.exists() and prediction_vtu.stat().st_size > 0:
        metrics = _metrics_for_prediction(prediction_vtu.as_posix(), prediction_vtu.stat().st_mtime_ns)
    return {
        "prediction_vtu": prediction_vtu.as_posix(),
        "prediction_usd": prediction_usd.as_posix(),
        "fan_mesh_usd": fan_mesh_usd.as_posix() if fan_mesh_usd.exists() else None,
        "prediction_streamlines_usd": streamlines_usd.as_posix() if streamlines_usd.exists() else None,
        "prediction_particles_usd": particles_usd.as_posix() if particles_usd.exists() else None,
        "fields": ["U_pred", "p_pred", "velocity_magnitude"],
        "metrics": metrics,
    }


class StaticPredictHandler(BaseHTTPRequestHandler):
    prediction_dir: Path

    def do_GET(self) -> None:
        if self.path.rstrip("/") == "/health":
            self._send_json({"status": "ok", "mode": "static"})
            return
        self.send_error(404)

    def do_POST(self) -> None:
        if self.path.rstrip("/") != "/predict":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0") or "0")
        body = self.rfile.read(length).decode("utf-8") if length else "{}"
        print(f"predict_request={body}", flush=True)
        self._send_json(build_static_response(self.prediction_dir))

    def log_message(self, fmt: str, *args) -> None:
        print(f"{self.address_string()} - {fmt % args}", flush=True)

    def _send_json(self, body: dict) -> None:
        payload = json.dumps(body).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--prediction-dir",
        default=(
            "D:/nvidia/fan-sim/runs/analysis/"
            "fan_mesh_streamlines_recheck_20260514/exporter_full_topology_smoke"
        ),
    )
    args = parser.parse_args()
    prediction_dir = Path(args.prediction_dir).resolve()
    for name in ("prediction.vtu", "prediction.usda"):
        if not (prediction_dir / name).exists():
            raise FileNotFoundError(prediction_dir / name)

    StaticPredictHandler.prediction_dir = prediction_dir
    server = ThreadingHTTPServer((args.host, args.port), StaticPredictHandler)
    print(f"static predict server listening on http://{args.host}:{args.port}", flush=True)
    print(f"prediction_dir={prediction_dir}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
