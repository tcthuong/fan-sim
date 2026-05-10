from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from fan_sim.config import expand_case_matrix, load_config
from fan_sim.export.artifacts import export_prediction_artifacts
from fan_sim.graph.build import build_cell_graph_sample
from fan_sim.inference.loader import load_predictor_from_artifacts
from fan_sim.ml.dataset import save_graph_sample
from fan_sim.ml.training import train_from_graphs
from fan_sim.openfoam.compat import migrate_case_for_foundation
from fan_sim.openfoam.case import clone_parameterized_case
from fan_sim.openfoam.runner import export_vtk, run_openfoam_case
from fan_sim.data.vtu import latest_vtu, read_vtu


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fan-sim")
    sub = parser.add_subparsers(dest="command", required=True)
    _add_config_arg(sub.add_parser("generate-cases"))
    run_parser = _add_config_arg(sub.add_parser("run-openfoam"))
    run_parser.add_argument("--case-id")
    export_parser = _add_config_arg(sub.add_parser("export-vtk"))
    export_parser.add_argument("--case-id")
    _add_config_arg(sub.add_parser("build-graphs"))
    train_parser = _add_config_arg(sub.add_parser("train"))
    train_parser.add_argument("--epochs", type=int, default=1)
    predict_parser = _add_config_arg(sub.add_parser("predict"))
    predict_parser.add_argument("--case-id", required=True)
    predict_parser.add_argument("--rpm", type=float, required=True)
    predict_parser.add_argument("--outlet-pressure", type=float, required=True)
    predict_parser.add_argument("--inlet-pressure", type=float, default=0.0)
    serve_parser = _add_config_arg(sub.add_parser("serve"))
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8765)
    serve_parser.add_argument("--case-id", default="fan_base")
    args = parser.parse_args(argv)

    config = load_config(args.config)
    if args.command == "generate-cases":
        _generate_cases(config)
    elif args.command == "run-openfoam":
        _run_openfoam(config, args.case_id)
    elif args.command == "export-vtk":
        _export_vtk(config, args.case_id)
    elif args.command == "build-graphs":
        _build_graphs(config)
    elif args.command == "train":
        graph_paths = sorted((config.root / "artifacts/graphs").glob("*.graph.pt"))
        checkpoint = train_from_graphs(config, graph_paths, epochs=args.epochs)
        print(checkpoint)
    elif args.command == "predict":
        predictor = load_predictor_from_artifacts(config, args.case_id)
        result = predictor.predict(rpm=args.rpm, inlet_pressure=args.inlet_pressure, outlet_pressure=args.outlet_pressure)
        output_dir = config.root / "runs/inference" / f"{args.case_id}_rpm{int(round(args.rpm)):04d}"
        artifacts = export_prediction_artifacts(result, output_dir=output_dir, write_vtu=True)
        print(
            json.dumps(
                {
                    "prediction_vtu": str(artifacts.prediction_vtu),
                    "prediction_usd": str(artifacts.prediction_usd),
                    "streamline_seeds_json": str(artifacts.streamline_seeds_json),
                    "particle_seeds_json": str(artifacts.particle_seeds_json),
                },
                indent=2,
            )
        )
    elif args.command == "serve":
        _serve(config, args.case_id, args.host, args.port)
    return 0


def _add_config_arg(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    parser.add_argument("--config", default="configs/fan_sim.yaml")
    return parser


def _generate_cases(config) -> None:
    output_root = config.root / "runs/openfoam"
    for case in expand_case_matrix(config):
        generated = clone_parameterized_case(
            base_case=config.base_case,
            output_root=output_root,
            case_id=case.case_id,
            rpm=case.rpm,
            inlet_pressure=case.inlet_pressure,
            outlet_pressure=case.outlet_pressure,
        )
        print(generated.case_dir)


def _run_openfoam(config, case_id: str | None = None) -> None:
    for case_dir in _case_dirs(config.root, case_id):
        report = migrate_case_for_foundation(case_dir)
        for note in report.notes:
            print(note)
        completed = run_openfoam_case(case_dir, config.openfoam)
        print(f"{case_dir}: {completed.returncode}")


def _export_vtk(config, case_id: str | None = None) -> None:
    for case_dir in _case_dirs(config.root, case_id):
        completed = export_vtk(case_dir, config.fields.velocity, config.fields.pressure)
        print(f"{case_dir}: {completed.returncode}")


def _case_dirs(root: Path, case_id: str | None = None) -> list[Path]:
    openfoam_root = root / "runs/openfoam"
    if case_id:
        case_dir = openfoam_root / case_id
        if not case_dir.is_dir():
            raise FileNotFoundError(f"Generated case not found: {case_dir}")
        return [case_dir]
    return sorted(openfoam_root.glob("case_*"))


def _build_graphs(config) -> None:
    output_dir = config.root / "artifacts/graphs"
    output_dir.mkdir(parents=True, exist_ok=True)
    for case_dir in sorted((config.root / "runs/openfoam").glob("case_*")):
        print(f"{case_dir}: locating VTU", flush=True)
        vtu_path = latest_vtu(case_dir)
        print(f"{case_dir}: reading {vtu_path}", flush=True)
        mesh = read_vtu(vtu_path, config.fields.velocity, config.fields.pressure)
        print(
            f"{case_dir}: loaded points={mesh.points.shape[0]} cells={len(mesh.cells)} "
            f"cell_fields={list(mesh.cell_data.keys())}",
            flush=True,
        )
        metadata = _read_case_metadata(case_dir)
        print(f"{case_dir}: building cell graph", flush=True)
        sample = build_cell_graph_sample(
            mesh=mesh,
            rpm=float(metadata["rpm"]),
            inlet_pressure=float(metadata.get("inlet_pressure", 0.0)),
            outlet_pressure=float(metadata["outlet_pressure"]),
            velocity_field=config.fields.velocity,
            pressure_field=config.fields.pressure,
        )
        output_path = output_dir / f"{case_dir.name}.graph.pt"
        print(
            f"{case_dir}: graph nodes={sample['x'].shape[0]} edges={sample['edge_index'].shape[1]} "
            f"-> {output_path}",
            flush=True,
        )
        save_graph_sample(sample, output_path)


def _read_case_metadata(case_dir: Path) -> dict:
    import json

    return json.loads((case_dir / "fan_sim_case.json").read_text(encoding="utf-8"))


def _serve(config, case_id: str, host: str, port: int) -> None:
    try:
        import uvicorn

        from fan_sim.service.app import create_app
    except ImportError as exc:
        raise SystemExit("Serving requires optional service dependencies: pip install -e .[service]") from exc
    predictor = load_predictor_from_artifacts(config, case_id)
    uvicorn.run(create_app(predictor=predictor, output_root=config.root / "runs/inference"), host=host, port=port)


if __name__ == "__main__":
    sys.exit(main())
