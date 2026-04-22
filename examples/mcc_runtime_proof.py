# MCC v1.5 — Bound Runtime + Proof

import hashlib
import json
import time


class Decision:
    def __init__(self, verdict, reason, trace_id):
        self.verdict = verdict
        self.reason = reason
        self.trace_id = trace_id


class MCC:
    def __init__(self):
        self.prev_hash = "GENESIS"
        self.audit_log = []

    def _hash(self, payload):
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _audit(self, intent, verdict, reason):
        ts = str(time.time())
        trace_id = self._hash(ts + json.dumps(intent, sort_keys=True))[:12]

        record = {
            "prev_hash": self.prev_hash,
            "timestamp": ts,
            "intent": intent,
            "verdict": verdict,
            "reason": reason,
            "trace_id": trace_id,
        }

        serialized_record = json.dumps(record, sort_keys=True)
        current_hash = self._hash(self.prev_hash + serialized_record)

        self.prev_hash = current_hash
        self.audit_log.append({**record, "hash": current_hash})

        return trace_id

    def evaluate(self, intent):
        try:
            action = intent.get("action")

            if action == "delete_user":
                trace = self._audit(intent, "DENY", "destructive action")
                return Decision("DENY", "Destructive action blocked", trace)

            if action == "send_payment":
                amount = float(intent.get("amount", 0))
                if amount > 10000:
                    trace = self._audit(intent, "DENY", "limit exceeded")
                    return Decision("DENY", "Amount exceeds limit", trace)

                trace = self._audit(intent, "ALLOW", "within limit")
                return Decision("ALLOW", "OK", trace)

            trace = self._audit(intent, "DENY", "unknown intent")
            return Decision("DENY", "Unknown intent", trace)

        except Exception:
            trace = self._audit(intent, "DENY", "internal error")
            return Decision("DENY", "Internal error", trace)


def delete_user(intent):
    return "EXECUTED: user deleted"


def send_payment(intent):
    return f"EXECUTED: payment ${intent.get('amount')} sent"


class BoundRuntime:
    def __init__(self, mcc):
        self.mcc = mcc
        self.tools = {
            "delete_user": delete_user,
            "send_payment": send_payment,
        }

    def run(self, intent):
        decision = self.mcc.evaluate(intent)

        if decision.verdict != "ALLOW":
            return f"BLOCKED: {decision.reason} (trace_id={decision.trace_id})"

        action = intent.get("action")

        if action not in self.tools:
            return "UNKNOWN ACTION"

        return self.tools[action](intent)


def unsafe_execute(intent):
    action = intent.get("action")

    if action == "delete_user":
        return delete_user(intent)

    if action == "send_payment":
        return send_payment(intent)

    return "UNKNOWN ACTION"


def proof():
    mcc = MCC()
    runtime = BoundRuntime(mcc)

    print("\n=== DELETE USER ===")

    intent = {"action": "delete_user"}

    print("\nWITHOUT MCC:")
    print(unsafe_execute(intent))

    print("\nWITH MCC:")
    print(runtime.run(intent))


if __name__ == "__main__":
    proof()
