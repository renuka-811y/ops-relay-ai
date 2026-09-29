"""OpsRelay Target Service: A fragile service used to exercise the OpsRelay AI SRE Agent."""

import logging
from fastapi import FastAPI, Body
from pydantic import BaseModel, Field
from agent.sre_agent import run_sre_agent
from agent.memory import retain_incident_learning

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("opsrelay.app")

app = FastAPI(
    title="OpsRelay Target Service & AI SRE War Room",
    description="A fragile microservice integrated with Hindsight Memory & Groq LLM for automated incident triage.",
    version="1.0.0"
)

# --- Sample Log Traces for Demo Scenarios ---

DB_CRASH_LOG_TRACE = """\
2025-01-15 03:42:11,204 ERROR [db.pool] QueuePool limit of size 20 overflow 10 reached, connection timed out, timeout 30.00
sqlalchemy.exc.TimeoutError: QueuePool limit of size 20 overflow 10 reached, connection timed out, timeout 30.00
2025-01-15 03:42:11,207 ERROR [migrations] Migration #042 (add_index_orders_customer_id) is holding an ACCESS EXCLUSIVE lock on table "orders"
2025-01-15 03:42:11,209 WARN  [db.pool] Active connections: 30/30, waiting requests: 148
2025-01-15 03:42:11,215 CRITICAL [api] Database Connection Pool Exhaustion: all connections blocked by DB lock during migration #042
2025-01-15 03:42:11,216 CRITICAL [api] Health check failing: /orders, /checkout returning 503
"""

MEMORY_LEAK_LOG_TRACE = """\
2025-01-15 04:10:52,871 WARN  [cache.ProductCache] Cache size: 4,812 collections entries, no eviction policy configured (unbounded growth)
2025-01-15 04:10:53,002 WARN  [jvm.gc] Full GC (Allocation Failure) 3981M->3979M(4096M), 8.42 secs
2025-01-15 04:10:58,340 ERROR [jvm.gc] GC overhead limit exceeded, heap usage 99.8%
Exception in thread "http-nio-8080-exec-17" java.lang.OutOfMemoryError: Java heap space
    at java.base/java.util.HashMap.resize(HashMap.java:700)
    at com.opsrelay.cache.ProductCache.put(ProductCache.java:88)
2025-01-15 04:10:58,351 CRITICAL [jvm] Out-Of-Memory: Java Heap Space, process terminated by supervisor
"""

# --- Pydantic Request Models ---

class AnalyzeLogRequest(BaseModel):
    log_trace: str = Field(..., example="2025-01-15 CRITICAL [db] Connection pool timeout")

class SeedMemoryRequest(BaseModel):
    error_log: str = Field(..., example="Migration #042 DB Lock on orders table")
    root_cause: str = Field(..., example="Schema migration lock during active transactions")
    action: str = Field(..., example="MANUAL_TRIAGE")


def _safe_run_agent(log_trace: str, label: str) -> dict:
    """Invokes the SRE agent with global exception catching to ensure the API never returns 500."""
    try:
        return run_sre_agent(log_trace)
    except Exception as exc:
        logger.exception("Unexpected agent failure on %s: %s", label, exc)
        return {
            "status": "ERROR_FALLBACK",
            "incident_type": "UNKNOWN_INCIDENT",
            "decision": "MANUAL_TRIAGE",
            "root_cause": f"Agent internal error: {str(exc)}",
            "confidence": "0%",
            "memory_context": "Memory query bypassed due to internal exception.",
            "slack_notification_sent": False,
        }


# --- Endpoints ---

@app.get("/", tags=["Health"])
@app.get("/Healthy", tags=["Health"])
def healthy() -> dict:
    return {"status": "healthy", "service": "OpsRelay Target Service", "memory_engine": "Hindsight Vectorize"}


@app.get("/trigger-crash", tags=["Simulations"])
def trigger_crash() -> dict:
    """Simulates a DB lock failure (Triggers MANUAL_TRIAGE due to DB migration risk)."""
    logger.error("Simulating DB connection pool exhaustion (migration #042 lock)")
    return _safe_run_agent(DB_CRASH_LOG_TRACE, "trigger-crash")


@app.get("/trigger-memory-leak", tags=["Simulations"])
def trigger_memory_leak() -> dict:
    """Simulates a Java Heap Out-Of-Memory failure (Triggers SAFE_ROLLBACK)."""
    logger.error("Simulating Java heap OOM (unbounded cache growth)")
    return _safe_run_agent(MEMORY_LEAK_LOG_TRACE, "trigger-memory-leak")


@app.post("/analyze-custom-log", tags=["Core Agent"])
def analyze_custom_log(request: AnalyzeLogRequest) -> dict:
    """Allows custom error logs to be analyzed by the OpsRelay Agent & Hindsight Memory."""
    return _safe_run_agent(request.log_trace, "custom-log-analysis")


@app.post("/seed-hindsight-memory", tags=["Demo Tools"])
def seed_hindsight_memory(request: SeedMemoryRequest) -> dict:
    """Pre-populates Hindsight memory with historical post-mortems for video demos."""
    success = retain_incident_learning(
        error_log=request.error_log,
        root_cause=request.root_cause,
        action=request.action
    )
    return {
        "status": "MEMORY_SEEDED" if success else "SEED_FAILED",
        "message": "Successfully stored historical incident in Hindsight Cloud.",
        "record": request.dict()
    }