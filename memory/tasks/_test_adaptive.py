import sys
import os
sys.path.append('/home/mettaclaw/iter/tools')
from adaptive_epistemic_weighting import run

# Mock reliability file for testing
import json
with open('/home/mettaclaw/iter/memory/config/tool_reliability.json', 'w') as f:
    json.dump({'tools': {'test_tool': 0.4}}, f)

result = run(base_certainty=0.9, tool_name='test_tool')
print(result)