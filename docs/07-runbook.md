# Runbook: Ubuntu-Only Fan-Sim

This project is now Ubuntu-first. Run `fan-sim` inside WSL Ubuntu or native Ubuntu. Do not run the pipeline from Windows PowerShell. Windows is only the file host at `D:\nvidia\fan-sim` and the Omniverse Kit-CAE host.

## 0. Enter Ubuntu

From Windows, open Ubuntu:

```powershell
wsl -d Ubuntu
```

All following commands run inside Ubuntu:

```bash
cd /mnt/d/nvidia/fan-sim
```

If this is native Ubuntu rather than WSL, use the native project path instead.

## 1. Create The Ubuntu Python Environment

Use Python 3.11 or 3.12. Do not use Python 3.14 for this project.

```bash
cd /mnt/d/nvidia/fan-sim
python3 --version
python3 -m venv .venv-ubuntu
source .venv-ubuntu/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[service,vtk,ml,dev]"
```

Verify:

```bash
python -c "import physicsnemo, torch; print('physicsnemo ok'); print(torch.__version__); print('cuda:', torch.cuda.is_available())"
python -c "from physicsnemo.models.meshgraphnet.meshgraphnet import MeshGraphNet; print('MeshGraphNet ok')"
python -m pytest -q
fan-sim --help
```

If `nvidia-physicsnemo` is too heavy for a quick smoke test, install without ML first:

```bash
python -m pip install -e ".[service,vtk,dev]"
```

Then use `model.backend: numpy` for smoke training.

The ML extra pins `warp-lang<1.13` because PhysicsNeMo 2.0 still imports `warp.context`. Letting pip install `warp-lang 1.13.0` causes MeshGraphNet import to fail.

On this machine, `torch.cuda.is_available()` currently reports `False` after installing `torch 2.11.0+cu130` because the installed NVIDIA driver exposes CUDA driver 12.6. CPU import/training still works, but GPU training needs either a newer NVIDIA driver or a PyTorch build compatible with the installed driver.

## 2. Source OpenFOAM 2406

The current base case matches OpenFOAM.com v2406.

```bash
if [ -f /usr/lib/openfoam/openfoam2406/etc/bashrc ]; then
  . /usr/lib/openfoam/openfoam2406/etc/bashrc
elif [ -f /opt/openfoam2406/etc/bashrc ]; then
  . /opt/openfoam2406/etc/bashrc
else
  echo "OpenFOAM 2406 bashrc not found"
fi

which simpleFoam
which foamToVTK
```

`fan-sim` sources the same paths automatically before OpenFOAM commands.

## 3. Base Case Location

Put the base OpenFOAM case here:

```text
/mnt/d/nvidia/fan-sim/data/base_case
```

Required structure:

```text
data/base_case/
  0/
  constant/
  system/
```

The current case already includes a mesh under:

```text
data/base_case/constant/polyMesh
```

So `configs/fan_sim.yaml` skips `blockMesh` and `snappyHexMesh` by default.

## 4. Config

The OpenFOAM runner is Ubuntu-native:

```yaml
openfoam:
  shell: bash
  solver: simpleFoam
  latest_time: true
  run_block_mesh: false
  run_surface_feature_extract: false
  run_snappy_hex_mesh: false
  run_check_mesh: false
```

`shell: wsl` is intentionally unsupported. If you see that value, change it to `bash`.

The current mesh has already been checked successfully. Set `run_check_mesh: true` only when you change the mesh or want a dedicated mesh validation run.

For first smoke testing, reduce the matrix:

```yaml
case_matrix:
  rpm: [600]
  outlet_pressure: [0]
```

## 5. Generate Cases

```bash
source .venv-ubuntu/bin/activate
fan-sim generate-cases --config configs/fan_sim.yaml
```

Generated cases are written to:

```text
runs/openfoam/
```

## 6. Run One OpenFOAM Case

For a fast smoke run on the large 3.5M-cell mesh, set the generated case controlDict to a tiny end time:

```bash
case_dir=runs/openfoam/case_rpm_0600_pout_000
python - <<'PY'
from pathlib import Path
p = Path("runs/openfoam/case_rpm_0600_pout_000/system/controlDict")
s = p.read_text()
s = s.replace("endTime 1000.0;", "endTime 2;").replace("writeInterval 1000;", "writeInterval 1;")
p.write_text(s)
PY
```

