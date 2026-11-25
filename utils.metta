;; utils.metta: the helpers of Iter's utils.py ported to MeTTa (PeTTa).
;; All configuration lives in iter.metta and is passed in as function arguments.
;; Only what needs Python stays in utils.py, imported via pyimport of petta_lib_easypy:
;;   dynamic_worker (the "--invoke" subprocess that loads tools/channels/transformations),
;;   init_client and chat_completion (OpenAI API), exception_text (Python exception objects).
;; Experience messages are atoms: (user "c") (system "c") (tool "call_id" "c") (assistant "<json>") (raw "<json>")
;; JSON values are SWI-Prolog json terms: objects json([key=value, ...]) keep their key order, arrays are lists, strings are strings.

!(import! &self (library lib_import))
!(git-import! "https://github.com/patham9/petta_lib_easypy.git")
!(import! &self (library petta_lib_easypy lib_easypy))
!(pyimport utils.py)
!(use-module! http/json)
!(use-module! process)
!(use-module! filesex)
!(import_prolog_function atomics_to_string)
!(import_prolog_function atomic_list_concat)
!(import_prolog_function text_to_string)
!(import_prolog_function directory_files)
!(import_prolog_function string_length)
!(import_prolog_function sub_string)

;; --------------------------------------------------------------------
;; Small helpers
;; --------------------------------------------------------------------
(= (succeeds $goal_result) (not (== $goal_result ())))
(= (is-string $x) (succeeds (collapse (progn (translatePredicate (string $x)) yes))))
(= (string-to-atom $s) (progn (translatePredicate (atom_string $atom $s)) $atom))
(= (join-text $sep $list) (text_to_string (atomic_list_concat $list $sep)))
(= (strip $s) (progn (translatePredicate (split_string $s "" " \t\n\r" $parts)) (car-atom $parts)))
(= (first-n $n $list) (if (or (<= $n 0) (== $list ())) () (cons-atom (car-atom $list) (first-n (- $n 1) (cdr-atom $list)))))
(= (starts-with-underscore $name) (succeeds (collapse (progn (translatePredicate (string_concat "_" $rest $name)) yes))))
(= (file-exists $path) (succeeds (collapse (progn (translatePredicate (exists_file $path)) yes))))
(= (directory-exists $path) (succeeds (collapse (progn (translatePredicate (exists_directory $path)) yes))))
(= (file-stem $path) (progn (translatePredicate (file_base_name $path $base)) (translatePredicate (file_name_extension $stem $ext $base)) $stem))
(= (path-parts $path) (progn (translatePredicate (split_string $path "/" "" $parts)) $parts))
(= (getenv-default $name $default) (let $r (collapse (progn (translatePredicate (getenv $name $value)) $value)) (if (== $r ()) $default (text_to_string (car-atom $r)))))
(= (read-text $path) (progn (translatePredicate (read_file_to_string $path $text ((Predicate (encoding utf8))))) $text))
(= (write-text $path $text)
   (progn (translatePredicate (open $path write $stream ((Predicate (encoding utf8)))))
          (translatePredicate (write $stream $text))
          (translatePredicate (close $stream))
          true))

;; sorted(Path(dir).glob("*.py")) without names beginning with _
(= (python-files $dir)
   (if (directory-exists $dir)
       (map-atom (sort-atom (filter-atom (directory_files $dir) $name
                                         (and (succeeds (collapse (progn (translatePredicate (file_name_extension $base py $name)) yes)))
                                              (not (starts-with-underscore $name)))))
                 $name (atomics_to_string ($dir "/" $name)))
       ()))

;; --------------------------------------------------------------------
;; JSON
;; --------------------------------------------------------------------
(= (json-options) ((Predicate (value_string_as string)) (Predicate (null null)) (Predicate (true true)) (Predicate (false false))))
(= (json-parse $text)
   (progn (translatePredicate (open_string $text $stream))
          (translatePredicate (json_read $stream $term (json-options)))
          (translatePredicate (read_string $stream $length $rest))
          (translatePredicate (close $stream))
          (if (== (strip $rest) "") $term (progn (translatePredicate (syntax_error json_extra_data)) $term))))
