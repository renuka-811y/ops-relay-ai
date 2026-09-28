"""
agent/sre_agent.py - OpsRelay AI incident remediation orchestrator.

Pipeline for every incident:
    1. Ingest the production error log.
    2. Recall similar past incidents from Vectorize Hindsight.
    3. Ask Gemini 2.5 Flash for a ROLLBACK / MANUAL_TRIAGE decision + root cause.
    4. Apply a deterministic safety guardrail: if memory says a previous rollback
       failed due to DB locks / schema migrations, the rollback is OVERRIDDEN and
       the incident is escalated to MANUAL_TRIAGE (regardless of what the LLM said).
    5. Execute the action (GitHub Actions rollback or Slack escalation).
    6. Send a Slack alert.
    7. Retain the post-mortem in Hindsight so the agent learns permanently.

Run the demo end-to-end from the project root:
    python -m agent.sre_agent --scenario crash --seed --dry-run
    python -m agent.sre_agent --scenario memory-leak --dry-run
    python -m agent.sre_agent --app-url http://localhost:8000 --scenario crash
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv
from pydantic import BaseModel

# Make `agent` and `app` importable even when this file is run as a script.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv(PROJECT_ROOT / ".env")

from google import genai  # noqa: E402
from google.genai import types  # noqa: E402

from agent import memory, notifications  # noqa: E402
from app.main import CRASH_ERROR_MESSAGE, MEMORY_LEAK_ERROR_MESSAGE  # noqa: E402

logger = logging.getLogger("opsrelay.agent")

GEMINI_MODEL = "gemini-2.5-flash"
GITHUB_API_VERSION = "2022-11-28"

DECISION_ROLLBACK = "ROLLBACK"
DECISION_MANUAL_TRIAGE = "MANUAL_TRIAGE"

SCENARIOS = {
    "crash": ("/trigger-crash", CRASH_ERROR_MESSAGE),
    "memory-leak": ("/trigger-memory-leak", MEMORY_LEAK_ERROR_MESSAGE),
}

SYSTEM_INSTRUCTION = """You are OpsRelay AI, a senior Site Reliability Engineer.
You triage production incidents and decide between two actions:
  ROLLBACK       - automatically roll back the suspect deployment.
  MANUAL_TRIAGE  - do NOT roll back; page a human engineer.

Hard policy:
- If the recalled incident history shows a previous rollback caused or coincided
  with a database lock, schema-migration problem, or cascading failure,
  you MUST choose MANUAL_TRIAGE.
- Otherwise, if the log points at a bad deployment (crash, OOM, regression),
  choose ROLLBACK.
