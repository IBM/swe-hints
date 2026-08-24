#!/usr/bin/env bash
# leave_one_out/run_loo_eval_swerebench_v3.sh
# ============================================
# Gather patches and evaluate for every LOO v3 coalition that has a preds.json,
# using the SWErebench evaluator (nebius/SWE-rebench-leaderboard).
#
# Usage:
#   bash leave_one_out/run_loo_eval_swerebench_v3.sh <run_id>
#
# Examples:
#   bash leave_one_out/run_loo_eval_swerebench_v3.sh loo_swerebench_v3_r1
#   bash leave_one_out/run_loo_eval_swerebench_v3.sh loo_swerebench_v3_r2
#   bash leave_one_out/run_loo_eval_swerebench_v3.sh loo_swerebench_v3_r3
#
# Idempotent: skips any coalition whose eval result JSON already exists.

set -uo pipefail

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────
HINTS_DIR="/home/USERNAME/hints"
MINI_DIR="/home/USERNAME/mini-swe-agent"
SWE_BENCH_FORK="/home/USERNAME/SWE-bench-fork"

DATASET_NAME="nebius/SWE-rebench-leaderboard"
NAMESPACE="swerebench"
MAX_WORKERS=12

REPETITIONS=(0)
# ─────────────────────────────────────────────────────────────────────────────

RUN_ID="${1:?Usage: $0 <run_id>  (e.g. loo_swerebench_v3_r1)}"

RUN_DIR="${HINTS_DIR}/leave_one_out/runs/${RUN_ID}"
MANIFEST="${RUN_DIR}/coalition_manifest.json"
EVAL_BASE_DIR="${RUN_DIR}/eval_results"
LOGS_DIR="${RUN_DIR}/logs"
PROGRESS_LOG="${RUN_DIR}/progress.log"

# ── helpers ───────────────────────────────────────────────────────────────────
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "${PROGRESS_LOG}"
}
log_fail() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] FAIL $*" | tee -a "${PROGRESS_LOG}" >&2
}

# ── pre-flight ────────────────────────────────────────────────────────────────
command -v jq >/dev/null 2>&1 || { echo "ERROR: jq not installed."; exit 1; }

[[ -f "${MANIFEST}" ]] || {
    echo "ERROR: coalition_manifest.json not found: ${MANIFEST}"
    echo "       Run plan_loo_coalitions_v3.py first."
    exit 1
}

[[ -d "${SWE_BENCH_FORK}" ]] || {
    echo "ERROR: SWE-bench fork not found: ${SWE_BENCH_FORK}"
    exit 1
}

[[ -f "${SWE_BENCH_FORK}/.venv/bin/activate" ]] || {
    echo "ERROR: .venv not found in ${SWE_BENCH_FORK}"
    exit 1
}

source "${SWE_BENCH_FORK}/.venv/bin/activate"

# ── main loop ─────────────────────────────────────────────────────────────────
mkdir -p "${EVAL_BASE_DIR}" "${LOGS_DIR}"
FAILED=0
TOTAL=$(jq 'keys | length' "${MANIFEST}")
NUM=0

log "START eval run  run_id=${RUN_ID}  coalitions=${TOTAL}"

while IFS= read -r CID; do
    NUM=$((NUM + 1))
    CTYPE=$(jq -r --arg c "${CID}" '.[$c].coalition_type' "${MANIFEST}")

    for REPETITION in "${REPETITIONS[@]}"; do
        AGENT_OUTPUT="${MINI_DIR}/output/leave_one_out_v3/${RUN_ID}/${CID}/repeat_${REPETITION}"
        PREDS_FILE="${AGENT_OUTPUT}/preds.json"
        EVAL_DIR="${EVAL_BASE_DIR}/${CID}/repeat_${REPETITION}"
        EVAL_RESULT="${SWE_BENCH_FORK}/openai__azure__DeepSeek-V4-Flash.loo_v3_${RUN_ID}_${CID}_rep${REPETITION}.json"
        JOB_LOG="${LOGS_DIR}/eval_${CID}_rep${REPETITION}.log"

        # Skip if already evaluated
        if [[ -f "${EVAL_RESULT}" ]]; then
            log "SKIP  [${NUM}/${TOTAL}] coalition=${CID} type=${CTYPE} rep=${REPETITION}"
            mkdir -p "${EVAL_DIR}"
            # Convert swerebench format -> {instance_id: bool} for collect_loo_outcomes_v3.py
            python3 -c "
import json
raw = json.load(open('${EVAL_RESULT}'))
submitted = set(raw.get('submitted_ids', []))
resolved  = set(raw.get('resolved_ids',  []))
out = {iid: (iid in resolved) for iid in submitted}
json.dump(out, open('${EVAL_DIR}/eval_results.json', 'w'))
"
            continue
        fi

        if [[ ! -f "${PREDS_FILE}" ]]; then
            log "WAIT  [${NUM}/${TOTAL}] coalition=${CID} type=${CTYPE} rep=${REPETITION}  (preds.json not yet present)"
            continue
        fi

        log "START [${NUM}/${TOTAL}] coalition=${CID} type=${CTYPE} rep=${REPETITION}"
        mkdir -p "${EVAL_DIR}"

        {
            cd "${SWE_BENCH_FORK}"
            python -m swebench.harness.run_evaluation \
                --dataset_name  "${DATASET_NAME}" \
                --predictions_path "${PREDS_FILE}" \
                --cache_level   instance \
                --run_id        "loo_v3_${RUN_ID}_${CID}_rep${REPETITION}" \
                --namespace     "${NAMESPACE}" \
                --max_workers   "${MAX_WORKERS}" \
            || { echo "[eval] FAIL exit=$?"; exit 1; }

            [[ -f "${EVAL_RESULT}" ]] \
            || { echo "[eval] FAIL result JSON missing: ${EVAL_RESULT}"; exit 1; }

            # Convert swerebench format -> {instance_id: bool} for collect_loo_outcomes_v3.py
            python3 -c "
import json, sys
raw = json.load(open('${EVAL_RESULT}'))
submitted = set(raw.get('submitted_ids', []))
resolved  = set(raw.get('resolved_ids',  []))
out = {iid: (iid in resolved) for iid in submitted}
json.dump(out, open('${EVAL_DIR}/eval_results.json', 'w'))
" || { echo "[convert] FAIL"; exit 1; }
            echo "[eval] DONE"

        } 2>&1 | tee "${JOB_LOG}" \
        || { log_fail "[${NUM}/${TOTAL}] coalition=${CID} rep=${REPETITION}"; FAILED=$((FAILED+1)); continue; }

        log "DONE  [${NUM}/${TOTAL}] coalition=${CID} type=${CTYPE} rep=${REPETITION}"

    done
done < <(jq -r 'keys[]' "${MANIFEST}")

# ── summary ───────────────────────────────────────────────────────────────────
DONE=$(find "${EVAL_BASE_DIR}" -name "eval_results.json" 2>/dev/null | wc -l)
log "Finished: ${DONE} eval_results.json found.  Failed: ${FAILED}."

if [[ "${FAILED}" -gt 0 ]]; then
    log "WARNING: ${FAILED} job(s) failed. Check logs in ${LOGS_DIR}."
    exit 1
fi
log "All eval jobs completed successfully."
