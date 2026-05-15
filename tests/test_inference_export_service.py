from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from fan_sim.export.artifacts import _fan_preview_seed_points, _write_colored_polyline_usd, export_prediction_artifacts
from fan_sim.config import FanSimConfig, CaseMatrix, ModelConfig
from fan_sim.inference.predictor import FanPredictor
from fan_sim.inference.loader import load_predictor_from_artifacts
from fan_sim.ml.dataset import save_graph_sample
from fan_sim.ml.model import NumpyLinearSurrogate
from fan_sim.ml.normalizer import GraphNormalizer
from fan_sim.service.app import create_app


class ConstantModel:
    def predict(self, sample):
        return np.array([[3.0, 0.0, 0.0, 30.0], [0.0, 4.0, 0.0, 40.0]], dtype=np.float32)


def _sample():
    return {
        "x": np.zeros((2, 10), dtype=np.float32),
        "edge_index": np.array([[0, 1], [1, 0]], dtype=np.int64),
        "edge_attr": np.ones((2, 4), dtype=np.float32),
        "pos": np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]], dtype=np.float32),
        "case_meta": {"case_id": "fan_base"},
        "schema_version": "fan-sim-graph-v1",
    }


def _write_two_tet_vtu(path: Path):
    vtk = pytest.importorskip("vtk")

    points = vtk.vtkPoints()
    for point in [
        (0.0, 0.0, 0.0),
        (1.0, 0.0, 0.0),
        (0.0, 1.0, 0.0),
        (0.0, 0.0, 1.0),
        (1.0, 1.0, 1.0),
    ]:
        points.InsertNextPoint(*point)

    grid = vtk.vtkUnstructuredGrid()
    grid.SetPoints(points)
    for cell_points in ([0, 1, 2, 3], [1, 2, 3, 4]):
        ids = vtk.vtkIdList()
        for point_id in cell_points:
            ids.InsertNextId(point_id)
        grid.InsertNextCell(vtk.VTK_TETRA, ids)

    velocity = vtk.vtkFloatArray()
    velocity.SetName("U")
    velocity.SetNumberOfComponents(3)
    velocity.InsertNextTuple3(0.0, 0.0, 0.0)
    velocity.InsertNextTuple3(0.0, 0.0, 0.0)
    pressure = vtk.vtkFloatArray()
    pressure.SetName("p")
    pressure.InsertNextValue(0.0)
    pressure.InsertNextValue(0.0)
    grid.GetCellData().AddArray(velocity)
    grid.GetCellData().AddArray(pressure)

    writer = vtk.vtkXMLUnstructuredGridWriter()
    writer.SetFileName(str(path))
    writer.SetInputData(grid)
    assert writer.Write() == 1
    return vtk


def _write_triangle_vtp(path: Path):
    vtk = pytest.importorskip("vtk")

    points = vtk.vtkPoints()
    for point in [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]:
        points.InsertNextPoint(*point)

    triangle = vtk.vtkTriangle()
    for index in range(3):
        triangle.GetPointIds().SetId(index, index)
    polys = vtk.vtkCellArray()
    polys.InsertNextCell(triangle)

    poly = vtk.vtkPolyData()
    poly.SetPoints(points)
    poly.SetPolys(polys)

    writer = vtk.vtkXMLPolyDataWriter()
    writer.SetFileName(str(path))
    writer.SetInputData(poly)
    assert writer.Write() == 1


def test_predictor_updates_operating_condition_and_returns_fields():
    predictor = FanPredictor(model=ConstantModel(), template_sample=_sample(), normalizer=None)

    result = predictor.predict(rpm=1500, inlet_pressure=0.0, outlet_pressure=25.0)

    assert result.prediction.shape == (2, 4)
    assert result.sample["case_meta"]["rpm"] == 1500
    assert result.sample["case_meta"]["outlet_pressure"] == 25.0
    assert result.fields == ["U_pred", "p_pred", "velocity_magnitude"]


def test_export_prediction_artifacts_writes_usd_and_seed_files(tmp_path: Path):
    predictor = FanPredictor(model=ConstantModel(), template_sample=_sample(), normalizer=None)
    result = predictor.predict(rpm=1500, inlet_pressure=0.0, outlet_pressure=25.0)

    artifacts = export_prediction_artifacts(result, output_dir=tmp_path, write_vtu=False)

    assert artifacts.prediction_usd.exists()
    assert artifacts.streamline_seeds_json.exists()
    assert artifacts.particle_seeds_json.exists()
    assert "rpm = 1500" in artifacts.prediction_usd.read_text(encoding="utf-8")


