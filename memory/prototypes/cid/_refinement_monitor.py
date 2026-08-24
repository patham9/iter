import time
import json
import os
import datetime

RELIABILITY_JSON = '/home/mettaclaw/iter/memory/config/tool_reliability.json'
AUDIT_LOG = '/home/mettaclaw/iter/memory/logs/ebp_audit.log'

class RefinementMonitor:
    def __init__(self):
        self.last_position = 0
        if os.path.exists(AUDIT_LOG):
            self.last_position = os.path.getsize(AUDIT_LOG)
        if not os.path.exists(RELIABILITY_JSON):
            with open(RELIABILITY_JSON, 'w') as f:
                json.dump({'tools': {}}, f)

    def update_reliability(self, tool_name):
        try:
            with open(RELIABILITY_JSON, 'r+') as f:
                data = json.load(f)
                tools = data.get('tools', {})
                current_score = tools.get(tool_name, 1.0)
                new_score = max(0.0, current_score - 0.05)
                tools[tool_name] = round(new_score, 2)
                f.seek(0)
                json.dump(data, f, indent=4)
                f.truncate()
        except Exception as e:
            print(f"ERR: {e}")

    def run(self):
        while True:
            if os.path.exists(AUDIT_LOG):
                with open(AUDIT_LOG, 'r') as f:
                    f.seek(self.last_position)
                    lines = f.readlines()
                    self.last_position = f.tell()
                    for line in lines:
                        if "REJECTED" in line.upper() and "TOOL:" in line:
                            parts = line.split('|')
                            if len(parts) > 1:
                                tool_name = parts[1].split(":")[1].strip().lower()
                                self.update_reliability(tool_name)
            time.sleep(0.5)

if __name__ == '__main__':
    RefinementMonitor().run()