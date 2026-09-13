; Treat projects and the global block as top-level modules or classes
(project_block) @class.outer
(global_block) @class.outer

; Treat sections as smaller, function-like blocks
(project_section) @function.outer
(global_section) @function.outer

; Assignments (Key-Value pairs and properties)
(key_value_pair
  key: (_) @assignment.lhs
  value: (_) @assignment.rhs) @assignment.outer

(property
  name: (identifier) @assignment.lhs
  version: (version) @assignment.rhs) @assignment.outer
