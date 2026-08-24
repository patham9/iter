import sys
import os
sys.path.append('/home/mettaclaw/iter/tools')
from reliability_dispatcher import ReliabilityDispatcher

def test_tool(val):
    if val < 0: return "ERROR: Failed"
    return "OK"

dispatcher = ReliabilityDispatcher()
# Reset tool score for test
dispatcher.data['tools']['test_tool'] = 1.0
with open('/home/mettaclaw/iter/memory/config/reliability_dispatcher.py', 'w') as f:
    import json
    json.dump({'tools': {'test_tool': 1.0}}, f)

print("Score 1:", dispatcher.get_score('test_tool'))
dispatcher.dispatch(test_tool, 'test_tool', val=-1)
print("Score 2 (after fail):", dispatcher.get_score('test_tool'))