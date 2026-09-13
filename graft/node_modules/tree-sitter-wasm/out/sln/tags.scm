; Projects act like modules/namespaces
(project_block
  name: (string) @name) @module

; Sections act like functions or structural blocks
(project_section
  name: (identifier) @name) @function

(global_section
  name: (identifier) @name) @function

; Top-level properties
(property
  name: (identifier) @name) @property
