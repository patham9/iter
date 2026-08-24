"""
Effect-Boundary Engine — implements the epistemic transition framework.

Three regimes based on certainty score σ(C):
  - AXIOMATIC:    σ ≥ ε_high  → direct execution
  - PROBABILISTIC: ε_low < σ < ε_high → cautious execution + verification
  - HYPOTHETICAL: σ ≤ ε_low   → information gathering first

Uses SpaceReader for STV lookups (no MeTTa subprocess needed).
"""

import os
import sys

current_file_dir = os.path.dirname(os.path.abspath(__file__))
if current_file_dir not in sys.path:
    sys.path.insert(0, current_file_dir)

from metta_bridge import SpaceReader


class EffectBoundary:
    """
    Dynamically adjusts decision rigor based on epistemic certainty.
    
    σ(C) = s_pos / (s_pos + s_neg + 1)
    where s_pos/s_neg come from STV confidence in space.metta.
    """
    
    def __init__(self, epsilon_high=0.7, epsilon_low=0.3):
        self.epsilon_high = epsilon_high
        self.epsilon_low = epsilon_low
        self.reader = SpaceReader()
    
    def certainty_score(self, concept: str) -> float:
        """
        Compute σ(C) from space.metta STV values.
        Uses confidence as proxy for s_pos/(s_pos+s_neg+1).
        """
        stv, conf = self.reader.get_stv(concept)
        # confidence already represents the certainty in [0,1]
        return conf
    
    def classify(self, concept: str) -> str:
        """Classify a concept into its operational regime."""
        sigma = self.certainty_score(concept)
        if sigma >= self.epsilon_high:
            return "AXIOMATIC"
        elif sigma > self.epsilon_low:
            return "PROBABILISTIC"
        else:
            return "HYPOTHETICAL"
    
    def should_escalate(self, concept: str) -> bool:
        """True if the concept requires escalation (not axiomatic)."""
        return self.classify(concept) != "AXIOMATIC"
    
    def dispatch(self, concept: str, action: str) -> dict:
        """
        Route an action based on the epistemic regime of its premise.
        
        Returns:
            {
                "regime": str,
                "sigma": float,
                "action_taken": str,
                "escalated": bool
            }
        """
        sigma = self.certainty_score(concept)
        regime = self.classify(concept)
        
        if regime == "AXIOMATIC":
            action_taken = f"EXECUTE: {action}"
            escalated = False
        elif regime == "PROBABILISTIC":
            action_taken = f"VERIFY_THEN_EXECUTE: {action} (check provenance + conflict)"
            escalated = True
        else:
            action_taken = f"INVESTIGATE_FIRST: {action} (gather evidence before acting)"
            escalated = True
        
        return {
            "regime": regime,
            "sigma": sigma,
            "action_taken": action_taken,
            "escalated": escalated
        }
    
    def audit_all(self) -> dict:
        """Classify all atoms in space.metta by regime."""
        self.reader.invalidate()
        cache = self.reader.list_all()
        
        regimes = {"AXIOMATIC": [], "PROBABILISTIC": [], "HYPOTHETICAL": []}
        for term, (stv, conf) in cache.items():
            regime = "AXIOMATIC" if conf >= self.epsilon_high else \
                     "PROBABILISTIC" if conf > self.epsilon_low else "HYPOTHETICAL"
            regimes[regime].append((term[:50], conf))
        
        return {
            "total": len(cache),
            "axiomatic": len(regimes["AXIOMATIC"]),
            "probabilistic": len(regimes["PROBABILISTIC"]),
            "hypothetical": len(regimes["HYPOTHETICAL"]),
            "details": {k: v[:5] for k, v in regimes.items()}
        }


if __name__ == "__main__":
    eb = EffectBoundary(epsilon_high=0.7, epsilon_low=0.3)
    
    print("=== Effect-Boundary Audit ===")
    audit = eb.audit_all()
    print(f"Total atoms: {audit['total']}")
    print(f"  Axiomatic (σ≥0.7):     {audit['axiomatic']}")
    print(f"  Probabilistic (0.3<σ<0.7): {audit['probabilistic']}")
    print(f"  Hypothetical (σ≤0.3):    {audit['hypothetical']}")
    print()
    
    # Test specific dispatches
    test_cases = [
        ("NAL_truth_functions", "apply_inference"),
        ("watchdog_daemon", "run_stability_check"),
        ("Zarathustra", "execute_oslf_checker"),
        ("nonexistent_concept", "do_something"),
    ]
    
    print("=== Dispatch Tests ===")
    for concept, action in test_cases:
        result = eb.dispatch(concept, action)
        print(f"  {concept:30s} σ={result['sigma']:.3f} → {result['regime']:15s} → {result['action_taken'][:50]}")
