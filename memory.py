import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional
from dotenv import load_dotenv

try:
    from hindsight import HindsightClient
    HINDSIGHT_AVAILABLE = True
except ImportError:
    HINDSIGHT_AVAILABLE = False

load_dotenv()

logger = logging.getLogger("opsrelay.memory")

BANK_ID = os.getenv("HINDSIGHT_BANK_ID", "sre_incidents")
DEFAULT_BASE_URL = "https://api.hindsight.vectorize.io"

ROLLBACK_RISK_TERMS = (
    "database lock",
    "db lock",
    "table lock",
    "lock timeout",
    "migration in progress",
    "schema-migration",
)

# Local memory store for testing/demo fallback
_local_memory_bank = []


def get_client():
    if not HINDSIGHT_AVAILABLE:
        logger.warning("Hindsight SDK package not installed (`pip install hindsight-api`).")
        return None
    
    api_key = os.getenv("HINDSIGHT_API_KEY")
    if not api_key or api_key in ("demo_key", "hsk_609389209fb6569ed04f45892edc2222_6f5b66d4d3cbea34"):
        logger.warning("No valid HINDSIGHT_API_KEY found in environment variables.")
        return None
        
    try:
        base_url = os.getenv("HINDSIGHT_BASE_URL", DEFAULT_BASE_URL)
        return HindsightClient(api_key=api_key, base_url=base_url)
    except Exception as e:
        logger.warning(f"Failed to initialize Hindsight client: {e}")
        return None


def recall_past_incidents(error_log: str, *args, **kwargs) -> dict:
    """Queries Hindsight memory to check if this error pattern occurred previously."""
    client = get_client()
    
    if client:
        try:
            results = client.recall(
                bank_id=BANK_ID,
                query=f"Incident error and fix: {error_log}"
            )
            
            memories_list = getattr(results, "memories", results) if results else []
            has_records = bool(memories_list)
            
            extracted_text = ""
            if isinstance(memories_list, list):
                extracted_text = " | ".join([
                    m.get("content", str(m)) if isinstance(m, dict) else str(m) 
                    for m in memories_list
                ])
            else:
                extracted_text = str(results)

            has_risk = any(term in extracted_text.lower() for term in ROLLBACK_RISK_TERMS)
            
            summary_text = (
                extracted_text if has_records 
                else "No matching past incidents found in Hindsight memory."
            )
            
            return {
                "available": True,
                "memories": memories_list,
                "summary": summary_text,
                "rollback_risk": has_risk,
                "risk": has_risk,
                "record_count": len(memories_list) if isinstance(memories_list, list) else 1
            }
        except Exception as e:
            logger.warning(f"Hindsight cloud recall failed: {e}")

    has_risk = any(
        term in error_log.lower() or term in str(_local_memory_bank).lower() 
        for term in ROLLBACK_RISK_TERMS
    )
    
    has_local_data = len(_local_memory_bank) > 0
    summary_text = (
        " | ".join(_local_memory_bank[-3:]) if has_local_data 
        else "No prior incident records found."
    )
    
    return {
        "available": has_local_data,
        "memories": _local_memory_bank,
        "summary": summary_text,
        "rollback_risk": has_risk,
        "risk": has_risk,
        "record_count": len(_local_memory_bank)
    }


def recall_incident_learning(log_trace: str) -> str:
    """
    Bridge function for sre_agent.py.
    Queries Hindsight memory and returns a plain string context.
    """
    result = recall_past_incidents(log_trace)
    return result.get("summary", "No prior incident records found.")


def retain_incident_learning(error_log: str, resolution: str = "", action: str = "", root_cause: str = "", **kwargs) -> bool:
    """Saves new post-mortem insights into Hindsight memory."""
    client = get_client()
    final_action = action or resolution or "MANUAL_TRIAGE"
    record = f"Timestamp: {datetime.now(timezone.utc).isoformat()} | Error: {error_log} | Action: {final_action} | Cause: {root_cause}"
    
    if client:
        try:
            client.retain(bank_id=BANK_ID, content=record)
            logger.info("Successfully retained memory in Hindsight cloud.")
            return True
        except Exception as e:
            logger.warning(f"Hindsight retain failed: {e}")

    _local_memory_bank.append(record)
    logger.info("Retained memory in local fallback store.")
    return True