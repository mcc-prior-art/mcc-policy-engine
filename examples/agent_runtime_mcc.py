from mcc.runtime import Runtime

# === TOOLS ===
def delete_user(intent):
    return f"EXECUTED: deleted user {intent.get('user_id')}"

def send_payment(intent):
    return f"EXECUTED: sent ${intent.get('amount')}"

tools = {
    "delete_user": delete_user,
    "send_payment": send_payment,
}

# === RUNTIME ===
runtime = Runtime(tools)

cases = [
    {"action": "delete_user", "user_id": 1},
    {"action": "send_payment", "amount": 50000},
    {"action": "send_payment", "amount": 100},
]

for c in cases:
    print(c, "→", runtime.run(c))