(= (json-text $term) (progn (translatePredicate (atom_json_term $text $term (cons-atom (Predicate (as string)) (cons-atom (Predicate (width 0)) (json-options))))) $text))
(= (json-text-indented $term) (progn (translatePredicate (atom_json_term $text $term (cons-atom (Predicate (as string)) (json-options)))) $text))
(= (json-term $list) (progn (translatePredicate (=.. $term $list)) $term))
(= (json-list $term) (progn (translatePredicate (=.. $term $list)) $list))
(= (json-pair $key $value) (json-term (cons-atom = (cons-atom $key (cons-atom $value ())))))
(= (json-pair-key $pair) (index-atom (json-list $pair) 1))
(= (json-pair-value $pair) (index-atom (json-list $pair) 2))
(= (json-object $pairs) (json-term (cons-atom json (cons-atom $pairs ()))))
(= (json-pairs $object) (index-atom (json-list $object) 1))
(= (json-is-object $value) (let $list (json-list $value) (and (== (car-atom $list) json) (== (size-atom $list) 2))))
(= (json-keys $object) (map-atom (json-pairs $object) $pair (json-pair-key $pair)))
(= (json-get $object $key $default)
   (let $found (filter-atom (json-pairs $object) $pair (== (json-pair-key $pair) $key))
        (if (== $found ()) $default (json-pair-value (car-atom $found)))))
(= (json-put $object $key $value)
   (json-object (if (is-member $key (json-keys $object))
                    (map-atom (json-pairs $object) $pair (if (== (json-pair-key $pair) $key) (json-pair $key $value) $pair))
                    (append (json-pairs $object) (cons-atom (json-pair $key $value) ())))))
(= (json-delete $object $key) (json-object (filter-atom (json-pairs $object) $pair (not (== (json-pair-key $pair) $key)))))

;; --------------------------------------------------------------------
;; 1. Dynamic execution (python3 utils.py --invoke path function result_file payload_file):
;; --------------------------------------------------------------------
(= (temp-file $content)
   (progn (translatePredicate (tmp_file_stream utf8 $file $stream))
          (translatePredicate (write $stream $content))
          (translatePredicate (close $stream))
          $file))
(= (delete-temp-file $file) (collapse (catch (once (progn (translatePredicate (delete_file $file)) true)))))
(= (process-status $pid) (progn (translatePredicate (process_wait $pid $status ((Predicate (timeout 0))))) $status))
(= (wait-worker $pid $deadline $delay)
   (let $status (process-status $pid)
        (if (and (== $status timeout) (< (current-time) $deadline))
            (progn (translatePredicate (sleep $delay))
                   (wait-worker $pid $deadline (min 0.05 (* 2 $delay))))
            $status)))
(= (kill-worker $pid $inherit_stdin)
   (progn (collapse (catch (once (progn (if $inherit_stdin
                                            (translatePredicate (process_kill $pid 9))
                                            (translatePredicate (process_group_kill $pid 9)))
                                        true))))
          (translatePredicate (process_wait $pid $status))
          true))
(= (exit-code $status)
   (case (json-list $status)
         (((exit $code) $code)
          ((killed $signal) (- 0 $signal))
          ($other (repr $status)))))

(= (worker-options $inherit_stdin)
   (if $inherit_stdin
       ((Predicate (stdin std)) (Predicate (stdout null)) (Predicate (stderr null)))
       ((Predicate (stdin null)) (Predicate (stdout null)) (Predicate (stderr null)) (Predicate (detached true)))))

(= (run-worker $path $function $result_file $payload_file $inherit_stdin $timeout)
   (let* (($utils_py (progn (translatePredicate (absolute_file_name "utils.py" $abs_utils)) $abs_utils))
          ($dynamic_path (progn (translatePredicate (absolute_file_name $path $abs_path)) $abs_path))
          ($argv (cons-atom $utils_py (cons-atom "--invoke" (cons-atom $dynamic_path (cons-atom $function (cons-atom $result_file (cons-atom $payload_file ())))))))
          ($options (worker-options $inherit_stdin))
          ($pid (progn (translatePredicate (process_create (Predicate (path python3)) $argv (cons-atom (Predicate (process $p)) $options))) $p)))
     (let $status (wait-worker $pid (+ (current-time) $timeout) 0.005)
               (if (== $status timeout)
                   (progn (kill-worker $pid $inherit_stdin)
                          (error (atomics_to_string ("TIMEOUT after " $timeout "s"))))
                   (case (collapse (catch (once (json-parse (read-text $result_file)))))
                         ((((Error $type $context)) (error (atomics_to_string ("Dynamic process exited with code " (exit-code $status) " without a valid result"))))
                          (((Error $exception)) (error (atomics_to_string ("Dynamic process exited with code " (exit-code $status) " without a valid result"))))
                          (($output) (if (== (json-get $output ok false) true)
                                         (ok (json-get $output result null))
                                         (error (json-get $output error ""))))
                          ($none (error (atomics_to_string ("Dynamic process exited with code " (exit-code $status) " without a valid result"))))))))))

