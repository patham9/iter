import time
import os
import datetime
import sys

LOG_FILE = '/home/mettaclaw/iter/memory/logs/ebp_audit.log'
SUSPICIOUS_PATTERNS = ["REJECTED", "CRITICAL", "UNAUTHORIZED", "UNRECOGNIZED"]

class IntegrityMonitor:
    def __init__(self, log_path):
        self.log_path = log_path
        self.last_position = 0
        if os.path.exists(log_path):
            self.last_position = os.path.getsize(log_path)

    def start_monitoring(self):
        print(f"[{datetime.datetime.now().isoformat()}] Monitor started.")
        while True:
            if os.path.exists(self.log_path):
                with open(self.log_path, 'r') as f:
                    f.seek(self.last_position)
                    lines = f.readlines()
                    self.last_position = f.tell()
                    for line in lines:
                        for pattern in SUSPICIOUS_PATTERNS:
                            if pattern in line.upper():
                                # Output to stdout/stderr for easy capture
                                print(f"[!!! ALERT !!!] {line.strip()}")
                                sys.stdout.flush()
            time.sleep(0.5)

if __name__ == '__main__':
    IntegrityMonitor(LOG_FILE).start_monitoring()