Run the case:

```bash
fan-sim run-openfoam --config configs/fan_sim.yaml --case-id case_rpm_0600_pout_000
```

Expected:

```text
/mnt/d/nvidia/fan-sim/runs/openfoam/case_rpm_0600_pout_000: 0
```

For a full CFD run, restore the base/generated `controlDict` to the real `endTime` and run the same command. On the current 16 GB machine, the full 3.5M-cell case is expected to take a long time and can exhaust WSL memory.

## 7. Export VTU

```bash
fan-sim export-vtk --config configs/fan_sim.yaml --case-id case_rpm_0600_pout_000
```

Expected output:

```text
runs/openfoam/case_rpm_0600_pout_000/VTK/case_rpm_0600_pout_000_2/internal.vtu
```

## 8. Build Graph Samples

```bash
fan-sim build-graphs --config configs/fan_sim.yaml
```

Expected:

```text
artifacts/graphs/*.graph.pt
```

The graph is cell-centered:

- nodes = OpenFOAM cells
- node features = cell center, rpm, inlet pressure, outlet pressure, patch flags
- edge features = dx, dy, dz, distance
- target = Ux, Uy, Uz, p

## 9. Train

PhysicsNeMo:

```bash
fan-sim train --config configs/fan_sim.yaml --epochs 1
```

Smoke backend:

```yaml
model:
  backend: numpy
```

Then:

```bash
fan-sim train --config configs/fan_sim.yaml --epochs 1
```

Outputs:

```text
artifacts/models/fan_mgn/checkpoint.pt
artifacts/models/fan_mgn/normalizer.json
```

For `backend: numpy`, the checkpoint is:

```text
artifacts/models/fan_mgn/checkpoint.npz
```

## 10. Predict A New RPM

```bash
fan-sim predict \
  --config configs/fan_sim.yaml \
  --case-id case_rpm_0600_pout_000 \
  --rpm 1200 \
  --outlet-pressure 20
```

Outputs:

```text
runs/inference/case_rpm_0600_pout_000_rpm1200/prediction.vtu
runs/inference/case_rpm_0600_pout_000_rpm1200/prediction.usda
runs/inference/case_rpm_0600_pout_000_rpm1200/streamline_seeds.json
runs/inference/case_rpm_0600_pout_000_rpm1200/particle_seeds.json
```

## 11. Serve For Omniverse

Run the service in Ubuntu:

```bash
fan-sim serve \
  --config configs/fan_sim.yaml \
  --case-id case_rpm_0600_pout_000 \
  --host 0.0.0.0 \
  --port 8765
```

Check from Ubuntu:

```bash
curl http://127.0.0.1:8765/health
```

Omniverse Kit-CAE on Windows can call the WSL service through:

```text
http://127.0.0.1:8765
```

## 12. Omniverse Kit-CAE

Kit-CAE remains external at:

```text
D:\nvidia\kit-cae
```

The Fan-Sim extension is:

```text
D:\nvidia\fan-sim\extensions\omni.fan_sim
```

The extension calls the Ubuntu service, receives `prediction.usda` and `prediction.vtu`, and loads predicted fields for pressure/velocity contours, streamlines, slices, volume views, and passive particle traces.

## 13. Verified Smoke Result On This Machine

The following has been verified on 2026-05-09:

```bash
fan-sim run-openfoam --config configs/fan_sim.yaml --case-id case_rpm_0600_pout_000
fan-sim export-vtk --config configs/fan_sim.yaml --case-id case_rpm_0600_pout_000
```

Verified output:

```text
runs/openfoam/case_rpm_0600_pout_000/VTK/case_rpm_0600_pout_000_2/internal.vtu
```

This was a smoke run with `endTime 2`, not a full `endTime 1000` CFD solve.

## 14. Move To A Linux SSH Server

For real CFD/training runs, prefer a native Linux directory on the server instead of `/mnt/d`.

From the current WSL machine:

```bash
cd /mnt/d/nvidia/fan-sim

USER=your_user
HOST=your.server.ip
REMOTE_DIR=/home/your_user/fan-sim

rsync -avh --progress \
  --exclude ".venv" \
  --exclude ".venv-ubuntu" \
  --exclude "__pycache__" \
  --exclude "*.pyc" \
  --exclude "src/*.egg-info" \
  --exclude "runs/openfoam/*/VTK" \
  ./ "$USER@$HOST:$REMOTE_DIR/"
```

