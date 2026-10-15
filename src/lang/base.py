#
# Copyright IBM Corp. 2026
# SPDX-License-Identifier: MIT
#
"""
Language adapter contract for step-1 extraction.

Java support lives in sibling modules of the Python ones (src/identifier_extractor.py,
src/identifier_usage.py) that emit the SAME record shapes, so every downstream
consumer (src/identifier_information.py, identity_projection/*) keeps working unchanged.

------------------------------------------------------------------------------
CONTRACT 1 — catalogue record, per entity
------------------------------------------------------------------------------
extract_rich_entities(code: str, file_path: str, is_new_file: bool = False)
    -> dict[catalogue_key, dict]

Every value dict is passed to IdentifierInformation.model_validate(), so keys
MUST be a subset of that model's fields.  Absent facts are None (never "" or []).

function entity          class entity              variable entity
  name                     name                      name
  entity_type="function"   entity_type="class"       entity_type="variable"
  path                     path                      path
  is_new_file              is_new_file               is_new_file
  partial_location         partial_location          partial_location
  complete_location        complete_location         complete_location
  weak_semantics           weak_semantics            weak_semantics
  strong_semantics         strong_semantics          strong_semantics
  signature                superclass                var_type
  input_spec               generics                  var_value
  input_names              public_methods
  input_types              private_methods
  output_partial_type      cls_methods    (list of function dicts)
  output_complete_type     cls_variables  (list of variable dicts)
  local_variables
  exception_types
  exception_values
  param_defaults

Every top-level entity additionally carries `imports` (file-level, "; "-joined).
List-valued fields are ", "-joined strings EXCEPT cls_methods / cls_variables,
which are real lists of nested dicts.
partial_location  = f"{file_path}:{start_line}"
complete_location = f"{file_path}:{start_line}-{end_line}"   (1-based)

entity_type stays in {"function", "class", "variable"} — the downstream
_ENTITY_GATE recognises only those three.  A Java interface/enum/record/
annotation is entity_type="class" plus entity_kind="interface"|"enum"|... .
entity_kind is a NEW optional field; Python never sets it, so exclude_none
serialisation keeps Python output byte-identical.

------------------------------------------------------------------------------
CONTRACT 2 — catalogue key (Java overloading)
------------------------------------------------------------------------------
Python keys the catalogue by bare name.  Java may declare doThing(String) and
doThing(int) in one class, so Java callables are keyed "name#arity"
(e.g. "doThing#2"); Java types and fields keep the bare name.  The RECORD's
"name" field always stays the bare name — the discriminator lives only in the
dict key, so rendered hints are unaffected.

------------------------------------------------------------------------------
CONTRACT 3 — read/write scanner
------------------------------------------------------------------------------
extract_entities(code: str, local_modules: set[str])
    -> tuple[set[tuple[str, str]], set[tuple[str, str]]]        # (writes, reads)

Typed tokens are (name, entity_type) pairs; entity_type is one of
"function" | "class" | "variable" | "attribute".  Callers project to bare names.
The four instance-level sets (code_read/code_write/test_read/test_write) and all
seven usage operators stay keyed on BARE NAMES — a call site cannot recover
parameter types, so a richer key would make every intersection empty.
"""

from __future__ import annotations

from typing import Protocol, Optional


class LanguageAdapter(Protocol):
    """What a language must supply to step 1."""

    name: str                    # "python" | "java"
    extensions: tuple[str, ...]  # (".py",) | (".java",)

    def parse(self, code: str): ...

    def extract_rich_entities(
        self, code: str, file_path: str, is_new_file: bool = False
    ) -> dict[str, dict]: ...

    def extract_entities(
        self, code: str, local_modules: Optional[set] = None
    ) -> tuple[set, set]: ...

    def path_to_module(self, path: str) -> str: ...
