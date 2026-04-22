# MCC v1.5 Policy Engine — Reference Implementation

![Status](https://img.shields.io/badge/status-alpha-orange)
![Prior Art](https://img.shields.io/badge/prior%20art-2026--04--22-blue)
![License](https://img.shields.io/badge/license-MIT-green)

> **MCC defines a control boundary between intent and execution in AI systems.**

Fail-closed control layer for policy-gated execution with cryptographic hash-chain audit.

---

## Prior Art Notice

This repository establishes public prior art as of **2026-04-22** for fail-closed policy enforcement with tamper-evident SHA256 hash-chain audit logging.

- Release: v1.5  
- Commit: `9b4bfad1b6af628f4feb39e9913d98fe586aa766`

All artifacts are publicly accessible and reproducible.

---

## TL;DR

- Deny-by-default execution  
- Fail-closed on uncertainty or error  
- Intent ≠ execution (enforced boundary)  
- Cryptographic audit (hash-chain)  
- Defines a control standard for AI systems that act  

---

## Definition

MCC (Meta-Cognitive Control) is a control layer that separates intent generation from action execution using policy evaluation and fail-closed semantics.

---

## Control Model

All actions MUST pass through MCC before execution.

```text
Intent → MCC → Decision → Execution
```

| Condition | Result |
|---|---|
| Unknown intent | DENY |
| Policy violation | DENY |
| Error / uncertainty | DENY |

Execution requires explicit `ALLOW`.

---

## Normative Requirements

An MCC-compliant system MUST:

1. Enforce deny-by-default execution  
2. Evaluate all intents before execution  
3. Fail closed on any error or uncertainty  
4. Gate execution strictly by decision outcome  
5. Record all decisions in an audit log  
6. Maintain tamper-evident (hash-linked) audit records  
7. Execution MUST NOT occur outside the MCC control path  

---

## Decision Contract

```python
decision = mcc.evaluate(intent)

# decision object
decision.verdict   # "ALLOW" | "DENY"
decision.reason    # explanation
decision.trace_id  # audit reference
```

---

## Proof (Minimal Demonstration)

This demonstrates the necessity of a control boundary.

### Without MCC

```python
execute({"action": "delete_user"})
```

```text
EXECUTED: user deleted
```

---

### With MCC

```python
decision = mcc.evaluate({"action": "delete_user"})

if decision.verdict == "ALLOW":
    execute(...)
else:
    block()
```

```text
Decision: DENY
Result: BLOCKED
```

---

### Conclusion

Without MCC → execution occurs  
With MCC → execution is controlled  

MCC is not advisory.  
It is an enforcement boundary.  
It is a required control layer for systems that act.  
**This behavior is deterministic and enforceable by design.**

---

## Audit Model

Each decision produces a hash-linked record:

```python
record = {
  "prev_hash": ...,
  "intent": ...,
  "verdict": ...,
  "trace_id": ...
}

hash = SHA256(prev_hash + serialized_record)
```

---

## Security Properties

- Fail-closed (safe by default)  
- Deny-by-default execution  
- Policy-gated control boundary  
- Full traceability via audit  

---

## Scope

MCC defines:

- control boundaries for acting systems  
- policy-gated execution  
- fail-closed enforcement  

---

## Non-Goals

MCC does NOT define:

- how intents are generated  
- policy logic implementation  
- execution systems  
- domain-specific rules  

---

## Conformance

An implementation is MCC-compliant if it satisfies all normative requirements.

Minimum validation:

1. Unknown intent → DENY  
2. Policy violation → DENY  
3. Error → DENY  
4. No execution without ALLOW  
5. Audit records MUST be hash-linked  
6. Every evaluation MUST produce an audit entry  

Implementations failing any condition MUST NOT be considered compliant.

---

## License

MIT. No patent rights are granted.
