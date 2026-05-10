from __future__ import annotations

from pathlib import Path
import platform
import subprocess

from fan_sim.config import OpenFOAMConfig


def native_linux_path(path: str | Path) -> str:
    raw = str(path).replace("\\", "/")
    if raw.startswith("/"):
        return raw
    resolved = Path(path)
    if not resolved.is_absolute():
        resolved = resolved.resolve()
    return str(resolved).replace("\\", "/")


def default_openfoam_commands(config: OpenFOAMConfig) -> list[str]:
    commands: list[str] = []
    if config.run_block_mesh:
        commands.append("blockMesh")
    if config.run_surface_feature_extract:
        commands.append("surfaceFeatureExtract")
    if config.run_snappy_hex_mesh:
        commands.append("snappyHexMesh -overwrite")
    if config.run_check_mesh:
        commands.append("checkMesh")
    commands.append(config.solver)
    return commands


def build_bash_command(case_dir: str | Path, commands: list[str]) -> list[str]:
    linux_case_dir = native_linux_path(Path(case_dir))
    quoted_dir = _quote_shell(linux_case_dir)
    source_openfoam = (
        "if [ -f /usr/lib/openfoam/openfoam2406/etc/bashrc ]; then . /usr/lib/openfoam/openfoam2406/etc/bashrc; "
        "elif [ -f /opt/openfoam2406/etc/bashrc ]; then . /opt/openfoam2406/etc/bashrc; "
        "elif [ -f /opt/openfoam13/etc/bashrc ]; then . /opt/openfoam13/etc/bashrc; "
        "elif [ -f /opt/openfoam12/etc/bashrc ]; then . /opt/openfoam12/etc/bashrc; "
        "elif [ -f /opt/openfoam11/etc/bashrc ]; then . /opt/openfoam11/etc/bashrc; "
        "fi"
    )
    script = f"{source_openfoam} && cd {quoted_dir} && " + " && ".join(commands)
    return ["bash", "-lc", script]


def run_openfoam_case(case_dir: str | Path, config: OpenFOAMConfig) -> subprocess.CompletedProcess[str]:
    _require_ubuntu_runtime(config)
    command = build_bash_command(case_dir, default_openfoam_commands(config))
    return _run_checked(command, "OpenFOAM run", Path(case_dir) / "log.fan-sim-openfoam")


def export_vtk(case_dir: str | Path, velocity_field: str = "U", pressure_field: str = "p") -> subprocess.CompletedProcess[str]:
    _require_ubuntu_runtime()
    fields = f"'({velocity_field} {pressure_field})'"
    command = build_bash_command(case_dir, [f"foamToVTK -latestTime -fields {fields}"])
    return _run_checked(command, "foamToVTK export", Path(case_dir) / "log.fan-sim-foamToVTK")


def _require_ubuntu_runtime(config: OpenFOAMConfig | None = None) -> None:
    if config is not None and config.shell != "bash":
        raise ValueError("Unsupported OpenFOAM shell. Use shell: bash and run fan-sim inside Ubuntu/WSL.")
    if platform.system().lower().startswith("win"):
        raise RuntimeError("Run fan-sim inside Ubuntu/WSL bash. This project no longer invokes wsl.exe from Windows.")


def _quote_shell(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def _run_checked(command: list[str], label: str, log_path: Path | None = None) -> subprocess.CompletedProcess[str]:
    if log_path is None:
        completed = subprocess.run(command, check=False, text=True, capture_output=True)
    else:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("w", encoding="utf-8", errors="replace") as stream:
            completed = subprocess.run(command, check=False, text=True, stdout=stream, stderr=subprocess.STDOUT)
    if completed.returncode != 0:
        stdout = completed.stdout.strip() if completed.stdout else ""
        stderr = completed.stderr.strip() if completed.stderr else ""
        log_tail = _tail(log_path) if log_path is not None else ""
        raise RuntimeError(
            f"{label} failed with exit code {completed.returncode}.\n"
            f"Command: {command!r}\n"
            f"Log: {log_path if log_path is not None else '<none>'}\n"
            f"Log tail:\n{log_tail or '<empty>'}\n"
            f"STDOUT:\n{stdout or '<empty>'}\n"
            f"STDERR:\n{stderr or '<empty>'}"
        )
    return completed


def _tail(path: Path | None, lines: int = 120) -> str:
    if path is None or not path.exists():
        return ""
    return "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])
