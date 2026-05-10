from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator, Sequence

import numpy as np


@dataclass
class CellTable(Sequence[np.ndarray]):
    values: np.ndarray
    starts: np.ndarray
    ends: np.ndarray

    def __len__(self) -> int:
        return int(self.starts.shape[0])

    def __getitem__(self, index: int) -> np.ndarray:
        return self.values[int(self.starts[index]) : int(self.ends[index])]

    def __iter__(self) -> Iterator[np.ndarray]:
        for index in range(len(self)):
            yield self[index]


@dataclass
class CellFaceTable(Sequence[list[np.ndarray]]):
    values: np.ndarray
    face_starts: np.ndarray
    face_ends: np.ndarray
    cell_starts: np.ndarray
    cell_ends: np.ndarray

    def __len__(self) -> int:
        return int(self.cell_starts.shape[0])

    def __getitem__(self, index: int) -> list[np.ndarray]:
        start = int(self.cell_starts[index])
        end = int(self.cell_ends[index])
        return [self.values[int(self.face_starts[face]) : int(self.face_ends[face])] for face in range(start, end)]

    @classmethod
    def from_nested(cls, cells: Sequence[Sequence[Sequence[int]]]) -> "CellFaceTable":
        values: list[int] = []
        face_starts: list[int] = []
        face_ends: list[int] = []
        cell_starts: list[int] = []
        cell_ends: list[int] = []
        for cell_faces in cells:
            cell_starts.append(len(face_starts))
            for face in cell_faces:
                face_starts.append(len(values))
                values.extend(int(point_id) for point_id in face)
                face_ends.append(len(values))
            cell_ends.append(len(face_starts))
        return cls(
            values=np.asarray(values, dtype=np.int64),
            face_starts=np.asarray(face_starts, dtype=np.int64),
            face_ends=np.asarray(face_ends, dtype=np.int64),
            cell_starts=np.asarray(cell_starts, dtype=np.int64),
            cell_ends=np.asarray(cell_ends, dtype=np.int64),
        )


@dataclass
class MeshData:
    points: np.ndarray
    cells: Sequence[Sequence[int]]
    cell_data: dict[str, np.ndarray]
    point_data: dict[str, np.ndarray]
    source: str
    cell_types: np.ndarray | None = None
    cell_faces: Sequence[Sequence[Sequence[int]]] | None = None


def validate_field_association(mesh: MeshData, velocity_field: str = "U", pressure_field: str = "p") -> None:
    _require_cell_field(mesh, velocity_field)
    _require_cell_field(mesh, pressure_field)

    velocity = np.asarray(mesh.cell_data[velocity_field])
    pressure = np.asarray(mesh.cell_data[pressure_field])
    n_cells = len(mesh.cells)
    if velocity.shape != (n_cells, 3):
        raise ValueError(f"Velocity field {velocity_field!r} must have shape ({n_cells}, 3); got {velocity.shape}.")
    if pressure.shape not in {(n_cells,), (n_cells, 1)}:
        raise ValueError(f"Pressure field {pressure_field!r} must have shape ({n_cells},) or ({n_cells}, 1); got {pressure.shape}.")


def read_vtu(
    path: str | Path,
    velocity_field: str = "U",
    pressure_field: str = "p",
    progress: Callable[[str], None] | None = None,
) -> MeshData:
    try:
        import pyvista as pv
    except ImportError as exc:
        raise RuntimeError("Reading VTU files requires the optional 'vtk' extra: pip install -e .[vtk]") from exc

    source = Path(path)
    _progress(progress, "loading VTU grid")
    grid = pv.read(source)
    _progress(progress, f"loaded VTU grid points={grid.n_points} cells={grid.n_cells}")
    _progress(progress, "extracting cell connectivity")
    cells = _extract_cells_from_grid(grid)
    cell_types = np.asarray(grid.celltypes, dtype=np.uint8) if hasattr(grid, "celltypes") else None
    _progress(progress, "extracting polyhedron face metadata")
    cell_faces = _extract_polyhedron_faces(grid, cell_types)
    _progress(progress, "copying field arrays")
    mesh = MeshData(
        points=np.asarray(grid.points, dtype=np.float32),
        cells=cells,
        cell_data={name: np.asarray(grid.cell_data[name]) for name in grid.cell_data.keys()},
        point_data={name: np.asarray(grid.point_data[name]) for name in grid.point_data.keys()},
        source=str(source),
        cell_types=cell_types,
        cell_faces=cell_faces,
    )
    validate_field_association(mesh, velocity_field, pressure_field)
    _progress(progress, "validated required cell fields")
    return mesh


def latest_vtu(case_dir: str | Path) -> Path:
    candidates = sorted(Path(case_dir).glob("VTK/**/*.vtu")) + sorted(Path(case_dir).glob("VTK/*.vtu"))
    if not candidates:
        raise FileNotFoundError(f"No .vtu files found under {Path(case_dir) / 'VTK'}")
    return candidates[-1]


def _require_cell_field(mesh: MeshData, field_name: str) -> None:
    if field_name not in mesh.cell_data:
        if field_name in mesh.point_data:
            raise ValueError(f"Field {field_name!r} is present in point_data but must be available in cell_data.")
        raise ValueError(f"Required cell_data field {field_name!r} is missing.")


def _extract_cells(flat_cells: Sequence[int]) -> CellTable:
    values = np.asarray(flat_cells, dtype=np.int64)
    starts: list[int] = []
    ends: list[int] = []
    i = 0
    while i < len(values):
        n_points = int(values[i])
        start = i + 1
        end = start + n_points
        starts.append(start)
        ends.append(end)
        i = end
    return CellTable(values=values, starts=np.asarray(starts, dtype=np.int64), ends=np.asarray(ends, dtype=np.int64))


def _extract_cells_from_grid(grid) -> CellTable:
    if hasattr(grid, "cell_connectivity") and hasattr(grid, "offset"):
        connectivity = np.asarray(grid.cell_connectivity, dtype=np.int64)
        offsets = np.asarray(grid.offset, dtype=np.int64)
        if offsets.shape[0] == int(grid.n_cells) + 1:
            return CellTable(values=connectivity, starts=offsets[:-1], ends=offsets[1:])
    return _extract_cells(grid.cells)


def _extract_polyhedron_faces(grid, cell_types: np.ndarray | None) -> CellFaceTable | None:
    if cell_types is None or not np.any(cell_types == 42):
        return None

    cell_faces: list[list[list[int]]] = []
    for cell_id in range(int(grid.n_cells)):
        if int(cell_types[cell_id]) != 42:
            cell_faces.append([])
            continue
        cell = grid.get_cell(cell_id)
        faces: list[list[int]] = []
        for face_id in range(int(cell.n_faces)):
            faces.append([int(point_id) for point_id in cell.get_face(face_id).point_ids])
        cell_faces.append(faces)
    return CellFaceTable.from_nested(cell_faces)


def _progress(progress: Callable[[str], None] | None, message: str) -> None:
    if progress is not None:
        progress(message)
