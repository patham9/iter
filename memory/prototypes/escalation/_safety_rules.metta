;; Advanced rule-base for testing the Hybrid Escalation Engine.

;; 1. Safety Rule (Existing)
(deffunction check_safety (-> Symbol Bool)
  (match $action
    ("write_system_config" false)
    (else true)))

;; 2. Provenance Rule (New)
;; Denies actions based on unreliable sources (e.g., 'stochastic_lm')
(deffunction check_provenance (-> Symbol Symbol Bool)
  (match (pair $action $source)
    (("update_knowledgebase" "stochastic_lm") false)
    (else true)))

;; 3. Conflict Rule (New)
;; Denies actions that contradict 'Gold Standard' truths
(deffunction check_conflict (-> Symbol Bool)
  (match $action
    ("set_coord_x_10" false) ;; Assume x=10 is a known physical impossibility
    (else true)))

;; 4. Resource Rule (New)
;; Denies actions exceeding logical capacity limits
(deffunction check_resource (-> Symbol Bool)
  (match $action
    ("alloc_infinite_memory" false)
    (else true)))
