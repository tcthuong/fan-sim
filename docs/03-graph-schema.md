# Graph Sample Schema

Each generated training sample is saved as a `.graph.pt` file compatible with PyTorch and PyTorch Geometric style graph data.

## Sample Keys

```python
{
    "x": FloatTensor[N, F_node],
    "edge_index": LongTensor[2, E],
    "edge_attr": FloatTensor[E, 4],
    "y": FloatTensor[N, 4],
    "pos": FloatTensor[N, 3],
    "case_meta": dict,
    "schema_version": "fan-sim-graph-v1"
}
```

## Node Features

The default node feature vector is:

```text
[
  cell_center_x,
  cell_center_y,
  cell_center_z,
  rpm,
  inlet_pressure,
  outlet_pressure,
  is_internal,
  is_wall_adjacent,
  is_inlet_adjacent,
  is_outlet_adjacent
]
```

Patch flags default to `is_internal=1` when patch-to-cell mapping is unavailable. The patch mapping file can be added later without changing the public schema.

## Edge Features

For each directed edge `src -> dst`:

```text
[
  x_dst - x_src,
  y_dst - y_src,
  z_dst - z_src,
  euclidean_distance
]
```

Edges are bidirectional and contain no self-loops. For VTU meshes with cell type metadata, cell adjacency is based on shared faces, not shared points. This matches the finite-volume mesh topology and avoids connecting cells that merely touch at an edge or vertex. If cell type metadata is unavailable, the builder falls back to point-based adjacency for compatibility with minimal synthetic meshes.

## Target

The target vector is:

```text
[Ux, Uy, Uz, p]
```

This is a steady-state field target. It is not a timestep delta or next-state target.

## Normalizer

Normalizer state is saved as `normalizer.json` and fitted only from training samples. It stores feature and target means/scales, plus physical reference values when supplied by config.
