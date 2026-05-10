# Inference Service

The local service is the stable interface between Omniverse and the ML backend.

## Request

```http
POST /predict
Content-Type: application/json

{
  "case_id": "fan_base",
  "rpm": 1200,
  "outlet_pressure": 20,
  "inlet_pressure": 0,
  "outputs": ["vtu", "usd", "streamlines", "particles"]
}
```

## Response

```json
{
  "prediction_vtu": "D:/nvidia/fan-sim/runs/inference/fan_base_rpm1200/prediction.vtu",
  "prediction_usd": "D:/nvidia/fan-sim/runs/inference/fan_base_rpm1200/prediction.usda",
  "fields": ["U_pred", "p_pred", "velocity_magnitude"],
  "metrics": {
    "estimated_pressure_drop": 0.0,
    "estimated_mass_flow": 0.0
  }
}
```

## Runtime Contract

The service loads:

- graph template or reference VTU for `case_id`.
- trained checkpoint.
- `normalizer.json`.

It returns file paths rather than large field arrays. Omniverse consumes the result files.

## Failure Modes

The service returns clear errors for:

- missing checkpoint.
- missing normalizer.
- unknown `case_id`.
- graph/template mismatch.
- optional dependency missing for requested output format.

