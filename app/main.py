"""
app/main.py - Target web service for OpsRelay AI.

This FastAPI app plays the role of the "production application" that OpsRelay
monitors. It exposes a healthy endpoint plus two endpoints that deliberately
fail so the SRE agent has realistic incident logs to triage.

Run locally:
    uvicorn app.main:app --reload --port 8000
"""

from __future__ import annotations

import logging

import uvicorn
from fastapi import FastAPI, HTTPException

logger = logging.getLogger("opsrelay.app")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

# --------------------------------------------------------------------------- #
# Canonical incident messages.
# agent/sre_agent.py imports these so the CLI simulator and the live service
# always emit byte-identical error logs.
# --------------------------------------------------------------------------- #
CRASH_ERROR_MESSAGE = (
    "CRITICAL: Database connection pool exhausted - DB lock during Commit #a1b2c3"
)
MEMORY_LEAK_ERROR_MESSAGE = (
    "CRITICAL: OOMKilled - container exceeded memory limit (limit=512Mi, rss=731Mi) "
    "after unbounded cache growth in request handler, Commit #d4e5f6"
)

app = FastAPI(
    title="OpsRelay Target Service",
    description="A deliberately fragile service used to exercise the OpsRelay AI incident agent.",
    version="1.0.0",
)


@app.get("/")
def healthy() -> dict:
    """Health endpoint - always returns a healthy response."""
    return {"status": "healthy", "service": "opsrelay-target-service", "version": "1.0.0"}


@app.get("/trigger-crash")
def trigger_crash() -> dict:
    """Simulates a database connection-pool exhaustion caused by a DB lock."""
    logger.error(CRASH_ERROR_MESSAGE)
    raise HTTPException(status_code=500, detail=CRASH_ERROR_MESSAGE)


@app.get("/trigger-memory-leak")
def trigger_memory_leak() -> dict:
    """Simulates an out-of-memory crash caused by a memory leak."""
    logger.error(MEMORY_LEAK_ERROR_MESSAGE)
    raise HTTPException(status_code=500, detail=MEMORY_LEAK_ERROR_MESSAGE)


if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=False)
