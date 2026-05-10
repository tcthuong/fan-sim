import numpy as np
import pytest

from fan_sim.data.vtu import MeshData, validate_field_association
from fan_sim.graph.build import build_cell_graph_sample
from fan_sim.ml.normalizer import GraphNormalizer


def _mesh_data() -> MeshData:
    points = np.array(
        [
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, 0.0, 1.0],
            [1.0, 1.0, 1.0],
        ],
        dtype=np.float32,
    )
    cells = [[0, 1, 2, 3], [1, 2, 3, 4]]
    cell_data = {
        "U": np.array([[1.0, 0.0, 0.0], [0.0, 2.0, 0.0]], dtype=np.float32),
        "p": np.array([10.0, 20.0], dtype=np.float32),
    }
    cell_types = np.array([10, 10], dtype=np.uint8)
    return MeshData(points=points, cells=cells, cell_data=cell_data, point_data={}, source="synthetic.vtu", cell_types=cell_types)


def test_validate_field_association_rejects_point_only_field():
    mesh = _mesh_data()
    mesh.cell_data.pop("U")
    mesh.point_data["U"] = np.zeros((5, 3), dtype=np.float32)

    with pytest.raises(ValueError, match="cell_data"):
        validate_field_association(mesh, velocity_field="U", pressure_field="p")


def test_build_cell_graph_sample_uses_cell_targets_and_bidirectional_edges():
    sample = build_cell_graph_sample(
        mesh=_mesh_data(),
        rpm=1200,
        inlet_pressure=0.0,
        outlet_pressure=20.0,
        velocity_field="U",
        pressure_field="p",
    )

    assert sample["schema_version"] == "fan-sim-graph-v1"
    assert sample["x"].shape == (2, 10)
    assert sample["pos"].shape == (2, 3)
    assert sample["y"].tolist() == [[1.0, 0.0, 0.0, 10.0], [0.0, 2.0, 0.0, 20.0]]
    assert sample["edge_index"].tolist() == [[0, 1], [1, 0]]
    assert sample["edge_attr"].shape == (2, 4)
    assert np.all(sample["edge_attr"][:, 3] > 0)


def test_cell_graph_uses_face_adjacency_not_point_adjacency():
    points = np.array(
        [
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, 0.0, 1.0],
            [0.0, 0.0, -1.0],
            [1.0, 1.0, 0.0],
            [1.0, 1.0, 1.0],
        ],
        dtype=np.float32,
    )
    mesh = MeshData(
        points=points,
        cells=[
            [0, 1, 2, 3],  # shares full face [0,1,2] with cell 1
            [0, 1, 2, 4],
            [0, 1, 5, 6],  # shares only edge [0,1], so no cell edge
        ],
        cell_types=np.array([10, 10, 10], dtype=np.uint8),
        cell_data={
            "U": np.zeros((3, 3), dtype=np.float32),
            "p": np.zeros(3, dtype=np.float32),
        },
        point_data={},
        source="synthetic.vtu",
    )

    sample = build_cell_graph_sample(
        mesh=mesh,
        rpm=1200,
        inlet_pressure=0.0,
        outlet_pressure=20.0,
        velocity_field="U",
        pressure_field="p",
    )

    assert sample["edge_index"].tolist() == [[0, 1], [1, 0]]


def test_graph_normalizer_round_trips_features_and_targets():
    sample = build_cell_graph_sample(
        mesh=_mesh_data(),
        rpm=1200,
        inlet_pressure=0.0,
        outlet_pressure=20.0,
        velocity_field="U",
        pressure_field="p",
    )

    normalizer = GraphNormalizer.fit([sample])
    transformed = normalizer.transform(sample)
    restored = normalizer.inverse_transform_target(transformed["y"])

    assert transformed["x"].shape == sample["x"].shape
    assert transformed["edge_attr"].shape == sample["edge_attr"].shape
    np.testing.assert_allclose(restored, sample["y"], rtol=1e-6, atol=1e-6)
