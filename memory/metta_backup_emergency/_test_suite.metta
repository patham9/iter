;; ================================================================
;; Iter Reasoning System Test Suite (2026-08-12, updated 06:47)
;; Run via: metta tool with this code
;; Verifies: NAL (|-), NAL7 Temporal (|-nal7), PLN (|- with PLN link types)
;; ================================================================
;; KEY: PLN uses |- operator (not |~), and truth values are SEPARATE tuple
;; elements: ((Inheritance A B) (stv f c)) NOT (Inheritance A B (stv f c))

!(import! &self lib/lib_nars)
!(import! &self lib/lib_nal7)
!(import! &self lib/lib_pln)

;; STV override for PLN stateless mode
(= (STV $atom) (stv 0.5 0.5))

;; === NAL TESTS (|- operator, --> link type) ===

;; 1. NAL Deduction: socrates -> human -> mortal
!(|- ((--> socrates human) (stv 0.9 0.9)) ((--> human mortal) (stv 0.9 0.9)))
;; Expected: (--> socrates mortal) stv ~0.81/0.6561

;; 2. NAL Induction: bird/raven -> animal
!(|- ((--> raven bird) (stv 0.9 0.9)) ((--> raven animal) (stv 0.9 0.9)))
;; Expected: (--> animal bird) via induction

;; 3. NAL Abduction
!(|- ((--> socrates mortal) (stv 0.9 0.9)) ((--> human mortal) (stv 0.9 0.9)))
;; Expected: (--> human socrates) via abduction

;; 4. NAL Revision
!(|- ((--> sky blue) (stv 0.8 0.9)) ((--> sky blue) (stv 0.7 0.8)))
;; Expected: (--> sky blue) with revised truth ~0.769/0.929

;; 5. NAL Exemplification
!(|- ((--> socrates human) (stv 0.9 0.9)) ((--> socrates mortal) (stv 0.9 0.9)))
;; Expected: (--> human mortal) via exemplification

;; === NAL7 TEMPORAL TESTS (|-nal7 operator) ===

;; 6. Temporal Induction: sunrise -> rooster_crow
!(|-nal7 (sunrise (stv 0.9 0.9)) (rooster_crow (stv 0.8 0.9)))
;; Expected: (=/> sunrise rooster_crow) stv ~0.9/0.393

;; 7. Temporal Syllogism: rain -> wet -> slippery
!(|-nal7 ((=/> rain wet) (stv 0.9 0.9)) ((=/> wet slippery) (stv 0.8 0.8)))
;; Expected: (=/> rain slippery) stv ~0.72/0.518

;; 8. Temporal Modus Ponens
!(|-nal7 (rain (stv 0.9 0.9)) ((=/> rain wet) (stv 0.9 0.9)))
;; Expected: (wet) stv ~0.81/0.656

;; 9. Temporal Abduction
!(|-nal7 (wet (stv 0.9 0.9)) ((=/> rain wet) (stv 0.9 0.9)))
;; Expected: (rain) stv ~0.9/0.422

;; 10. Temporal Analogy (consequent)
!(|-nal7 ((=/> alarm wake) (stv 0.9 0.9)) ((</> wake rouse) (stv 0.8 0.9)))
;; Expected: (=/> alarm rouse) stv ~0.72/0.648

;; 11. Retroactive Syllogism
!(|-nal7 ((=|> sunset dusk) (stv 0.9 0.9)) ((=|> dusk dark) (stv 0.8 0.8)))
;; Expected: (=|> sunset dark) stv ~0.72/0.518

;; 12. Equivalence Resemblance
!(|-nal7 ((</> cat feline) (stv 0.9 0.9)) ((</> feline mammal) (stv 0.8 0.8)))
;; Expected: (</> cat mammal) stv ~0.72/0.706

;; 13. Concurrent Resemblance
!(|-nal7 ((<|> flash thunder) (stv 0.9 0.9)) ((<|> thunder rumble) (stv 0.8 0.8)))
;; Expected: (<|> flash rumble) stv ~0.72/0.706

;; 14. Equivalence Construction
!(|-nal7 ((=|> sunset dusk) (stv 0.9 0.9)) ((=|> dusk sunset) (stv 0.8 0.9)))
;; Expected: (<|> sunset dusk) stv ~0.72/0.81

;; === PLN TESTS (|- operator with PLN link types) ===
;; NOTE: PLN uses same |- operator, but with explicit link type atoms
;; AND truth values as separate tuple elements:
;;   ((Inheritance A B) (stv f c))  — CORRECT
;;   (Inheritance A B (stv f c))   — WRONG (won't match)

;; 15. PLN Deduction (Inheritance)
!(|- ((Inheritance socrates human) (stv 0.9 0.9)) ((Inheritance human mortal) (stv 0.9 0.9)))
;; Expected: (Inheritance socrates mortal) stv ~0.82/0.5

;; 16. PLN Modus Ponens
!(|- (raining (stv 0.9 0.9)) ((Implication raining wet) (stv 0.95 0.9)))
;; Expected: (wet) stv ~0.857/0.81

;; 17. PLN Revision
!(|- (raining (stv 0.8 0.9)) (raining (stv 0.7 0.8)))
;; Expected: (raining) stv ~0.769/0.929

;; 18. PLN Negation
!(|- ((Not fire) (stv 0.9 0.9)))
;; Expected: (fire) stv ~0.1/0.9

;; 19. PLN Symmetric Modus Ponens
!(|- (cat (stv 0.9 0.9)) ((Similarity cat lynx) (stv 0.85 0.9)))
;; Expected: (lynx) stv ~0.802/0.9

;; 20. PLN Induction (Inheritance)
!(|- ((Inheritance raven bird) (stv 0.9 0.9)) ((Inheritance raven animal) (stv 0.9 0.9)))
;; Expected: (Inheritance bird animal) stv ~0.82/0.47

;; 21. PLN Abduction (Inheritance)
!(|- ((Inheritance socrates mortal) (stv 0.9 0.9)) ((Inheritance human mortal) (stv 0.9 0.9)))
;; Expected: (Inheritance socrates human) stv ~0.82/0.47

;; 22. PLN Transitive Similarity
!(|- ((Similarity cat lynx) (stv 0.85 0.9)) ((Similarity lynx feline) (stv 0.8 0.9)))
;; Expected: (Similarity cat feline) stv ~0.703/0.9

;; === CROSS-SYSTEM TEST ===

;; 23. NAL + NAL7 + PLN coexistence
!(|- ((--> cat feline) (stv 0.9 0.9)) ((--> feline mammal) (stv 0.9 0.9)))
!(|-nal7 ((=/> feeding_time cat_hungry) (stv 0.9 0.9)) ((=/> cat_hungry cat_eats) (stv 0.9 0.9)))
!(|- ((Inheritance bird animal) (stv 0.9 0.9)) ((Inheritance animal living_thing) (stv 0.9 0.9)))
;; All three should produce results in same session
