#!/usr/bin/env bash
# Start the background Ollama service, ensure the configured Gemma model exists,
# and optionally send one prompt to it.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
MODEL="${WSW_OLLAMA_MODEL:-gemma4:12b-it-qat}"
OLLAMA_URL="${WSW_OLLAMA_URL:-http://127.0.0.1:11434}"

if ! command -v ollama >/dev/null 2>&1; then
  echo "Ollama is not installed. Install it with: brew install ollama" >&2
  exit 1
fi

if command -v brew >/dev/null 2>&1; then
  brew services start ollama >/dev/null 2>&1 || true
fi

for _ in $(seq 1 30); do
  if curl -fsS "$OLLAMA_URL/api/tags" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

if ! curl -fsS "$OLLAMA_URL/api/tags" >/dev/null 2>&1; then
  echo "Ollama did not become ready at $OLLAMA_URL" >&2
  exit 1
fi

if ! ollama list | awk 'NR > 1 {print $1}' | grep -Fxq "$MODEL"; then
  echo "Pulling $MODEL (first run downloads several GB)..."
  ollama pull "$MODEL"
fi

echo "Ollama is ready: $MODEL"
if (($#)); then
  exec ollama run "$MODEL" "$*"
fi
