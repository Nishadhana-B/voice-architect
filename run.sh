#!/bin/bash
# Talk through an architecture; a live page shows the diagram, risks and cost. Usage: ./run.sh [--headphones]
cd "$(dirname "$0")"
. .venv/bin/activate
export AWS_PROFILE="${AWS_PROFILE:-voice-chef}" AWS_REGION="${AWS_REGION:-us-east-1}"
export PYTHONWARNINGS=ignore
python scripts/preflight.py || exit 1
echo
python scripts/live.py "$@"
