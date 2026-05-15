# Omniverse Visualization

Fan-Sim uses the existing `D:/nvidia/kit-cae` repository as the Omniverse visualization base.

## Result Files

Inference writes:

```text
prediction.vtu
prediction.usda
fan_mesh.usda
particle_seeds.json
streamline_seeds.json
```

`prediction.vtu` is the authoritative CFD result artifact. When the graph sample contains a valid source `internal.vtu`, the exporter preserves the original OpenFOAM unstructured-grid topology and attaches predicted fields to it. If the source file was built on Colab, the exporter maps `/content/fan-sim/runs/openfoam/...` back to the local `runs/openfoam/...` tree before writing the result.

It contains:

- `cell_data["U_pred"]`
- `cell_data["p_pred"]`
- `cell_data["velocity_magnitude"]`
- point-interpolated equivalents for streamline, slice, and CAE Flow visualization.

`fan_mesh.usda` is written when `foamToVTK` boundary VTP files are available beside `internal.vtu`. It follows the Kit-CAE reference pattern: skip domain patches `face1` through `face6`, merge the remaining boundary patches, and write a standalone fan boundary mesh.

`prediction.usda` is a lightweight stage/layer that references result metadata and, when available, references `fan_mesh.usda` so the stage contains both the predicted dataset and the fan surface mesh.

## Kit-CAE Path

Kit-CAE already contains:

- `.vtu` importer.
- CAE USD schema.
- VTK/Warp streamline algorithms.
- IndeX volume/slice support.

The Fan-Sim extension calls the local `/predict` service, imports `prediction.vtu`, and then creates visualization prims using Kit-CAE commands where available.

The extension UI reads the committed `configs/fan_sim.yaml` RPM list and exposes an RPM slider from the configured minimum to maximum. After prediction it can show or hide:

- `FanSimStreamlines`: a Kit-CAE streamline operator driven by `U_pred`.
- `FanSimFlow`: a CAE Flow environment with dataset and fuel injectors driven by `U_pred`.

The streamline controls are configured for the fan-case scale instead of Kit defaults:

- seed mesh: `UnitSphere`, resolution `32`, placed near the fan outlet region.
- integration: direction `forward`, min step `0.0004`, initial step `0.002`, max step `0.006`, max steps `900`.
- color field: `velocity_magnitude`.
- visual width: `0.0009`.

The CAE Flow toggle follows the Kit-CAE reference demo pattern: create a hidden dataset bounding box, create five hidden pulsed smoke injectors bound to that box, create a boundary emitter, then create a dataset velocity emitter bound to `U_pred`. The dataset emitter uses voxel max resolution `192` and inflate bounds `4`.

## Streamlines And Particle Traces

V1 particle support means passive traces advected by predicted `U_pred`. These are visualization particles, not a validated Lagrangian particle physics model.

## Volume And Slices

For unstructured results, volume visualization should use Kit-CAE unstructured grid support when available. If a dense volume is required, add a separate resampling step from `prediction.vtu` to VDB/VTI.
