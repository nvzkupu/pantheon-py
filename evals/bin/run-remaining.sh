#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ENV_FILE="$REPO_ROOT/.env"

export PATH="$HOME/.local/share/fnm:$PATH"
eval "$(fnm env)" 2>/dev/null || true

if [[ -f "$ENV_FILE" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    set +a
fi

export NIM_API_KEY="$API_KEY" NIM_BASE_URL="$GATEWAY_URL" NIM_MODEL="nvidia/llama-3.1-nemotron-ultra-253b-v1"

EVALS_DIR="$REPO_ROOT/evals"
RESULTS_FILE="$EVALS_DIR/bin/ultra-run-results.txt"

if [[ "$#" -gt 0 ]]; then
    SKILLS=("$@")
else
    mapfile -t SKILLS < <(
        for eval_file in "$EVALS_DIR"/*/eval.yaml; do
            skill="$(basename "$(dirname "$eval_file")")"
            [[ "$skill" == "_template" ]] && continue
            printf '%s\n' "$skill"
        done | sort
    )
fi

if [[ "${#SKILLS[@]}" -eq 0 ]]; then
    echo "No evals found to run" >&2
    exit 1
fi

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
        exit_code=$?
        echo "$output"
        echo "$output" >> "$RESULTS_FILE"
        echo "--- $skill: EXIT $exit_code ---" >> "$RESULTS_FILE"
    fi
    echo "" >> "$RESULTS_FILE"
done

echo "=== All done — $(date) ===" >> "$RESULTS_FILE"
echo "=== All done ==="
