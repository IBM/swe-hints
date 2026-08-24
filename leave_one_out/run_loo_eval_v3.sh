#!/usr/bin/env bash
# leave_one_out/run_loo_eval_v3.sh
# =================================
# Gather patches and evaluate for every LOO v3 coalition that has a preds.json.
#
# Uses the v3 taxonomy (plan_loo_coalitions_v3.py / run_loo_agent_v3.sh).
# LOO is over subgraph roots (File, Class, ClsFunc, ClsVar, Func, Var) plus
# NONE and FULL coalitions.
#
# Mirrors run_loo_eval_v2.sh exactly — same gather_patches.py +
# swe_bench_pro_eval.py invocations, same idempotency logic.
# Agent output is read from output/leave_one_out_v3/<run_id>/ (written by
# run_loo_agent_v3.sh).
#
# Usage:
#   bash leave_one_out/run_loo_eval_v3.sh <run_id>
#
# Example:
#   bash leave_one_out/run_loo_eval_v3.sh loo_helped_v3_r1

set -uo pipefail

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────
HINTS_DIR="/home/USERNAME/hints"
MINI_DIR="/home/USERNAME/mini-swe-agent"
SWE_PRO_DIR="/home/USERNAME/SWE-bench_Pro-os"
SWE_PRO_PYTHON="${SWE_PRO_DIR}/.venv/bin/python"

EVAL_WORKERS=25
DOCKERHUB_USERNAME="jefzda"
RAW_SAMPLE_PATH="results/python_all.jsonl"   # relative to SWE_PRO_DIR
SCRIPTS_DIR="run_scripts"                    # relative to SWE_PRO_DIR

REPETITIONS=(0)
# ─────────────────────────────────────────────────────────────────────────────

RUN_ID="${1:?Usage: $0 <run_id>  (e.g. loo_helped_v3_r1)}"

RUN_DIR="${HINTS_DIR}/leave_one_out/runs/${RUN_ID}"
MANIFEST="${RUN_DIR}/coalition_manifest.json"
PATCHES_DIR="${RUN_DIR}/patches"
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
json_valid() {
    [[ -f "$1" ]] && python3 -c "import json,sys; json.load(open(sys.argv[1]))" "$1" 2>/dev/null
}

