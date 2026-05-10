# Data Pipeline

The data pipeline converts a case matrix into graph training samples.

## Case Generation

The CLI reads `configs/fan_sim.yaml`, clones `base_case` into `runs/openfoam`, and expands every combination in `case_matrix`.

Example case names:

```text
runs/openfoam/case_rpm_0600_pout_000
runs/openfoam/case_rpm_0800_pout_020
```

Each generated case receives a `fan_sim_case.json` metadata file containing RPM, inlet pressure, outlet pressure, and source base case.

## OpenFOAM Execution

The default runtime shell is Ubuntu/Linux `bash`:

```text
cd /mnt/d/nvidia/fan-sim/runs/openfoam/<case_name>
checkMesh
simpleFoam
foamToVTK -latestTime -fields '(U p)'
```

The runner records command stdout/stderr into per-case log files such as `runs/openfoam/<case_id>/log.fan-sim-openfoam`.

## VTU Selection

The graph builder uses the latest generated `.vtu` file under a case `VTK/` directory unless an explicit file is provided.

## Graph Conversion

The VTU reader extracts:

- cell centers as graph node positions.
- cell field `U` as velocity target.
- cell field `p` as pressure target.
- cell types/connectivity as adjacency source.

The graph builder creates bidirectional edges between cells that share a full face when VTU cell type metadata is available. If cell type metadata is unavailable, it falls back to point-based adjacency for compatibility with minimal synthetic meshes. When OpenFOAM owner/neighbour files are available in a future version, those can replace the VTU-derived face adjacency.
