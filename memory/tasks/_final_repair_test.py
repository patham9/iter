import os
import json
import subprocess
import datetime

RELIABILITY_JSON = '/home/mettaclaw/iter/memory/config/tool_reliability.json'
DRIFT_ANALYZER_PATH = '/home/mettaclaw/iter/tools/drift_analyzer.py'
AUDIT_LOG_PATH = '/home/mettaclaw/iter/memory/logs/ebp_audit.log'
DAEMON_PATH = '/home/mettaclaw/iter/tools/epistemic_refinement_daemon.py'

def run_test():
    print("Starting definitive verification...")
    
    # 1. Reset environment
    with open(RELIABILITY_JSON, 'w') as f:
        json.dump({'tools': {'test_tool': 1.0}}, f)
    
    with open(AUDIT_LOG_PATH, 'a') as f:
        f.write(f"[2026-08-21T07:55:53.125477] TOOL: test_tool | STATUS: REJECTED\n")
    print("Environment reset and failure injected.")

    # 2. Test Analyzer
    print("Testing Drift Analyzer...")
    res = subprocess.run(['python3', DRIFT_ANALYZER_PATH], capture_output=True, text=True)
    if "test_tool" not in res.stdout:
        print("FAIL: Analyzer did not detect test_tool.")
        return False
    print("Analyzer output captured.")

    # 3. Test Daemon
    print("Testing Epistemic Daemon...")
    # Run daemon for a single pass
    res_daemon = subprocess.run(['python3', DAEMON_PATH], capture_output=True, text=True)
    print("Daemon output:", res_daemon.stdout)

    # 4. Check result
    with open(RELIABILITY_JSON, 'r') as f:
        data = json.load(f)
        score = data['tools'].get('test_tool')
    
    print(f"Final tool score: {score}")
    if score is not None and score < 1.0:
        print("SUCCESS: Reliability was downgraded.")
        return True
    else:
        print("FAIL: Reliability remained at 1.0.")
        return False

if __name__ == '__main__':
    if run_test():
        print("VERIFICATION SUCCESS")
    else:
        print("VERIFICATION FAILED")