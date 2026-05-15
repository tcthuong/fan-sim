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
  "fan_mesh_usd": "D:/nvidia/fan-sim/runs/inference/fan_base_rpm1200/fan_mesh.usda",
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

When the graph template points back to a source OpenFOAM `internal.vtu`, `prediction.vtu` preserves that source topology and adds predicted cell/point fields. If the matching `boundary/face*.vtp` folder exists, the response also includes `fan_mesh_usd`.

## Failure Modes

The service returns clear errors for:

- missing checkpoint.
- missing normalizer.
- unknown `case_id`.
- graph/template mismatch.
- optional dependency missing for requested output format.