def test_write_colored_polyline_usd_groups_curves_by_speed(tmp_path: Path):
    output = tmp_path / "streamlines.usda"
    polylines = [
        np.array([[0.0, 0.0, 0.2], [0.0, 0.0, 0.0], [0.0, 0.0, -0.2]], dtype=np.float32),
        np.array([[0.05, 0.0, 0.2], [0.04, 0.0, 0.0], [0.03, 0.0, -0.2]], dtype=np.float32),
    ]

    _write_colored_polyline_usd(
        output,
        polylines,
        speeds=[5.0, 120.0],
        root_name="FanSimStreamlinePreview",
        curve_name_prefix="SpeedBin",
        width=0.002,
    )

    text = output.read_text(encoding="utf-8")
    assert 'defaultPrim = "FanSimStreamlinePreview"' in text
    assert 'def BasisCurves "SpeedBin' in text
    assert "int[] curveVertexCounts = [3]" in text
    assert "primvars:displayColor" in text
    assert "rel material:binding" in text


def test_fan_preview_seed_points_focus_near_fan_region():
    seeds = _fan_preview_seed_points((-0.13, 0.13, -0.13, 0.13, -0.30, 0.30), ring_count=3, angles_per_ring=8)

    assert seeds.shape == (72, 3)
    assert np.max(np.linalg.norm(seeds[:, :2], axis=1)) < 0.05
    assert np.allclose(np.unique(np.round(seeds[:, 2], 6)), [-0.036, 0.0, 0.036])


def test_export_prediction_vtu_preserves_source_openfoam_topology(tmp_path: Path):
    pv = pytest.importorskip("pyvista")
    source = tmp_path / "internal.vtu"
    vtk = _write_two_tet_vtu(source)

    predictor = FanPredictor(model=ConstantModel(), template_sample=_sample(), normalizer=None)
    result = predictor.predict(rpm=1500, inlet_pressure=0.0, outlet_pressure=25.0)
    result.sample["case_meta"]["source"] = str(source)

    artifacts = export_prediction_artifacts(result, output_dir=tmp_path / "out", write_vtu=True)

    exported = pv.read(artifacts.prediction_vtu)
    assert exported.n_cells == 2
    assert exported.celltypes.tolist() == [vtk.VTK_TETRA, vtk.VTK_TETRA]
    assert "U_pred" in exported.cell_data
    assert "p_pred" in exported.cell_data
    assert "velocity_magnitude" in exported.cell_data
    assert "U_pred" in exported.point_data
    assert "p_pred" in exported.point_data
    np.testing.assert_allclose(exported.cell_data["U_pred"], result.velocity)
    np.testing.assert_allclose(exported.cell_data["p_pred"], result.pressure)
    header = artifacts.prediction_vtu.read_bytes()[:4096]
    assert b'version="2.3"' in header
    assert b'format="appended"' in header
    assert b'encoding="raw"' in header
    assert b'type="Int32" Name="types"' in header


def test_export_prediction_vtu_maps_colab_source_to_local_runs_tree(tmp_path: Path):
    pv = pytest.importorskip("pyvista")
    repo = tmp_path / "repo"
    source = repo / "runs" / "openfoam" / "case_rpm_1500_pout_000" / "VTK" / "latest" / "internal.vtu"
    source.parent.mkdir(parents=True)
    vtk = _write_two_tet_vtu(source)

    predictor = FanPredictor(model=ConstantModel(), template_sample=_sample(), normalizer=None)
    result = predictor.predict(rpm=1500, inlet_pressure=0.0, outlet_pressure=25.0)
    result.sample["case_meta"]["source"] = "/content/fan-sim/runs/openfoam/case_rpm_1500_pout_000/VTK/latest/internal.vtu"

    artifacts = export_prediction_artifacts(result, output_dir=repo / "runs" / "inference" / "out", write_vtu=True)

    exported = pv.read(artifacts.prediction_vtu)
    assert exported.n_cells == 2
    assert exported.celltypes.tolist() == [vtk.VTK_TETRA, vtk.VTK_TETRA]
    np.testing.assert_allclose(exported.cell_data["U_pred"], result.velocity)


