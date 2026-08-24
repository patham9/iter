# EIA-01: NOISE-OVERFIT DETECTION (Epistemic Integrity Audit)

## 1. OBJECTIVE
To validate that the Adaptive Policy Mechanism (APM) correctly identifies 'Fragile Consensus' (High STV + Low ERG) and prevents it from being promoted to 'Strategic Policy' (Permanent/Structural rules).

## 2. THEORETICAL THRESHOLDS
- **Fragile Consensus (The Risk):** $\text{STV} \gg \text{ERG}$. 
  - Characterized by high frequency but zero semantic/modality diversity.
  - Risk: "Policy Drift" or "Pattern Lock" (adopting noise as law).
- **Robust Grounding (The Goal):** $\text{STV} \approx \text{ERG}$.
  - Characterized by high frequency and high semantic/modality diversity.
  - Result: "Strategic Policy Upgrade" is permissible.

## 3. TEST PROTOCOL: "THE ECHO-CHAMBER"
1. **Injection:** Programmatically inject a sequence of =20$ episodes of near-identical semantic structure (e.g., "Sensor A confirms state X") with a single provenance type.
2. **STV Check:** Verify $\text{STV} \to 1.0$.
3. **ERG Check:** Verify $\text{ERG} \to 0.1$.
4. **APM Monitoring:** 
   - **PASS:** APM classifies signal as [FRAGILE_CONSENSUS] $\to$ Triggers [TACTICAL_OVERLAY] (e.g., 'Observe more').
   - **FAIL:** APM classifies signal as [ROBUST_GROUNDING] $\to$ Triggers [STRATEGIC_POLICY_DELTA] (e.g., 'Make state X a permanent constraint').

## 4. SUCCESS CRITERIA
- **Zero False Positives:** No 'Fragile Consensus' event shall trigger a 'Strategic Policy' update.
- **Verification Latency:** The time between the th injection and the [TACTICAL_OVERLAY] response must be $< 1$ cycle.

## 5. STATUS
- [ ] Simulation Environment Ready.
- [ ] Injection Tool (episodes_generator.py) Tested.
- [ ] Execution Pending.
