# Omniverse Visualization

Fan-Sim uses the existing `D:/nvidia/kit-cae` repository as the Omniverse visualization base.

## Result Files

Inference writes:

```text
prediction.vtu
prediction.usda
particle_seeds.json
streamline_seeds.json
```

`prediction.vtu` is the authoritative CFD result artifact. It contains:

- `cell_data["U_pred"]`
- `cell_data["p_pred"]`
- `cell_data["velocity_magnitude"]`
- optional point-interpolated equivalents for visualization.

`prediction.usda` is a lightweight stage/layer that references result metadata and can be loaded by Kit.

## Kit-CAE Path

Kit-CAE already contains:

- `.vtu` importer.
- CAE USD schema.
- VTK/Warp streamline algorithms.
- IndeX volume/slice support.

The Fan-Sim extension should call the local `/predict` service, import `prediction.vtu`, and then create visualization prims using Kit-CAE commands where available.

## Streamlines And Particle Traces

V1 particle support means passive traces advected by predicted `U_pred`. These are visualization particles, not a validated Lagrangian particle physics model.

## Volume And Slices

For unstructured results, volume visualization should use Kit-CAE unstructured grid support when available. If a dense volume is required, add a separate resampling step from `prediction.vtu` to VDB/VTI.

