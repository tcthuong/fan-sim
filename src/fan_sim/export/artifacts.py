from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import zlib
import xml.etree.ElementTree as ET

import numpy as np

from fan_sim.inference.predictor import PredictionResult


@dataclass
class PredictionArtifacts:
    prediction_vtu: Path | None
    prediction_usd: Path
    streamline_seeds_json: Path
    particle_seeds_json: Path
    metrics_json: Path
    fan_mesh_usd: Path | None = None
    prediction_streamlines_usd: Path | None = None
    prediction_particles_usd: Path | None = None


def export_prediction_artifacts(
    result: PredictionResult,
    *,
    output_dir: str | Path,
    write_vtu: bool = True,
    write_streamlines_usd: bool = False,
    write_particles_usd: bool = False,
) -> PredictionArtifacts:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    prediction_vtu = output / "prediction.vtu" if write_vtu else None
    prediction_usd = output / "prediction.usda"
    streamline_seeds = output / "streamline_seeds.json"
    particle_seeds = output / "particle_seeds.json"
    metrics = output / "metrics.json"
    streamlines_usd = output / "prediction_streamlines.usda" if write_streamlines_usd else None
    particles_usd = output / "prediction_particles.usda" if write_particles_usd else None
    source_vtu = _resolve_source_vtu(result, output)
    fan_mesh_usd = _write_fan_mesh_artifact(output, source_vtu)

    if prediction_vtu is not None:
        write_prediction_vtu(prediction_vtu, result, search_root=output)
    if streamlines_usd is not None and prediction_vtu is not None:
        streamlines_usd = write_prediction_streamlines_usd(streamlines_usd, prediction_vtu)
    if particles_usd is not None and prediction_vtu is not None:
        particles_usd = write_prediction_particles_usd(particles_usd, prediction_vtu)
    write_prediction_usd(prediction_usd, result, prediction_vtu, fan_mesh_usd=fan_mesh_usd)
    _write_seed_json(streamline_seeds, result, kind="streamlines")
    _write_seed_json(particle_seeds, result, kind="particles")
    metrics.write_text(json.dumps(compute_metrics(result), indent=2), encoding="utf-8")

    return PredictionArtifacts(
        prediction_vtu,
        prediction_usd,
        streamline_seeds,
        particle_seeds,
        metrics,
        fan_mesh_usd,
        streamlines_usd,
        particles_usd,
    )


def write_prediction_vtu(path: str | Path, result: PredictionResult, search_root: str | Path | None = None) -> None:
    source_vtu = _resolve_source_vtu(result, search_root)
    if source_vtu is not None and _write_prediction_on_source_vtu(path, result, source_vtu):
        return
    _write_prediction_vertex_vtu(path, result)


def _write_prediction_on_source_vtu(path: str | Path, result: PredictionResult, source_vtu: Path) -> bool:
    try:
        import pyvista as pv
    except ImportError:
        return False

    grid = pv.read(source_vtu)
    n_cells = int(grid.n_cells)
    if result.prediction.shape[0] != n_cells:
        return False

    grid.cell_data["U_pred"] = np.asarray(result.velocity, dtype=np.float32)
    grid.cell_data["p_pred"] = np.asarray(result.pressure, dtype=np.float32)
    grid.cell_data["velocity_magnitude"] = np.asarray(result.velocity_magnitude, dtype=np.float32)

    point_grid = grid.cell_data_to_point_data(pass_cell_data=True)
    _write_kit_cae_vtu(path, point_grid)
    return True


def _write_kit_cae_vtu(path: str | Path, grid) -> None:
    import vtk

    output = Path(path)
    writer = vtk.vtkXMLUnstructuredGridWriter()
    writer.SetFileName(str(output))
    writer.SetInputData(grid)
    writer.SetDataModeToAppended()
    writer.EncodeAppendedDataOff()
    writer.SetCompressorTypeToZLib()
    if writer.Write() != 1:
        raise RuntimeError(f"Failed to write VTU file: {output}")

    # Kit-CAE's optimized VTU delegate currently gates on VTK XML version 2.3
    # plus raw appended payloads. VTK writes a compatible payload but labels it
    # 0.1, which makes Kit fall back to the slower delegate that fails on large
    # OpenFOAM VTUs during deferred array reads.
    data = output.read_bytes()
    data = data.replace(b'version="0.1"', b'version="2.3"', 1)
    data = _patch_vtu_cell_types_to_int32(data)
    output.write_bytes(data)


