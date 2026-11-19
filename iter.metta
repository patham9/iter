;; Iter main loop ("# 4. Main loop" of the original iter.py) in MeTTa (PeTTa).
;; utils.metta provides the helpers (dynamic execution, JSON, file listing), the OpenAI client stays in utils.py.
;; All configuration is here and passed onward to the utils functions as arguments.
;; Python variables of the loop are MeTTa states with the same names (&experience, &post_task_mode, ...).
;; Experience messages are atoms: (user "c") (system "c") (tool "call_id" "c") (assistant "<json>") (raw "<json>")

!(import! &self utils)
!(import_prolog_function atomics_to_string)
!(import_prolog_function string_length)
!(import_prolog_function sub_string)

;; --------------------------------------------------------------------
;; 0. Configuration:
;; --------------------------------------------------------------------
(= (LLM_TIMEOUT) 600)
(= (MAX_TOKENS) 2524)
(= (MAX_TOOLS) 30)
(= (MAX_SKILLS) 30)
(= (MAX_TOOL_DESCRIPTION_CHARS) 500)
(= (DYNAMIC_TIMEOUT) 5)
(= (MODEL) (getenv-default "LLM_MODEL" "mlx-community/gemma-4-26b-a4b-it-4bit"))
(= (BASE_URL) (getenv-default "BASE_URL" "http://192.168.64.1:2277/v1"))
(= (API_KEY) (getenv-default "AI_API_KEY" "dummy"))
(= (MAX_MEMORY_CHARS) 3000) ;When memory turns into an index
(= (KEEP_REASONING_IN_EPISODE) true)
(= (MAX_TOOL_CALLS) 10)
(= (MAX_TOOL_OUTPUT_CHARS) 5000)
(= (MAX_EXPERIENCE_SIZE) 100)   ;20 percent
(= (RETAIN_EXPERIENCE_SIZE) 80) ;jumps
(= (MAX_FAST_STEPS) 50)
(= (SLOW_STEP_DELAY) 10)
(= (ERROR_RECOVERY_TIME) 1) ;after how long to retry when exception occurs
(= (RETURN_VALUE_PRESERVE) 0)
(= (RETURN_VALUE_PRESERVE_MESSAGES) 10)
(= (DEFAULT_DELAY) 0) ;default delay added irregard of whether in slow mode
(= (INIT_WAIT) 10)

;; --------------------------------------------------------------------
;; Small helpers
;; --------------------------------------------------------------------
(= (str-cat $parts) (atomics_to_string $parts))
(= (empty-string $s) (== (string_length $s) 0))
(= (join $sep $list) (if (== $list ()) "" (foldl-atom (cdr-atom $list) (car-atom $list) $acc $x (str-cat ($acc $sep $x)))))
(= (snoc $list $x) (append $list ($x)))
(= (push! $state $x) (change-state! $state (snoc (get-state $state) $x)))
(= (sleep $t) (progn (translatePredicate (sleep $t)) true))
(= (gc) (progn (translatePredicate (garbage_collect)) true))
(= (get_current_time) (format-time "%Y-%m-%d %H:%M:%S"))
(= (step $text) (str-cat ("Step " (get_current_time) ": " $text)))
(= (save_experience) (save_experience (get-state &experience)))
(= (truncate $s $n) (str-cat ((sub_string $s 0 $n $_) " [TRUNCATED]")))
(= (take $n $list) (if (or (<= $n 0) (== $list ())) () (cons-atom (car-atom $list) (take (- $n 1) (cdr-atom $list)))))
(= (drop $n $list) (if (or (<= $n 0) (== $list ())) $list (drop (- $n 1) (cdr-atom $list))))
(= (error_text $error)
   (case $error
         (((Error $type $ctx)
           (let $r (collapse (progn (translatePredicate (= $type (Predicate (python_error $T $V))))
                                    (exception_text $V)))
                (if (== $r ()) (repr $type) (car-atom $r))))
          ($other (repr $other)))))

;; --------------------------------------------------------------------
;; 2. Runtime helpers (receive, slow_wait_for_input)
;; --------------------------------------------------------------------
(= (receive)
   (join "\n" (filter-atom (map-atom (channel_paths) $path
                                     (receive_channel $path (DYNAMIC_TIMEOUT)))
                           $event (not (empty-string $event)))))