Be concise. Base your root cause on the log and the recalled history only."""


class GeminiDecision(BaseModel):
    """Structured output requested from Gemini."""

    decision: str  # "ROLLBACK" or "MANUAL_TRIAGE"
    root_cause: str
    reasoning: str
    confidence: float  # 0.0 - 1.0


# --------------------------------------------------------------------------- #
# Step 1: parsing
# --------------------------------------------------------------------------- #
def extract_commit(error_log: str) -> str:
    """Pull the suspect commit SHA out of a log line like '... Commit #a1b2c3'."""
    match = re.search(r"[Cc]ommit\s*#?([0-9a-fA-F]{6,40})", error_log)
    return match.group(1).lower() if match else "unknown"


# --------------------------------------------------------------------------- #
# Step 3: Gemini analysis
# --------------------------------------------------------------------------- #
def analyze_with_gemini(error_log: str, recall: dict, commit: str) -> GeminiDecision:
    """Ask Gemini 2.5 Flash for a decision, given the log and Hindsight context.

    Raises:
        RuntimeError: if no Gemini API key is configured.
        Exception:    any API/parsing failure (caller falls back to heuristics).
    """
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set")

    if recall.get("memories"):
        memory_block = "\n".join(f"- {m}" for m in recall["memories"])
    else:
        memory_block = "(no related past incidents recalled)"

    prompt = (
        f"CURRENT INCIDENT LOG:\n{error_log}\n\n"
        f"SUSPECT COMMIT: {commit}\n\n"
        f"HINDSIGHT MEMORY (past incidents and outcomes):\n{memory_block}\n\n"
        f"MEMORY RISK FLAG (rollback previously failed due to DB lock / migration): "
        f"{recall.get('rollback_risk', False)}\n\n"
        "Return your decision as JSON."
    )

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
            temperature=0.1,
            response_mime_type="application/json",
            response_schema=GeminiDecision,
        ),
    )

    parsed = getattr(response, "parsed", None)
    if isinstance(parsed, GeminiDecision):
        return parsed
    return GeminiDecision(**json.loads(response.text))


def heuristic_decision(error_log: str, recall: dict, reason: str) -> GeminiDecision:
    """Deterministic fallback used when Gemini is unavailable."""
    if recall.get("rollback_risk"):
        decision = DECISION_MANUAL_TRIAGE
        root_cause = "Database lock / migration risk recorded in memory; LLM analysis unavailable."
    else:
        decision = DECISION_ROLLBACK
        root_cause = f"Crash detected in log; LLM analysis unavailable ({reason})."
    return GeminiDecision(
        decision=decision,
        root_cause=root_cause,
        reasoning="Heuristic fallback: rollback unless memory flags rollback risk.",
        confidence=0.4,
    )


# --------------------------------------------------------------------------- #
# Step 5: executing actions
# --------------------------------------------------------------------------- #
def trigger_rollback(commit: str, reason: str, dry_run: bool) -> dict:
    """Dispatch the GitHub Actions rollback workflow.

    Requires GITHUB_TOKEN (repo/actions scope) and GITHUB_REPO ("owner/name").
    Without them, or with dry_run=True, the dispatch is only simulated.

    Returns:
        {"success": bool, "mode": "github" | "dry_run", "detail": str}
    """
    token = os.getenv("GITHUB_TOKEN")
    repo = os.getenv("GITHUB_REPO")
    workflow_file = os.getenv("GITHUB_WORKFLOW_FILE", "rollback.yml")
    ref = os.getenv("GITHUB_REF_NAME", "main")

    if dry_run or not token or not repo:
        why = "dry-run enabled" if dry_run else "GITHUB_TOKEN / GITHUB_REPO not configured"
        return {
            "success": True,
            "mode": "dry_run",
            "detail": f"[SIMULATED] Would dispatch {workflow_file} to revert commit {commit} ({why}).",
        }

    url = f"https://api.github.com/repos/{repo}/actions/workflows/{workflow_file}/dispatches"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": GITHUB_API_VERSION,
    }
    body = {
        "ref": ref,
        "inputs": {"bad_commit": commit, "reason": reason[:250], "environment": "production"},
    }

    try:
        response = requests.post(url, headers=headers, json=body, timeout=15)
    except requests.RequestException as exc:
        return {"success": False, "mode": "github", "detail": f"GitHub dispatch failed: {exc}"}

    if response.status_code == 204:  # GitHub returns 204 No Content on success
        return {
            "success": True,
            "mode": "github",
            "detail": f"Dispatched {workflow_file} on {repo}@{ref} to roll back commit {commit}.",
        }
    return {
        "success": False,
        "mode": "github",
        "detail": f"GitHub dispatch rejected (HTTP {response.status_code}): {response.text[:200]}",
    }


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def handle_incident(error_log: str, dry_run: bool = False) -> dict:
    """Run the full OpsRelay pipeline for one incident and return a report."""
    error_log = error_log.strip()
    commit = extract_commit(error_log)
    logger.info("Incident ingested (suspect commit: %s)", commit)

    # Step 2: Hindsight recall
    recall = memory.recall_past_incidents(error_log)
    logger.info("Hindsight recall: %s", recall["summary"])

    # Step 3: LLM analysis (with a deterministic fallback)
    try:
        analysis = analyze_with_gemini(error_log, recall, commit)
    except Exception as exc:  # noqa: BLE001 - never let LLM failure stop remediation
        logger.warning("Gemini analysis failed, using heuristic fallback: %s", exc)
        analysis = heuristic_decision(error_log, recall, reason=str(exc))

    decision = analysis.decision.strip().upper()
    if decision not in (DECISION_ROLLBACK, DECISION_MANUAL_TRIAGE):
        decision = DECISION_MANUAL_TRIAGE  # unknown output -> fail safe
    root_cause = analysis.root_cause

    # Step 4: deterministic safety guardrail - memory overrides the rollback
    overridden = False
    if decision == DECISION_ROLLBACK and recall["rollback_risk"]:
        overridden = True
        decision = DECISION_MANUAL_TRIAGE
        root_cause = (
            f"{root_cause} | Rollback OVERRIDDEN: Hindsight memory shows a previous rollback "
            "was associated with a database lock / schema migration failure."
        )
        logger.warning("Rollback overridden by Hindsight memory -> MANUAL_TRIAGE")

    # Step 5: execute
    if decision == DECISION_ROLLBACK:
        rollback = trigger_rollback(commit, root_cause, dry_run)
        if rollback["success"]:
            action_detail = rollback["detail"]
        else:
            # A rollback that could not even start must not be silently dropped.
            decision = DECISION_MANUAL_TRIAGE
            action_detail = f"{rollback['detail']} Escalating to a human engineer."
    elif overridden or recall["rollback_risk"]:
        action_detail = (
            "Automated rollback blocked. Past rollback of a similar failure caused a database "
            "lock / schema-migration problem. Escalating to on-call for manual triage."
        )
    else:
        action_detail = "Escalating to on-call for manual triage."

    # Step 6: Slack alert
    slack_sent = notifications.send_incident_alert(
        error_log=error_log,
        recall=recall,
        decision=decision,
        root_cause=root_cause,
        action_detail=action_detail,
        overridden=overridden,
        confidence=analysis.confidence,
    )

    # Step 7: Hindsight retain
    retained = memory.retain_incident_learning(
        error_log=error_log,
        action=f"{decision}: {action_detail}",
        root_cause=root_cause,
    )

    return {
        "error_log": error_log,
        "suspect_commit": commit,
        "memory_available": recall["available"],
        "rollback_risk_from_memory": recall["rollback_risk"],
        "memories_recalled": len(recall["memories"]),
        "decision": decision,
        "overridden_by_memory": overridden,
        "root_cause": root_cause,
        "reasoning": analysis.reasoning,
        "confidence": analysis.confidence,
        "action_detail": action_detail,
        "slack_alert_sent": slack_sent,
        "memory_retained": retained,
    }


# --------------------------------------------------------------------------- #
# CLI helpers
# --------------------------------------------------------------------------- #
def fetch_live_error(app_url: str, endpoint: str) -> Optional[str]:
    """Hit the running target app and return the error message it emits."""
    try:
        response = requests.get(app_url.rstrip("/") + endpoint, timeout=10)
    except requests.RequestException as exc:
        logger.error("Could not reach target app at %s: %s", app_url, exc)
        return None
    if response.status_code < 500:
        logger.error("Target app returned HTTP %s - no incident to process.", response.status_code)
        return None
    try:
        return str(response.json().get("detail", response.text))
    except ValueError:
        return response.text


def seed_failed_rollback_memory(wait_seconds: float) -> None:
    """Teach Hindsight that rolling back the crash scenario once caused a DB lock."""
    logger.info("Seeding Hindsight with a past FAILED rollback incident...")
    ok = memory.retain_incident_learning(
        error_log=CRASH_ERROR_MESSAGE,
        action="ROLLBACK via GitHub Actions - FAILED",
        root_cause=(
            "The automated rollback of Commit #a1b2c3 reverted a schema migration while "
            "transactions were in flight, causing a database lock and a cascading "
            "connection-pool failure. The rollback made the outage worse."
        ),
    )
    if not ok:
        logger.warning("Seeding failed (check HINDSIGHT_API_KEY / network).")
        return
    if wait_seconds > 0:
        logger.info("Waiting %.0fs for Hindsight to index the memory...", wait_seconds)
        time.sleep(wait_seconds)


def main() -> int:
    parser = argparse.ArgumentParser(description="OpsRelay AI - autonomous incident remediation agent")
    parser.add_argument("--scenario", choices=sorted(SCENARIOS), default="crash",
                        help="Built-in incident to simulate (default: crash)")
    parser.add_argument("--log", help="Process a custom error log instead of a built-in scenario")
    parser.add_argument("--app-url", help="Fetch the error from a live target app, e.g. http://localhost:8000")
    parser.add_argument("--seed", action="store_true",
                        help="First store a past failed-rollback memory in Hindsight (demo setup)")
    parser.add_argument("--seed-wait", type=float, default=10.0,
                        help="Seconds to wait after seeding so memory is searchable (default: 10)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Simulate the GitHub rollback instead of dispatching it")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    endpoint, builtin_log = SCENARIOS[args.scenario]
    if args.log:
        error_log: Optional[str] = args.log
    elif args.app_url:
        error_log = fetch_live_error(args.app_url, endpoint)
    else:
        error_log = builtin_log

    if not error_log:
        return 1

    if args.seed:
        seed_failed_rollback_memory(args.seed_wait)

    report = handle_incident(error_log, dry_run=args.dry_run)

    print("\n=========== OPSRELAY AI INCIDENT REPORT ===========")
    print(json.dumps(report, indent=2))
    print("===================================================")
    return 0


if __name__ == "__main__":
    sys.exit(main())