from pathlib import Path
import json

import pytest

from fan_sim.config import load_config, expand_case_matrix
from fan_sim.cli import _case_dirs, _run_cases
from fan_sim.openfoam.compat import migrate_case_for_foundation
from fan_sim.openfoam.case import clone_parameterized_case, validate_base_case
from fan_sim.openfoam.runner import build_bash_command


def test_load_config_and_expand_case_matrix(tmp_path: Path):
    cfg_path = tmp_path / "fan_sim.yaml"
    cfg_path.write_text(
        """
base_case: data/base_case
case_matrix:
  rpm: [600, 800]
  outlet_pressure: [0, 20]
openfoam:
  shell: bash
  solver: simpleFoam
fields:
  velocity: U
  pressure: p
omniverse:
  kit_cae_root: D:/nvidia/kit-cae
""",
        encoding="utf-8",
    )

    cfg = load_config(cfg_path)
    cases = expand_case_matrix(cfg)

    assert cfg.fields.velocity == "U"
    assert [case.case_id for case in cases] == [
        "case_rpm_0600_pout_000",
        "case_rpm_0600_pout_020",
        "case_rpm_0800_pout_000",
        "case_rpm_0800_pout_020",
    ]


def test_openfoam_shell_defaults_to_ubuntu_bash(tmp_path: Path):
    cfg_path = tmp_path / "fan_sim.yaml"
    cfg_path.write_text(
        """
base_case: data/base_case
case_matrix:
  rpm: [600]
  outlet_pressure: [0]
""",
        encoding="utf-8",
    )

    cfg = load_config(cfg_path)

    assert cfg.openfoam.shell == "bash"


def test_validate_base_case_requires_openfoam_folders(tmp_path: Path):
    base_case = tmp_path / "base_case"
    (base_case / "0").mkdir(parents=True)
    (base_case / "constant").mkdir()

    with pytest.raises(ValueError, match="system"):
        validate_base_case(base_case)


def test_clone_parameterized_case_replaces_placeholders(tmp_path: Path):
    base_case = tmp_path / "base_case"
    (base_case / "0").mkdir(parents=True)
    (base_case / "constant").mkdir()
    (base_case / "system").mkdir()
    (base_case / "constant" / "MRFProperties").write_text("omega {{RPM}}\n", encoding="utf-8")
    (base_case / "0" / "p").write_text("outlet {{OUTLET_PRESSURE}}\n", encoding="utf-8")

    generated = clone_parameterized_case(
        base_case=base_case,
        output_root=tmp_path / "runs",
        case_id="case_rpm_1200_pout_020",
        rpm=1200,
        inlet_pressure=0.0,
        outlet_pressure=20.0,
    )

    assert generated.case_dir.name == "case_rpm_1200_pout_020"
    assert "1200" in (generated.case_dir / "constant" / "MRFProperties").read_text(encoding="utf-8")
    assert "20" in (generated.case_dir / "0" / "p").read_text(encoding="utf-8")
    assert (generated.case_dir / "fan_sim_case.json").exists()


def test_bash_command_builds_native_ubuntu_case_path():
    command = build_bash_command(
        case_dir=Path("/mnt/d/nvidia/fan-sim/runs/openfoam/case_a"),
        commands=["blockMesh", "simpleFoam"],
    )

    assert command[:2] == ["bash", "-lc"]
    assert "/usr/lib/openfoam/openfoam2406/etc/bashrc" in command[2]
    assert "/opt/openfoam13/etc/bashrc" in command[2]
    assert "cd '/mnt/d/nvidia/fan-sim/runs/openfoam/case_a'" in command[2]
    assert "blockMesh && simpleFoam" in command[2]


def test_bash_command_converts_relative_case_path_to_absolute_path():
    command = build_bash_command(
        case_dir=Path("runs/openfoam/case_rpm_0600_pout_000"),
        commands=["checkMesh"],
    )

    assert "cd 'runs/openfoam" not in command[2]
    assert "case_rpm_0600_pout_000" in command[2]


