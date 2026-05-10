from pathlib import Path

import numpy as np
import pytest

from fan_sim.data.vtu import read_vtu


def test_read_vtu_extracts_polyhedron_faces(tmp_path: Path):
    vtk = pytest.importorskip("vtk")

    points = vtk.vtkPoints()
    for point in [
        (0, 0, 0),
        (1, 0, 0),
        (1, 1, 0),
        (0, 1, 0),
        (0, 0, 1),
        (1, 0, 1),
        (1, 1, 1),
        (0, 1, 1),
    ]:
        points.InsertNextPoint(*point)

    faces = vtk.vtkCellArray()
    for face in [[0, 3, 2, 1], [4, 5, 6, 7], [0, 1, 5, 4], [1, 2, 6, 5], [2, 3, 7, 6], [3, 0, 4, 7]]:
        ids = vtk.vtkIdList()
        for point_id in face:
            ids.InsertNextId(point_id)
        faces.InsertNextCell(ids)

    grid = vtk.vtkUnstructuredGrid()
    grid.SetPoints(points)
    grid.InsertNextCell(vtk.VTK_POLYHEDRON, 8, list(range(8)), faces)

    velocity = vtk.vtkDoubleArray()
    velocity.SetName("U")
    velocity.SetNumberOfComponents(3)
    velocity.InsertNextTuple3(1.0, 2.0, 3.0)
    pressure = vtk.vtkDoubleArray()
    pressure.SetName("p")
    pressure.InsertNextValue(4.0)
    grid.GetCellData().AddArray(velocity)
    grid.GetCellData().AddArray(pressure)

    path = tmp_path / "polyhedron.vtu"
    writer = vtk.vtkXMLUnstructuredGridWriter()
    writer.SetFileName(str(path))
    writer.SetInputData(grid)
    assert writer.Write() == 1

    mesh = read_vtu(path)

    assert mesh.cell_types is not None
    assert mesh.cell_types.tolist() == [42]
    assert sorted(mesh.cells[0].tolist()) == list(range(8))
    assert mesh.cell_faces is not None
    assert len(mesh.cell_faces[0]) == 6
    np.testing.assert_allclose(mesh.cell_data["U"], [[1.0, 2.0, 3.0]])
    np.testing.assert_allclose(mesh.cell_data["p"], [4.0])
