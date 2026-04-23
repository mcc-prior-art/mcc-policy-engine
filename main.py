#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional

import redis.asyncio as redis
from fastapi import FastAPI, Header, HTTPException, Request, Response, Depends
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import Counter, Histogram, generate_latest
from pydantic import BaseModel
from pydantic_settings import BaseSettings
from starlette.middleware.base import BaseHTTPMiddleware

# ---------- Settings ----------
class Settings(BaseSettings):
    hmac_secret: str = "change-me"
    redis_url: str = "redis://localhost:6379"
    rate_limit_per_min: int = 60

settings = Settings()

# ---------- Logging ----------
logging.basicConfig(level="INFO")
logger = logging.getLogger("mcc")

# ---------- Metrics ----------
DECISIONS = Counter("mcc_decisions_total", "decisions", ["decision"])
LATENCY = Histogram("mcc_latency_seconds", "latency")

# ---------- Redis ----------
redis_client: Optional[redis.Redis] = None

async def get_redis():
    global redis_client
    if redis_client is None:
        redis_client = redis.from_url(settings.redis_url, decode_responses=True)
    return redis_client

# ---------- Models ----------
class Decision(str, Enum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    ESCALATE = "ESCALATE"

class EvaluateRequest(BaseModel):
    session_id: str
    intent: str
    args: Dict[str, Any]
    idempotency_key: Optional[str] = None

class EvaluateResponse(BaseModel):
    decision: Decision
    trace_id: str
    reason: str

# ---------- Auth ----------
def get_tenant(x_api_key: str = Header(...)):
    if x_api_key != "demo-key":
        raise HTTPException(status_code=401, detail="INVALID_API_KEY")
    return {"tenant": "demo"}

# ---------- MCC Core ----------
class MCC:
    def __init__(self):
        self.prev_hash = "GENESIS"
        self._lock = asyncio.Lock()
        self._idem_cache: Dict[str, EvaluateResponse] = {}

    def _trace(self, session_id: str) -> str:
        return hashlib.sha256((session_id + str(uuid.uuid4())).encode()).hexdigest()[:12]

    async def evaluate(self, tenant: str, req: EvaluateRequest) -> EvaluateResponse:
        trace_id = self._trace(req.session_id)

        # ---------- Idempotency ----------
        if req.idempotency_key:
            key = f"{tenant}:{req.idempotency_key}"
            if key in self._idem_cache:
                return self._idem_cache[key]

        # ---------- Decision Logic ----------
        decision = Decision.DENY
        reason = "deny-by-default"

        if req.intent == "send_payment":
            amount = req.args.get("amount", 0)

            if amount <= 5000:
                decision = Decision.ALLOW
                reason = "within safe limit"

            elif amount <= 10000:
                decision = Decision.ESCALATE
                reason = "requires human approval"

            else:
                decision = Decision.DENY
                reason = "amount exceeds policy limit"

        elif req.intent == "delete_user":
            decision = Decision.ESCALATE
            reason = "high-risk action requires approval"

        # ---------- Result ----------
        result = EvaluateResponse(
            decision=decision,
            trace_id=trace_id,
            reason=reason
        )

        # ---------- Idempotency store ----------
        if req.idempotency_key:
            key = f"{tenant}:{req.idempotency_key}"
            self._idem_cache[key] = result

        DECISIONS.labels(decision=decision.value).inc()

        logger.info(
            f"{decision.value} | intent={req.intent} | trace={trace_id}"
        )

        return result


mcc = MCC()

# ---------- FastAPI ----------
app = FastAPI(
    title="MCC Policy Engine",
    version="1.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- Signature Middleware ----------
class SignMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        if request.url.path == "/evaluate":
            body = b""
            async for chunk in response.body_iterator:
                body += chunk

            sig = hmac.new(
                settings.hmac_secret.encode(),
                body,
                hashlib.sha256
            ).hexdigest()

            return Response(
                content=body,
                headers={"X-MCC-Signature": sig},
                media_type="application/json"
            )

        return response

app.add_middleware(SignMiddleware)

# ---------- API ----------
@app.post("/evaluate", response_model=EvaluateResponse)
async def evaluate(req: EvaluateRequest, tenant_ctx: Dict = Depends(get_tenant)):
    with LATENCY.time():
        return await mcc.evaluate(tenant_ctx["tenant"], req)

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.get("/metrics")
async def metrics():
    return Response(generate_latest(), media_type="text/plain")

# ---------- Run ----------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
