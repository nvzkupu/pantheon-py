#!/usr/bin/env bash
set -euo pipefail

export PATH="$HOME/.local/share/fnm:$PATH"
eval "$(fnm env)" 2>/dev/null || true

set -a && source /home/zkupu/git/pantheon-py/.env && set +a
export NIM_API_KEY="$API_KEY" NIM_BASE_URL="$GATEWAY_URL" NIM_MODEL="nvidia/llama-3.1-nemotron-ultra-253b-v1"

EVALS_DIR="/home/zkupu/git/pantheon-py/evals"
SKILLS=(themis aphrodite calliope eris freya pele seshat maat kali demeter)
RESULTS_FILE="$EVALS_DIR/bin/ultra-run-results.txt"

echo "=== Ultra Run — $(date) ===" > "$RESULTS_FILE"
echo "" >> "$RESULTS_FILE"

for skill in "${SKILLS[@]}"; do
    echo "--- Running $skill ---"
    echo "--- $skill (started $(date +%H:%M:%S)) ---" >> "$RESULTS_FILE"
    cd "$EVALS_DIR/$skill"
    if output=$(skillgrade --smoke --provider=local --agent=nim 2>&1); then
        echo "$output"
        echo "$output" >> "$RESULTS_FILE"
        echo "--- $skill: EXIT 0 ---" >> "$RESULTS_FILE"
    else
        echo "$output"
        echo "$output" >> "$RESULTS_FILE"
        echo "--- $skill: EXIT $? ---" >> "$RESULTS_FILE"
    fi
    echo "" >> "$RESULTS_FILE"
done

echo "=== All done — $(date) ===" >> "$RESULTS_FILE"
echo "=== All done ==="
