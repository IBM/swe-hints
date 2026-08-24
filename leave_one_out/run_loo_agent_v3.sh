#!/usr/bin/env bash
# leave_one_out/run_loo_agent_v3.sh
# ==================================
# Run mini-SWE-agent for every coalition in a leave-one-out v3 run.
#
# Uses the v3 taxonomy (plan_loo_coalitions_v3.py).
# LOO is over subgraph roots (File, Class, ClsFunc, ClsVar, Func, Var) plus
# NONE (no hints) and FULL (all hints).
#
# Mirrors run_loo_agent_v2.sh exactly — same coalition_manifest.json layout,
# same mini-extra invocation, same idempotency logic.
# Agent output is written under output/leave_one_out_v3/<run_id>/ to keep
# v1/v2/v3 results separate.
#
# Usage:
#   bash leave_one_out/run_loo_agent_v3.sh <run_id> [parallel_jobs] [benchmark_config]
#
# Examples:
#   bash leave_one_out/run_loo_agent_v3.sh loo_helped_v3_r1
#   bash leave_one_out/run_loo_agent_v3.sh loo_helped_v3_r1 20
#   bash leave_one_out/run_loo_agent_v3.sh loo_swerebench_v3_r1 20 swerebench_hints.yaml
#
# Idempotent: skips any coalition whose preds.json already exists.

set -uo pipefail

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────
HINTS_DIR="/home/USERNAME/hints"
MINI_DIR="/home/USERNAME/mini-swe-agent"

AGENT_CONFIG_2="rits_swebench_ds.yaml"     # model config
INNER_WORKERS=1

REPETITIONS=(0)
# ─────────────────────────────────────────────────────────────────────────────

RUN_ID="${1:?Usage: $0 <run_id> [parallel_jobs] [benchmark_config]}"
PARALLEL_JOBS="${2:-12}"
AGENT_CONFIG_1="${3:-swebench_pro_hints.yaml}"   # benchmark / prompt config

RUN_DIR="${HINTS_DIR}/leave_one_out/runs/${RUN_ID}"
MANIFEST="${RUN_DIR}/coalition_manifest.json"
LOGS_DIR="${RUN_DIR}/logs"
PROGRESS_LOG="${RUN_DIR}/progress.log"

# ── helpers ───────────────────────────────────────────────────────────────────
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "${PROGRESS_LOG}"
}

# ── pre-flight ────────────────────────────────────────────────────────────────
command -v jq >/dev/null 2>&1 || { echo "ERROR: jq not installed."; exit 1; }

[[ -f "${MANIFEST}" ]] || {
    echo "ERROR: coalition_manifest.json not found: ${MANIFEST}"
    echo "       Run plan_loo_coalitions_v3.py first."
    exit 1
}

[[ -f "${MINI_DIR}/.venv/bin/activate" ]] || {
    echo "ERROR: .venv not found in ${MINI_DIR}."
    exit 1
}

source "${MINI_DIR}/.venv/bin/activate"
command -v mini-extra >/dev/null 2>&1 || {
    echo "ERROR: mini-extra not found after activating venv."
    exit 1
}

# ── main ──────────────────────────────────────────────────────────────────────
mkdir -p "${LOGS_DIR}"
TOTAL=$(jq 'keys | length' "${MANIFEST}")
log "START run_id=${RUN_ID}  coalitions=${TOTAL}  parallel_jobs=${PARALLEL_JOBS}  inner_workers=${INNER_WORKERS}  benchmark=${AGENT_CONFIG_1}"

mapfile -t ALL_CIDS < <(jq -r 'keys[]' "${MANIFEST}")

ACTIVE_PIDS=()
FAILED_CIDS=()

for CID in "${ALL_CIDS[@]}"; do
    SUBSET="${RUN_DIR}/agent_inputs/instances_${CID}.jsonl"

    # Skip if agent input file is missing (not yet generated)
    if [[ ! -f "${SUBSET}" ]]; then
        log "SKIP  coalition=${CID}  (agent input file not found — run generate_all_hints_v3.py --run-dir first)"
        continue
    fi

    for REPETITION in "${REPETITIONS[@]}"; do
        # v3 results live under leave_one_out_v3/ to stay separate from v1/v2
        AGENT_OUTPUT="${MINI_DIR}/output/leave_one_out_v3/${RUN_ID}/${CID}/repeat_${REPETITION}"
        PREDS_FILE="${AGENT_OUTPUT}/preds.json"
        JOB_LOG="${LOGS_DIR}/agent_${CID}_rep${REPETITION}.log"

        if [[ -f "${PREDS_FILE}" ]]; then
            log "SKIP  coalition=${CID} rep=${REPETITION}"
            continue
        fi

        # ── throttle ─────────────────────────────────────────────────────────
        while (( ${#ACTIVE_PIDS[@]} >= PARALLEL_JOBS )); do
            NEW_PIDS=()
            for PID in "${ACTIVE_PIDS[@]}"; do
                if kill -0 "${PID}" 2>/dev/null; then
                    NEW_PIDS+=("${PID}")
                else
                    if ! wait "${PID}"; then
                        FAILED_CIDS+=("${PID}")
                        log "FAIL  pid=${PID}"
                    fi
                fi
            done
            ACTIVE_PIDS=("${NEW_PIDS[@]+"${NEW_PIDS[@]}"}")
            (( ${#ACTIVE_PIDS[@]} >= PARALLEL_JOBS )) && sleep 2
        done

        # ── launch ───────────────────────────────────────────────────────────
        log "START coalition=${CID} rep=${REPETITION}"
        mkdir -p "${AGENT_OUTPUT}"
        (
            source "${MINI_DIR}/.venv/bin/activate"
            cd "${MINI_DIR}"
            mini-extra swebench \
                -c "${AGENT_CONFIG_1}" \
                -c "${AGENT_CONFIG_2}" \
                --subset  "${SUBSET}" \
                --workers "${INNER_WORKERS}" \
                --output  "${AGENT_OUTPUT}" \
            || { echo "[agent] FAIL exit=$?"; exit 1; }
            [[ -f "${PREDS_FILE}" ]] || { echo "[agent] FAIL preds.json missing"; exit 1; }
            log "DONE  coalition=${CID} rep=${REPETITION}"
        ) >"${JOB_LOG}" 2>&1 &
        ACTIVE_PIDS+=($!)

    done
done

# ── wait for remaining ────────────────────────────────────────────────────────
for PID in "${ACTIVE_PIDS[@]+"${ACTIVE_PIDS[@]}"}"; do
    if ! wait "${PID}"; then
        FAILED_CIDS+=("${PID}")
        log "FAIL  pid=${PID}"
    fi
done

# ── summary ───────────────────────────────────────────────────────────────────
DONE=$(find "${MINI_DIR}/output/leave_one_out_v3/${RUN_ID}" -name "preds.json" 2>/dev/null | wc -l)
log "Finished: ${DONE} preds.json found.  Failed jobs: ${#FAILED_CIDS[@]}."

if (( ${#FAILED_CIDS[@]} > 0 )); then
    log "WARNING: ${#FAILED_CIDS[@]} job(s) failed. Check logs in ${LOGS_DIR}."
    exit 1
fi
log "All agent jobs completed successfully."
