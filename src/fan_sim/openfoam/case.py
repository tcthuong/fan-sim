from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
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
        "{{INLET_PRESSURE}}": _number_text(inlet_pressure),
        "{{OUTLET_PRESSURE}}": _number_text(outlet_pressure),
    }
    _replace_placeholders(destination, replacements)

    metadata = {
        "case_id": case_id,
        "base_case": str(source),
        "rpm": rpm,
        "inlet_pressure": inlet_pressure,
        "outlet_pressure": outlet_pressure,
    }
    (destination / "fan_sim_case.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return GeneratedCase(case_id, destination, rpm, inlet_pressure, outlet_pressure)


def _replace_placeholders(case_dir: Path, replacements: dict[str, str]) -> None:
    for path in case_dir.rglob("*"):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        updated = text
        for key, value in replacements.items():
            updated = updated.replace(key, value)
        if updated != text:
            path.write_text(updated, encoding="utf-8")


def _number_text(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(value)

