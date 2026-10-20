#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OLLAMA_MODELS="${PROJECT_ROOT}/.models/ollama"
OLLAMA_HOST="127.0.0.1:11434"
OLLAMA_CONTEXT_LENGTH="${OLLAMA_CONTEXT_LENGTH:-1024}"
export OLLAMA_MODELS OLLAMA_HOST
export OLLAMA_CONTEXT_LENGTH

exec "${PROJECT_ROOT}/.tools/ollama/bin/ollama" serve
