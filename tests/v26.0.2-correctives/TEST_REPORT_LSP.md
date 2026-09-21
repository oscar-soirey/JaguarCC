# Jaguar Language Server — diagnostic regression report

## Source of truth

The language server now publishes diagnostics exclusively from the colocated JaguarCC module.
The tolerant scanner is retained for completion/hover, but it is not used to invent semantic diagnostics.

Compiler loading order:

1. `JAGUAR_JCC` environment variable, when set.
2. `jcc.py` next to the language server.
3. `jcc_fixed_round2.py` (development/test fallback).
4. `jcc_fixed.py` (development/test fallback).
5. `jcc(9).py` (legacy fallback).

## Targeted checks

| Case | Expected | LSP matches compiler |
|---|---|---|
| const method writes member | error | yes |
| override changes constness | error | yes |
| Calculator `add(i32)` + `add(f64)` | no error | yes |
| `list.size()` | no error | yes |
| `map.size()` | no error | yes |
| `dynamic_list.size()` | no error | yes |
| unknown class member | error | yes |
| bad return type | error | yes |
| bad assignment type | error | yes |

## Previous Jaguar regression suite

24 `.ja` files were checked through the language server and compared structurally with direct `JCC.diagnose_source()` output.

Result: **24/24 exact matches**.

This includes positive tests for classes, inheritance, overloads, virtual methods, structs, unions, enums, namespaces, collections, reflection, signals and constness, plus negative tests for const violations, readonly pointers, shadowing, invalid collection writes, references, invalid `while`, and reflection misuse.

## Important behavior

The LSP does not maintain a second semantic implementation for published diagnostics. This avoids stale rules such as reporting `map.size()` as unknown after JaguarCC already recognizes it, or leaking a method's `const` state into another class member context.