progress_summary() {
    local total done_count partial pending
    total=$(jq 'keys | length' "${MANIFEST}")
    total=$((total * ${#REPETITIONS[@]}))
    done_count=0; partial=0; pending=0
    while IFS= read -r cid; do
        for rep in "${REPETITIONS[@]}"; do
            eval_f="${EVAL_BASE_DIR}/${cid}/repeat_${rep}/eval_results.json"
            patch_f="${PATCHES_DIR}/patches_${cid}_repeat_${rep}.json"
            if json_valid "${eval_f}"; then
                done_count=$((done_count+1))
            elif [[ -f "${patch_f}" ]]; then
                partial=$((partial+1))
            else
                pending=$((pending+1))
            fi
        done
    done < <(jq -r 'keys[]' "${MANIFEST}")
    log "Progress: ${done_count}/${total} eval done, ${partial} gathered (awaiting eval), ${pending} not started"
}

# ── pre-flight ────────────────────────────────────────────────────────────────
command -v jq >/dev/null 2>&1 || { echo "ERROR: jq not installed."; exit 1; }

[[ -f "${MANIFEST}" ]] || {
    echo "ERROR: coalition_manifest.json not found: ${MANIFEST}"
    echo "       Run plan_loo_coalitions_v3.py first."
    exit 1
}

[[ -d "${SWE_PRO_DIR}" ]] || {
    echo "ERROR: SWE-bench Pro directory not found: ${SWE_PRO_DIR}"
    exit 1
}

[[ -x "${SWE_PRO_PYTHON}" ]] || {
    echo "ERROR: SWE-bench Pro venv not found: ${SWE_PRO_PYTHON}"
    exit 1
}

"${SWE_PRO_PYTHON}" -c "import docker" 2>/dev/null || {
    echo "ERROR: 'docker' package not found in ${SWE_PRO_PYTHON}"
    echo "       Run: ${SWE_PRO_DIR}/.venv/bin/pip install docker"
    exit 1
}

# ── main loop ─────────────────────────────────────────────────────────────────
mkdir -p "${PATCHES_DIR}" "${EVAL_BASE_DIR}" "${LOGS_DIR}"
FAILED=0
TOTAL=$(jq 'keys | length' "${MANIFEST}")
NUM=0

log "START eval run  run_id=${RUN_ID}  coalitions=${TOTAL}"

while IFS= read -r CID; do
    NUM=$((NUM + 1))
    CTYPE=$(jq -r --arg c "${CID}" '.[$c].coalition_type' "${MANIFEST}")
    ROWS=$(jq -r --arg c "${CID}" '.[$c].rows | join(",")' "${MANIFEST}")

    for REPETITION in "${REPETITIONS[@]}"; do
        # Read agent output from the v3 subdirectory
        AGENT_OUTPUT="${MINI_DIR}/output/leave_one_out_v3/${RUN_ID}/${CID}/repeat_${REPETITION}"
        PREDS_FILE="${AGENT_OUTPUT}/preds.json"
        PATCH_FILE="${PATCHES_DIR}/patches_${CID}_repeat_${REPETITION}.json"
        EVAL_DIR="${EVAL_BASE_DIR}/${CID}/repeat_${REPETITION}"
        JOB_LOG="${LOGS_DIR}/eval_${CID}_rep${REPETITION}.log"

        if json_valid "${EVAL_DIR}/eval_results.json"; then
            log "SKIP  [${NUM}/${TOTAL}] coalition=${CID} type=${CTYPE} rep=${REPETITION}"
            continue
        fi

        if [[ ! -f "${PREDS_FILE}" ]]; then
            log "WAIT  [${NUM}/${TOTAL}] coalition=${CID} type=${CTYPE} rep=${REPETITION}  (preds.json not yet present)"
            continue
        fi

        log "START [${NUM}/${TOTAL}] coalition=${CID} type=${CTYPE} rep=${REPETITION}  rows=[${ROWS}]"
        mkdir -p "${EVAL_DIR}"

        {
            # ── gather patches ────────────────────────────────────────────────
            if [[ -f "${PATCH_FILE}" ]] && [[ -s "${PATCH_FILE}" ]]; then
                echo "[gather] SKIP — patch file already exists"
            else
                echo "[gather] START  coalition=${CID}"
                cd "${SWE_PRO_DIR}"
                "${SWE_PRO_PYTHON}" helper_code/gather_patches.py \
                    --directory "${AGENT_OUTPUT}" \
                    --prefix    "loo_v3_${CID}_repeat_${REPETITION}" \
                    --output    "${PATCH_FILE}" \
                    --mini \
                || { echo "[gather] FAIL exit=$?"; exit 1; }
                echo "[gather] DONE"
            fi

            # ── evaluate ──────────────────────────────────────────────────────
            echo "[eval] START  coalition=${CID}"
            cd "${SWE_PRO_DIR}"
            "${SWE_PRO_PYTHON}" swe_bench_pro_eval.py \
                --raw_sample_path="${RAW_SAMPLE_PATH}" \
                --patch_path="${PATCH_FILE}" \
                --output_dir="${EVAL_DIR}" \
                --scripts_dir="${SCRIPTS_DIR}" \
                --num_workers="${EVAL_WORKERS}" \
                --dockerhub_username="${DOCKERHUB_USERNAME}" \
                --use_local_docker \
            || { echo "[eval] FAIL exit=$?"; exit 1; }

            json_valid "${EVAL_DIR}/eval_results.json" \
            || { echo "[eval] FAIL eval_results.json missing or invalid"; exit 1; }
            echo "[eval] DONE"

        } 2>&1 | tee "${JOB_LOG}" \
        || { log_fail "[${NUM}/${TOTAL}] coalition=${CID} rep=${REPETITION}"; FAILED=$((FAILED+1)); continue; }

        log "DONE  [${NUM}/${TOTAL}] coalition=${CID} type=${CTYPE} rep=${REPETITION}"

    done
done < <(jq -r 'keys[]' "${MANIFEST}")

# ── summary ───────────────────────────────────────────────────────────────────
progress_summary

if [[ "${FAILED}" -gt 0 ]]; then
    log "WARNING: ${FAILED} job(s) failed. Check logs in ${LOGS_DIR}."
    exit 1
fi
log "All eval jobs completed successfully."
