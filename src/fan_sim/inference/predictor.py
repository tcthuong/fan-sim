from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np


@dataclass
class PredictionResult:
    sample: dict[str, Any]
    prediction: np.ndarray
    fields: list[str]

    @property
    def velocity(self) -> np.ndarray:
        return self.prediction[:, :3]

    @property
    def pressure(self) -> np.ndarray:
        return self.prediction[:, 3]

    @property
    def velocity_magnitude(self) -> np.ndarray:
        return np.linalg.norm(self.velocity, axis=1)


class FanPredictor:
    def __init__(self, *, model: Any, template_sample: dict[str, Any], normalizer: Any | None):
        self.model = model
        self.template_sample = template_sample
        self.normalizer = normalizer

    def predict(self, *, rpm: float, inlet_pressure: float, outlet_pressure: float) -> PredictionResult:
        sample = _copy_sample(self.template_sample)
        sample["x"][:, 3] = rpm
        sample["x"][:, 4] = inlet_pressure
        sample["x"][:, 5] = outlet_pressure
        sample["case_meta"].update(
            {
                "rpm": rpm,
                "inlet_pressure": inlet_pressure,
                "outlet_pressure": outlet_pressure,
            }
        )

        model_sample = self.normalizer.transform(sample) if self.normalizer is not None else sample
        raw_prediction = self._predict_with_model(model_sample)
        prediction = (
            self.normalizer.inverse_transform_target(raw_prediction) if self.normalizer is not None else _to_numpy(raw_prediction)
        )
        return PredictionResult(sample=sample, prediction=prediction.astype(np.float32), fields=["U_pred", "p_pred", "velocity_magnitude"])

    def _predict_with_model(self, sample: dict[str, Any]) -> Any:
        if hasattr(self.model, "predict"):
            return self.model.predict(sample)
        return self.model(sample)


def _copy_sample(sample: dict[str, Any]) -> dict[str, Any]:
    copied = dict(sample)
    for key in ("x", "edge_index", "edge_attr", "pos", "y"):
        if key in copied:
            copied[key] = np.asarray(copied[key]).copy()
    copied["case_meta"] = dict(sample.get("case_meta", {}))
    return copied


def _to_numpy(value: Any) -> np.ndarray:
    if hasattr(value, "detach"):
        value = value.detach().cpu().numpy()
    return np.asarray(value, dtype=np.float32)

