import subprocess
import time
import os
import json
import datetime

def run_test():
    m_path = '/home/mettaclaw/iter/memory/prototypes/cid/refinement_monitor.py'
    r_path = '/home/mettaclaw/iter/memory/config/tool_reliability.json'
    l_path = '/home/mettaclaw/iter/memory/logs/ebp_audit.log'
    
    print("Starting robustness test...")
    
    # Reset reliability
    with open(r_path, 'w') as f:
        json.dump({'tools': {'shell': 1.0}}, f)
    
    # Start monitor
    proc = subprocess.Popen(['python3', m_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    time.sleep(2)
    
    # Inject failure
    with open(l_path, 'a') as f:
        f.write(f"[2026-08-21T07:30:55.596166] TOOL: shell | STATUS: REJECTED\n")
    print("Injected failure.")
    
    # Wait and check
    time.sleep(3)
    proc.terminate()
    
    with open(r_path, 'r') as f:
        data = json.load(f)
        score = data['tools'].get('shell', 1.0)
        print(f"Score: {score}")
        if score < 1.0:
            return True
        return False

if __name__ == '__main__':
    if run_test():
        print("SUCCESS")
    else:
        print("FAIL")