#!/usr/bin/env bash
set -euo pipefail

SUDO=""
if command -v sudo >/dev/null 2>&1; then
  SUDO="sudo"
fi

if [ -f /usr/lib/openfoam/openfoam2406/etc/bashrc ] || [ -f /opt/openfoam2406/etc/bashrc ]; then
  echo "OpenFOAM 2406 already installed."
else
  $SUDO apt-get update
  $SUDO apt-get install -y curl ca-certificates gnupg lsb-release
  curl -s https://dl.openfoam.com/add-debian-repo.sh | $SUDO bash
  $SUDO apt-get update
  $SUDO apt-get install -y openfoam2406-default
fi

bash -lc '
if [ -f /usr/lib/openfoam/openfoam2406/etc/bashrc ]; then
  . /usr/lib/openfoam/openfoam2406/etc/bashrc
elif [ -f /opt/openfoam2406/etc/bashrc ]; then
  . /opt/openfoam2406/etc/bashrc
else
  echo "OpenFOAM 2406 bashrc not found" >&2
  exit 1
fi
which simpleFoam
which foamToVTK
'
