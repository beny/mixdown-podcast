#!/usr/bin/env bash
set -e

python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python mixdown.py
# rozpoznat tracklisty nových epizod přes Shazam a promítnout je do XML
python enrich.py --limit 3
python mixdown.py
