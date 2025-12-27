#!/usr/bin/env bash
set -e

VENV=".venv"
SCRIPT="${1:-mixdown.py}"

python3 -m venv "$VENV"
source "$VENV/bin/activate"

pip install --upgrade pip
pip install -r requirements.txt

python "$SCRIPT"
