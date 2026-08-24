import importlib.util
import os

path = '/home/mettaclaw/iter/tools/edmp_mitigator.py'
spec = importlib.util.spec_from_file_location("edmp", path)
edmp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(edmp)
result = edmp.run(target_tools=['shell'])
print(result)