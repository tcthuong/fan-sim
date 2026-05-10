from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from typing import Any

import numpy as np

from fan_sim.data.vtu import MeshData, validate_field_association

SCHEMA_VERSION = "fan-sim-graph-v1"


def build_cell_graph_sample(
    *,
    mesh: MeshData,
    rpm: float,
    inlet_pressure: float,
    outlet_pressure: float,
    velocity_field: str = "U",
    pressure_field: str = "p",
    patch_flags: dict[str, np.ndarray] | None = None,
) -> dict[str, Any]:
    validate_field_association(mesh, velocity_field, pressure_field)
    pos = compute_cell_centers(mesh.points, mesh.cells)
    edge_index = build_bidirectional_edges(mesh.cells, mesh.cell_types)
    edge_attr = build_edge_features(pos, edge_index)
    x = build_node_features(pos, rpm, inlet_pressure, outlet_pressure, patch_flags)
    y = build_targets(mesh.cell_data[velocity_field], mesh.cell_data[pressure_field])

    return {
        "x": x.astype(np.float32),
        "edge_index": edge_index.astype(np.int64),
        "edge_attr": edge_attr.astype(np.float32),
        "y": y.astype(np.float32),
        "pos": pos.astype(np.float32),
        "case_meta": {
            "rpm": rpm,
            "inlet_pressure": inlet_pressure,
            "outlet_pressure": outlet_pressure,
            "source": mesh.source,
        },
        "schema_version": SCHEMA_VERSION,
    }


def compute_cell_centers(points: np.ndarray, cells: Sequence[Sequence[int]]) -> np.ndarray:
    point_array = np.asarray(points, dtype=np.float32)
    centers = []
    for cell in cells:
        if not cell:
            raise ValueError("Encountered empty cell while computing cell centers.")
        centers.append(point_array[np.asarray(cell, dtype=np.int64)].mean(axis=0))
    return np.asarray(centers, dtype=np.float32)


def build_bidirectional_edges(cells: Sequence[Sequence[int]], cell_types: np.ndarray | None = None) -> np.ndarray:
    if cell_types is not None:
        face_edges = _build_face_adjacency_edges(cells, cell_types)
        if face_edges is not None:
            return face_edges
    return _build_point_adjacency_edges(cells)


def _build_face_adjacency_edges(cells: Sequence[Sequence[int]], cell_types: np.ndarray) -> np.ndarray | None:
    if len(cells) != len(cell_types):
        return None

    face_owner: dict[tuple[int, ...], int] = {}
    undirected: list[tuple[int, int]] = []
    for cell_id, cell in enumerate(cells):
        cell_array = np.asarray(cell, dtype=np.int64)
        patterns = _face_patterns(int(cell_types[cell_id]), len(cell_array))
        if patterns is None:
            return None
        for pattern in patterns:
            face = tuple(sorted(int(cell_array[index]) for index in pattern))
            owner = face_owner.pop(face, None)
            if owner is None:
                face_owner[face] = cell_id
            else:
                undirected.append((owner, cell_id))

    return _directed_edges_from_undirected(undirected)


def _build_point_adjacency_edges(cells: Sequence[Sequence[int]]) -> np.ndarray:
    point_to_cells: dict[int, list[int]] = defaultdict(list)
    for cell_id, cell in enumerate(cells):
        for point_id in set(np.asarray(cell, dtype=np.int64).tolist()):
            point_to_cells[int(point_id)].append(cell_id)

    undirected: set[tuple[int, int]] = set()
    for incident_cells in point_to_cells.values():
        ordered = sorted(set(incident_cells))
        for i, src in enumerate(ordered):
            for dst in ordered[i + 1 :]:
                undirected.add((src, dst))

    return _directed_edges_from_undirected(sorted(undirected))


def _directed_edges_from_undirected(undirected: Sequence[tuple[int, int]]) -> np.ndarray:
    directed: list[tuple[int, int]] = []
    for src, dst in undirected:
        if src == dst:
            continue
        directed.append((src, dst))
        directed.append((dst, src))
    if not directed:
        return np.zeros((2, 0), dtype=np.int64)
    return np.asarray(directed, dtype=np.int64).T


def _face_patterns(cell_type: int, n_points: int) -> tuple[tuple[int, ...], ...] | None:
    # VTK cell type ids for common OpenFOAM volume cells.
    if cell_type == 10 and n_points == 4:  # VTK_TETRA
        return ((0, 1, 2), (0, 1, 3), (0, 2, 3), (1, 2, 3))
    if cell_type == 11 and n_points == 8:  # VTK_VOXEL
        return ((0, 1, 3, 2), (4, 5, 7, 6), (0, 1, 5, 4), (2, 3, 7, 6), (0, 2, 6, 4), (1, 3, 7, 5))
    if cell_type == 12 and n_points == 8:  # VTK_HEXAHEDRON
        return ((0, 1, 2, 3), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7))
    if cell_type == 13 and n_points == 6:  # VTK_WEDGE / prism
        return ((0, 1, 2), (3, 4, 5), (0, 1, 4, 3), (1, 2, 5, 4), (2, 0, 3, 5))
    if cell_type == 14 and n_points == 5:  # VTK_PYRAMID
        return ((0, 1, 2, 3), (0, 1, 4), (1, 2, 4), (2, 3, 4), (3, 0, 4))
    return None


def build_edge_features(pos: np.ndarray, edge_index: np.ndarray) -> np.ndarray:
    if edge_index.shape[1] == 0:
        return np.zeros((0, 4), dtype=np.float32)
    src = edge_index[0]
    dst = edge_index[1]
    delta = pos[dst] - pos[src]
    distance = np.linalg.norm(delta, axis=1, keepdims=True)
    return np.concatenate([delta, distance], axis=1).astype(np.float32)


def build_node_features(
    pos: np.ndarray,
    rpm: float,
    inlet_pressure: float,
    outlet_pressure: float,
    patch_flags: dict[str, np.ndarray] | None = None,
) -> np.ndarray:
    n_nodes = pos.shape[0]
    scalar_features = np.column_stack(
        [
            np.full(n_nodes, rpm, dtype=np.float32),
            np.full(n_nodes, inlet_pressure, dtype=np.float32),
            np.full(n_nodes, outlet_pressure, dtype=np.float32),
        ]
    )
    if patch_flags is None:
        flags = np.column_stack(
            [
                np.ones(n_nodes, dtype=np.float32),
                np.zeros(n_nodes, dtype=np.float32),
                np.zeros(n_nodes, dtype=np.float32),
                np.zeros(n_nodes, dtype=np.float32),
            ]
        )
    else:
        flags = np.column_stack(
            [
                patch_flags.get("is_internal", np.zeros(n_nodes)),
                patch_flags.get("is_wall_adjacent", np.zeros(n_nodes)),
                patch_flags.get("is_inlet_adjacent", np.zeros(n_nodes)),
                patch_flags.get("is_outlet_adjacent", np.zeros(n_nodes)),
            ]
        ).astype(np.float32)
    return np.concatenate([pos.astype(np.float32), scalar_features, flags], axis=1)


def build_targets(velocity: np.ndarray, pressure: np.ndarray) -> np.ndarray:
    u = np.asarray(velocity, dtype=np.float32)
    p = np.asarray(pressure, dtype=np.float32).reshape(-1, 1)
    return np.concatenate([u, p], axis=1)
