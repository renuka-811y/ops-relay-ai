# OpsRelay AI

> An incident-response agent that combines LLM reasoning, persistent incident memory, and deterministic safety guardrails to prevent unsafe automated remediation.

OpsRelay AI is an experimental SRE/incident-response agent designed around a simple idea:

**An AI agent should not treat every incident as a brand-new problem.**

When an incident occurs, OpsRelay analyzes the failure, recalls relevant history from **Hindsight agent memory**, evaluates the risk of the proposed remediation, and either allows the action or escalates to manual triage.

The important part is that memory is not just supplied as extra context to the model. It can directly influence the safety boundary around an automated action.

---

## Why OpsRelay?

Traditional incident automation often looks like:

```text
Incident
   ↓
LLM analyzes logs
   ↓
LLM chooses remediation
   ↓
Execute remediation
```

The problem is that the model may not know that a similar remediation caused another failure in the past.

OpsRelay adds persistent memory and a deterministic policy layer:

```text
Incident
   ↓
Recall similar incidents from Hindsight
   ↓
LLM / heuristic analysis
   ↓
Safety policy checks the proposed action
   ↓
┌─────────────────────────────┐
│ Safe → automated action     │
│ Risky → MANUAL_TRIAGE       │
└─────────────────────────────┘
   ↓
Retain the incident outcome
```

This creates a feedback loop where previous incidents can affect future remediation decisions.

---

## Key Idea

The core design principle is:

> **Memory informs the decision; deterministic policy constrains the action.**

Hindsight provides persistent incident memory.

The agent recalls previous incidents and converts relevant history into a machine-readable signal such as:

```text
rollback_risk = true
```

The final action is still constrained by deterministic code rather than relying entirely on an LLM response.

For example:

```python
decision = analysis.decision.strip().upper()

if decision not in (DECISION_ROLLBACK, DECISION_MANUAL_TRIAGE):
    decision = DECISION_MANUAL_TRIAGE

if decision == DECISION_ROLLBACK and recall["rollback_risk"]:
    decision = DECISION_MANUAL_TRIAGE
    overridden = True
```

This means a model cannot simply recommend a rollback and bypass the safety boundary when previous incident memory identifies rollback risk.

---

## Architecture

```text
                         ┌─────────────────────┐
                         │     Target App      │
                         │      FastAPI         │
                         └──────────┬──────────┘
                                    │
                              Incident/Error
                                    │
                                    ▼
                         ┌─────────────────────┐
                         │    OpsRelay Agent   │
                         │   sre_agent.py      │
                         └──────────┬──────────┘
                                    │
                         ┌──────────┴──────────┐
                         │                     │
                         ▼                     ▼
              ┌──────────────────┐   ┌──────────────────┐
              │ Hindsight Memory │   │   LLM Analysis   │
              │    recall()      │   │  Gemini / fallback│
              └────────┬─────────┘   └─────────┬────────┘
                       │                       │
                       └──────────┬────────────┘
                                  ▼
                       ┌─────────────────────┐
                       │ Deterministic       │
                       │ Safety Policy       │
                       └──────────┬──────────┘
                                  │
                       ┌──────────┴──────────┐
                       ▼                     ▼
                ┌─────────────┐       ┌───────────────┐
                │  Rollback   │       │ Manual Triage │
                └─────────────┘       └───────────────┘
                       │                     │
                       └──────────┬──────────┘
                                  ▼
                         ┌──────────────────┐
                         │ Hindsight retain │
                         └──────────────────┘
```

---

## Project Structure

```text
ops-relay-ai/
│
├── agent/
│   ├── __init__.py
│   ├── memory.py
│   ├── notifications.py
│   └── sre_agent.py
│
├── app/
│   ├── __init__.py
│   └── main.py
│
├── article-assets/
│   ├── opsrelay-architecture.png
│   ├── hindsight-recall-retain.png
│   ├── opsrelay-incident-flow.png
│   └── opsrelay-incident-report.png
│
├── article.md
├── .gitignore
└── README.md
```

---

## Components

### `app/main.py`

A small FastAPI service used as the target application.

It provides endpoints for triggering simulated failures, including:

```text
/
 /trigger-crash
 /trigger-memory-leak
```

The crash scenario generates an incident similar to:

```text
CRITICAL: Database connection pool exhausted -
DB lock during Commit #a1b2c3
```

This gives the agent a realistic incident signal to analyze.

---

### `agent/sre_agent.py`

The main incident-response orchestrator.

It coordinates:

1. Triggering / observing the incident
2. Extracting the error information
3. Recalling relevant historical incidents
4. Asking the LLM for analysis when available
5. Applying deterministic safety checks
6. Selecting remediation
7. Sending an alert
8. Retaining the incident outcome in memory

---

### `agent/memory.py`

The memory layer for OpsRelay.

It integrates with **Hindsight agent memory** and provides two important operations:

```text
recall()
retain()
```

`recall()` searches previous incident history.

`retain()` stores the current incident and its outcome so that future incidents can benefit from it.

The implementation also contains a local fallback memory mechanism when Hindsight is unavailable.

---

### `agent/notifications.py`

Builds incident notifications and provides a console fallback when a Slack webhook is not configured.

---

## How Hindsight Changes the Behavior

Without persistent memory, the system can see:

```text
Database connection pool exhausted
DB lock during commit
```

and may conclude:

```text
Rollback the suspect deployment.
```

With Hindsight, the agent can recall that similar incidents involved:

```text
database locks
schema migrations
rollback-related problems
```

The historical information becomes a risk signal:

```text
rollback_risk = true
```

The safety policy can then change the final action:

```text
ROLLBACK
   ↓
Historical risk detected
   ↓
MANUAL_TRIAGE
```

This is the important distinction:

**The memory is capable of changing what the system does next.**

---

## Incident Walkthrough

The demonstrated scenario used:

```text
CRITICAL: Database connection pool exhausted -
DB lock during Commit #a1b2c3
```

OpsRelay queried Hindsight for related incident history.

Hindsight successfully returned relevant memories involving database locks and migration-related risk.

The system detected:

```text
rollback_risk = true
```

During this particular captured run, Gemini returned a temporary:

```text
HTTP 503 Service Unavailable
```

Instead of failing completely, OpsRelay used its heuristic fallback.

The fallback saw the rollback-risk signal from memory and selected:

```text
MANUAL_TRIAGE
```

The resulting report included:

```text
decision: MANUAL_TRIAGE
memory_available: true
rollback_risk_from_memory: true
memory_retained: true
```

Importantly, `overridden_by_memory` was:

```text
false
```

because Gemini did **not** successfully return a rollback recommendation in this run. The heuristic fallback selected manual triage directly.

The incident outcome was then retained in Hindsight.

---

## Safety Boundary

OpsRelay does not allow the LLM to directly control remediation.

Instead, the architecture separates:

```text
Reasoning
    ↓
Policy
    ↓
Action
```

The LLM can propose a decision.

The deterministic policy validates that decision.

If the proposed action conflicts with a known historical risk, the system can block automated remediation.

For example:

```text
LLM recommendation:
ROLLBACK

Historical memory:
Previous rollback caused database-lock / migration problems

Policy:
BLOCK ROLLBACK

Final action:
MANUAL_TRIAGE
```

This is intentionally conservative.

---

## Environment Variables

Create a `.env` file locally with the credentials required for the integrations you want to use.

Typical variables include:

```env
GEMINI_API_KEY=your_gemini_api_key
GITHUB_TOKEN=your_github_token
GITHUB_REPO=owner/repository
GITHUB_WORKFLOW_FILE=rollback.yml
GITHUB_REF_NAME=main
HINDSIGHT_API_KEY=your_hindsight_api_key
```

A Slack webhook can also be configured for notifications.

**Do not commit `.env` or API keys to GitHub.**

The repository should keep secrets out of source control through `.gitignore` and environment variables.

---

## Installation

Clone the repository:

```bash
git clone https://github.com/renuka-811y/ops-relay-ai.git
cd ops-relay-ai
```

Create a virtual environment:

```bash
python -m venv venv
```

Activate it on Windows:

```bash
venv\Scripts\activate
```

Install the required packages:

```bash
pip install python-dotenv requests pydantic google-genai fastapi uvicorn hindsight-client
```

---

## Running the Target Application

Start the FastAPI service:

```bash
uvicorn app.main:app --reload --port 8000
```

The application will be available at:

```text
http://localhost:8000
```

You can trigger the simulated crash from another terminal:

```text
http://localhost:8000/trigger-crash
```

---

## Running OpsRelay

From the repository root:

```bash
python -m agent.sre_agent --app-url http://localhost:8000 --scenario crash
```

The agent will:

```text
Trigger incident
      ↓
Collect error
      ↓
Recall Hindsight memory
      ↓
Analyze incident
      ↓
Apply safety policy
      ↓
Select action
      ↓
Retain outcome
      ↓
Report result
```

---

## Example Final Report

A captured run produced a report similar to:

```json
{
  "error_log": "CRITICAL: Database connection pool exhausted - DB lock during Commit #a1b2c3",
  "suspect_commit": "a1b2c3",
  "memory_available": true,
  "rollback_risk_from_memory": true,
  "memories_recalled": 3,
  "decision": "MANUAL_TRIAGE",
  "overridden_by_memory": false,
  "confidence": 0.4,
  "slack_alert_sent": false,
  "memory_retained": true
}
```

The exact values can change depending on the available memory, model response, configuration, and incident being tested.

---

## What This Project Demonstrates

OpsRelay explores several practical ideas for AI agents:

* Persistent memory instead of stateless incident handling
* Retrieval of relevant historical experiences
* LLM reasoning combined with deterministic policy
* Safety checks around autonomous actions
* Graceful fallback when an external model is unavailable
* Learning from incident outcomes
* Human escalation when automation becomes risky

The broader idea is simple:

> **An agent becomes more useful when its past experiences can change its next action—but that memory should still operate inside explicit safety boundaries.**

---

## Article

A detailed write-up of the design and incident walkthrough is available in:

```text
article.md
```

The article explains why Hindsight was placed directly in the action path and how the memory signal affected the incident-handling workflow.

---

## Technologies

* Python
* FastAPI
* Google Gemini
* Hindsight Agent Memory
* GitHub Actions / GitHub API
* Requests
* Pydantic
* Uvicorn

---

## Status

This is an experimental incident-response agent demonstrating how **persistent agent memory + LLM reasoning + deterministic guardrails** can be combined for safer automated operations.

It is not intended to replace production SRE processes without additional testing, observability, authentication, authorization, rollback validation, and operational safeguards.
