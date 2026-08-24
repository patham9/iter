import subprocess
import sys

class EscalationEngine:
    def __init__(self, metta_script, metta_bin):
        self.metta_script = metta_script
        self.metta_bin = metta_bin

    def _call_metta_simple(self, func_name, *args):
        """Calls a specific MeTTa function with provided arguments."""
        try:
            # Constructing the MeTTa call string: (func_name arg1 arg2 ...)
            arg_str = " ".join([f'(quote {a})' for a in args])
            call_str = f'({func_name} {arg_str})'
            cmd = [self.metta_bin, self.metta_script, call_str]
            
            result = subprocess.check_output(
                cmd, 
                stderr=subprocess.STDOUT,
                text=True
            ).strip()
            return 'True' in result
        except subprocess.CalledProcessError as e:
            print(f"MeTTa Error: {e.output}")
            return False

    def process_proposal(self, proposal):
        p_type = proposal.get("type")
        p_action = proposal.get("action")
        p_meta = proposal.get("meta", {})

        print(f"\n[Dispatcher] Proposal: {p_type} | {p_action} | Meta: {p_meta}")

        if p_type == "safety":
            print("  -> Escalating to MeTTa (Safety Check)...")
            if self._call_metta_simple("check_safety", p_action):
                print("  -> [MeTTa Result: PASS]")
                return True
            else:
                print("  -> [MeTTa Result: FAIL]")
                return False

        elif p_type == "provenance":
            print("  -> Escalating to MeTTa (Provenance Check)...")
            source = p_meta.get("source", "unknown")
            if self._call_metta_simple("check_provenance", p_action, source):
                print("  -> [MeTTa Result: PASS]")
                return True
            else:
                print("  -> [MeTTa Result: FAIL]")
                return False

        elif p_type == "conflict":
            print("