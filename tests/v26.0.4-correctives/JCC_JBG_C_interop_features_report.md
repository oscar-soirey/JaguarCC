# JCC / JBG — C interop: fixed arrays, explicit enums, variadic functions

## Scope

This revision adds three C-interop capabilities to JaguarCC (JCC) and Jaguar BindGen (JBG):

1. Fixed-size arrays with ABI-preserving layout.
2. C enum members with explicit integer initializers.
3. Variadic C function declarations and variadic function-pointer types.

The changes are implemented in the compiler/bindgen path rather than by weakening the generated C ABI.

## Jaguar syntax

### Fixed-size arrays

Jaguar uses the type-first array syntax already accepted by the declaration grammar:

```jaguar
struct Fixed {
    u8[4] bytes;
    f32[2] values;
}
```

Multiple dimensions are represented similarly, for example `u8[2][3]`.

C array parameters keep C's parameter-adjustment rule and are emitted as pointers in the generated C function prototype.

The current implementation intentionally rejects fixed arrays whose element type is itself a pointer (for example `u8*[4]`) rather than guessing at a declaration form.

### Explicit enum values

Jaguar enums can now preserve explicit integer initializers:

```jaguar
enum Test {
    A = 1,
    B = 7,
    C,
    D = 17
}
```

For C headers, JBG evaluates integer constant expressions and emits their resulting integer values. Supported C enum expressions include integer literals, earlier enum members, unary `+`, `-`, `~`, arithmetic, shifts, bitwise operators, and comparisons.

### Variadic declarations

Jaguar can represent a C variadic declaration with `...`:

```jaguar
@extern void c_variadic(i8* fmt, ...);
using CVariadicFn = fn(i8*, ...) -> void;
```

JCC preserves the ellipsis in generated C prototypes and function-pointer types and allows calls with additional positional arguments after the fixed parameters.

Variadic Jaguar function definitions with bodies are intentionally rejected for now because Jaguar does not yet expose a `va_list`/variadic-argument API to function bodies. This prevents generating a superficially valid declaration that cannot be implemented safely from Jaguar.

## JCC changes

- Parser accepts `...` in function declarations and function-pointer types.
- Parser accepts fixed array dimensions in type position.
- Enum declarations retain explicit initializer expressions.
- Resolver distinguishes variadic overloads from non-variadic overloads.
- Call checking accepts additional arguments for variadic functions while still checking all fixed parameters.
- Function-type inference and function-pointer calls preserve the variadic marker.
- C code generation emits real fixed-size C arrays with exact dimensions.
- Array indexing and indexed assignment work for fixed arrays.
- C parameter arrays are emitted as decayed pointers.
- Enum members with explicit values are emitted as explicit C enum initializers.

## JBG changes

- `ArrayDecl` is converted to Jaguar fixed-array syntax outside function parameters.
- Parameter arrays continue to decay to pointers.
- `EllipsisParam` is converted to Jaguar `...` in functions and function-pointer aliases.
- Explicit C enum initializers are evaluated when they are integer constant expressions.
- Unsupported enum initializers are rejected with a warning instead of producing an unsafe ABI guess.

## GLFW validation

The supplied GLFW 3.4 header was regenerated with the modified JBG.

Results:

- 120 external GLFW functions generated.
- 0 JBG warnings.
- `GLFWgamepadstate` is no longer an opaque placeholder.
- Its layout is emitted as:

```jaguar
struct GLFWgamepadstate {
    u8[15] buttons;
    f32[6] axes;
}
```

- `glfwGetGamepadState(int, GLFWgamepadstate*)` remains available with the concrete struct type.
- Array element access generates normal C indexing such as `state.buttons[0]` and `state.axes[0]`.

## Test matrix

### JCC feature tests

`features.ja` validates:

- explicit enum initializers;
- fixed arrays in a struct;
- fixed-array indexing and assignment;
- direct variadic calls.

It transpiles successfully in both normal mode and `--c89` mode.

### Variadic function pointers

`fnptr_variadic_full.ja` validates:

- `using CVariadicFn = fn(i8*, ...) -> void`;
- a function returning that function-pointer type;
- assignment to a function-pointer variable;
- calling the pointer with extra arguments.

The generated C compiles successfully in normal and C89 modes.

### GLFW integration

`glfw_use.ja` validates:

- inclusion of the regenerated GLFW binding;
- construction of `GLFWgamepadstate`;
- calling `glfwGetGamepadState`;
- indexing `state.buttons[0]` and `state.axes[0]`.

The generated C compiles successfully in normal and C89 modes.

### Existing string/C-string regression tests

The previous C-string contextual-conversion behavior remains intact:

- C-string literal passed to `i8*`: PASS.
- Jaguar `string` remains a native Jaguar type: PASS.
- Runtime Jaguar `string` is not implicitly converted to `i8*`: PASS (correct rejection).
- Explicit `i8*` variable initialized from a literal: PASS.

## Files

- `jcc_features_fixed.py` — modified JCC.
- `jbg_features_fixed.py` — modified JBG.
- `glfw3_features_regenerated.jah` — regenerated GLFW binding.
- `jaguar_feature_tests/` — regression and ABI tests.
