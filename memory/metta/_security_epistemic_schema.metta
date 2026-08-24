;; EBP SECURITY SCHEMA
;; Formalizing the relationship between certainty and tool access.

;; Type Definitions
(declare $tool Type)
(declare $certainty Type)
(declare $decision Type)

;; EBP Gating Logic:
;; If certainty is high, decision is APPROVED.
;; If certainty is low, decision is REJECTED.
(forall $t $c 
    (==> (and (is_tool $t) (is_certainty $c) (is_high $c)) 
         (is_decision $t APPROVED)))

(forall $t $c 
    (==> (and (is_tool $t) (is_certainty $c) (is_low $c)) 
         (is_decision $t REJECTED)))

;; Axioms for the current system (Phase 4 deployed)
(is_tool shell)
(is_tool python)
(is_tool weather)
(is_tool websearch)

(is_certainty 90)
(is_certainty 10)

(is_high 90)
(is_low 10)

;; Example checks:
;; (check (is_decision shell APPROVED)) -> True
;; (check (is_decision shell REJECTED)) -> False (since 90 is high)