;; returns (ok result) or (error "text")
(= (invoke_dynamic $path $function $args $kwargs $timeout)
   (let* (($result_file (temp-file ""))
          ($payload_file (temp-file (json-text (json-object ((json-pair args $args) (json-pair kwargs $kwargs))))))
          ($inherit_stdin (and (== (file-stem $path) terminal) (== $function "receive")))
          ($outcome (collapse (catch (once (run-worker $path $function $result_file $payload_file $inherit_stdin $timeout))))))
         (progn (delete-temp-file $result_file)
                (delete-temp-file $payload_file)
                (case $outcome
                      ((((Error $type $context)) (error (repr (Error $type $context))))
                       (((Error $exception)) (error (repr $exception)))
                       (($result) $result)
                       ($none (error "Dynamic execution failed")))))))

(= (no-kwargs) (json-object ()))

;; --------------------------------------------------------------------
;; 2. Library for iter.metta
;; --------------------------------------------------------------------
(= (to_message $atom)
   (case $atom
         (((assistant $message) (json-parse $message))
          ((raw $message) (json-parse $message))
          ((tool $id $content) (json-object ((json-pair role "tool") (json-pair tool_call_id $id) (json-pair content $content))))
          (($role $content) (json-object ((json-pair role (text_to_string $role)) (json-pair content $content)))))))

(= (keys-within $keys $allowed) (== (filter-atom $keys $key (not (is-member $key $allowed))) ()))
(= (json-str $value) (if (is-string $value) $value (json-text $value)))

(= (from_message $message)
   (let* (($role (json-get $message role null))
          ($keys (json-keys $message)))
         (if (and (== $role "tool") (keys-within $keys (role tool_call_id content)))
             (tool (json-str (json-get $message tool_call_id "")) (json-str (json-get $message content "")))
             (if (and (or (== $role "user") (== $role "system"))
                      (and (keys-within $keys (role content)) (is-string (json-get $message content null))))
                 (cons-atom (string-to-atom $role) (cons-atom (json-get $message content "") ()))
                 (if (== $role "assistant")
                     (assistant (json-text $message))
                     (raw (json-text $message)))))))

(= (load_experience)
   (if (file-exists "experience.json")
       (map-atom (json-parse (read-text "experience.json")) $message (from_message $message))
       ()))

(= (save_experience $experience)
   (progn (write-text "experience.tmp" (json-text-indented (map-atom $experience $atom (to_message $atom))))
          (translatePredicate (rename_file "experience.tmp" "experience.json"))
          true))

(= (read_prompt) (strip (read-text "prompt.txt")))

;; returns (("memory/path" "content") ...), files with a path part beginning with _ excluded
(= (memory_files)
   (map-atom (sort-atom (map-atom (filter-atom (collapse (progn (translatePredicate (directory_member "memory" $file ((Predicate (recursive true)) (Predicate (file_type regular))))) $file))
                                               $member (not (is-member true (map-atom (cdr-atom (path-parts $member)) $part (starts-with-underscore $part)))))
                                  $kept (cons-atom (path-parts $kept) (cons-atom (text_to_string $kept) ()))))
             $entry (let $path (index-atom $entry 1)
                         (cons-atom $path (cons-atom (strip (read-text $path)) ())))))

(= (channel_paths) (python-files "channels"))

(= (receive_channel $path $timeout)
   (case (invoke_dynamic $path "receive" () (no-kwargs) $timeout)
         (((ok $event) (if (or (== $event null) (== $event "")) "" (atomics_to_string ("[" (file-stem $path) "] " $event))))
          ((error $error) (atomics_to_string ("[CHANNEL ERROR in " $path ": RuntimeError: " $error ". Repair " $path " if needed.]"))))))

(= (limit-description $description $max_description_chars)
   (if (> (string_length $description) $max_description_chars)
       (atomics_to_string ((sub_string $description 0 $max_description_chars $_) " [DESCRIPTION TRUNCATED]"))
       $description))

(= (tool_metadata $path $max_description_chars $timeout)
   (case (invoke_dynamic $path "__tool_metadata__" () (no-kwargs) $timeout)
         (((ok $metadata) (inop (cons-atom (file-stem $path) (cons-atom $path (cons-atom (limit-description (json-get $metadata description "") $max_description_chars) (cons-atom (json-get $metadata parameters ()) ()))))))
          ((error $error) (failed (atomics_to_string ("[TOOL ERROR in " $path ": RuntimeError: " $error ". Repair " $path " if needed.]")))))))

;; returns ((name path description (parameters)) ...) omitted_tools errors
(= (load_tools $max_tools $max_description_chars $timeout)
   (let* (($paths (python-files "tools"))
          ($results (map-atom (first-n $max_tools $paths) $path (tool_metadata $path $max_description_chars $timeout))))
         ((map-atom (filter-atom $results $result (== (car-atom $result) inop)) $result (index-atom $result 1))
          (- (size-atom $paths) $max_tools)
          (join-text "\n" (map-atom (filter-atom $results $result (== (car-atom $result) failed)) $result (index-atom $result 1))))))

