# Google Colab Runbook

Colab support is for smoke tests, graph conversion, lightweight training, and quick demos. It is not the preferred place for full 3.5M-cell OpenFOAM sweeps because Colab sessions are temporary and can time out. For production CFD solves, use the Linux SSH flow in `docs/07-runbook.md`.

## Recommended Colab Modes

Use Colab for:

- Validating the Python package install.
- Running one small/smoke OpenFOAM case.
- Exporting a VTU from a short solve.
- Building graph samples from precomputed VTU files.
- Training a small `numpy` smoke model or a short PhysicsNeMo test.

Avoid Colab for:

- Running all OpenFOAM cases in the full matrix.
- Long `simpleFoam` runs that need many hours.
- Storing large VTU/model artifacts only in `/content`, because the runtime can reset.

## Runtime Setup

Use a GPU or High-RAM runtime when available. First check Python:

```python
!python --version
```

Fan-Sim requires:

```text
Python >=3.11,<3.13
```

If Colab gives Python 3.10, use a different runtime image or run on a Linux SSH server instead.

## Project Location

Clone or pull the source from GitHub in the Colab runtime:

```python
REPO_URL = "https://github.com/tcthuong/fan-sim.git"
PROJECT_ROOT = "/content/fan-sim"
import os

if os.path.isdir(f"{PROJECT_ROOT}/.git"):
    !git -C "$PROJECT_ROOT" pull --ff-only
else:
    !rm -rf "$PROJECT_ROOT"
    !git clone "$REPO_URL" "$PROJECT_ROOT"

%cd $PROJECT_ROOT
```

For persistent input/output data, mount Google Drive:

```python
from google.colab import drive
drive.mount("/content/drive")
```

Keep the repo itself disposable and put large inputs/artifacts in Drive. The OpenFOAM base case is not committed to git; copy or unzip it into:

```text
/content/fan-sim/data/base_case
```

For example:

```python
!mkdir -p data/base_case
!cp -r /content/drive/MyDrive/fan-sim-data/base_case/. data/base_case/
```

## Install Fan-Sim

For smoke tests without the heavy ML stack:

```python
!python -m pip install --upgrade pip
!python -m pip install -e ".[service,vtk,dev]"
```

For PhysicsNeMo:

```python
!python -m pip install -e ".[ml]"
```

Verify:

```python
!python -m pytest -q
!fan-sim --help
```

PhysicsNeMo verification:

```python
!python -c "from physicsnemo.models.meshgraphnet.meshgraphnet import MeshGraphNet; print('MeshGraphNet ok')"
```

The project pins `warp-lang<1.13` because PhysicsNeMo 2.0 imports `warp.context`.

## Install OpenFOAM 2406

Colab runtimes are root-like environments, so the install script works with or without `sudo`:

```python
!bash scripts/colab_install_openfoam2406.sh
```

The script verifies:

```text
simpleFoam
foamToVTK
```

## Use The Colab Pro A100 Config

The Colab config is set up for a full Colab Pro/A100 run:

```text
configs/fan_sim_colab.yaml
```

It uses:

```yaml
case_matrix:
  rpm: [60, 180, 300, 450, 600, 750, 900, 1050, 1200, 1500]
  outlet_pressure: [0, 20, 40, 60, 80, 100]
model:
  backend: physicsnemo
  output_dir: artifacts/models/fan_mgn_colab_a100
```

This expands to 60 cases. The minimum RPM is 60 instead of a near-zero operating point so the full Colab run avoids unstable or non-physical fan cases.

For a quick smoke run, make a temporary copy of this config and reduce the matrix instead of editing the committed Colab config.

## Generate All Cases

```python
!fan-sim generate-cases --config configs/fan_sim_colab.yaml
```

Do not patch `controlDict` down to `endTime 2` for the full A100 run.

## Run OpenFOAM

```python
!fan-sim run-openfoam --config configs/fan_sim_colab.yaml
```

Check logs:

```python
!find runs/openfoam -name "log.fan-sim-openfoam" -print
```

## Export VTU

```python
!fan-sim export-vtk --config configs/fan_sim_colab.yaml
```

Check output:

```python
!find runs/openfoam -path "*/VTK/*" -name "*.vtu" -print
```

## Build Graphs And Train

```python
!fan-sim build-graphs --config configs/fan_sim_colab.yaml
!find artifacts/graphs -name "*.graph.pt" -print
```

If `train` reports `No graph paths supplied for training`, the graph build did not complete. Check whether a graph file exists:

```python
!find artifacts/graphs -name "*.graph.pt" -print
```

Train on the A100 runtime:

```python
!fan-sim train --config configs/fan_sim_colab.yaml --epochs 1
```

## Persist Artifacts

If the project is under Google Drive, artifacts persist automatically. If the project is under `/content`, copy outputs before the runtime resets:

```python
!mkdir -p /content/drive/MyDrive/fan-sim-artifacts
!cp -r artifacts runs/inference /content/drive/MyDrive/fan-sim-artifacts/ 2>/dev/null || true
```

## Full Solves

Colab can technically run:

```python
!fan-sim run-openfoam --config configs/fan_sim.yaml
```

but this is not recommended for the full case matrix. Use SSH Linux with `tmux` for full solves:

```bash
tmux new -s fan-sim
fan-sim run-openfoam --config configs/fan_sim.yaml
```

## Common Colab Failures

### Python 3.10

Fan-Sim will not install:

```text
requires a different Python: 3.10.x not in '<3.13,>=3.11'
```

Use Python 3.11/3.12, or run on a Linux SSH server.

### Runtime Reset

Colab loses `/content` data after reset. Store the project and outputs in Google Drive when possible.

### OpenFOAM Install Fails

Check the Colab Ubuntu release:

```python
!cat /etc/os-release
```

If OpenFOAM.com packages do not support the runtime image, use Colab for ML/graph work only and run OpenFOAM on SSH Linux.

### Out Of Memory

The current fan mesh is large. Reduce the case to a smoke `endTime 2` run, or move full solves to a larger Linux server.

### `serializing a string larger than 4 GiB`

This happened when saving a large `.graph.pt` with PyTorch's older default pickle protocol. Update Fan-Sim, reinstall editable, remove the partial graph, and rerun:

```python
!python -m pip install -e ".[service,vtk,dev]"
!rm -f artifacts/graphs/case_rpm_0600_pout_000.graph.pt artifacts/graphs/case_rpm_0600_pout_000.graph.pt.tmp
!/usr/bin/time -v fan-sim build-graphs --config configs/fan_sim_colab.yaml
!find artifacts/graphs -name "*.graph.pt" -print -exec ls -lh {} \;
```

Fan-Sim saves graph samples with pickle protocol 4+ and writes through a `.tmp` file so interrupted saves do not leave corrupt final graph files.
