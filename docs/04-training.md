# Training

Fan-Sim trains a steady MeshGraphNet surrogate on case-level graph samples.

## Dataset Split

Splits happen by case, not by cell. Random cell-level split is invalid because cells from the same CFD solution are strongly correlated and would leak information.

Default split files:

```text
artifacts/splits/train.txt
artifacts/splits/val.txt
artifacts/splits/test.txt
```

Each line points to a `.graph.pt` sample.

## Model

The production path uses PhysicsNeMo MeshGraphNet when available. The implementation keeps the model behind a wrapper so the rest of the pipeline does not depend on PhysicsNeMo import details.

Model dimensions:

```text
input_dim_nodes = graph["x"].shape[1]
input_dim_edges = graph["edge_attr"].shape[1]
output_dim = 4
```

## Loss

The default loss is MSE over normalized `[Ux, Uy, Uz, p]`. Pressure and velocity can be weighted in config once validation shows imbalance.

## Checkpoints

Training writes:

```text
artifacts/models/fan_mgn/checkpoint.pt
artifacts/models/fan_mgn/normalizer.json
artifacts/models/fan_mgn/train_config.yaml
```

## Metrics

Validation reports:

- normalized MSE.
- velocity RMSE.
- pressure RMSE.
- optional pressure-drop and mass-flow estimates when patch integration metadata is available.