(= (native_tool ($name $path $description $parameters))
   (json-object ((json-pair type "function")
                 (json-pair function (json-object ((json-pair name (text_to_string $name))
                                                   (json-pair description $description)
                                                   (json-pair parameters (json-object ((json-pair type "object")
                                                                                       (json-pair properties (json-object (map-atom $parameters $parameter (json-pair (string-to-atom $parameter) (json-object ((json-pair type "string")))))))
                                                                                       (json-pair required $parameters)
                                                                                       (json-pair additionalProperties false))))))))))

;; returns the OpenAI tool schemas as JSON text
(= (native_tools $inops) (json-text (map-atom $inops $inop (native_tool $inop))))

(= (load_transformation_descriptions $timeout)
   (join-text "\n" (map-atom (python-files "transformations") $path
                             (case (invoke_dynamic $path "__description__" () (no-kwargs) $timeout)
                                   (((ok $description) (atomics_to_string ((file-stem $path) ": " $description)))
                                    ($error (atomics_to_string ((file-stem $path) ": [DESCRIPTION MISSING]"))))))))

(= (transformation_step ($messages $tools $errors) $path $timeout)
   (case (invoke_dynamic $path "transform" (cons-atom $messages (cons-atom $tools ())) (no-kwargs) $timeout)
         (((ok ($new_messages $new_tools)) (cons-atom $new_messages (cons-atom $new_tools (cons-atom $errors ()))))
          ((ok $other) (cons-atom $messages (cons-atom $tools (cons-atom (append $errors (cons-atom (atomics_to_string ("[RUNTIME ERROR in " $path ": ValueError: transform must return (messages, tools). Repair " $path " if needed.]")) ())) ()))))
          ((error $error) (cons-atom $messages (cons-atom $tools (cons-atom (append $errors (cons-atom (atomics_to_string ("[RUNTIME ERROR in " $path ": RuntimeError: " $error ". Repair " $path " if needed.]")) ())) ())))))))

;; messages as atoms, tools as JSON text
(= (apply_transformation $messages $tools $timeout)
   (let ($new_messages $new_tools $errors) (foldl-atom (python-files "transformations")
                                                       ((map-atom $messages $atom (to_message $atom)) (json-parse $tools) ())
                                                       $state $path (transformation_step $state $path $timeout))
        ((map-atom $new_messages $message (from_message $message)) (json-text $new_tools) (join-text "\n" $errors))))

;; returns message_json finish_reason response usage
(= (llm $messages $tools $model $backup_model $tool_choice $max_tokens) (chat_completion (json-text (map-atom $messages $atom (to_message $atom))) $tools $model $backup_model $tool_choice $max_tokens))

(= (message_content $message)
   (let $content (json-get (json-parse $message) content null)
        (if (and (is-string $content) (not (== $content ""))) $content "")))

(= (message_content_repr $message)
   (let $content (json-get (json-parse $message) content null)
        (if (== $content null) "None" (repr $content))))

(= (set_message_content $message $content) (json-text (json-put (json-parse $message) content (text_to_string $content))))

(= (message_calls $message) (let $calls (json-get (json-parse $message) tool_calls null) (if (== $calls null) () $calls)))

;; returns ((id name arguments) ...)
(= (message_tool_calls $message)
   (map-atom (message_calls $message) $call
             (let $function (json-get $call function null)
                  (cons-atom (json-get $call id "") (cons-atom (string-to-atom (json-get $function name "")) (cons-atom (json-get $function arguments "") ()))))))

(= (limit_tool_calls $message $limit)
   (if (== (message_calls $message) ())
       $message
       (json-text (json-put (json-parse $message) tool_calls (first-n $limit (message_calls $message))))))

(= (strip_reasoning $message) (json-text (json-delete (json-delete (json-delete (json-parse $message) reasoning) reasoning_details) reasoning_content)))

;; returns status(ok/notdict/invalid) printable_arguments error
(= (parse_tool_arguments $arguments)
   (case (collapse (catch (once (json-parse $arguments))))
         ((((Error $type $context)) (invalid $arguments (atomics_to_string ("Invalid tool arguments from model: " (repr $type)))))
          (((Error $exception)) (invalid $arguments (atomics_to_string ("Invalid tool arguments from model: " (repr $exception)))))
          (($parsed) (if (json-is-object $parsed) (ok $arguments "") (notdict $arguments "")))
          ($none (invalid $arguments "Invalid tool arguments from model")))))

(= (invoke_tool $path $arguments $timeout)
   (case (collapse (catch (once (invoke_dynamic $path "run" () (json-parse $arguments) $timeout))))
         ((((ok $result)) (if (== $result null) "None" $result))
          (((error $error)) (atomics_to_string ("Tool execution failed: " $error)))
          ($exception (atomics_to_string ("Tool execution failed: " (repr $exception)))))))