def _patch_vtu_cell_types_to_int32(data: bytes) -> bytes:
    appended_tag = data.find(b"<AppendedData")
    if appended_tag < 0 or b'type="UInt8" Name="types"' not in data[:appended_tag]:
        return data

    root = ET.fromstring(data[:appended_tag].decode("ascii", errors="ignore") + "</VTKFile>")
    vtk_file = root
    byte_order = vtk_file.attrib.get("byte_order", "LittleEndian")
    header_dtype = np.dtype(np.uint64 if vtk_file.attrib.get("header_type") == "UInt64" else np.uint32)
    header_dtype = header_dtype.newbyteorder("<" if byte_order == "LittleEndian" else ">")
    compressor = vtk_file.attrib.get("compressor")

    types_elem = root.find(".//Cells/DataArray[@Name='types']")
    if types_elem is None or types_elem.attrib.get("type") != "UInt8":
        return data

    underscore = data.index(b"_", appended_tag)
    block_start = underscore + 1 + int(types_elem.attrib["offset"])
    cell_types, block_end = _read_vtu_appended_array_block(data, block_start, header_dtype, np.dtype(np.uint8), compressor)
    int32_types = np.asarray(cell_types, dtype=np.int32)
    replacement = _write_zlib_vtu_block(int32_types.view(np.uint8), header_dtype)

    patched = data[:appended_tag].replace(b'type="UInt8" Name="types"', b'type="Int32" Name="types"', 1)
    return patched + data[appended_tag:block_start] + replacement + data[block_end:]


def _read_vtu_appended_array_block(
    data: bytes, block_start: int, header_dtype: np.dtype, elem_dtype: np.dtype, compressor: str | None
) -> tuple[np.ndarray, int]:
    h = header_dtype.itemsize
    if not compressor:
        byte_count = int(np.frombuffer(data[block_start : block_start + h], dtype=header_dtype)[0])
        payload_start = block_start + h
        payload_end = payload_start + byte_count
        return np.frombuffer(data[payload_start:payload_end], dtype=elem_dtype), payload_end

    if compressor != "vtkZLibDataCompressor":
        raise RuntimeError(f"Unsupported VTU compressor for cell type patching: {compressor}")

    num_blocks = int(np.frombuffer(data[block_start : block_start + h], dtype=header_dtype)[0])
    uncompressed_block_size = int(np.frombuffer(data[block_start + h : block_start + 2 * h], dtype=header_dtype)[0])
    last_partial_size = int(np.frombuffer(data[block_start + 2 * h : block_start + 3 * h], dtype=header_dtype)[0])
    sizes_start = block_start + 3 * h
    sizes_end = sizes_start + num_blocks * h
    compressed_sizes = np.frombuffer(data[sizes_start:sizes_end], dtype=header_dtype)

    cursor = sizes_end
    chunks: list[bytes] = []
    for index, compressed_size in enumerate(compressed_sizes):
        compressed_end = cursor + int(compressed_size)
        chunk = zlib.decompress(data[cursor:compressed_end])
        expected = last_partial_size if index == num_blocks - 1 and last_partial_size > 0 else uncompressed_block_size
        if len(chunk) != expected:
            raise RuntimeError("Unexpected VTU compressed block size while patching cell types.")
        chunks.append(chunk)
        cursor = compressed_end

    return np.frombuffer(b"".join(chunks), dtype=elem_dtype), cursor


def _write_zlib_vtu_block(raw_bytes: np.ndarray, header_dtype: np.dtype, block_size: int = 32768) -> bytes:
    raw = raw_bytes.tobytes()
    chunks = [raw[start : start + block_size] for start in range(0, len(raw), block_size)]
    if not chunks:
        chunks = [b""]
    compressed = [zlib.compress(chunk) for chunk in chunks]
    last_partial_size = len(chunks[-1]) if len(chunks[-1]) != block_size else 0
    header = np.asarray(
        [len(chunks), block_size, last_partial_size, *(len(chunk) for chunk in compressed)],
        dtype=header_dtype,
    )
    return header.tobytes() + b"".join(compressed)