(= (slow_wait_for_input) (slow_wait_for_input 0))
(= (slow_wait_for_input $second)
   (if (>= $second (SLOW_STEP_DELAY))
       ""
       (progn (sleep 1)
              (let $event_append (receive)
                   (if (empty-string $event_append)
                       (slow_wait_for_input (+ $second 1))
                       $event_append)))))

;; for i, old_message in enumerate(experience): ...
(= (cleanup_old_messages $experience $i $n)
   (if (== $experience ())
       ()
       (cons-atom (if (< $i (- $n (RETURN_VALUE_PRESERVE_MESSAGES)))
                      (case (car-atom $experience)
                            (((tool $id $content) (if (> (string_length $content) (RETURN_VALUE_PRESERVE))
                                                      (tool $id (truncate $content (RETURN_VALUE_PRESERVE)))
                                                      (tool $id $content)))
                             ((assistant $m) (assistant (strip_reasoning $m)))
                             ((raw $m) (raw (strip_reasoning $m)))
                             ($old_message $old_message)))
                      (car-atom $experience))
                  (cleanup_old_messages (cdr-atom $experience) (+ $i 1) $n))))

;; while experience and experience[0].get("role") == "tool": experience = experience[1:]
(= (drop_leading_tool_messages $experience)
   (if (== $experience ())
       ()
       (case (car-atom $experience)
             (((tool $id $content) (drop_leading_tool_messages (cdr-atom $experience)))
              ($other $experience)))))

;; --------------------------------------------------------------------
;; 4. Main loop
;; --------------------------------------------------------------------
(= (cleanup_interval) (- (MAX_EXPERIENCE_SIZE) (RETAIN_EXPERIENCE_SIZE)))

(= (main)
   (progn (change-state! &experience (load_experience))
          (init_client (BASE_URL) (API_KEY) (LLM_TIMEOUT))
          (sleep (INIT_WAIT))
          (translatePredicate (make_directory_path "memory"))
          (translatePredicate (make_directory_path "skills"))
          (translatePredicate (make_directory_path "transformations"))
          (change-state! &post_task_mode false)
          (change-state! &autonomous_steps 0)
          (change-state! &new_burst true)
          (change-state! &pending_event_append "")
          (change-state! &cleanup_bucket (floor-math (/ (size-atom (get-state &experience)) (cleanup_interval))))
          (Loop)))