If you want to copy previously generated VTU results too, remove this exclude:

```text
--exclude "runs/openfoam/*/VTK"
```

SSH into the server:

```bash
ssh "$USER@$HOST"
cd "$REMOTE_DIR"
```

Install system dependencies on Ubuntu:

```bash
sudo apt update
sudo apt install -y python3.11 python3.11-venv python3.11-dev build-essential tmux rsync
```

If `python3.11` is unavailable on Ubuntu 22.04, use deadsnakes:

```bash
sudo apt install -y software-properties-common
sudo add-apt-repository -y ppa:deadsnakes/ppa
sudo apt update
sudo apt install -y python3.11 python3.11-venv python3.11-dev build-essential tmux rsync
```

Create the server venv:

```bash
cd "$REMOTE_DIR"
python3.11 -m venv .venv
source .venv/bin/activate
python --version
python -m pip install --upgrade pip
python -m pip install -e ".[service,vtk,ml,dev]"
```

Expected Python:

```text
Python 3.11.x
```

If the server only has Python 3.10, `pip install -e .` will fail because Fan-Sim requires `>=3.11,<3.13`.

Install/source OpenFOAM 2406 on the server:

```bash
curl https://dl.openfoam.com/add-debian-repo.sh | sudo bash
sudo apt update
sudo apt install -y openfoam2406-default

. /usr/lib/openfoam/openfoam2406/etc/bashrc
which simpleFoam
which foamToVTK
```

Verify Fan-Sim:

```bash
source .venv/bin/activate
python -m pytest -q
fan-sim --help
```

On the Linux server, `configs/fan_sim.yaml` should still use:

```yaml
openfoam:
  shell: bash
```

Do not introduce `D:\...` paths into the Linux config.

## 15. Run All Solves

Generate cases:

```bash
cd /home/your_user/fan-sim
source .venv/bin/activate
fan-sim generate-cases --config configs/fan_sim.yaml
```

Run one case first:

```bash
fan-sim run-openfoam \
  --config configs/fan_sim.yaml \
  --case-id case_rpm_0600_pout_000
```

If it returns `0`, run all generated cases sequentially:

```bash
fan-sim run-openfoam --config configs/fan_sim.yaml
```

Use `tmux` for long runs:

```bash
tmux new -s fan-sim
cd /home/your_user/fan-sim
source .venv/bin/activate
fan-sim run-openfoam --config configs/fan_sim.yaml
```

Detach from `tmux` with:

```text
Ctrl+B, then D
```

Reattach:

```bash
tmux attach -t fan-sim
```

Each case writes logs here:

```text
runs/openfoam/<case_id>/log.fan-sim-openfoam
runs/openfoam/<case_id>/log.fan-sim-foamToVTK
```

Monitor a running case:

```bash
tail -f runs/openfoam/case_rpm_0600_pout_000/log.fan-sim-openfoam
```

After all solves complete, export all VTU:

```bash
fan-sim export-vtk --config configs/fan_sim.yaml
```

Then build graphs:

```bash
fan-sim build-graphs --config configs/fan_sim.yaml
```

Do not parallelize OpenFOAM cases until you know memory per case. The current mesh is large enough that parallel runs can exhaust RAM.

## 16. Common Failures

### Running From PowerShell

This is now intentionally unsupported:

```text
Run fan-sim inside Ubuntu/WSL bash. This project no longer invokes wsl.exe from Windows.
```

Fix:

```powershell
wsl -d Ubuntu
```

Then:

```bash
cd /mnt/d/nvidia/fan-sim
source .venv-ubuntu/bin/activate
```

### `shell: wsl`

This is intentionally rejected. Use:

```yaml
openfoam:
  shell: bash
```

### `simpleFoam` Not Found

Source OpenFOAM 2406:

```bash
. /usr/lib/openfoam/openfoam2406/etc/bashrc
which simpleFoam
```

### `autoTurbulentMixingLengthFrequencyInlet` Not Found

The case came from OpenFOAM.com/SimScale. Fan-Sim migrates generated cases before running:

```text
autoTurbulentMixingLengthFrequencyInlet -> turbulentMixingLengthFrequencyInlet
```

It also removes unavailable SimScale custom libraries/functionObjects, replaces the custom `localBlended` scheme, and converts dynamic pressure dimensions to kinematic pressure for `simpleFoam`.
