@echo off
REM Launch all five FastAPI services locally (RUN_OFFLINE mode, sqlite + StubLLM).
set RUN_OFFLINE=true
set DATABASE_URL=sqlite+aiosqlite:///./aipr.db
set GITHUB_WEBHOOK_SECRET=dev-secret
set PYTHONPATH=%~dp0

start "gateway" uvicorn gateway.main:app --port 8000
start "webhook" uvicorn webhook.main:app --port 8001
start "orchestrator" uvicorn orchestrator.main:app --port 8002
start "reviewer" uvicorn reviewer.main:app --port 8003
start "learner" uvicorn learner.main:app --port 8004
echo All services starting. Close this window to stop.
pause