;; while True:
(= (Loop)
   (progn
     (let $current_bucket (#// (size-atom (get-state &experience)) (cleanup_interval))
          (if (> $current_bucket (get-state &cleanup_bucket))
              (progn (change-state! &experience (cleanup_old_messages (get-state &experience) 0 (size-atom (get-state &experience))))
                     (change-state! &cleanup_bucket $current_bucket)) _))
     (if (>= (size-atom (get-state &experience)) (MAX_EXPERIENCE_SIZE))
         (progn (change-state! &experience (drop (- (size-atom (get-state &experience)) (RETAIN_EXPERIENCE_SIZE)) (get-state &experience)))
                (change-state! &cleanup_bucket (#// (size-atom (get-state &experience)) (cleanup_interval)))) _)
     (change-state! &experience (drop_leading_tool_messages (get-state &experience)))
     (change-state! &history_checkpoint (size-atom (get-state &experience))) ;before user input
     ;; try:
     (case (collapse (catch (once
       (progn
         (sleep (DEFAULT_DELAY))
         (println! "BEFORE RECEIVE")
         (change-state! &event_append (if (empty-string (get-state &pending_event_append))
                                          (receive)
                                          (get-state &pending_event_append)))
         (println! "AFTER RECEIVE")
         (if (not (empty-string (get-state &event_append)))
             (progn (change-state! &autonomous_steps 0)
                    (change-state! &new_burst false)
                    (change-state! &post_task_mode false)
                    (println! (str-cat ("IN FROM CHANNEL " (get-state &event_append))))
                    (push! &experience (user (step (get-state &event_append))))
                    (save_experience)
                    (change-state! &pending_event_append "")
                    (change-state! &base_temporary_message ()))
             (if (get-state &new_burst)
                 (progn (change-state! &post_task_mode true)
                        (change-state! &new_burst false)
                        (change-state! &base_temporary_message ((user (step "[TASK COMPLETED. DO NOT RE-SEND THE COMPLETED RESPONSE BUT SEND IN CASE YOU FORGOT. NOW QUERY FOR AND PICK A TASK BASED ON YOUR GOALS, PREFERABLY MEMORY CONSOLIDATION: FINDING EPISODES WHICH SUPPORT / CONTRADICT LTM ITEMS, LINKING EPISODES, PROMOTING USEFUL MEMORIES]")))))
                 (if (get-state &post_task_mode)
                     (change-state! &base_temporary_message ((user (step "[NO NEW USER INPUT. CONTINUE AUTONOMOUS WORK. DO NOT REPEAT THE PREVIOUS RESPONSE. ONLY USE send FOR GENUINELY NEW INFORMATION OR WHEN USER INPUT IS NEEDED.]"))))
                     (change-state! &base_temporary_message ((user (step "[NO ADDITIONAL USER INPUT. CONTINUE THE CURRENT USER TASK.]")))))))
         (change-state! &history_checkpoint (size-atom (get-state &experience))) ;as we want not to loose user input even when exception
         (LLMLoop ()) ;the inner while True, sets &INOPS &response &message &tool_calls
         (println! (str-cat ("RESPONSE " (get-state &response) "\nFINISH_REASON " (get-state &finish_reason) "\nUSAGE " (get-state &usage))))
         (push! &experience (assistant (if (KEEP_REASONING_IN_EPISODE)
                                           (get-state &message)
                                           (strip_reasoning (get-state &message)))))
         (change-state! &tool_outputs ())
         (map-atom (get-state &tool_calls) $tool_call (ToolCall $tool_call))
         (change-state! &history_checkpoint (size-atom (get-state &experience))) ;tool calls succeeded, even on later exception we won't unroll them
         (save_experience)
         (println! (str-cat ("Output> " (join "\n" (get-state &tool_outputs)))))
         (change-state! &autonomous_steps (if (empty-string (get-state &event_append)) (+ (get-state &autonomous_steps) 1) 0))
         (let $called_nop (is-member nop (map-atom (get-state &tool_calls) $call (index-atom $call 1)))
              (if $called_nop
                  (progn (change-state! &new_burst true)
                         (change-state! &autonomous_steps 0)
                         (change-state! &pending_event_append (slow_wait_for_input)))
                  (if (>= (get-state &autonomous_steps) (MAX_FAST_STEPS))
                      (progn (change-state! &autonomous_steps 0)
                             (change-state! &pending_event_append (slow_wait_for_input))) _)))
         ok))))
       ;; except Exception as error:
       (((ok) _)
        ($error (progn (println! (str-cat ("Output> " (if (== $error ()) "no result" (error_text (car-atom $error))))))
                       (change-state! &experience (take (get-state &history_checkpoint) (get-state &experience)))
                       (sleep (ERROR_RECOVERY_TIME))))))
     (cut)
     (gc)
     (Loop)))

;; The inner "while True:" which calls the LLM until the response contains a tool call
(= (LLMLoop $retry_message)
   (progn
     (change-state! &temporary_message (append (get-state &base_temporary_message) $retry_message))
     (let ($INOPS $omitted_tools $tool_load_error) (load_tools (MAX_TOOLS) (MAX_TOOL_DESCRIPTION_CHARS) (DYNAMIC_TIMEOUT))
          (progn (change-state! &INOPS $INOPS)
                 (if (not (empty-string $tool_load_error)) (push! &temporary_message (user $tool_load_error)) _)
                 (if (> $omitted_tools 0)
                     (push! &temporary_message (user (str-cat ("[TOOL LIMIT REACHED: " $omitted_tools " tools are currently omitted. Consolidate or remove tools if they are needed.]")))) _)))
     (change-state! &TOOLS (native_tools (get-state &INOPS)))
     (change-state! &TRANSFORMATIONS (load_transformation_descriptions (DYNAMIC_TIMEOUT)))
     (let ($SKILLS $omitted_skills) (load_skills (MAX_SKILLS))
          (progn (change-state! &SKILLS $SKILLS)
                 (if (> $omitted_skills 0)
                     (push! &temporary_message (user (str-cat ("[SKILL LIMIT REACHED: " $omitted_skills " Markdown skills are omitted. Consolidate or remove skills if they are needed.]")))) _)))
     (let* (($memory_contents (memory_files))
            ($memory_len (foldl-atom $memory_contents 0 $acc $mc (+ $acc (string_length (index-atom $mc 1))))))
           (if (<= $memory_len (MAX_MEMORY_CHARS))
               (change-state! &MEMORY (str-cat ("[" (- (MAX_MEMORY_CHARS) $memory_len) " CHARACTERS BELOW MAXIMUM]\n./memory/:\n"
                                                (join "\n\n" (map-atom $memory_contents $mc (let ($path $content) $mc (str-cat ($path ":\n" $content))))))))
               (progn (change-state! &MEMORY (str-cat ("./memory/:\n" (join "\n" (map-atom $memory_contents $mc (index-atom $mc 0))))))
                      (push! &temporary_message (user (str-cat ("[MEMORY FOLDER TOTAL CHARACTER CAPACITY BY FILES NOT BEGINNING WITH _ EXCEEDED BY " (- $memory_len (MAX_MEMORY_CHARS)) " CHARS. FIX THIS FIRST.]")))))))
     (change-state! &request_messages (cons-atom (system (str-cat ("prompt.txt:\n" (read_prompt)
                                                                   "\n\n./transformations/:\n" (get-state &TRANSFORMATIONS)
                                                                   "\n\n" (get-state &MEMORY)
                                                                   "\n\n" (get-state &SKILLS))))
                                                 (append (get-state &experience) (get-state &temporary_message))))
     (let ($request_messages $request_tools $transformation_error) (apply_transformation (get-state &request_messages) (get-state &TOOLS) (DYNAMIC_TIMEOUT))
          (progn (change-state! &request_messages $request_messages)
                 (change-state! &request_tools $request_tools)
                 (if (not (empty-string $transformation_error)) (push! &request_messages (user $transformation_error)) _)))
     (println! "BEFORE LLM")
     (let ($message $finish_reason $response $usage) (llm (get-state &request_messages) (get-state &request_tools) (MODEL) (MAX_TOKENS))
          (progn (change-state! &message $message)
                 (change-state! &finish_reason $finish_reason)
                 (change-state! &response $response)
                 (change-state! &usage $usage)))
     (println! (str-cat ("AFTER LLM " (get-state &response))))
     (let $content (message_content (get-state &message))
          (if (not (empty-string $content))
              (change-state! &message (set_message_content (get-state &message) (str-cat ($content "\n[NOT DELIVERED TO ANY CHANNEL. IF THIS WAS INTENDED AS COMMUNICATION, USE send.]")))) _))
     (change-state! &tool_calls (message_tool_calls (get-state &message)))
     (if (not (== (get-state &tool_calls) ()))
         (progn (change-state! &message (limit_tool_calls (get-state &message) (MAX_TOOL_CALLS)))
                (change-state! &tool_calls (take (MAX_TOOL_CALLS) (get-state &tool_calls)))) ;break
         (LLMLoop (if (== (get-state &finish_reason) length)
                      ((user "[OUTPUT TOKEN LIMIT REACHED. CALL THE REQUIRED TOOL CONCISELY.]"))
                      ((user (str-cat ("[YOUR PREVIOUS RESPONSE CONTAINED NO TOOL CALL AND WAS NOT DELIVERED. CALL AT LEAST ONE TOOL NOW. IF YOU INTENDED THIS CONTENT AS COMMUNICATION, USE send: "
                                       (message_content_repr (get-state &message)) "]")))))))))

;; Body of "for tool_call in message.tool_calls:"
(= (ToolCall ($id $tool_name $arguments))
   (let* ((($status $tool_arguments $parse_error) (parse_tool_arguments $arguments))
          ($tool (filter-atom (get-state &INOPS) $inop (== (index-atom $inop 0) $tool_name)))
          ($ret0 (if (== $status invalid)
                     $parse_error
                     (if (== $tool ())
                         (str-cat ("Unknown tool: " $tool_name))
                         (if (== $status notdict)
                             "Tool arguments must be a JSON object"
                             (invoke_tool (index-atom (car-atom $tool) 1) $arguments (DYNAMIC_TIMEOUT))))))
          ($ret (if (> (string_length $ret0) (MAX_TOOL_OUTPUT_CHARS)) (truncate $ret0 (MAX_TOOL_OUTPUT_CHARS)) $ret0)))
         (progn (push! &experience (tool $id (step $ret)))
                (push! &tool_outputs (str-cat ("tool call: " $tool_name " " $tool_arguments "\ntool return: " $ret))))))

!(main)
