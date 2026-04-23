#!/usr/bin/env python3
"""
MCC Policy Engine v2.1 – истинный Meta‑Cognitive Control.
Безопасность: история и confidence вычисляются внутри, строгая валидация,
идемпотентность, распределённые компоненты. Production‑grade.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
import uuid
from datetime import datetime, timezone, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import redis.asyncio as redis
import yaml
from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import Counter, Histogram, generate_latest
from pydantic import BaseModel, Field, root_validator, ValidationError
from pydantic_settings import BaseSettings
from starlette.middleware.base import BaseHTTPMiddleware
from watchfiles import awatch

# ---------- Настройки ----------
class Settings(BaseSettings):
    max_intent_length: int = 64
    max_args_bytes: int = 2048
    policy_timeout_sec: float = 0.2
    rate_limit_per_min: int = 60
    block_window_sec: int = 30
    hmac_secret: str = "change-me-in-production"
    redis_url: str = "redis://localhost:6379"
    policy_file: str = "policies.yaml"
    api_keys: Dict[str, Dict] = {
        "demo-key": {
            "tenant": "tenant_demo",
            "scopes": ["payments:write", "users:read", "users:admin"],
        }
    }
    log_level: str = "INFO"
    port: int = 8000
    idempotency_ttl_sec: int = 86400  # 24 часа
    session_history_size: int = 20

    class Config:
        env_prefix = "MCC_"

settings = Settings()

# ---------- Логирование ----------
logging.basicConfig(
    level=settings.log_level,
    format='{"time":"%(asctime)s","level":"%(levelname)s","name":"%(name)s","message":"%(message)s"}',
)
logger = logging.getLogger("mcc")

# ---------- Prometheus метрики ----------
DECISIONS = Counter(
    "mcc_decisions_total",
    "Total decisions by type",
    ["decision", "intent", "tenant"]
)
LATENCY = Histogram(
    "mcc_evaluate_latency_seconds",
    "Evaluation latency",
    ["tenant"]
)

# ---------- Redis ----------
redis_client: Optional[redis.Redis] = None

async def get_redis() -> redis.Redis:
    global redis_client
    if redis_client is None:
        redis_client = redis.from_url(settings.redis_url, encoding="utf-8", decode_responses=True)
    return redis_client

# ---------- Хранилище аудита ----------
class AuditRepository:
    async def append(self, entry: Dict) -> None:
        raise NotImplementedError

class InMemoryAuditRepository(AuditRepository):
    def __init__(self):
        self.entries: List[Dict] = []
        self._lock = asyncio.Lock()

    async def append(self, entry: Dict) -> None:
        async with self._lock:
            self.entries.append(entry)

class RedisAuditRepository(AuditRepository):
    async def append(self, entry: Dict) -> None:
        r = await get_redis()
        await r.xadd("mcc:audit", entry)

audit_repo = RedisAuditRepository() if settings.redis_url.startswith("redis://") else InMemoryAuditRepository()

# ---------- Хранилище истории сессий ----------
class SessionHistoryStore:
    async def append(self, session_id: str, decision_record: Dict) -> None:
        raise NotImplementedError

    async def get_history(self, session_id: str, max_len: int = 20) -> List[Dict]:
        raise NotImplementedError

class InMemorySessionHistory(SessionHistoryStore):
    def __init__(self):
        self.store: Dict[str, List[Dict]] = {}
        self._lock = asyncio.Lock()

    async def append(self, session_id: str, record: Dict) -> None:
        async with self._lock:
            lst = self.store.setdefault(session_id, [])
            lst.append(record)
            if len(lst) > settings.session_history_size:
                self.store[session_id] = lst[-settings.session_history_size:]

    async def get_history(self, session_id: str, max_len: int = 20) -> List[Dict]:
        async with self._lock:
            lst = self.store.get(session_id, [])
            return lst[-max_len:] if lst else []

class RedisSessionHistory(SessionHistoryStore):
    async def append(self, session_id: str, record: Dict) -> None:
        r = await get_redis()
        key = f"session:{session_id}:history"
        await r.rpush(key, json.dumps(record, default=str))
        await r.ltrim(key, -settings.session_history_size, -1)
        await r.expire(key, 86400)  # TTL сессии

    async def get_history(self, session_id: str, max_len: int = 20) -> List[Dict]:
        r = await get_redis()
        key = f"session:{session_id}:history"
        items = await r.lrange(key, -max_len, -1)
        return [json.loads(item) for item in items]

session_history = RedisSessionHistory() if settings.redis_url.startswith("redis://") else InMemorySessionHistory()

# ---------- Rate Limiter ----------
class RateLimiter:
    async def check(self, tenant: str) -> bool:
        raise NotImplementedError

class InMemoryRateLimiter(RateLimiter):
    def __init__(self):
        self.counters: Dict[str, List[float]] = {}
        self.blocked_until: Dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def check(self, tenant: str) -> bool:
        async with self._lock:
            now = time.time()
            if tenant not in self.counters:
                self.counters[tenant] = []
            self.counters[tenant] = [t for t in self.counters[tenant] if t > now - 60]
            if self.blocked_until.get(tenant, 0) > now:
                return False
            if len(self.counters[tenant]) >= settings.rate_limit_per_min:
                self.blocked_until[tenant] = now + settings.block_window_sec
                return False
            self.counters[tenant].append(now)
            return True

class RedisRateLimiter(RateLimiter):
    async def check(self, tenant: str) -> bool:
        r = await get_redis()
        key = f"rate:{tenant}"
        now = time.time()
        async with r.pipeline(transaction=True) as pipe:
            pipe.zremrangebyscore(key, 0, now - 60)
            pipe.zcard(key)
            pipe.zadd(key, {str(uuid.uuid4()): now})
            pipe.expire(key, 60)
            _, count, _, _ = await pipe.execute()
            return count <= settings.rate_limit_per_min

rate_limiter = RedisRateLimiter() if settings.redis_url.startswith("redis://") else InMemoryRateLimiter()

# ---------- Политики (YAML + горячая перезагрузка) ----------
POLICIES: Dict[str, Any] = {}

def load_policies(path: str = settings.policy_file) -> Dict:
    try:
        with open(path, "r") as f:
            data = yaml.safe_load(f)
        logger.info("Policies loaded", extra={"file": path})
        return data or {}
    except FileNotFoundError:
        logger.warning("Policy file not found, using empty policies")
        return {}

async def watch_policies():
    async for changes in awatch(Path(settings.policy_file).parent):
        for change in changes:
            if Path(change[1]).name == Path(settings.policy_file).name:
                global POLICIES
                POLICIES = load_policies()
                logger.info("Policies hot‑reloaded")

POLICIES = load_policies()

# ---------- Модели данных ----------
class Decision(str, Enum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    ESCALATE = "ESCALATE"

class Reason(BaseModel):
    code: str
    message: str

class EvaluateResponse(BaseModel):
    decision: Decision
    reason: Reason
    trace_id: str
    request_id: str
    escalation_queue: Optional[str] = None
    signature: Optional[str] = None  # заполнится middleware

# Строгие модели для аргументов (по intent)
class SendPaymentArgs(BaseModel):
    amount: float = Field(..., gt=0)
    recipient: str = Field(..., min_length=1)

class DeleteUserArgs(BaseModel):
    user_id: str

# Сопоставление intent -> Pydantic модель
INTENT_ARGS_MODELS = {
    "send_payment": SendPaymentArgs,
    "delete_user": DeleteUserArgs,
}

class EvaluateRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=128)
    intent: str = Field(..., min_length=1, max_length=settings.max_intent_length)
    args: Dict[str, Any]
    idempotency_key: Optional[str] = None
    # model_confidence и history убраны – теперь они внутренние

    @root_validator(pre=True)
    def validate_args_size(cls, values):
        args = values.get("args", {})
        if len(json.dumps(args)) > settings.max_args_bytes:
            raise ValueError("ARGS_TOO_LARGE")
        return values

# ---------- Аутентификация ----------
def get_tenant(x_api_key: str = Header(...)) -> Dict:
    if x_api_key not in settings.api_keys:
        raise HTTPException(status_code=401, detail="INVALID_API_KEY")
    return settings.api_keys[x_api_key]

# ---------- Ядро MCC ----------
class MCC:
    def __init__(self, audit: AuditRepository):
        self.audit = audit
        self.prev_hash = "GENESIS"
        self._lock = asyncio.Lock()

    def _hash(self, data: str) -> str:
        return hashlib.sha256(data.encode()).hexdigest()

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    async def _record_audit(
        self, tenant: str, req: EvaluateRequest, decision: Decision,
        reason: Reason, trace_id: str, request_id: str,
        escalation_queue: Optional[str],
    ):
        async with self._lock:
            entry = {
                "timestamp": self._now(),
                "tenant": tenant,
                "session_id": req.session_id,
                "intent": req.intent,
                "args": req.args,
                "decision": decision.value,
                "reason": reason.dict(),
                "trace_id": trace_id,
                "request_id": request_id,
                "escalation_queue": escalation_queue,
                "prev_hash": self.prev_hash,
            }
            serialized = json.dumps(entry, sort_keys=True, default=str)
            current_hash = self._hash(self.prev_hash + serialized)
            entry["hash"] = current_hash
            await self.audit.append(entry)
            self.prev_hash = current_hash

    async def _get_session_history(self, session_id: str) -> List[Dict]:
        return await session_history.get_history(session_id)

    async def _record_decision_in_session(self, session_id: str, decision_record: Dict):
        await session_history.append(session_id, decision_record)

    def _estimate_confidence(self, intent: str, args: Dict, history: List[Dict]) -> float:
        """
        Внутренняя оценка уверенности в безопасности намерения.
        Здесь могут быть реальные эвристики, ML-модели, проверки консистентности.
        В этой реализации – простые правила:
        - Если в истории за последние 5 мин уже было 5 действий, снижаем уверенность.
        - Если сумма платежа > 9000, немного снижаем.
        Возвращает 0.0–1.0.
        """
        confidence = 1.0
        # Штраф за частые действия
        now = datetime.now(timezone.utc)
        recent_count = sum(
            1 for h in history
            if (now - datetime.fromisoformat(h["timestamp"])).total_seconds() < 300
        )
        if recent_count > 10:
            confidence -= 0.4
        elif recent_count > 5:
            confidence -= 0.2

        # Штраф для крупных платежей
        if intent == "send_payment" and args.get("amount", 0) > 9000:
            confidence -= 0.1

        return max(0.0, min(1.0, confidence))

    async def evaluate(
        self, tenant_ctx: Dict, req: EvaluateRequest
    ) -> EvaluateResponse:
        tenant = tenant_ctx["tenant"]
        scopes = tenant_ctx.get("scopes", [])
        request_id = str(uuid.uuid4())
        trace_id = self._hash(request_id + req.session_id)[:12]

        # Идемпотентность – проверка кеша
        if req.idempotency_key:
            idem_key = f"idempotency:{tenant}:{req.idempotency_key}"
            r = await get_redis() if settings.redis_url.startswith("redis://") else None
            if r:
                cached = await r.get(idem_key)
                if cached:
                    return EvaluateResponse.parse_raw(cached)
            else:
                # in‑memory fallback с простым словарём
                async with self._lock:
                    if hasattr(self, "_idem_cache") and req.idempotency_key in self._idem_cache:
                        return self._idem_cache[req.idempotency_key]

        # Получаем историю сессии
        history = await self._get_session_history(req.session_id)

        # Строгая валидация аргументов
        args_model = INTENT_ARGS_MODELS.get(req.intent)
        if args_model:
            try:
                validated_args = args_model(**req.args)
                req.args = validated_args.dict()  # заменяем на чистые проверенные
            except ValidationError as e:
                result = EvaluateResponse(
                    decision=Decision.DENY,
                    reason=Reason(code="INVALID_ARGS", message=str(e)),
                    trace_id=trace_id,
                    request_id=request_id,
                )
                await self._finalize(tenant, req, result)
                return result

        # Таймаут вычисления
        try:
            result = await asyncio.wait_for(
                self._evaluate_internal(tenant, scopes, req, history, trace_id, request_id),
                timeout=settings.policy_timeout_sec,
            )
        except asyncio.TimeoutError:
            result = EvaluateResponse(
                decision=Decision.DENY,
                reason=Reason(code="TIMEOUT", message="policy evaluation timeout"),
                trace_id=trace_id,
                request_id=request_id,
            )
        except Exception:
            logger.exception("Evaluation error")
            result = EvaluateResponse(
                decision=Decision.DENY,
                reason=Reason(code="ERROR", message="fail-closed internal error"),
                trace_id=trace_id,
                request_id=request_id,
            )

        await self._finalize(tenant, req, result)
        return result

    async def _finalize(self, tenant: str, req: EvaluateRequest, result: EvaluateResponse):
        # Сохраняем решение в историю сессии
        decision_record = {
            "timestamp": self._now(),
            "intent": req.intent,
            "args": req.args,
            "decision": result.decision.value,
        }
        await self._record_decision_in_session(req.session_id, decision_record)

        # Аудит
        await self._record_audit(
            tenant, req, result.decision, result.reason,
            result.trace_id, result.request_id, result.escalation_queue,
        )

        # Метрики
        DECISIONS.labels(
            decision=result.decision.value,
            intent=req.intent,
            tenant=tenant,
        ).inc()

        # Кеширование идемпотентности
        if req.idempotency_key:
            idem_key = f"idempotency:{tenant}:{req.idempotency_key}"
            r = await get_redis() if settings.redis_url.startswith("redis://") else None
            if r:
                await r.set(idem_key, result.json(), ex=settings.idempotency_ttl_sec)
            else:
                async with self._lock:
                    if not hasattr(self, "_idem_cache"):
                        self._idem_cache = {}
                    self._idem_cache[req.idempotency_key] = result

        logger.info(
            f"Decision: {result.decision.value}",
            extra={
                "tenant": tenant,
                "intent": req.intent,
                "trace_id": result.trace_id,
                "request_id": result.request_id,
            },
        )

    async def _evaluate_internal(
        self, tenant: str, scopes: List[str], req: EvaluateRequest,
        history: List[Dict], trace_id: str, request_id: str,
    ) -> EvaluateResponse:
        # Проверка наличия политики
        policy = POLICIES.get(req.intent)
        if not policy:
            return EvaluateResponse(
                decision=Decision.DENY,
                reason=Reason(code="UNKNOWN_INTENT", message="intent not in policy"),
                trace_id=trace_id,
                request_id=request_id,
            )

        # Запрещённые действия
        if policy.get("forbidden", False):
            return EvaluateResponse(
                decision=Decision.DENY,
                reason=Reason(code="FORBIDDEN", message="blocked by policy"),
                trace_id=trace_id,
                request_id=request_id,
            )

        # Проверка scope
        required_scope = policy.get("scope")
        if required_scope and required_scope not in scopes:
            return EvaluateResponse(
                decision=Decision.DENY,
                reason=Reason(code="FORBIDDEN_SCOPE", message="missing required scope"),
                trace_id=trace_id,
                request_id=request_id,
            )

        # Внутренняя оценка уверенности (мета-когнитивный шаг)
        confidence = self._estimate_confidence(req.intent, req.args, history)
        min_confidence = policy.get("min_confidence", 0.9)
        if confidence < min_confidence:
            return EvaluateResponse(
                decision=Decision.ESCALATE,
                reason=Reason(
                    code="LOW_CONFIDENCE",
                    message=f"estimated confidence {confidence:.2f} below threshold {min_confidence}"
                ),
                trace_id=trace_id,
                request_id=request_id,
                escalation_queue=policy.get("escalation_queue", "default"),
            )

        # Контекстные проверки на основе истории (например, два крупных платежа подряд)
        if req.intent == "send_payment":
            large_payments = [
                h for h in history[-5:]
                if h.get("intent") == "send_payment" and h.get("args", {}).get("amount", 0) > 5000
            ]
            if len(large_payments) >= 2:
                return EvaluateResponse(
                    decision=Decision.DENY,
                    reason=Reason(code="TOO_MANY_LARGE_PAYMENTS", message="contextual limit exceeded"),
                    trace_id=trace_id,
                    request_id=request_id,
                )

        # Проверка конкретных интентов
        if req.intent == "send_payment":
            amount = req.args.get("amount", 0)
            max_amount = policy.get("max_amount", 0)
            escalation_threshold = policy.get("escalation_threshold", max_amount)

            if amount <= escalation_threshold:
                return EvaluateResponse(
                    decision=Decision.ALLOW,
                    reason=Reason(code="OK", message="within limit"),
                    trace_id=trace_id,
                    request_id=request_id,
                )
            elif amount <= max_amount:
                return EvaluateResponse(
                    decision=Decision.ESCALATE,
                    reason=Reason(code="AMOUNT_ESCALATED", message="requires human approval"),
                    trace_id=trace_id,
                    request_id=request_id,
                    escalation_queue=policy.get("escalation_queue", "payments_review"),
                )
            else:
                return EvaluateResponse(
                    decision=Decision.DENY,
                    reason=Reason(code="LIMIT_EXCEEDED", message="amount exceeds policy limit"),
                    trace_id=trace_id,
                    request_id=request_id,
                )

        if req.intent == "delete_user":
            if "users:admin" in scopes:
                return EvaluateResponse(
                    decision=Decision.ALLOW,
                    reason=Reason(code="OK", message="allowed"),
                    trace_id=trace_id,
                    request_id=request_id,
                )
            else:
                return EvaluateResponse(
                    decision=Decision.DENY,
                    reason=Reason(code="FORBIDDEN_SCOPE", message="admin scope required"),
                    trace_id=trace_id,
                    request_id=request_id,
                )

        # Deny by default
        return EvaluateResponse(
            decision=Decision.DENY,
            reason=Reason(code="DEFAULT", message="no matching rule, deny by default"),
            trace_id=trace_id,
            request_id=request_id,
        )

# ---------- Инициализация ядра ----------
mcc = MCC(audit_repo)

# ---------- FastAPI приложение ----------
app = FastAPI(
    title="MCC Policy Engine v2.1",
    description="Эталонный Meta‑Cognitive Control – полностью автономный контроль",
    version="2.1.0",
)

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["POST"], allow_headers=["*"])

class HMACSignMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        if response.status_code == 200 and request.url.path == "/evaluate":
            body = b""
            async for chunk in response.body_iterator:
                body += chunk
            key = settings.hmac_secret.encode()
            sig = hmac.new(key, body, hashlib.sha256).hexdigest()
            headers = dict(response.headers)
            headers["X-MCC-Signature"] = sig
            response = Response(
                content=body,
                status_code=response.status_code,
                headers=headers,
                media_type=response.media_type,
            )
        return response

app.add_middleware(HMACSignMiddleware)

@app.post("/evaluate", response_model=EvaluateResponse)
async def evaluate(req: EvaluateRequest, tenant_ctx: Dict = Depends(get_tenant)):
    if not await rate_limiter.check(tenant_ctx["tenant"]):
        raise HTTPException(status_code=429, detail="RATE_LIMIT_EXCEEDED")
    with LATENCY.labels(tenant_ctx["tenant"]).time():
        return await mcc.evaluate(tenant_ctx, req)

@app.get("/health")
async def health():
    status = "ok"
    try:
        r = await get_redis()
        await r.ping()
    except Exception:
        status = "degraded"
    return {"status": status}

@app.get("/metrics")
async def metrics():
    return Response(generate_latest(), media_type="text/plain")

@app.get("/ready")
async def ready():
    return {"ready": True}

@app.on_event("startup")
async def startup():
    asyncio.create_task(watch_policies())

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=settings.port)