def test_export_prediction_artifacts_writes_fan_mesh_usd_from_boundary_vtp(tmp_path: Path):
    repo = tmp_path / "repo"
    case_vtk_dir = repo / "runs" / "openfoam" / "case_rpm_1500_pout_000" / "VTK" / "latest"
    boundary_dir = case_vtk_dir / "boundary"
    boundary_dir.mkdir(parents=True)
    _write_two_tet_vtu(case_vtk_dir / "internal.vtu")
    _write_triangle_vtp(boundary_dir / "face1.vtp")
    _write_triangle_vtp(boundary_dir / "face7.vtp")

    predictor = FanPredictor(model=ConstantModel(), template_sample=_sample(), normalizer=None)
    result = predictor.predict(rpm=1500, inlet_pressure=0.0, outlet_pressure=25.0)
    result.sample["case_meta"]["source"] = "/content/fan-sim/runs/openfoam/case_rpm_1500_pout_000/VTK/latest/internal.vtu"

    artifacts = export_prediction_artifacts(result, output_dir=repo / "runs" / "inference" / "out", write_vtu=True)

    assert artifacts.fan_mesh_usd is not None
    assert artifacts.fan_mesh_usd.exists()
    fan_mesh_text = artifacts.fan_mesh_usd.read_text(encoding="utf-8")
    assert "openfoam:boundaryPatchCount = 1" in fan_mesh_text
    assert "openfoam:boundaryPointCount" in fan_mesh_text
    assert "openfoam:boundaryFaceCount" in fan_mesh_text
    assert "face7.vtp" in fan_mesh_text
    assert "face1.vtp" not in fan_mesh_text
    assert 'def BasisCurves "FanMeshWire"' in fan_mesh_text
    assert 'def Material "FanMeshMaterial"' in fan_mesh_text
    assert "normal3f[] normals" in fan_mesh_text
    prediction_text = artifacts.prediction_usd.read_text(encoding="utf-8")
    assert "fan_mesh.usda" in prediction_text


def test_service_predict_endpoint_returns_artifact_paths(tmp_path: Path):
    predictor = FanPredictor(model=ConstantModel(), template_sample=_sample(), normalizer=None)
    app = create_app(predictor=predictor, output_root=tmp_path, write_vtu=False)
    client = TestClient(app)

    response = client.post(
        "/predict",
        json={
            "case_id": "fan_base",
            "rpm": 1500,
            "inlet_pressure": 0,
            "outlet_pressure": 25,
            "outputs": ["usd", "streamlines", "particles"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["prediction_usd"].endswith("prediction.usda")
    assert body["fan_mesh_usd"] is None
    assert body["fields"] == ["U_pred", "p_pred", "velocity_magnitude"]
    assert Path(body["prediction_usd"]).exists()


def test_load_predictor_from_artifacts_uses_saved_template_normalizer_and_numpy_checkpoint(tmp_path: Path):
    graph_dir = tmp_path / "artifacts" / "graphs"
    model_dir = tmp_path / "artifacts" / "models" / "fan_mgn"
    sample = _sample()
    sample["y"] = np.array([[3.0, 0.0, 0.0, 30.0], [0.0, 4.0, 0.0, 40.0]], dtype=np.float32)
    save_graph_sample(sample, graph_dir / "fan_base.graph.pt")
    normalizer = GraphNormalizer.fit([sample])
    normalizer.save(model_dir / "normalizer.json")
    normalized = normalizer.transform(sample)
    model = NumpyLinearSurrogate()
    model.fit([normalized])
    model.save(model_dir / "checkpoint.npz")
    cfg = FanSimConfig(
        base_case=tmp_path / "data" / "base_case",
        case_matrix=CaseMatrix(rpm=[1200], outlet_pressure=[20]),
        model=ModelConfig(backend="numpy", output_dir=model_dir),
        root=tmp_path,
    )

    predictor = load_predictor_from_artifacts(cfg, case_id="fan_base")
    result = predictor.predict(rpm=1500, inlet_pressure=0.0, outlet_pressure=25.0)

    assert result.prediction.shape == (2, 4)
    assert result.sample["case_meta"]["rpm"] == 1500
