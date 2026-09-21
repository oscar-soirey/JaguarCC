# Jaguar compiler update — 2026-09-21

Contains the modified compiler/build-system/language-server Python files, all Jaguar examples used for regression/feature testing, and the final test logs.

The supplied official documentation file was not modified.

## Modified files

- `compiler/jcc.py`
  - custom `void @decorator(params):func { ... }` declarations and decorator use on void functions;
  - class-member `signal:` handlers, with qualified external member signals rejected;
  - binary operator overload declarations such as `MyStruct operator==(MyStruct a, MyStruct b)`;
  - native `thread:` runtime with `start`, `join`, `detach`, `sleep`, `yield`;
  - existing unary `!` code path left untouched and covered by regression testing.
- `compiler/jbs.py`
  - literal `.jbs` project filename accepted;
  - `.jbs` auto-discovered when JBS is launched without a project argument and that file exists in the current directory.
- `compiler/jlanguage_server.py`
  - `thread:` completion and hover signatures;
  - `operator` remains available as a normal identifier, matching the compiler.

## Examples

- `examples_before/`: 10 pre-existing regression programs run with the compiler before and after the change.
- `examples_after/`: valid and invalid programs covering the requested additions and targeted edge cases.

## Test logs

- `final_jcc_tests.txt` — baseline before/after comparison and primary new tests.
- `final_jcc_extra_tests.txt` — additional decorator-argument, member-string-signal, `operator+`, identifier-stability, and C89-thread checks.
- `final_jbs_tests.txt` — literal `.jbs` explicit and auto-discovery tests.
- `final_lsp_tests.txt` — modified-JCC loading and thread completion checks.

## Environment note

The uploaded compiler source tree did not include the distribution's `toolchain/bin/gcc`. End-to-end compiler tests therefore used a temporary test fixture with the system `/usr/bin/gcc` exposed at the exact `toolchain/bin/gcc` path expected by JCC. This did not alter the shipped source files.
