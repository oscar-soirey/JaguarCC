# Jaguar BindGen — GLFW 3.4 validation report

## Goal

Generate a Jaguar Header (`.jah`) from the supplied `glfw3.h`, using the
current Jaguar syntax and ABI rules documented for C interoperability.

## Changes in `jbg_fixed.py`

- Parses multiline preprocessor conditionals instead of treating each `#...`
  line independently.
- Evaluates the common `#if/#ifdef/#ifndef/#elif/#else/#endif` subset used by
  GLFW.
- Handles the C++-only `extern "C" { ... }` wrapper used by `glfw3.h`.
- Automatically selects GLFW's no-OpenGL/no-Vulkan branch when the input is
  clearly a GLFW header; unrelated headers are not affected by this default.
- Removes declaration-only annotation macros from the parser input.
- Propagates annotation classification through simple macro aliases, so
  `GLAPIENTRY -> APIENTRY` is not emitted as an API constant.
- Converts C array parameters to pointers, matching C parameter adjustment.
- Keeps non-parameter arrays unsupported rather than silently changing their
  ABI.
- Sanitizes emitted C identifiers that are Jaguar keywords (`string` becomes
  `string_`, etc.).
- Emits opaque one-byte Jaguar structs for opaque C handles such as
  `GLFWwindow`, `GLFWmonitor` and `GLFWcursor`, because the current JCC
  implementation does not correctly resolve the documented forward
  declarations when they are later used through pointers/function types.
- If a concrete struct contains a non-representable field, emits an opaque
  placeholder instead of a partially-defined struct that would silently have
  the wrong C ABI layout.
- Adds `-D/--define` support for predefined preprocessor symbols.
- Filters internal/header-guard/annotation macros from the generated API.

## Result for GLFW 3.4

Generated file: `glfw3_final.jah`

- 120 external GLFW functions
- 25 `using` aliases, including callback/function-pointer aliases
- 8 Jaguar structs
- 332 object-like macros
- no Vulkan-only GLFW functions are emitted in the default binding
- `glfwUpdateGamepadMappings(..., string)` is emitted with the safe Jaguar
  parameter name `string_`
- `glfwSetClipboardString(..., string)` is emitted with `string_`
- annotation aliases such as `GLAPIENTRY` are not emitted

## Known representability warning

`GLFWgamepadstate` contains two fixed C arrays (`buttons[15]` and `axes[6]`).
Jaguar currently has no fixed-array declaration syntax that JBG can use while
preserving that exact C struct layout. The generator therefore emits a one-byte
opaque placeholder for this struct and reports a warning.

This avoids generating a partial or pointer-substituted struct with a false ABI.
The GLFW pointer-based API remains bindable, but direct field access to the
fixed arrays is not exposed by this generated binding.

## Validation

### Original JBG

The supplied original `jbg(1).py` fails on `glfw3.h` with:

`C parse error: ?: Invalid declaration`

### Fixed JBG

Normal generation succeeds with three explicit representability warnings for
`GLFWgamepadstate`.

`--strict` correctly returns exit code 2 because those warnings are intentional.

The generated Jaguar API was concatenated with a small Jaguar program and
accepted by the current JCC frontend/code generator (exit code 0).

### GCC backend limitation discovered

The current JCC C backend does not yet correctly lower Jaguar functions whose
return type is a function-pointer alias. The GLFW API contains several such
functions (for example the callback setter functions and `glfwGetProcAddress`).
The generated `.jah` uses the documented Jaguar function-pointer syntax and is
therefore semantically appropriate at the JBG level, but full GCC compilation
of the combined generated C currently fails in JCC because its backend emits
raw `fn(...) -> T` syntax in those return positions.

This is a separate JCC backend issue, not a parsing/binding-generation issue in
JBG. It should be fixed in JCC rather than weakening the GLFW ABI in JBG by
changing function-pointer returns to `void*` or another incompatible type.

## Function-set check

Header-declared GLFW API functions (excluding the 4 Vulkan entry points): 120

Generated GLFW API functions: 120

Missing: none

Extra: none
