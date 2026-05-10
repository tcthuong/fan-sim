# OpenFOAM Base Case Contract

The input is one valid OpenFOAM base case at `data/base_case`. The case must be parameterizable by RPM and boundary conditions.

## Required Structure

```text
data/base_case/
  0/
  constant/
  system/
```

Required solver dictionaries depend on the base case, but the v1 runner expects the following commands to be valid when executed from the case directory:

```bash
blockMesh
surfaceFeatureExtract
snappyHexMesh -overwrite
checkMesh
simpleFoam
foamToVTK -latestTime -fields '(U p)'
```

`surfaceFeatureExtract` and `snappyHexMesh` can be disabled in config when the base case already contains a mesh.

## Fields

Training expects these OpenFOAM fields to export into the latest VTU:

- velocity field: `U`
- pressure field: `p`

The reliable training path expects both fields in VTU `cell_data`. If a field is present only in `point_data`, the data loader fails unless the caller explicitly allows point data.

## Parameters

The v1 parameter contract includes:

- `rpm`: fan rotational speed.
- `inlet_pressure`: optional scalar pressure feature.
- `outlet_pressure`: required scalar pressure feature.

The patcher supports conservative text replacement for placeholders in case dictionaries:

```text
{{RPM}}
{{INLET_PRESSURE}}
{{OUTLET_PRESSURE}}
```

If the base case uses a different MRF or boundary-condition expression, add those placeholders to the base case template rather than editing generated cases by hand.

## Solver Assumption For This Base Case

The current base case was authored by OpenFOAM.com v2406/SimScale. The recommended runtime is therefore OpenFOAM.com v2406 on Ubuntu/Linux, not OpenFOAM Foundation 13.

Use:

```bash
simpleFoam
```

This is the configured default in `configs/fan_sim.yaml`.

OpenFOAM Foundation 13 can read far enough to start this case after compatibility migration, but it is not the target runtime for this base case. Transient `pimpleFoam` rollout is out of scope for v1 because it requires timestep samples and a different target definition.

## OpenFOAM.com / SimScale Compatibility

The current sample base case was authored with OpenFOAM.com v2406/SimScale. It contains entries unavailable in OpenFOAM Foundation 13:

- `autoTurbulentMixingLengthFrequencyInlet`
- `libchtgfm.so`
- `libsimScaleFunctionObjects.so`
- several SimScale custom function objects

Before each OpenFOAM run, Fan-Sim applies a narrow compatibility migration to generated cases:

- replace `autoTurbulentMixingLengthFrequencyInlet` with Foundation's `turbulentMixingLengthFrequencyInlet`;
- remove unsupported helper keys `diameterFraction` and `mixingLengthSet`;
- remove unavailable custom libraries from `system/controlDict`;
- disable unavailable SimScale function objects.

The migration does not alter mesh geometry or primary `U`, `p`, `k`, `omega`, `nut` values beyond the unsupported boundary-condition type mapping.
