#!/usr/bin/env bash
# run_swerebench_no_hints.sh
# ==========================
# Run mini-SWE-agent 3 times on the swerebench no-hints (plain) baseline.
# Each run writes to a separate output directory (repeat_0, repeat_1, repeat_2).
# Idempotent: skips any run whose preds.json already exists.
#
# Usage:
#   bash leave_one_out/run_swerebench_no_hints.sh [parallel_jobs]
#
# Example:
#   bash leave_one_out/run_swerebench_no_hints.sh 4

set -uo pipefail

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────
HINTS_DIR="/home/USERNAME/hints"
MINI_DIR="/home/USERNAME/mini-swe-agent"

BENCHMARK_CONFIG="swerebench_hints.yaml"
MODEL_CONFIG="rits_swebench_ds.yaml"
WORKERS=4

SUBSET="${HINTS_DIR}/leave_one_out/output/hints_communication_all_nonempty_merged_no_hints_v3.jsonl"
OUTPUT_BASE="${MINI_DIR}/output/swerebench_no_hints_v3"

REPETITIONS=(0 1 2)
# ─────────────────────────────────────────────────────────────────────────────

PARALLEL_JOBS="${1:-4}"
LOG_DIR="${HINTS_DIR}/leave_one_out/logs/swerebench_no_hints_v3"
mkdir -p "${LOG_DIR}"

PROGRESS_LOG="${LOG_DIR}/progress.log"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "${PROGRESS_LOG}"
}

# ── pre-flight ────────────────────────────────────────────────────────────────
[[ -f "${SUBSET}" ]] || { echo "ERROR: subset file not found: ${SUBSET}"; exit 1; }

[[ -f "${MINI_DIR}/.venv/bin/activate" ]] || {
    echo "ERROR: .venv not found in ${MINI_DIR}."; exit 1; }

source "${MINI_DIR}/.venv/bin/activate"
command -v mini-extra >/dev/null 2>&1 || {
    echo "ERROR: mini-extra not found after activating venv."; exit 1; }

# ── main ──────────────────────────────────────────────────────────────────────
log "START  subset=${SUBSET}"
log "       output_base=${OUTPUT_BASE}"
log "       repetitions=${REPETITIONS[*]}  parallel_jobs=${PARALLEL_JOBS}"

ACTIVE_PIDS=()
FAILED=()

for REP in "${REPETITIONS[@]}"; do
    OUTPUT_DIR="${OUTPUT_BASE}/repeat_${REP}"
    PREDS_FILE="${OUTPUT_DIR}/preds.json"
    JOB_LOG="${LOG_DIR}/run_rep${REP}.log"

    if [[ -f "${PREDS_FILE}" ]]; then
        log "SKIP   repeat=${REP}  (preds.json exists)"
        continue
    fi

    # ── throttle ─────────────────────────────────────────────────────────────
    while (( ${#ACTIVE_PIDS[@]} >= PARALLEL_JOBS )); do
        NEW_PIDS=()
        for PID in "${ACTIVE_PIDS[@]}"; do
            if kill -0 "${PID}" 2>/dev/null; then
                NEW_PIDS+=("${PID}")
            else
                wait "${PID}" || { FAILED+=("rep${REP}"); log "FAIL   pid=${PID}"; }
            fi
        done
        ACTIVE_PIDS=("${NEW_PIDS[@]+"${NEW_PIDS[@]}"}")
        (( ${#ACTIVE_PIDS[@]} >= PARALLEL_JOBS )) && sleep 2
    done

    log "START  repeat=${REP}"
    mkdir -p "${OUTPUT_DIR}"
    (
        source "${MINI_DIR}/.venv/bin/activate"
        cd "${MINI_DIR}"
        mini-extra swebench \
            -c "${BENCHMARK_CONFIG}" \
            -c "${MODEL_CONFIG}" \
            --subset  "${SUBSET}" \
            --workers "${WORKERS}" \
            --output  "${OUTPUT_DIR}" \
        || { echo "[agent] FAIL exit=$?"; exit 1; }
        [[ -f "${PREDS_FILE}" ]] || { echo "[agent] FAIL preds.json missing"; exit 1; }
        log "DONE   repeat=${REP}"
    ) >"${JOB_LOG}" 2>&1 &
    ACTIVE_PIDS+=($!)
done

# ── wait ──────────────────────────────────────────────────────────────────────
for PID in "${ACTIVE_PIDS[@]+"${ACTIVE_PIDS[@]}"}"; do
    wait "${PID}" || FAILED+=("pid=${PID}")
done

DONE=$(find "${OUTPUT_BASE}" -name "preds.json" 2>/dev/null | wc -l)
log "Finished: ${DONE}/${#REPETITIONS[@]} preds.json found.  Failed: ${#FAILED[@]}."
(( ${#FAILED[@]} > 0 )) && { log "WARNING: failed runs: ${FAILED[*]}"; exit 1; }
log "All runs completed successfully."
