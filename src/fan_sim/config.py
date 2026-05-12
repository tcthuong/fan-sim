from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class CaseSpec:
    case_id: str
    rpm: float
    outlet_pressure: float
    inlet_pressure: float = 0.0


@dataclass(frozen=True)
class CaseMatrix:
    rpm: list[float]
    outlet_pressure: list[float]
    inlet_pressure: list[float] = field(default_factory=lambda: [0.0])


@dataclass(frozen=True)
class OpenFOAMConfig:
    shell: str = "bash"
    solver: str = "simpleFoam"
    latest_time: bool = True
    run_block_mesh: bool = True
    run_surface_feature_extract: bool = False
    run_snappy_hex_mesh: bool = True
    run_check_mesh: bool = True

    def __post_init__(self) -> None:
        if self.shell != "bash":
            raise ValueError("OpenFOAM shell must be shell: bash. Run fan-sim inside Ubuntu/WSL, not from PowerShell.")


@dataclass(frozen=True)
class FieldsConfig:
    velocity: str = "U"
    pressure: str = "p"


@dataclass(frozen=True)
class ModelConfig:
    backend: str = "physicsnemo"
    output_dir: Path = Path("artifacts/models/fan_mgn")
    processor_size: int = 15
    hidden_dim: int = 128
    max_nodes_per_graph: int | None = None
    sample_seed: int = 0


@dataclass(frozen=True)
class OmniverseConfig:
    kit_cae_root: Path = Path("D:/nvidia/kit-cae")
    export_point_data: bool = True
    export_volume_vdb: str | None = "optional"


@dataclass(frozen=True)
class FanSimConfig:
    base_case: Path
    case_matrix: CaseMatrix
    openfoam: OpenFOAMConfig = field(default_factory=OpenFOAMConfig)
    fields: FieldsConfig = field(default_factory=FieldsConfig)
    model: ModelConfig = field(default_factory=ModelConfig)
    omniverse: OmniverseConfig = field(default_factory=OmniverseConfig)
    root: Path = Path(".")


def load_config(path: str | Path) -> FanSimConfig:
    config_path = Path(path).resolve()
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    root = config_path.parent.parent if config_path.parent.name == "configs" else config_path.parent

    case_matrix_raw = raw.get("case_matrix", {})
    if "rpm" not in case_matrix_raw or "outlet_pressure" not in case_matrix_raw:
        raise ValueError("Config case_matrix must define rpm and outlet_pressure lists.")

    model_raw = raw.get("model", {})
    omni_raw = raw.get("omniverse", {})

    return FanSimConfig(
        base_case=_as_path(raw.get("base_case", "data/base_case"), root),
        case_matrix=CaseMatrix(
            rpm=[float(v) for v in case_matrix_raw["rpm"]],
            outlet_pressure=[float(v) for v in case_matrix_raw["outlet_pressure"]],
            inlet_pressure=[float(v) for v in case_matrix_raw.get("inlet_pressure", [0.0])],
        ),
        openfoam=OpenFOAMConfig(**raw.get("openfoam", {})),
        fields=FieldsConfig(**raw.get("fields", {})),
        model=ModelConfig(
            backend=str(model_raw.get("backend", "physicsnemo")),
            output_dir=_as_path(model_raw.get("output_dir", "artifacts/models/fan_mgn"), root),
            processor_size=int(model_raw.get("processor_size", 15)),
            hidden_dim=int(model_raw.get("hidden_dim", 128)),
            max_nodes_per_graph=_optional_int(model_raw.get("max_nodes_per_graph")),
            sample_seed=int(model_raw.get("sample_seed", 0)),
        ),
        omniverse=OmniverseConfig(
            kit_cae_root=Path(omni_raw.get("kit_cae_root", "D:/nvidia/kit-cae")),
            export_point_data=bool(omni_raw.get("export_point_data", True)),
            export_volume_vdb=omni_raw.get("export_volume_vdb", "optional"),
        ),
        root=root,
    )


def expand_case_matrix(config: FanSimConfig) -> list[CaseSpec]:
    cases: list[CaseSpec] = []
    for inlet_pressure in config.case_matrix.inlet_pressure:
        for rpm in config.case_matrix.rpm:
            for outlet_pressure in config.case_matrix.outlet_pressure:
                cases.append(
                    CaseSpec(
                        case_id=f"case_rpm_{_format_number(rpm, 4)}_pout_{_format_number(outlet_pressure, 3)}",
                        rpm=rpm,
                        inlet_pressure=inlet_pressure,
                        outlet_pressure=outlet_pressure,
                    )
                )
    return cases


def _as_path(value: Any, root: Path) -> Path:
    path = Path(str(value))
    return path if path.is_absolute() else root / path


def _optional_int(value: Any) -> int | None:
    return None if value is None else int(value)


def _format_number(value: float, width: int) -> str:
    rounded = int(round(value))
    if rounded < 0:
        return "m" + str(abs(rounded)).zfill(width - 1)
    return str(rounded).zfill(width)