def _write_prediction_vertex_vtu(path: str | Path, result: PredictionResult) -> None:
    pos = np.asarray(result.sample["pos"], dtype=np.float32)
    velocity = result.velocity
    pressure = result.pressure
    speed = result.velocity_magnitude
    n_points = pos.shape[0]
    connectivity = " ".join(str(i) for i in range(n_points))
    offsets = " ".join(str(i + 1) for i in range(n_points))
    types = " ".join("1" for _ in range(n_points))

    text = f"""<?xml version="1.0"?>
<VTKFile type="UnstructuredGrid" version="0.1" byte_order="LittleEndian">
  <UnstructuredGrid>
    <Piece NumberOfPoints="{n_points}" NumberOfCells="{n_points}">
      <Points>
        <DataArray type="Float32" NumberOfComponents="3" format="ascii">
          {_format_array(pos)}
        </DataArray>
      </Points>
      <Cells>
        <DataArray type="Int64" Name="connectivity" format="ascii">{connectivity}</DataArray>
        <DataArray type="Int64" Name="offsets" format="ascii">{offsets}</DataArray>
        <DataArray type="UInt8" Name="types" format="ascii">{types}</DataArray>
      </Cells>
      <PointData Vectors="U_pred" Scalars="p_pred">
        <DataArray type="Float32" Name="U_pred" NumberOfComponents="3" format="ascii">{_format_array(velocity)}</DataArray>
        <DataArray type="Float32" Name="p_pred" format="ascii">{_format_array(pressure.reshape(-1, 1))}</DataArray>
        <DataArray type="Float32" Name="velocity_magnitude" format="ascii">{_format_array(speed.reshape(-1, 1))}</DataArray>
      </PointData>
    </Piece>
  </UnstructuredGrid>
</VTKFile>
"""
    Path(path).write_text(text, encoding="utf-8")


def _resolve_source_vtu(result: PredictionResult, search_root: str | Path | None) -> Path | None:
    source = str(result.sample.get("case_meta", {}).get("source", "")).strip()
    if not source:
        return None

    direct = Path(source)
    if direct.exists():
        return direct

    normalized = source.replace("\\", "/")
    marker = "runs/openfoam/"
    marker_index = normalized.find(marker)
    if marker_index < 0 or search_root is None:
        return None

    suffix = normalized[marker_index + len(marker) :]
    for parent in [Path(search_root).resolve(), *Path(search_root).resolve().parents]:
        candidate = parent / marker / suffix
        if candidate.exists():
            return candidate
    return None


def write_prediction_usd(
    path: str | Path,
    result: PredictionResult,
    prediction_vtu: Path | None,
    fan_mesh_usd: Path | None = None,
) -> None:
    meta = result.sample.get("case_meta", {})
    vtu_asset = "" if prediction_vtu is None else prediction_vtu.as_posix()
    rpm = meta.get("rpm", 0.0)
    outlet_pressure = meta.get("outlet_pressure", 0.0)
    fan_mesh_reference = ""
    if fan_mesh_usd is not None:
        fan_mesh_reference = f'''
    def Xform "FanMesh" (
        references = @{fan_mesh_usd.name}@</OpenFOAMCase>
    )
    {{
    }}
'''
    text = f"""#usda 1.0
(
    defaultPrim = "World"
)

def Xform "World"
{{
    custom string fanSim:predictionVtu = "{vtu_asset}"
    custom float rpm = {rpm:g}
    custom float outlet_pressure = {outlet_pressure:g}
    def Scope "FanSimPrediction"
    {{
        custom string[] fields = ["U_pred", "p_pred", "velocity_magnitude"]
    }}
{fan_mesh_reference.rstrip()}
}}
"""
    Path(path).write_text(text, encoding="utf-8")


def write_prediction_streamlines_usd(path: str | Path, prediction_vtu: str | Path) -> Path | None:
    curves = _build_streamline_polylines(prediction_vtu)
    if curves is None:
        return None
    polylines, speeds = curves
    if not polylines:
        return None
    output = Path(path)
    _write_colored_polyline_usd(
        output,
        polylines,
        speeds,
        root_name="FanSimStreamlinePreview",
        curve_name_prefix="SpeedBin",
        width=0.0009,
    )
    return output


