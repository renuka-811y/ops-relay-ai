import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict

# IMPORTANT: Load environment variables BEFORE importing agent submodules
from dotenv import load_dotenv

load_dotenv()

# Setup module search paths for agent sub-package
AGENT_DIR = os.path.join(os.path.dirname(__file__), "agent")
if AGENT_DIR not in sys.path:
    sys.path.insert(0, AGENT_DIR)

from fastapi import Body, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

try:
    from sre_agent import run_sre_agent
    from memory import retain_incident_learning
except ImportError:
    from agent.sre_agent import run_sre_agent
    from agent.memory import retain_incident_learning

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("opsrelay.app")

app = FastAPI(
    title="OpsRelay Target Service & AI SRE War Room",
    description="A microservice integrated with Hindsight Memory & Groq LLM for automated incident triage.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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


class AnalyzeLogRequest(BaseModel):
    log_trace: str = Field(
        ..., example="2025-01-15 CRITICAL [db] Connection pool timeout"
    )


class SeedMemoryRequest(BaseModel):
    error_log: str = Field(
        ..., example="Migration #042 DB Lock on orders table"
    )
    root_cause: str = Field(
        ..., example="Schema migration lock during active transactions"
    )
    action: str = Field(..., example="MANUAL_TRIAGE")


class PostMortemRequest(BaseModel):
    incident_type: str = Field(..., example="DATABASE_LOCK")
    root_cause: str = Field(
        ..., example="Migration #042 held AccessExclusive lock"
    )
    decision: str = Field(..., example="MANUAL_TRIAGE")


def _safe_run_agent(log_trace: str, label: str) -> Dict[str, Any]:
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
            "remediation_command": "kubectl get events -n prod",
            "memory_context": "Memory query bypassed due to internal exception.",
            "slack_notification_sent": False,
        }


@app.get("/", tags=["Health"])
@app.get("/Healthy", tags=["Health"])
def healthy() -> Dict[str, Any]:
    return {
        "status": "healthy",
        "service": "OpsRelay Target Service",
        "memory_engine": "Hindsight Vectorize",
        "llm_engine": "Groq Llama-3.3-70B",
    }


