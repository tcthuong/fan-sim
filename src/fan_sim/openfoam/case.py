from __future__ import annotations

from dataclasses import dataclass
import gzip
import json
import math
from pathlib import Path
import re
import shutil


@dataclass(frozen=True)
class GeneratedCase:
    case_id: str
    case_dir: Path
    rpm: float
    inlet_pressure: float
    outlet_pressure: float


def validate_base_case(base_case: str | Path) -> None:
    base = Path(base_case)
    missing = [name for name in ("0", "constant", "system") if not (base / name).is_dir()]
    if missing:
        raise ValueError(f"Base OpenFOAM case is missing required folder(s): {', '.join(missing)}")


def clone_parameterized_case(
    *,
    base_case: str | Path,
    output_root: str | Path,
    case_id: str,
    rpm: float,
    inlet_pressure: float,
    outlet_pressure: float,
    overwrite: bool = True,
) -> GeneratedCase:
    validate_base_case(base_case)
    source = Path(base_case)
    destination = Path(output_root) / case_id
    if destination.exists():
        if not overwrite:
            raise FileExistsError(f"Generated case already exists: {destination}")
        shutil.rmtree(destination)
    shutil.copytree(source, destination)

    replacements = {
        "{{RPM}}": _number_text(rpm),
        "{{OMEGA_RAD_PER_SEC}}": _number_text(_rpm_to_rad_per_sec(rpm)),
        "{{INLET_PRESSURE}}": _number_text(inlet_pressure),
        "{{OUTLET_PRESSURE}}": _number_text(outlet_pressure),
    }
    replacement_counts = _replace_placeholders(destination, replacements)
    _patch_mrf_omega(destination, rpm)
    if replacement_counts.get("{{OUTLET_PRESSURE}}", 0) == 0:
        _patch_outlet_pressure(destination, outlet_pressure)

    metadata = {
        "case_id": case_id,
        "base_case": str(source),
        "rpm": rpm,
        "inlet_pressure": inlet_pressure,
        "outlet_pressure": outlet_pressure,
    }
    (destination / "fan_sim_case.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return GeneratedCase(case_id, destination, rpm, inlet_pressure, outlet_pressure)


def _replace_placeholders(case_dir: Path, replacements: dict[str, str]) -> dict[str, int]:
    counts = {key: 0 for key in replacements}
    for path in case_dir.rglob("*"):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        updated = text
        for key, value in replacements.items():
            counts[key] += updated.count(key)
            updated = updated.replace(key, value)
        if updated != text:
            path.write_text(updated, encoding="utf-8")
    return counts


def _number_text(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(value)


def _rpm_to_rad_per_sec(rpm: float) -> float:
    return float(rpm) * 2.0 * math.pi / 60.0


def _patch_mrf_omega(case_dir: Path, rpm: float) -> None:
    mrf_path = case_dir / "constant" / "MRFProperties"
    if not mrf_path.exists():
        raise ValueError(f"RPM parameterization requires {mrf_path}")

    text = mrf_path.read_text(encoding="utf-8")
    omega = _number_text(_rpm_to_rad_per_sec(rpm))
    updated, count = re.subn(
        r"\bomega\s+(?:constant\s+)?[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?\s*;",
        f"omega constant {omega};",
        text,
    )
    if count == 0:
        raise ValueError(f"Could not patch MRF omega in {mrf_path}")
    mrf_path.write_text(updated, encoding="utf-8")


def _patch_outlet_pressure(case_dir: Path, outlet_pressure: float) -> None:
    pressure_path = _find_pressure_file(case_dir)
    text = _read_case_text(pressure_path)
    pressure = _number_text(outlet_pressure)
    updated, count = re.subn(
        r"(\bvalue\s+uniform\s+)[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?(\s*;)",
        rf"\g<1>{pressure}\2",
        text,
    )
    if count == 0:
        raise ValueError(f"Could not patch outlet pressure in {pressure_path}")
    _write_case_text(pressure_path, updated)


def _find_pressure_file(case_dir: Path) -> Path:
    for candidate in (case_dir / "0" / "p", case_dir / "0" / "p.gz"):
        if candidate.exists():
            return candidate
    raise ValueError(f"Outlet pressure parameterization requires {case_dir / '0' / 'p'} or p.gz")


def _read_case_text(path: Path) -> str:
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            return stream.read()
    return path.read_text(encoding="utf-8")


def _write_case_text(path: Path, text: str) -> None:
    if path.suffix == ".gz":
        with gzip.open(path, "wt", encoding="utf-8") as stream:
            stream.write(text)
        return
    path.write_text(text, encoding="utf-8")
