import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional
from dotenv import load_dotenv

# Try importing official Hindsight SDK; fall back gracefully if needed
try:
    from hindsight_client import Hindsight
    HINDSIGHT_AVAILABLE = True
except ImportError:
    HINDSIGHT_AVAILABLE = False

load_dotenv()

logger = logging.getLogger("opsrelay.memory")

BANK_ID = "sre_incidents"
DEFAULT_BASE_URL = "https://api.hindsight.vectorize.io"
MAX_MEMORIES = 8

ROLLBACK_RISK_TERMS = (
    "database lock",
    "db lock",
    "table lock",
    "lock timeout",
    "migration in progress",
)

# Global memory fallback for local offline testing
_local_memory_bank = []

def get_client():
    if not HINDSIGHT_AVAILABLE:
        return None
    api_key = os.getenv("HINDSIGHT_API_KEY")
    if not api_key or api_key == "demo_key":
        return None
    try:
        return Hindsight(
            base_url=DEFAULT_BASE_URL,
            api_key=api_key
            )
    except Exception as e:
        logger.warning(f"Failed to initialize Hindsight client: {e}")
        return None

def recall_past_incidents(error_log: str, *args, **kwargs) -> dict:
    """Queries Hindsight memory to check if this error pattern occurred previously."""
    client = get_client()
    if client:
        try:
            results = client.recall(
                query=f"How did we handle this error: {error_log}?",
                bank_id=BANK_ID
            )
            has_risk = any(term in str(results).lower() for term in ROLLBACK_RISK_TERMS)
            summary_text = str(results) if results else "No previous matching incidents found."
            return {
                "available": True,
                "memories": results,
                "summary": summary_text,
                "rollback_risk": has_risk,
                "risk": has_risk
            }
        except Exception as e:
            logger.warning(f"Hindsight recall failed: {e}")

    # Fallback to local memory store if API key/client is unavailable
    has_risk = any(term in error_log.lower() or term in str(_local_memory_bank).lower() for term in ROLLBACK_RISK_TERMS)
    summary_text = f"Local memory bank contains {len(_local_memory_bank)} past records." if _local_memory_bank else "No prior memory records found."
    return {
        "available": False,
        "memories": _local_memory_bank,
        "summary": summary_text,
        "rollback_risk": has_risk,
        "risk": has_risk
    }

def retain_incident_learning(error_log: str, resolution: str = "", action: str = "", root_cause: str = "", **kwargs) -> bool:
    """Saves new post-mortem insights into Hindsight memory."""
    client = get_client()
    final_action = action or resolution or "MANUAL_TRIAGE"
    record = f"Timestamp: {datetime.now(timezone.utc).isoformat()} | Error: {error_log} | Action: {final_action} | Cause: {root_cause}"
    
    if client:
        try:
            client.retain(content=record, bank_id=BANK_ID)
            logger.info("Successfully retained memory in Hindsight cloud.")
            return True
        except Exception as e:
            logger.warning(f"Hindsight retain failed: {e}")

    _local_memory_bank.append(record)
    logger.info("Retained memory in local fallback store.")
    return True