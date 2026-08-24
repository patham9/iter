import os
import json
import subprocess
import datetime

RELIABILITY_JSON = '/home/mettaclaw/iter/memory/config/tool_reliability.json'
PROBE_TOOL = '/home/mettaclaw/iter/tools/proactive_probing_engine.py'

def run_test():
    print("Starting definitive PST verification...")
    
    # 1. Reset reliability and ensure 'shell' exists
    with open(RELIABILITY_JSON, 'w') as f:
        json.dump({'tools': {'shell': 1.0, 'python': 1.0}}, f)
    print("Environment prepared with 'shell' at 1.0.")

    # 2. Inject anomaly
    print("Injecting artificial degradation: shell -> 0.2")
    with open(RELIABILITY_JSON, 'r') as f:
        data = json.load(f)
    data['tools']['shell'] = 0.2
    with open(RELIABILITY_JSON, 'w') as f:
        json.dump(data, f, indent=4)

    # 3. Run Proactive Probe
    print("Triggering proactive probe...")
    res = subprocess.run(['python3', PROBE_TOOL], capture_output=True, text=True)
    print("Probe Output:", res.stdout)

    # 4. Verification
    if "anomalies_detected': 1" in res.stdout:
        print("VERIFICATION SUCCESS: Anomaly detected!")
        return True
    else:
        print("VERIFICATION FAILED: Anomaly NOT detected.")
        return False

if __name__ == '__main__':
    if run_test():
        exit(0)
    else:
        exit(1)