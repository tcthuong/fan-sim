from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from fan_sim.export.artifacts import compute_metrics, export_prediction_artifacts


class PredictRequest(BaseModel):
    case_id: str
    rpm: float
    outlet_pressure: float
    inlet_pressure: float = 0.0
    outputs: list[str] = Field(default_factory=lambda: ["vtu", "usd"])


class PredictResponse(BaseModel):
    prediction_vtu: str | None
    prediction_usd: str
    fields: list[str]
    metrics: dict[str, float]


def create_app(*, predictor: Any | None = None, output_root: str | Path = "runs/inference", write_vtu: bool = True) -> FastAPI:
    app = FastAPI(title="Fan-Sim Inference Service", version="0.1.0")
    app.state.predictor = predictor
    app.state.output_root = Path(output_root)
    app.state.write_vtu = write_vtu

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/predict", response_model=PredictResponse)
    def predict(request: PredictRequest) -> PredictResponse:
        if app.state.predictor is None:
            raise HTTPException(status_code=503, detail="Predictor is not configured.")
        result = app.state.predictor.predict(
            rpm=request.rpm,
            inlet_pressure=request.inlet_pressure,
            outlet_pressure=request.outlet_pressure,
        )
        run_dir = app.state.output_root / f"{request.case_id}_rpm{int(round(request.rpm)):04d}"
        artifacts = export_prediction_artifacts(result, output_dir=run_dir, write_vtu=app.state.write_vtu and "vtu" in request.outputs)
        return PredictResponse(
            prediction_vtu=str(artifacts.prediction_vtu) if artifacts.prediction_vtu is not None else None,
            prediction_usd=str(artifacts.prediction_usd),
            fields=result.fields,
            metrics=compute_metrics(result),
        )

    return app

