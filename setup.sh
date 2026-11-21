#!/bin/bash
# One-time setup for a fresh Mac. Usage: ./setup.sh   then   ./run.sh
set -e
cd "$(dirname "$0")"

if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew is not installed. Install it from https://brew.sh, then run ./setup.sh again."; exit 1
fi
BREW="$(brew --prefix)"

echo "1/5 Audio library (portaudio)"
brew list portaudio >/dev/null 2>&1 || brew install portaudio

echo "2/5 Python 3.12 or newer"
PY=""
for c in python3.14 python3.13 python3.12 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3,12) else 1)' 2>/dev/null; then PY="$(command -v "$c")"; break; fi
done
if [ -z "$PY" ]; then brew install python@3.13; PY="$BREW/bin/python3.13"; fi
echo "   using $PY ($($PY --version))"

echo "3/5 Virtual environment and packages (a few minutes the first time)"
[ -d .venv ] || "$PY" -m venv .venv
. .venv/bin/activate
pip install -q --upgrade pip
CFLAGS="-I$BREW/include" LDFLAGS="-L$BREW/lib" pip install -q -r requirements.txt

echo "4/5 AWS command line + profile 'voice-chef'"
command -v aws >/dev/null 2>&1 || brew install awscli
if ! aws configure list-profiles 2>/dev/null | grep -qx voice-chef; then
  echo "   Enter the access key for the voice-chef IAM user. Region: us-east-1. Output: json."
  aws configure --profile voice-chef
fi

echo "5/5 Pre-flight check"
PYTHONWARNINGS=ignore python scripts/preflight.py
echo; echo "Setup done. Start the voice architect with: ./run.sh"
