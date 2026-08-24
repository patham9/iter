# Effect-Boundary Proposal: Formalizing Epistemic Transition in Agentic Agency

## 1. Executive Summary
This proposal defines a mathematical framework for the 'Effect-boundary' ($\epsilon$), a mechanism that dynamically adjusts the rigor of agentic decision-making based on the epistemic certainty of the underlying symbolic claims. By implementing this boundary, we bridge the gap between high-speed symbolic execution and high-integrity probabilistic verification.

## 2. Mathematical Formulation
Let $\mathcal{C}$ be a claim in the LTM with truth-weight $w$ and support episodes $s_{pos}, s_{neg}$. We define the **Certainty Score** $\sigma(\mathcal{C})$ as:
$$\sigma(\mathcal{C}) = \frac{s_{pos}}{s_{pos} + s_{neg} + 1}$$

The **Epistemic Boundary** is defined by two thresholds, $\epsilon_{high}$ and $\epsilon_{low}$, creating three distinct operational regimes:

| Regime | Threshold | Agent Behavior | Verification Protocol |
| :--- | :--- | :--- | :--- |
| **Axiomatic** | $\sigma(\mathcal{C}) \geq \epsilon_{high}$ | High-velocity execution; minimal latency. | Bypass Escalation |
| **Probabilistic** | $\epsilon_{low} < \sigma(\mathcal{C}) < \epsilon_{high}$ | Cautious execution; increased latency. | `check_provenance` / `check_conflict` |
| **Hypothetical** | $\sigma(\mathcal{C}) \leq \epsilon_{low}$ | Exploration-first; high latency. | Information-gathering / Sensor-sweep |

## 3. Implementation via Hybrid Dispatcher
The enforcement of these regimes is handled by the `EscalationEngine`. The dispatcher evaluates the `boundary_status` of a claim before processing any proposal:

- **Status: AXIOMATIC** $\rightarrow$ Direct execution.
- **Status: PROBABILISTIC** $\rightarrow$ Dispatch to `EscalationEngine` (MeTTa verification).
- **Status: HYPOTHETICAL** $\rightarrow$ Re-route to 'Information Acquisition' module.

## 4. Empirical Validation (Simulation Results)
Simulation of the decision-latency curve confirms a non-linear 'epistemic braking' effect. As $\sigma$ approaches $\epsilon_{low}$, the latency spikes, preventing the agent from making high-stakes utility decisions on low-certainty premises.

**Status**: PENDING REVIEW (Patrick)
