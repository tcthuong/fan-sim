from __future__ import annotations

from dataclasses import dataclass, field
import gzip
from pathlib import Path
import re


@dataclass
class MigrationReport:
    modified_files: list[Path] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def migrate_case_for_foundation(case_dir: str | Path) -> MigrationReport:
    """Patch known OpenFOAM.com/SimScale case entries for OpenFOAM Foundation runs.

    The current fan base case was authored for OpenFOAM.com v2406/SimScale and
    contains custom boundary conditions, function objects, and schemes that are
    not guaranteed to be available in the local OpenFOAM runtime. This migration
    keeps the case runnable for the training pipeline without changing mesh or
    primary field values.
    """

    root = Path(case_dir)
    report = MigrationReport()
    rho_ref = _read_rho_ref(root)
    for path in _candidate_text_files(root):
        original = _read_text(path)
        if original is None:
            continue
        updated = _migrate_text(path, original, report, rho_ref)
        if updated != original:
            _write_text(path, updated)
            report.modified_files.append(path)
    return report


def _candidate_text_files(root: Path) -> list[Path]:
    candidates: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix == ".gz" or path.name in {"controlDict", "fvSchemes", "omega", "U", "p", "k", "nut"}:
            candidates.append(path)
    return candidates


def _read_text(path: Path) -> str | None:
    try:
        if path.suffix == ".gz":
            with gzip.open(path, "rt", encoding="utf-8") as stream:
                return stream.read()
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None


def _write_text(path: Path, text: str) -> None:
    if path.suffix == ".gz":
        with gzip.open(path, "wt", encoding="utf-8") as stream:
            stream.write(text)
    else:
        path.write_text(text, encoding="utf-8")


def _migrate_text(path: Path, text: str, report: MigrationReport, rho_ref: float) -> str:
    updated = text
    if "autoTurbulentMixingLengthFrequencyInlet" in updated:
        updated = updated.replace("autoTurbulentMixingLengthFrequencyInlet", "turbulentMixingLengthFrequencyInlet")
        updated = _drop_lines_containing(updated, ("diameterFraction", "mixingLengthSet"))
        report.notes.append(f"{path}: replaced autoTurbulentMixingLengthFrequencyInlet")

    if path.name == "controlDict":
        if "libchtgfm.so" in updated or "libsimScaleFunctionObjects.so" in updated:
            updated = _drop_lines_containing(updated, ("libchtgfm.so", "libsimScaleFunctionObjects.so"))
            report.notes.append(f"{path}: removed unavailable SimScale custom libraries")
        if "functions" in updated and _contains_custom_function_objects(updated):
            updated = _replace_dictionary_block(updated, "functions", "functions\n{\n}\n")
            report.notes.append(f"{path}: disabled unavailable SimScale custom function objects")
    if path.name == "fvSchemes" and "localBlended" in updated:
        updated = updated.replace(
            "div(phi,U) bounded Gauss localBlended upwind linearUpwindV grad(U);",
            "div(phi,U) bounded Gauss upwind;",
        )
        report.notes.append(f"{path}: replaced localBlended U scheme that requires UBlendingFactor")
    if _is_pressure_file(path) and "[1 -1 -2 0 0 0 0]" in updated:
        updated = updated.replace("dimensions      [1 -1 -2 0 0 0 0];", "dimensions      [0 2 -2 0 0 0 0];")
        updated = updated.replace("dimensions [1 -1 -2 0 0 0 0];", "dimensions [0 2 -2 0 0 0 0];")
        updated = _scale_uniform_values(updated, 1.0 / rho_ref)
        report.notes.append(f"{path}: converted dynamic pressure to kinematic pressure using rhoRef={rho_ref:g}")
    return updated


def _read_rho_ref(root: Path) -> float:
    transport = root / "constant" / "transportProperties"
    text = _read_text(transport)
    if not text:
        return 1.0
    match = re.search(r"\brhoRef\s+([-+0-9.eE]+)\s*;", text)
    if not match:
        return 1.0
    return float(match.group(1))


def _is_pressure_file(path: Path) -> bool:
    return path.name == "p" or path.name == "p.gz"


def _scale_uniform_values(text: str, factor: float) -> str:
    def replace(match: re.Match[str]) -> str:
        value = float(match.group(1))
        scaled = value * factor
        return "uniform " + f"{scaled:.12g}"

    return re.sub(r"uniform\s+([-+]?\d+(?:\.\d*)?(?:[eE][-+]?\d+)?)", replace, text)


def _drop_lines_containing(text: str, needles: tuple[str, ...]) -> str:
    return "\n".join(line for line in text.splitlines() if not any(needle in line for needle in needles)) + "\n"


def _contains_custom_function_objects(text: str) -> bool:
    custom_types = (
        "stabilityBlendingFactor",
        "openFoamWriteOldTimesOnSignal",
        "flexibleWriter",
        "divergenceHandler",
        "convergenceIndicator",
    )
    return any(custom_type in text for custom_type in custom_types)


def _replace_dictionary_block(text: str, name: str, replacement: str) -> str:
    name_index = text.find(name)
    if name_index < 0:
        return text
    brace_index = text.find("{", name_index + len(name))
    if brace_index < 0:
        return text

    depth = 0
    for index in range(brace_index, len(text)):
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                end = index + 1
                if end < len(text) and text[end] == "\n":
                    end += 1
                return text[:name_index] + replacement + text[end:]
    return text