def write_prediction_particles_usd(path: str | Path, prediction_vtu: str | Path) -> Path | None:
    curves = _build_streamline_polylines(prediction_vtu, seed_resolution=10, max_steps=700, max_time=0.16)
    if curves is None:
        return None
    polylines, speeds = curves
    particle_points: list[np.ndarray] = []
    particle_speeds: list[float] = []
    for polyline, speed in zip(polylines, speeds):
        if len(polyline) < 2:
            continue
        stride = max(1, len(polyline) // 4)
        particle_points.append(polyline[::stride])
        particle_speeds.extend([speed] * len(polyline[::stride]))
    if not particle_points:
        return None
    points = np.concatenate(particle_points, axis=0)
    if len(points) > 120:
        sample = np.linspace(0, len(points) - 1, 120).astype(np.int64)
        points = points[sample]
        particle_speeds = [particle_speeds[index] for index in sample]

    output = Path(path)
    _write_colored_points_usd(
        output,
        points,
        particle_speeds,
        root_name="FanSimParticlePreview",
        points_name_prefix="SpeedPoints",
        width=0.0028,
    )
    return output


def _build_streamline_polylines(
    prediction_vtu: str | Path,
    *,
    seed_resolution: int = 16,
    max_steps: int = 1800,
    max_time: float = 1.2,
) -> tuple[list[np.ndarray], list[float]] | None:
    try:
        import pyvista as pv
    except ImportError:
        return None

    mesh = pv.read(prediction_vtu)
    if "U_pred" not in mesh.point_data:
        if "U_pred" in mesh.cell_data:
            mesh = mesh.cell_data_to_point_data(pass_cell_data=True)
        else:
            return None

    seed_points = _fan_preview_seed_points(
        mesh.bounds,
        ring_count=max(2, min(4, seed_resolution // 4)),
        angles_per_ring=max(8, seed_resolution),
    )
    seeds = pv.PolyData(seed_points)
    if seeds.n_points == 0:
        return None

    try:
        lines = mesh.streamlines_from_source(
            seeds,
            vectors="U_pred",
            integrator_type=45,
            integration_direction="both",
            initial_step_length=0.002,
            step_unit="l",
            min_step_length=0.0004,
            max_step_length=0.006,
            max_steps=max_steps,
            terminal_speed=1e-8,
            max_length=max_time,
        )
    except TypeError:
        lines = mesh.streamlines_from_source(
            seeds,
            vectors="U_pred",
            integrator_type=45,
            integration_direction="both",
            initial_step_length=0.002,
            step_unit="l",
            min_step_length=0.0004,
            max_step_length=0.006,
            max_steps=max_steps,
            terminal_speed=1e-8,
        )

    if lines.n_points == 0 or lines.n_cells == 0:
        return None

    speed_array = lines.point_data.get("velocity_magnitude")
    if speed_array is None:
        speed_array = np.linalg.norm(np.asarray(lines.point_data["U_pred"], dtype=np.float32), axis=1)
    return _extract_polyline_points(lines.points, lines.lines, speed_array)


def _fan_preview_seed_points(
    bounds,
    *,
    ring_count: int = 4,
    angles_per_ring: int = 16,
    plane_count: int = 3,
) -> np.ndarray:
    x_min, x_max, y_min, y_max, z_min, z_max = [float(value) for value in bounds]
    span_x = max(x_max - x_min, 1e-6)
    span_y = max(y_max - y_min, 1e-6)
    span_z = max(z_max - z_min, 1e-6)
    center_x = (x_min + x_max) * 0.5
    center_y = (y_min + y_max) * 0.5
    center_z = (z_min + z_max) * 0.5
    plane_offsets = np.linspace(-0.06 * span_z, 0.06 * span_z, max(1, plane_count))
    max_radius = 0.16 * min(span_x, span_y)
    radii = np.linspace(max_radius / (ring_count + 1), max_radius, ring_count)
    angles = np.linspace(0.0, 2.0 * np.pi, angles_per_ring, endpoint=False)
    points = [
        (center_x + radius * np.cos(angle), center_y + radius * np.sin(angle), center_z + z_offset)
        for z_offset in plane_offsets
        for radius in radii
        for angle in angles
    ]
    return np.asarray(points, dtype=np.float32)


def _extract_polyline_points(points, lines, speeds) -> tuple[list[np.ndarray], list[float]]:
    all_points = np.asarray(points, dtype=np.float32)
    all_speeds = np.asarray(speeds, dtype=np.float32)
    cells = np.asarray(lines, dtype=np.int64)
    polylines: list[np.ndarray] = []
    line_speeds: list[float] = []
    index = 0
    while index < cells.size:
        count = int(cells[index])
        ids = cells[index + 1 : index + 1 + count]
        if count >= 2 and ids.size == count:
            polyline = all_points[ids]
            polylines.append(polyline)
            line_speeds.append(float(np.nanmean(all_speeds[ids])))
        index += count + 1
    return polylines, line_speeds


def _write_colored_polyline_usd(
    path: str | Path,
    polylines: list[np.ndarray],
    speeds,
    *,
    root_name: str,
    curve_name_prefix: str,
    width: float,
) -> None:
    bins = _group_indices_by_speed(speeds)
    with Path(path).open("w", encoding="utf-8", newline="\n") as stream:
        _write_preview_usd_header(stream, root_name)
        _write_preview_materials(stream, root_name)
        for bin_index, indices in enumerate(bins):
            if not indices:
                continue
            points: list[list[float]] = []
            counts: list[int] = []
            for curve_index in indices:
                polyline = np.asarray(polylines[curve_index], dtype=float)
                if len(polyline) < 2:
                    continue
                counts.append(len(polyline))
                points.extend(polyline.tolist())
            if not counts:
                continue
            stream.write(f'    def BasisCurves "{curve_name_prefix}{bin_index:02d}"\n')
            stream.write("    {\n")
            stream.write('        uniform token type = "linear"\n')
            stream.write('        uniform token wrap = "nonperiodic"\n')
            stream.write('        float[] widths = [{0}] (\n'.format(_format_usd_float(width)))
            stream.write('            interpolation = "constant"\n')
            stream.write("        )\n")
            _write_display_color(stream, bin_index, "        ")
            _write_usd_array(stream, "int[] curveVertexCounts", counts, str, "        ")
            _write_usd_array(stream, "point3f[] points", points, _format_usd_point, "        ", inline_limit=4)
            stream.write(f"        rel material:binding = </{root_name}/Materials/Speed{bin_index:02d}>\n")
            stream.write("    }\n")
        stream.write("}\n")


def _write_colored_points_usd(
    path: str | Path,
    points: np.ndarray,
    speeds,
    *,
    root_name: str,
    points_name_prefix: str,
    width: float,
) -> None:
    bins = _group_indices_by_speed(speeds)
    all_points = np.asarray(points, dtype=float)
    with Path(path).open("w", encoding="utf-8", newline="\n") as stream:
        _write_preview_usd_header(stream, root_name)
        _write_preview_materials(stream, root_name)
        for bin_index, indices in enumerate(bins):
            if not indices:
                continue
            subset = all_points[indices]
            stream.write(f'    def Points "{points_name_prefix}{bin_index:02d}"\n')
            stream.write("    {\n")
            stream.write('        float[] widths = [{0}] (\n'.format(_format_usd_float(width)))
            stream.write('            interpolation = "constant"\n')
            stream.write("        )\n")
            _write_display_color(stream, bin_index, "        ")
            _write_usd_array(stream, "point3f[] points", subset.tolist(), _format_usd_point, "        ", inline_limit=4)
            stream.write(f"        rel material:binding = </{root_name}/Materials/Speed{bin_index:02d}>\n")
            stream.write("    }\n")
        stream.write("}\n")


def _group_indices_by_speed(speeds, bin_count: int = 7) -> list[list[int]]:
    values = np.asarray(list(speeds), dtype=np.float32)
    groups: list[list[int]] = [[] for _ in range(bin_count)]
    if values.size == 0:
        return groups
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        groups[0].extend(range(values.size))
        return groups
    quantiles = np.quantile(finite, np.linspace(0.0, 1.0, bin_count + 1))
    for index, value in enumerate(values):
        if not np.isfinite(value) or float(quantiles[-1] - quantiles[0]) <= 1e-12:
            bin_index = 0
        else:
            bin_index = int(np.searchsorted(quantiles[1:-1], float(value), side="right"))
        groups[bin_index].append(index)
    return groups


def _write_preview_usd_header(stream, root_name: str) -> None:
    stream.write("#usda 1.0\n")
    stream.write("(\n")
    stream.write(f'    defaultPrim = "{root_name}"\n')
    stream.write("    metersPerUnit = 1\n")
    stream.write('    upAxis = "Z"\n')
    stream.write(")\n\n")
    stream.write(f'def Xform "{root_name}"\n')
    stream.write("{\n")


def _write_preview_materials(stream, root_name: str) -> None:
    colors = _preview_speed_colors()
    stream.write('    def Scope "Materials"\n')
    stream.write("    {\n")
    for index, color in enumerate(colors):
        color_text = _format_usd_point(color)
        stream.write(f'        def Material "Speed{index:02d}"\n')
        stream.write("        {\n")
        stream.write('            token outputs:surface.connect = </{0}/Materials/Speed{1:02d}/PreviewSurface.outputs:surface>\n'.format(root_name, index))
        stream.write('            def Shader "PreviewSurface"\n')
        stream.write("            {\n")
        stream.write('                uniform token info:id = "UsdPreviewSurface"\n')
        stream.write(f"                color3f inputs:diffuseColor = {color_text}\n")
        stream.write(f"                color3f inputs:emissiveColor = {color_text}\n")
        stream.write("                float inputs:roughness = 0.35\n")
        stream.write("                token outputs:surface\n")
        stream.write("            }\n")
        stream.write("        }\n")
    stream.write("    }\n")


def _preview_speed_colors() -> list[tuple[float, float, float]]:
    return [
        (0.12, 0.25, 0.95),
        (0.00, 0.62, 1.00),
        (0.00, 0.82, 0.72),
        (0.35, 0.86, 0.28),
        (0.95, 0.82, 0.16),
        (1.00, 0.48, 0.10),
        (0.95, 0.08, 0.08),
    ]


def _write_display_color(stream, bin_index: int, indent: str) -> None:
    color = _preview_speed_colors()[bin_index]
    stream.write(f"{indent}color3f[] primvars:displayColor = [{_format_usd_point(color)}] (\n")
    stream.write(f'{indent}    interpolation = "constant"\n')
    stream.write(f"{indent})\n")


def _write_fan_mesh_artifact(output_dir: Path, source_vtu: Path | None) -> Path | None:
    if source_vtu is None:
        return None
    boundary_dir = source_vtu.parent / "boundary"
    if not boundary_dir.is_dir():
        return None
    output_path = output_dir / "fan_mesh.usda"
    if write_fan_mesh_usd(output_path, boundary_dir):
        return output_path
    return None


def write_fan_mesh_usd(
    path: str | Path,
    boundary_dir: str | Path,
    *,
    excluded_patch_ids: set[int] | None = None,
) -> bool:
    excluded = {1, 2, 3, 4, 5, 6} if excluded_patch_ids is None else excluded_patch_ids
    try:
        import vtkmodules.vtkCommonDataModel  # noqa: F401
        from vtkmodules.util.numpy_support import vtk_to_numpy
        from vtkmodules.vtkFiltersCore import vtkAppendPolyData, vtkCleanPolyData, vtkPolyDataNormals, vtkTriangleFilter
        from vtkmodules.vtkFiltersModeling import vtkFillHolesFilter
        from vtkmodules.vtkIOXML import vtkXMLPolyDataReader
    except ImportError:
        return False

    boundary = Path(boundary_dir)
    append = vtkAppendPolyData()
    included_patches: list[str] = []
    for patch_path in sorted(boundary.glob("face*.vtp"), key=_patch_id):
        if _patch_id(patch_path) in excluded:
            continue
        reader = vtkXMLPolyDataReader()
        reader.SetFileName(str(patch_path))
        reader.Update()
        poly = reader.GetOutput()
        if poly is None or poly.GetNumberOfPoints() == 0 or poly.GetNumberOfPolys() == 0:
            continue
        append.AddInputData(poly)
        included_patches.append(patch_path.name)

    if not included_patches:
        return False

    append.Update()
    clean = vtkCleanPolyData()
    clean.SetInputConnection(append.GetOutputPort())
    clean.SetTolerance(1e-6)
    clean.Update()
    fill = vtkFillHolesFilter()
    fill.SetInputConnection(clean.GetOutputPort())
    fill.SetHoleSize(0.0045)
    fill.Update()
    triangle = vtkTriangleFilter()
    triangle.SetInputConnection(fill.GetOutputPort())
    triangle.Update()
    normals = vtkPolyDataNormals()
    normals.SetInputConnection(triangle.GetOutputPort())
    normals.ConsistencyOn()
    normals.AutoOrientNormalsOn()
    normals.ComputePointNormalsOn()
    normals.ComputeCellNormalsOff()
    normals.SplittingOff()
    normals.Update()
    poly = normals.GetOutput()

    if poly is None or poly.GetNumberOfPoints() == 0 or poly.GetNumberOfPolys() == 0:
        return False

    points = vtk_to_numpy(poly.GetPoints().GetData()).astype(np.float32, copy=False)
    point_normals = poly.GetPointData().GetNormals()
    normal_values = None
    if point_normals is not None:
        normal_values = vtk_to_numpy(point_normals).astype(np.float32, copy=False)
    face_counts: list[int] = []
    face_indices: list[int] = []
    polys = poly.GetPolys()
    if hasattr(polys, "GetConnectivityArray") and hasattr(polys, "GetOffsetsArray"):
        connectivity = vtk_to_numpy(polys.GetConnectivityArray()).astype(np.int64, copy=False)
        offsets = vtk_to_numpy(polys.GetOffsetsArray()).astype(np.int64, copy=False)
        for start, end in zip(offsets[:-1], offsets[1:]):
            count = int(end - start)
            if count >= 3:
                face_counts.append(count)
                face_indices.extend(int(value) for value in connectivity[start:end])
    else:
        cells = vtk_to_numpy(polys.GetData()).astype(np.int64, copy=False)
        index = 0
        while index < cells.size:
            count = int(cells[index])
            if count >= 3:
                face_counts.append(count)
                face_indices.extend(int(value) for value in cells[index + 1 : index + 1 + count])
            index += count + 1

    text_path = Path(path)
    with text_path.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write("#usda 1.0\n")
        stream.write("(\n")
        stream.write('    defaultPrim = "OpenFOAMCase"\n')
        stream.write("    metersPerUnit = 1\n")
        stream.write('    upAxis = "Z"\n')
        stream.write(")\n\n")
        stream.write('def Xform "OpenFOAMCase"\n')
        stream.write("{\n")
        stream.write('    def Mesh "FanMesh"\n')
        stream.write("    {\n")
        stream.write('        uniform token subdivisionScheme = "none"\n')
        stream.write("        uniform bool doubleSided = true\n")
        stream.write(f"        custom int openfoam:boundaryPointCount = {len(points)}\n")
        stream.write(f"        custom int openfoam:boundaryFaceCount = {len(face_counts)}\n")
        stream.write(f"        custom int openfoam:boundaryPatchCount = {len(included_patches)}\n")
        _write_usd_string_array(stream, "custom string[] openfoam:sourcePatches", included_patches, "        ")
        _write_usd_array(stream, "int[] faceVertexCounts", face_counts, str, "        ")
        _write_usd_array(stream, "int[] faceVertexIndices", face_indices, str, "        ")
        _write_usd_array(stream, "point3f[] points", points.tolist(), _format_usd_point, "        ", inline_limit=4)
        if normal_values is not None and normal_values.shape == points.shape:
            _write_usd_array(
                stream,
                "normal3f[] normals",
                normal_values.tolist(),
                _format_usd_point,
                "        ",
                inline_limit=4,
            )
            stream.write('        uniform token normalsInterpolation = "vertex"\n')
        stream.write('        color3f[] primvars:displayColor = [(0.76, 0.8, 0.78)] (\n')
        stream.write('            interpolation = "constant"\n')
        stream.write("        )\n")
        stream.write('        rel material:binding = </OpenFOAMCase/Looks/FanMeshMaterial>\n')
        stream.write("    }\n")
        _write_fan_wireframe_usd(stream, points, face_counts, face_indices)
        _write_fan_material_usd(stream)
        stream.write("}\n")
    return True


def _write_fan_wireframe_usd(
    stream,
    points: np.ndarray,
    face_counts: list[int],
    face_indices: list[int],
    *,
    stride: int = 260,
) -> None:
    segment_points: list[list[float]] = []
    cursor = 0
    for face_number, count in enumerate(face_counts):
        indices = face_indices[cursor : cursor + count]
        cursor += count
        if face_number % stride != 0 or count < 3:
            continue
        for index in range(count):
            segment_points.append(points[int(indices[index])].tolist())
            segment_points.append(points[int(indices[(index + 1) % count])].tolist())

    if not segment_points:
        return

    vertex_counts = [2] * (len(segment_points) // 2)
    stream.write('\n    def BasisCurves "FanMeshWire"\n')
    stream.write("    {\n")
    stream.write('        uniform token type = "linear"\n')
    stream.write('        uniform token wrap = "nonperiodic"\n')
    stream.write("        float[] widths = [0.0001] (\n")
    stream.write('            interpolation = "constant"\n')
    stream.write("        )\n")
    stream.write("        color3f[] primvars:displayColor = [(0.12, 0.15, 0.15)] (\n")
    stream.write('            interpolation = "constant"\n')
    stream.write("        )\n")
    _write_usd_array(stream, "int[] curveVertexCounts", vertex_counts, str, "        ")
    _write_usd_array(stream, "point3f[] points", segment_points, _format_usd_point, "        ", inline_limit=4)
    stream.write("    }\n")


def _write_fan_material_usd(stream) -> None:
    stream.write('\n    def Scope "Looks"\n')
    stream.write("    {\n")
    stream.write('        def Material "FanMeshMaterial"\n')
    stream.write("        {\n")
    stream.write(
        '            token outputs:surface.connect = </OpenFOAMCase/Looks/FanMeshMaterial/PreviewSurface.outputs:surface>\n'
    )
    stream.write('            def Shader "PreviewSurface"\n')
    stream.write("            {\n")
    stream.write('                uniform token info:id = "UsdPreviewSurface"\n')
    stream.write("                color3f inputs:diffuseColor = (0.76, 0.8, 0.78)\n")
    stream.write("                float inputs:opacity = 1\n")
    stream.write("                float inputs:roughness = 0.82\n")
    stream.write('                token outputs:surface\n')
    stream.write("            }\n")
    stream.write("        }\n")
    stream.write("    }\n")


def _patch_id(path: Path) -> int:
    stem = path.stem
    if not stem.startswith("face"):
        return 10**9
    try:
        return int(stem[4:])
    except ValueError:
        return 10**9


def _write_usd_string_array(stream, declaration: str, values: list[str], indent: str) -> None:
    quoted = [json.dumps(value) for value in values]
    _write_usd_array(stream, declaration, quoted, str, indent)


def _write_usd_array(stream, declaration: str, values, formatter, indent: str, inline_limit: int = 24) -> None:
    formatted = [formatter(value) for value in values]
    if len(formatted) <= inline_limit:
        stream.write(f"{indent}{declaration} = [{', '.join(formatted)}]\n")
        return
    stream.write(f"{indent}{declaration} = [\n")
    for start in range(0, len(formatted), 12):
        stream.write(f"{indent}    {', '.join(formatted[start:start + 12])}")
        if start + 12 < len(formatted):
            stream.write(",")
        stream.write("\n")
    stream.write(f"{indent}]\n")


def _format_usd_point(value) -> str:
    x, y, z = value
    return f"({_format_usd_float(x)}, {_format_usd_float(y)}, {_format_usd_float(z)})"


def _format_usd_float(value: float) -> str:
    return f"{float(value):.12g}"


def compute_metrics(result: PredictionResult) -> dict[str, float]:
    pressure = result.pressure
    return {
        "estimated_pressure_drop": float(pressure.max() - pressure.min()) if pressure.size else 0.0,
        "estimated_mass_flow": 0.0,
        "velocity_mean": float(result.velocity_magnitude.mean()) if result.velocity_magnitude.size else 0.0,
    }


def _write_seed_json(path: Path, result: PredictionResult, kind: str) -> None:
    pos = np.asarray(result.sample["pos"], dtype=float)
    seeds = pos[: min(16, len(pos))].tolist()
    path.write_text(json.dumps({"kind": kind, "seeds": seeds}, indent=2), encoding="utf-8")


def _format_array(array: np.ndarray) -> str:
    flat = np.asarray(array).reshape(-1)
    return " ".join(f"{float(value):.9g}" for value in flat)
