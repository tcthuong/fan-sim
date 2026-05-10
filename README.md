# Fan-Sim

Fan-Sim is a standalone OpenFOAM-to-PhysicsNeMo pipeline for a steady fan CFD surrogate. It generates OpenFOAM cases from one base case, converts VTU results into cell-centered graph samples, trains a MeshGraphNet-style surrogate, serves local inference, and exports prediction artifacts for Omniverse Kit-CAE.

Start with the docs:

- `docs/00-overview.md`
- `docs/07-runbook.md`
- `docs/08-google-colab.md`

Run the pipeline inside Ubuntu/WSL or native Ubuntu. Do not run `fan-sim` from Windows PowerShell; Windows is only used for editing files and launching Omniverse Kit-CAE.

Use Python 3.11 or 3.12. Do not use Python 3.14 for this project because the PhysicsNeMo/PyTorch stack is not reliable there yet.

Install inside Ubuntu:

```bash
cd /mnt/d/nvidia/fan-sim
python3 -m venv .venv-ubuntu
source .venv-ubuntu/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[service,vtk,ml,dev]"
```

Run tests:

```bash
python -m pytest -q
```

Full setup and execution steps are in `docs/07-runbook.md`.

For a native Linux SSH server, use the runbook sections:

- `14. Move To A Linux SSH Server`
- `15. Run All Solves`

For Google Colab smoke tests, use:

- `docs/08-google-colab.md`
- `notebooks/fan_sim_colab.ipynb`
