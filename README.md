\# 🚨 OpsRelay AI



> \*\*Autonomous, Memory-Aware SRE Incident Triage Engine\*\*



\[!\[Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

\[!\[Powered By: Gemini](https://img.shields.io/badge/LLM-Gemini\_Flash-orange.svg)](https://aistudio.google.com/)

\[!\[Memory: Vectorize Hindsight](https://img.shields.io/badge/Memory-Vectorize\_Hindsight-purple.svg)](https://vectorize.io/)



OpsRelay AI is an autonomous incident remediation engine built to eliminate \*\*"flapping" rollbacks\*\*. By pairing Gemini reasoning with Vectorize Hindsight's persistent memory (`retain` and `recall`), OpsRelay AI checks historical post-mortems before taking operational action—blocking automated rollbacks whenever database lock or schema migration risks are detected.



\---



\## 📌 Features



\- \*\*Contextual Incident Recall (`recall`)\*\*: Queries persistent incident memory before triggering automated deployment actions.

\- \*\*Autonomous Safety Overrides\*\*: Automatically halts automated rollbacks when historical memory indicates risk, escalating directly to `MANUAL\_TRIAGE`.

\- \*\*Continuous Post-Mortem Retention (`retain`)\*\*: Learns from resolved incidents in real time to avoid repeating operational failures.

\- \*\*Dual-Layer Fallback Architecture\*\*: Includes local memory fallback and deterministic heuristic decision checks when external APIs or cloud services are offline.

\- \*\*FastAPI Webhooks \& Alerting\*\*: Native FastAPI integration for log ingestion and automated Slack alerts.



\---



\## 🛠️ Tech Stack



\- \*\*Language \& Framework\*\*: Python 3.10+, FastAPI, Uvicorn

\- \*\*AI \& Reasoning Engine\*\*: Gemini 2.5 Flash

\- \*\*Memory Engine\*\*: Vectorize Hindsight API (`bank: sre\_incidents`)

\- \*\*CI/CD Automation\*\*: GitHub Actions Workflows



\---



\## 🚀 Quickstart



\### 1. Clone \& Install Dependencies

```bash

git clone \[https://github.com/renuka-811y/ops-relay-ai.git](https://github.com/renuka-811y/ops-relay-ai.git)

cd ops-relay-ai

python -m venv venv

venv\\Scripts\\activate

pip install -r requirements.txt

