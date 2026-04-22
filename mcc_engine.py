import hashlib
import json
import yaml
from datetime import datetime, timezone

class MCCEngine:
    def __init__(self, policy_path='policy.yaml', audit_path='audit.jsonl'):
        self.policy_path = policy_path
        self.audit_path = audit_path
        self.last_hash = '0' * 64
        self.load_policy()
        
    def load_policy(self):
        try:
            with open(self.policy_path, 'r') as f:
                self.policy = yaml.safe_load(f)
        except Exception as e:
            self.log_audit('DENY', 'policy_load_error', str(e))
            raise RuntimeError('Fail-closed: Policy load failed')
    
    def hash_chain(self, entry):
        data = json.dumps(entry, sort_keys=True).encode()
        h = hashlib.sha256(self.last_hash.encode() + data).hexdigest()
        self.last_hash = h
        return h
    
    def log_audit(self, decision, reason, details=''):
        entry = {
            'ts': datetime.now(timezone.utc).isoformat(),
            'decision': decision,
            'reason': reason,
            'details': details,
            'prev_hash': self.last_hash
        }
        entry['hash'] = self.hash_chain(entry)
        with open(self.audit_path, 'a') as f:
            f.write(json.dumps(entry) + '\n')
        return entry
    
    def evaluate(self, action, context):
        try:
            rules = self.policy.get('rules', [])
            for rule in rules:
                if action == rule.get('action'):
                    if rule.get('condition', True):
                        self.log_audit('ALLOW', f'action:{action}', str(context))
                        return True
            self.log_audit('DENY', f'no_rule_for_action:{action}', str(context))
            return False
        except Exception as e:
            self.log_audit('DENY', 'evaluation_error', str(e))
            return False

if __name__ == '__main__':
    engine = MCCEngine()
    print('MCC v1.5 Engine initialized. Fail-closed mode active.')
