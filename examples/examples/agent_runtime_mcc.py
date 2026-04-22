# examples/agent_runtime_mcc.py

"""
MCC Agent Runtime Demonstration

Shows:
- WITHOUT MCC → actions execute
- WITH MCC → actions are gated (fail-closed)
"""

from mcc.runtime import Runtime


# =========================
# TOOLS (real actions)
# =========================

def delete_user(intent):
    return f"EXECUTED: deleted user {intent.get('user_id')}"

def send_payment(intent):
    return f"EXECUTED: sent ${intent.get('amount')}"


tools = {
    "delete_user": delete_user,
    "send_payment": send_payment,
}


# =========================
# ❌ UNCONTROLLED EXECUTION
# =========================

def unsafe_execute(intent):
    action = intent.get("action")

    if action == "delete_user":
        return delete_user(intent)

    if action == "send_payment":
        return send_payment(intent)

    return "UNKNOWN ACTION"


# =========================
# 🔥 MCC RUNTIME (CONTROL)
# =========================

runtime = Runtime(tools)


# =========================
# TEST CASES
# =========================

cases = [
    {"action": "delete_user", "user_id": 1},
    {"action": "send_payment", "amount": 50000},
    {"action": "send_payment", "amount": 100},
]


# =========================
# DEMO
# =========================

for c in cases:
    print("\n==============================")
    print("INPUT:", c)

    print("\nWITHOUT MCC:")
    print(unsafe_execute(c))

    print("\nWITH MCC:")
    print(runtime.run(c))
