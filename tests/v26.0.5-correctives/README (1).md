# Jaguar compiler update — 2026-09-21 (v2)

This package contains the current modified Jaguar compiler/build/LSP Python files, the `.ja` examples used for verification, and the final test logs.

## Current fixes

- class-body `signal: member { ... }` handlers;
- positional `struct` value construction such as `v2(3, 5)`;
- direct JCC diagnostics for unsupported binary operators (`no operator exists ...`).

`examples/before/` contains the 10 reference regression programs.
`examples/after/` contains the examples from the previous feature pass.
`examples/new/` contains the current-pass examples.

The official documentation file supplied by the user is intentionally not included as a modified file because it was not changed.

The end-to-end tests used `/usr/bin/gcc` through a temporary `toolchain/bin/gcc` symlink because the uploaded source tree does not contain Jaguar's bundled GCC toolchain. The symlink is not part of the source changes.
