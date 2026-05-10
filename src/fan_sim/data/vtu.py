from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Sequence

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
class MeshData:
    points: np.ndarray
    cells: Sequence[Sequence[int]]
    cell_data: dict[str, np.ndarray]
    point_data: dict[str, np.ndarray]
    source: str
    cell_types: np.ndarray | None = None


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


def read_vtu(path: str | Path, velocity_field: str = "U", pressure_field: str = "p") -> MeshData:
    try:
        import pyvista as pv
    except ImportError as exc:
        raise RuntimeError("Reading VTU files requires the optional 'vtk' extra: pip install -e .[vtk]") from exc

    source = Path(path)
    grid = pv.read(source)
    cells = _extract_cells(grid.cells)
    mesh = MeshData(
        points=np.asarray(grid.points, dtype=np.float32),
        cells=cells,
        cell_data={name: np.asarray(grid.cell_data[name]) for name in grid.cell_data.keys()},
        point_data={name: np.asarray(grid.point_data[name]) for name in grid.point_data.keys()},
        source=str(source),
        cell_types=np.asarray(grid.celltypes, dtype=np.uint8) if hasattr(grid, "celltypes") else None,
    )
    validate_field_association(mesh, velocity_field, pressure_field)
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
