"""
agent/notifications.py - Slack alerting for OpsRelay AI.

Sends structured, Slack-mrkdwn formatted alerts through an incoming webhook
(`SLACK_WEBHOOK_URL`). Each alert contains three sections:

    🚨 INCIDENT DETECTED
    🧠 HINDSIGHT MEMORY RECALLED
    ⚡ ACTION TAKEN

If the webhook is not configured or the request fails, the alert is logged
to the console instead and the functions return False - they never raise.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("opsrelay.notifications")

# Slack section blocks accept at most 3000 characters of text.
SLACK_SECTION_LIMIT = 2800
REQUEST_TIMEOUT_SECONDS = 10


def _escape(text: str) -> str:
    """Escape the three characters Slack treats specially in mrkdwn."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _truncate(text, limit=350):
    text = str(text)
    return text if len(text) <= limit else text[: limit - 3] + "..."


def build_slack_payload(
    error_log: str,
    recall: dict,
    decision: str,
    root_cause: str,
    action_detail: str,
    overridden: bool = False,
    confidence: Optional[float] = None,
) -> dict:
    """Build the Slack webhook JSON body for an incident.

    Args:
        error_log:     Raw production error log.
        recall:        Dict returned by agent.memory.recall_past_incidents().
        decision:      Final decision, "ROLLBACK" or "MANUAL_TRIAGE".
        root_cause:    Root cause analysis text.
        action_detail: Human-readable description of what the agent did.
        overridden:    True if Hindsight memory overrode an automated rollback.
        confidence:    Optional model confidence between 0 and 1.
    """
    # ---- 🚨 INCIDENT DETECTED --------------------------------------------- #
    incident_text = (
        "*🚨 INCIDENT DETECTED*\n"
        f"```{_escape(_truncate(error_log.strip(), 1200))}```\n"
        f"*Root cause (AI analysis):* {_escape(root_cause)}"
    )
    if confidence is not None:
        incident_text += f"\n*Confidence:* {confidence:.0%}"

    # ---- 🧠 HINDSIGHT MEMORY RECALLED -------------------------------------- #
    if not recall.get("available"):
        memory_text = (
            "*🧠 HINDSIGHT MEMORY RECALLED*\n"
            "_Memory unavailable - decision made without historical context._"
        )
    else:
        lines = [f"*🧠 HINDSIGHT MEMORY RECALLED*\n{_escape(recall.get('summary', ''))}"]
        # Show the risky memories first, otherwise the top general matches.
        shown = recall.get("risk_reasons") or recall.get("memories") or []
        for memory in shown[:3]:
            lines.append(f"• {_escape(_truncate(memory, 350))}")
        if recall.get("rollback_risk"):
            lines.append("⚠️ *Rollback risk detected in memory.*")
        memory_text = "\n".join(lines)

    # ---- ⚡ ACTION TAKEN ---------------------------------------------------- #
    icon = "🛑" if decision == "MANUAL_TRIAGE" else "⏪"
    action_text = f"*⚡ ACTION TAKEN*\n{icon} *{decision}*"
    if overridden:
        action_text += " _(automated rollback OVERRIDDEN by Hindsight memory)_"
    action_text += f"\n{_escape(action_detail)}"
    if decision == "MANUAL_TRIAGE":
        action_text += "\n👉 *On-call engineer: please investigate manually.*"

    fallback_text = (
        f"🚨 INCIDENT DETECTED: {error_log.strip()[:120]} | "
        f"⚡ ACTION TAKEN: {decision}"
    )

    return {
        "text": fallback_text,  # shown in push notifications
        "blocks": [
            {"type": "section", "text": {"type": "mrkdwn", "text": _truncate(incident_text)}},
            {"type": "divider"},
            {"type": "section", "text": {"type": "mrkdwn", "text": _truncate(memory_text)}},
            {"type": "divider"},
            {"type": "section", "text": {"type": "mrkdwn", "text": _truncate(action_text)}},
        ],
    }


def send_slack_alert(payload: dict) -> bool:
    """POST a payload to the Slack incoming webhook.

    Returns:
        True on HTTP 200, False if the webhook is missing or the call fails.
    """
    webhook_url = os.getenv("SLACK_WEBHOOK_URL")
    if not webhook_url:
        logger.warning("SLACK_WEBHOOK_URL not set - printing alert to console instead.")
        print("\n----- SLACK ALERT (console fallback) -----")
        for block in payload.get("blocks", []):
            if block.get("type") == "section":
                print(block["text"]["text"])
                print()
        print("------------------------------------------\n")
        return False

    try:
        response = requests.post(webhook_url, json=payload, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        logger.info("Slack alert delivered.")
        return True
    except requests.RequestException as exc:
        logger.error("Failed to deliver Slack alert: %s", exc)
        return False


def send_incident_alert(
    error_log: str,
    recall: dict,
    decision: str,
    root_cause: str,
    action_detail: str,
    overridden: bool = False,
    confidence: Optional[float] = None,
) -> bool:
    """Build and send the full three-section incident alert to Slack."""
    payload = build_slack_payload(
        error_log=error_log,
        recall=recall,
        decision=decision,
        root_cause=root_cause,
        action_detail=action_detail,
        overridden=overridden,
        confidence=confidence,
    )
    return send_slack_alert(payload)