@app.get("/dashboard", response_class=HTMLResponse, tags=["UI Dashboard"])
async def serve_dashboard():
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>OpsRelay AI - Live SRE War Room</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <style>body { background-color: #0f172a; color: #f8fafc; font-family: monospace; }</style>
    </head>
    <body class="p-8 max-w-5xl mx-auto">
        <header class="border-b border-slate-700 pb-4 mb-6">
            <h1 class="text-3xl font-bold text-sky-400">🚨 OpsRelay AI - Autonomous SRE War Room</h1>
            <p class="text-slate-400 mt-1">Real-time Incident Triage Engine | Groq Llama-3.3 + Hindsight Memory</p>
        </header>

        <div class="grid grid-cols-2 gap-4 mb-6">
            <button onclick="triggerSim('/trigger-crash')" class="bg-red-600 hover:bg-red-700 text-white font-bold py-3 px-4 rounded shadow transition">
                💥 Simulate DB Lock Crash
            </button>
            <button onclick="triggerSim('/trigger-memory-leak')" class="bg-emerald-600 hover:bg-emerald-700 text-white font-bold py-3 px-4 rounded shadow transition">
                ⚡ Simulate OOM Memory Leak
            </button>
        </div>

        <div id="output-box" class="bg-slate-900 border border-slate-800 rounded-lg p-6 shadow-xl hidden">
            <div class="flex justify-between items-center mb-4">
                <span id="badge-decision" class="px-3 py-1 text-sm font-bold rounded"></span>
                <span id="badge-confidence" class="text-xs text-slate-400"></span>
            </div>
            <div class="mb-4">
                <h3 class="text-xs text-slate-500 uppercase tracking-wider mb-1">Incident Classification</h3>
                <p id="res-type" class="text-lg font-bold text-slate-200"></p>
            </div>
            <div class="mb-4">
                <h3 class="text-xs text-slate-500 uppercase tracking-wider mb-1">Root Cause Analysis</h3>
                <p id="res-rootcause" class="text-sm text-slate-300 bg-slate-950 p-3 rounded border border-slate-800"></p>
            </div>
            <div class="mb-4">
                <h3 class="text-xs text-slate-500 uppercase tracking-wider mb-1">Executable Runbook Command</h3>
                <code id="res-cmd" class="text-sm text-sky-300 bg-slate-950 p-3 rounded border border-slate-800 block"></code>
            </div>
            <div>
                <h3 class="text-xs text-slate-500 uppercase tracking-wider mb-1">Hindsight Memory Context</h3>
                <pre id="res-memory" class="text-xs text-slate-400 bg-slate-950 p-3 rounded border border-slate-800 whitespace-pre-wrap"></pre>
            </div>
        </div>

        <script>
            async function triggerSim(endpoint) {
                const box = document.getElementById('output-box');
                box.classList.remove('hidden');
                document.getElementById('res-type').innerText = "Analyzing log trace via Groq LLM...";
                document.getElementById('res-rootcause').innerText = "Querying Hindsight vector memory...";
                document.getElementById('res-cmd').innerText = "...";
                document.getElementById('res-memory').innerText = "...";
                
                const res = await fetch(endpoint);
                const data = await res.json();
                const result = data.triage_result;

                const decisionBadge = document.getElementById('badge-decision');
                if (result.decision === 'MANUAL_TRIAGE') {
                    decisionBadge.className = "px-3 py-1 text-xs font-bold rounded bg-red-950 text-red-400 border border-red-800";
                    decisionBadge.innerText = "⛔ ACTION REQUIRED: MANUAL_TRIAGE";
                } else {
                    decisionBadge.className = "px-3 py-1 text-xs font-bold rounded bg-emerald-950 text-emerald-400 border border-emerald-800";
                    decisionBadge.innerText = "✅ AUTOMATED ACTION: SAFE_ROLLBACK";
                }

                document.getElementById('badge-confidence').innerText = "Confidence: " + result.confidence;
                document.getElementById('res-type').innerText = result.incident_type;
                document.getElementById('res-rootcause').innerText = result.root_cause;
                document.getElementById('res-cmd').innerText = result.remediation_command;
                document.getElementById('res-memory').innerText = result.memory_context;
            }
        </script>
    </body>
    </html>
    """


@app.get("/trigger-crash", tags=["Simulations"])
def trigger_crash() -> Dict[str, Any]:
    logger.error("Simulating DB connection pool exhaustion (migration #042 lock)")
    return {"triage_result": _safe_run_agent(DB_CRASH_LOG_TRACE, "trigger-crash")}


@app.get("/trigger-memory-leak", tags=["Simulations"])
def trigger_memory_leak() -> Dict[str, Any]:
    logger.error("Simulating Java heap OOM (unbounded cache growth)")
    return {
        "triage_result": _safe_run_agent(
            MEMORY_LEAK_LOG_TRACE, "trigger-memory-leak"
        )
    }


@app.post("/analyze-custom-log", tags=["Core Agent"])
def analyze_custom_log(request: AnalyzeLogRequest) -> Dict[str, Any]:
    return {
        "triage_result": _safe_run_agent(
            request.log_trace, "custom-log-analysis"
        )
    }


@app.post("/seed-hindsight-memory", tags=["Demo Tools"])
def seed_hindsight_memory(request: SeedMemoryRequest) -> Dict[str, Any]:
    success = retain_incident_learning(
        error_log=request.error_log,
        root_cause=request.root_cause,
        action=request.action,
    )
    payload = (
        request.model_dump()
        if hasattr(request, "model_dump")
        else request.dict()
    )
    return {
        "status": "MEMORY_SEEDED" if success else "SEED_FAILED",
        "message": "Successfully stored historical incident in Hindsight Cloud.",
        "record": payload,
    }


@app.post("/generate-postmortem", tags=["SRE Tools"])
def generate_postmortem(request: PostMortemRequest) -> Dict[str, Any]:
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    markdown_report = f"""# 📋 Incident Post-Mortem Report

**Timestamp:** `{now_str}`
**Incident Classification:** `{request.incident_type}`
**Triage Decision:** `{request.decision}`

## 1. Executive Summary
OpsRelay AI intercepted a production telemetry alert. Safety guardrails were evaluated against historical incident memories, and the system enforced `{request.decision}`.

## 2. Root Cause Analysis
{request.root_cause}

## 3. Post-Incident Action Items
- [ ] Review database migration lock timeouts prior to future deployments.
- [ ] Verify heap allocation limits in production container specs.
- [ ] Update Hindsight Memory bank with verified resolution steps.
"""
    return {"status": "SUCCESS", "post_mortem_md": markdown_report}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)