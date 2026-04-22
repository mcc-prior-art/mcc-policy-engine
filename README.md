# MCC (Meta-Cognitive Control)

A control layer between AI-generated intent and real-world execution. **Non-Production Use only.**

MCC introduces a formal decision boundary between **intent generation** (LLMs, agents) and **execution authority** (systems, APIs, workflows).  
Instead of trusting AI outputs directly, MCC evaluates whether an action **should happen at all**.

---

## Why This Matters

AI systems can generate actions.  
They cannot reliably decide whether those actions should be executed.

As soon as systems:
- call APIs  
- move money  
- trigger workflows  
- control external systems  

the absence of a control boundary becomes a **systemic risk**.

MCC defines that boundary.

---

## Core Idea

AI Model → Intent → **MCC** → Decision → Execution (or Denial)

- AI proposes an action  
- MCC evaluates it against policy  
- Only approved actions are executed  

---

## Quick Start (Conceptual)

Example:

```json
{
  "intent": "send_payment",
  "amount": 50000,
  "recipient": "external_vendor"
}
```

MCC decision:

```text
DENY
reason: amount exceeds policy threshold
```

No execution occurs.

---

## Minimal Integration (Runnable Pattern)

Place MCC directly in front of your execution layer:

```python
def mcc_evaluate(request):
    if request["intent"] == "send_payment" and request["amount"] > 10000:
        return "DENY"
    return "ALLOW"

decision = mcc_evaluate({
    "intent": "send_payment",
    "amount": 50000,
    "recipient": "external_vendor"
})

if decision == "ALLOW":
    execute_payment()
else:
    block_execution()
```

MCC acts as a **hard execution gate** between AI and the real world.

---

## Reference Implementation

This repository provides a minimal PoC demonstrating:

- deny-by-default execution model  
- structured intent validation  
- policy-based decision logic  
- strict separation of intent and execution  

It is intended for:

- research  
- evaluation  
- architectural understanding  

---

## Where MCC Fits

MCC is applicable to:

- AI agents with tool execution  
- financial / transactional systems  
- API-driven automation  
- robotics and real-world control systems  
- enterprise AI governance layers  

---

## Licensing

Use of this repository is governed by the **MCC Evaluation License 1.0**.

- **Non-Production Use only**  
- Production use requires a separate commercial agreement  

Full license:

- [`LICENSE`](./LICENSE)  
- https://github.com/mcc-prior-art/mcc-policy-engine/blob/main/LICENSE  

---

## Commercial Use

Production deployment and enterprise integration are available under separate terms.

This may include:

- access to MCC Canon specifications (Canon-1, Canon-2, Canon-3)  
- production-grade policy design  
- governance, audit, and safety guarantees  
- integration and certification support  

Contact:  
**mcc.prior.art.2026@proton.me**

Early enterprise partnerships and pilot integrations are open.

---

## Prior Art

This repository establishes public prior art for the MCC control-layer pattern.

Private Canon materials are not included.

Proof of existence:

- Canon-2 SHA-256: `PASTE_REAL_HASH`  
- Canon-3 SHA-256: `PASTE_REAL_HASH`  

---

## Authorship Record

Git commit (HEAD):  
`PASTE_COMMIT_HASH_HERE`

Commit date (UTC):  
`PASTE_REAL_COMMIT_DATE`

Wayback snapshot:  
https://web.archive.org/web/PASTE_TIMESTAMP/https://github.com/mcc-prior-art/mcc-policy-engine  

---

## Context

MCC builds on:

- AI safety and alignment  
- policy enforcement systems  
- agent execution frameworks  
- distributed system governance  

It formalizes a **control boundary** between AI-generated intent and real-world execution.

---

## Notice

This repository documents a control architecture pattern.

Public availability does not grant rights to proprietary extensions, private Canon materials, or production implementations.

All rights not expressly granted are reserved.