def test_config_rejects_wsl_shell(tmp_path: Path):
    cfg_path = tmp_path / "fan_sim.yaml"
    cfg_path.write_text(
        """
base_case: data/base_case
case_matrix:
  rpm: [600]
  outlet_pressure: [0]
openfoam:
  shell: wsl
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="shell: bash"):
        load_config(cfg_path)


def test_colab_config_is_a100_full_run_safe():
    cfg = load_config(Path("configs/fan_sim_colab.yaml"))

    assert cfg.openfoam.shell == "bash"
    assert cfg.openfoam.run_block_mesh is False
    assert cfg.openfoam.run_snappy_hex_mesh is False
    assert cfg.openfoam.run_check_mesh is False
    assert cfg.case_matrix.rpm == [60.0, 180.0, 300.0, 450.0, 600.0, 750.0, 900.0, 1050.0, 1200.0, 1500.0]
    assert cfg.case_matrix.outlet_pressure == [0.0, 20.0, 40.0, 60.0, 80.0, 100.0]
    assert cfg.model.backend == "physicsnemo"


def test_colab_notebook_is_valid_json():
    notebook = json.loads(Path("notebooks/fan_sim_colab.ipynb").read_text(encoding="utf-8"))

    assert notebook["nbformat"] == 4
    assert any("Fan-Sim Colab - Full A100 Run" in "".join(cell.get("source", [])) for cell in notebook["cells"])


def test_migrate_case_replaces_simscale_omega_bc_and_disables_custom_functions(tmp_path: Path):
    import gzip

    case_dir = tmp_path / "case"
    omega_dir = case_dir / "0"
    system_dir = case_dir / "system"
    omega_dir.mkdir(parents=True)
    system_dir.mkdir()
    with gzip.open(omega_dir / "omega.gz", "wt", encoding="utf-8") as stream:
        stream.write(
            """
boundaryField
{
    face1
    {
        diameterFraction 0.07;
        mixingLengthSet true;
        type            autoTurbulentMixingLengthFrequencyInlet;
        mixingLength    0.018578;
        phi             phi;
        k               k;
        value           uniform 1;
    }
}
"""
        )
    (system_dir / "controlDict").write_text(
        """
application simscaleSimpleFoam;
libs ("libchtgfm.so" "libsimScaleFunctionObjects.so");
functions {
    customThing {
        type flexibleWriter;
    }
}
""",
        encoding="utf-8",
    )

    report = migrate_case_for_foundation(case_dir)

    with gzip.open(omega_dir / "omega.gz", "rt", encoding="utf-8") as stream:
        omega = stream.read()
    control = (system_dir / "controlDict").read_text(encoding="utf-8")
    assert report.modified_files
    assert "autoTurbulentMixingLengthFrequencyInlet" not in omega
    assert "turbulentMixingLengthFrequencyInlet" in omega
    assert "diameterFraction" not in omega
    assert "mixingLengthSet" not in omega
    assert "libsimScaleFunctionObjects" not in control
    assert "functions\n{" in control
    assert "flexibleWriter" not in control


def test_migrate_case_replaces_local_blended_scheme_that_depends_on_custom_field(tmp_path: Path):
    case_dir = tmp_path / "case"
    system_dir = case_dir / "system"
    system_dir.mkdir(parents=True)
    (system_dir / "fvSchemes").write_text(
        """
divSchemes {
    div(phi,U) bounded Gauss localBlended upwind linearUpwindV grad(U);
}
""",
        encoding="utf-8",
    )

    report = migrate_case_for_foundation(case_dir)

    fv_schemes = (system_dir / "fvSchemes").read_text(encoding="utf-8")
    assert report.modified_files
    assert "localBlended" not in fv_schemes
    assert "div(phi,U) bounded Gauss upwind;" in fv_schemes


def test_migrate_case_converts_dynamic_pressure_to_kinematic_pressure(tmp_path: Path):
    import gzip

    case_dir = tmp_path / "case"
    zero_dir = case_dir / "0"
    constant_dir = case_dir / "constant"
    zero_dir.mkdir(parents=True)
    constant_dir.mkdir()
    (constant_dir / "transportProperties").write_text(
        "rhoRef 1.25;\n",
        encoding="utf-8",
    )
    with gzip.open(zero_dir / "p.gz", "wt", encoding="utf-8") as stream:
        stream.write(
            """
dimensions      [1 -1 -2 0 0 0 0];
internalField   uniform 0;
boundaryField
{
    outlet
    {
        type fixedValue;
        value uniform 25;
    }
}
"""
        )

    report = migrate_case_for_foundation(case_dir)

    with gzip.open(zero_dir / "p.gz", "rt", encoding="utf-8") as stream:
        p_text = stream.read()
    assert report.modified_files
    assert "dimensions      [0 2 -2 0 0 0 0];" in p_text
    assert "value uniform 20" in p_text


def test_case_dirs_filters_single_case_id(tmp_path: Path):
    root = tmp_path / "runs" / "openfoam"
    (root / "case_a").mkdir(parents=True)
    (root / "case_b").mkdir()

    assert [path.name for path in _case_dirs(tmp_path, "case_b")] == ["case_b"]


def test_run_cases_accepts_parallel_jobs(tmp_path: Path):
    case_a = tmp_path / "case_a"
    case_b = tmp_path / "case_b"
    case_a.mkdir()
    case_b.mkdir()
    seen: list[str] = []

    _run_cases([case_a, case_b], jobs=2, worker=lambda case_dir: seen.append(case_dir.name))

    assert sorted(seen) == ["case_a", "case_b"]


def test_run_cases_rejects_invalid_jobs(tmp_path: Path):
    with pytest.raises(ValueError, match="--jobs"):
        _run_cases([tmp_path], jobs=0, worker=lambda case_dir: None)
