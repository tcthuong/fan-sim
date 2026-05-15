# Fan-Sim Architecture Overview

Fan-Sim is a standalone backend for training and serving a steady-state fan CFD surrogate. It starts from one parameterized OpenFOAM base case, generates operating-condition cases, converts final CFD fields to cell-centered graphs, trains a PhysicsNeMo MeshGraphNet model, and exports predictions for Omniverse Kit-CAE visualization.

## End-to-End Flow

```text
base OpenFOAM case
  -> generated OpenFOAM cases
  -> Ubuntu/Linux OpenFOAM run
  -> foamToVTK
  -> VTU files
  -> cell-centered graph.pt samples
  -> PhysicsNeMo MeshGraphNet training
  -> checkpoint + normalizer
  -> local inference API
  -> prediction.vtu + prediction.usda + fan_mesh.usda
  -> Kit-CAE visualization
```

## Main Components

- `fan_sim.openfoam`: validates and clones a base OpenFOAM case, patches operating-condition values, runs Ubuntu/Linux OpenFOAM commands, and exports VTU files.
- `fan_sim.data`: reads VTU meshes and validates that velocity and pressure fields are present with the expected association.
- `fan_sim.graph`: converts cell-centered mesh data into PyTorch graph samples.
- `fan_sim.ml`: normalizes data, loads datasets, trains/evaluates MeshGraphNet, and saves checkpoints.
- `fan_sim.inference`: loads a trained model, rebuilds features for a new RPM/boundary condition, predicts fields, and denormalizes outputs.
- `fan_sim.export`: writes topology-preserving VTU/USD outputs, optional fan boundary mesh USD, and streamline/particle seed artifacts for visualization.
- `fan_sim.service`: exposes a local FastAPI inference API for Omniverse.
- `extensions/omni.fan_sim`: a Kit extension scaffold that calls the local service and loads results into the active stage.

## Design Decisions

The v1 surrogate is steady-state, not transient rollout. Graph nodes represent OpenFOAM cells because OpenFOAM finite-volume fields such as `U` and `p` are cell-centered in the reliable training path. Point data is generated only for visualization.

Omniverse does not run the heavy PyTorch/PhysicsNeMo stack in-process for v1. The extension calls a local Python service to avoid Python, CUDA, PyTorch, and Kit runtime conflicts.
