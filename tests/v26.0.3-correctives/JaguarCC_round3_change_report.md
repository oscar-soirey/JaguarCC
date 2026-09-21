# JaguarCC — Round 3 correction report

## 1. Scope

This round started from `jcc_fixed_round2.py` and the problems identified during the previous compiler review. The goal was not to make individual examples pass with local patches, but to identify the phase and state responsible for each failure and correct the shared mechanism so the related cases are covered as well.

The main areas reviewed were:

- `const` correctness for class objects and class pointers;
- class method overload resolution and duplicate signatures;
- constructor/destructor declaration and selection;
- class types at C ABI boundaries;
- nested collection ownership;
- `map` scalar-key indexing;
- control-flow / non-void return analysis;
- lexical-scope state isolation;
- generated `main` parameter names;
- `@extern` overloading;
- interactions introduced by the fixes themselves.

No compiler functionality was removed merely to make a test pass. Where the runtime representation makes a language construct unsafe, the compiler now diagnoses that construct explicitly.

## 2. `const` class objects

### Previous failure

A declaration such as:

```jaguar
const A a = A();
a.mut();
```

could reach CodeGen as if `a` were an ordinary mutable class instance.

### Root cause

Jaguar class locals are represented as pointers in generated C. The existing read-only tracking mainly tracked scalar variables and pointer qualifiers. A class object declared `const` therefore did not have a separate receiver-const state, even though method calls and member writes need to observe it.

### Correction

A dedicated `_const_object_vars` state is now maintained. It is populated for `const Class` locals and `const` class parameters and is consulted by:

- class member assignment;
- class method calls;
- nested/member expressions that preserve constness.

Generated class method calls additionally receive a `const Class *self` when the method itself is declared `const`.

The compiler now rejects mutation through a const object and accepts const methods on that object.

## 3. Pointer-to-const class receivers

### Previous failure

The same problem existed for:

```jaguar
A* p = new A();
const A* q = p;
q.mut();
```

### Root cause

`pointee_const` was tracked semantically, but the C declaration path used `_decl_c_type(A)` while lowering the pointee. Since bare class types are intentionally represented as `A *` at C ABI boundaries, that produced an extra pointer level (`const A **`) for `const A*`.

### Correction

Added `_pointee_c_type()` which lowers the actual pointee without applying the implicit class-pointer transformation a second time.

This is used by both parameter and local-variable declaration generation. As a result:

```text
const A* q
```

now generates the correct C shape:

```c
const A *q;
```

The same const-receiver logic then correctly rejects non-const methods and accepts const methods.

## 4. `A* const` declarations

### Previous failure

For a custom class type, the parser could interpret:

```jaguar
A* const p = value;
```

as the beginning of an expression rather than as a variable declaration.

### Root cause

The generic variable-declaration fallback occurs after expression parsing. `A * ...` is also a valid expression prefix, so the parser consumed the `*` before seeing the declaration-level `const`.

### Correction

Added a deterministic declaration lookahead for the exact grammar pattern `IDENT * const IDENT` before expression parsing. The declaration now reaches the normal variable-declaration parser and preserves the distinction between a const pointer and a pointer to const data.

## 5. Duplicate class methods

### Previous failure

Methods with the same parameter types could survive resolution if their return types or constness differed, even though the generated C name could not represent both declarations safely.

### Root cause

The earlier resolver primarily treated overloadability through the method name and then generated names from parameter types. Return type is not part of the generated overload identity, and the C backend also cannot safely overload only by `const` in this implementation.

### Correction

`_resolve_classes()` now builds method groups by:

```text
(method name, parameter-type signature)
```

and rejects more than one declaration for the same signature, independent of return type or method constness.

The same duplicate-signature check is applied to constructors.

This prevents the failure from being deferred to GCC and gives a Jaguar-level diagnostic.

## 6. Class method overload resolution

### Previous failure

A class containing:

```jaguar
f64 f(f64 x) { ... }
i32 f(i32 x) { ... }
```

could infer the return type of a call from the first declaration rather than from the overload actually selected.

### Root cause

`infer_type(MemberAccess)` previously used the first matching method declaration to obtain a return type. That is insufficient for overloaded members because the selected overload depends on argument types.

### Correction

The same overload-resolution machinery used for actual calls is now used when resolving a member call's type. Arguments are checked, candidates are scored, and only the selected method's return type is returned to the enclosing expression.

The test is run with both declaration orders to ensure the result no longer depends on source order.

## 7. Overloaded constructors

### Previous failure

The language parser accepted multiple constructors, but CodeGen frequently used the first constructor found in the class rather than resolving the constructor call.

### Root cause

Several independent CodeGen paths used `next(... if is_constructor ...)`. This affected:

- explicit class construction;
- implicit construction of a class local without an initializer;
- base-constructor generation;
- reflection/factory registration.

### Correction

Added `resolve_class_constructor_call()` using the same argument ordering, default-argument, type compatibility, scoring and ambiguity rules as other overload resolution.

Every constructor-use site now calls this resolver instead of selecting the first declaration.

This also fixes base-class constructor selection and allows reflection registration to find a later zero-argument/defaultable constructor.

## 8. Destructors

### Previous failures

Two separate invalid forms were previously able to survive too far:

```jaguar
destr(i32 value) { }
```

and multiple `destr()` declarations.

### Root causes

The parser treated `destr` as a special member but did not reject parameters. CodeGen, however, has a fixed destructor ABI and emits exactly one `Class_destr(Class*)` entry point. Multiple destructor declarations therefore had no coherent representation.

### Correction

The parser now rejects destructor parameters immediately.

The resolver rejects multiple destructors in one class.

The destructor CodeGen remains a single fixed ABI entry point and no longer has to invent behavior for unsupported signatures.

## 9. `@extern` overloading

### Previous failure

Two `@extern` declarations with the same Jaguar name but different parameter types could both be accepted even though `@extern` deliberately preserves the native C symbol.

### Root cause

Normal Jaguar overloads can be mangled, but `@extern` explicitly opts out of mangling. Two declarations would therefore target the same C identifier with incompatible types.

### Correction

The resolver now rejects an `@extern` overload set containing more than one declaration of the same C symbol and reports the problem before C generation.

## 10. Class types at C ABI boundaries

### Previous failure

Jaguar class locals are represented internally as pointers, while bare class types in function parameters/returns and function-pointer aliases were originally lowered through ordinary C struct-value typing.

This made examples such as:

```jaguar
A make(A value) { return value; }
using Callback = fn(A) -> A;
```

inconsistent with how class values are represented everywhere else in generated C.

### Root cause

`c_type()` alone cannot model Jaguar's class ownership/representation rule. CodeGen had special handling for class locals but not for all ABI boundaries.

### Correction

Added `_decl_c_type()` as the C ABI lowering layer. Bare Jaguar class types become `Class *` there, while explicit pointer types retain their pointer depth.

This helper is now used by:

- function return types;
- function parameters;
- class method parameters;
- vtable signatures;
- function-pointer declarations and aliases.

Const class parameters consequently become `const Class *` rather than an unrelated struct value.

## 11. Nested owning collections

### Previous failure

Nested ownership types such as:

```jaguar
list<list<i32>>
map<string,list<i32>>
pair<list<i32>,i32>
```

could reach generic CodeGen paths where the runtime's shallow element-copy representation was incompatible with nested ownership.

### Root cause

The runtime list/map/pair representation copies element storage. A nested owning container would therefore copy ownership state rather than establish an independent ownership graph. Depending on the nested type, this can lead to invalid destruction, aliased storage or double destruction.

This is a runtime-model limitation, not merely a C syntax-generation problem.

### Correction

The resolver now recursively inspects generic types and rejects nested owning collections. The check also follows type aliases, so aliases cannot bypass the rule.

Non-owning/nontop-level generic compositions that the current runtime can represent remain available. For example, `list<pair<i32,f64>>` continues to compile.

## 12. Scalar-key `map` indexing

### Previous failure

The type system accepted maps whose key was not a `string`, but the expression generator only had a useful path for string keys.

### Root cause

The runtime already has a generic `_j_map_get()` mechanism, but its typed convenience paths were incomplete. The CodeGen special case fell through or rejected valid key expressions before it could call the runtime correctly.

### Correction

Map indexing now:

1. infers and checks the key type against the map's declared key type;
2. uses the existing string-specific runtime helpers for strings;
3. uses generated scalar-key helpers for integer, unsigned, floating-point and boolean keys;
4. supports addressable non-string key expressions through the generic runtime path where representation permits it.

The generated helpers use real C types such as `int32_t`, `uint64_t`, `float`, `double` and `_jBool`, not Jaguar alias names that are unavailable to the C compiler.

## 13. Non-void control-flow analysis

### Previous failure

A function such as:

```jaguar
i32 f() {
    while (true) { }
}
```

was previously treated as possibly falling through because the analysis was based on whether the body syntactically contained a `return`.

### Root cause

There are two different notions:

- “the body returns a value”;
- “execution can reach the statement after this construct.”

An unconditional loop with no `break` satisfies the second condition even if it never executes `return`.

### Correction

The flow analysis now models “no fallthrough” directly.

For `loop {}` and `while (true) {}`, the statement is considered non-fallthrough when there is no `break` targeting that loop. Breaks belonging only to nested loops do not invalidate the outer loop's analysis.

A direct `break` still makes the enclosing loop fallible, so a non-void function without another return remains correctly rejected.

## 14. Lexical-scope state isolation

### Previous failure

Compiler state such as `_readonly_vars`, `_pointee_const_vars`, `_const_object_vars`, dynamic reflection markers and signal handlers was stored on the CodeGen object and could survive a nested block.

A name legally reused in a sibling block could therefore inherit semantic state from the first block.

### Root cause

`local_types` was copied per nested block, but the auxiliary semantic sets were not. The variable namespace was therefore lexical while parts of the semantic metadata were effectively global to the whole function.

### Correction

`_gen_scoped()` now snapshots and restores all scope-local semantic state:

- readonly variables;
- pointer-to-const variables;
- const class receivers;
- dynamic reflection variables;
- signal/change handlers.

This keeps the existing outer bindings active while preventing inner names from leaking into later sibling scopes.

## 15. Generated `main` argument names

### Previous failure

Jaguar permits user identifiers such as `argc` and `argv`. The generated C `main` already used those names, so a legal Jaguar declaration could collide with compiler-generated identifiers.

### Root cause

The `main(string param)` lowering inserted C parameters with fixed names independently of the Jaguar function body.

### Correction

The generator now scans declared names in the main function body, including ordinary variables, numeric loop variables and collection-loop variables, and selects collision-free internal names such as `_j_main_argc` / `_j_main_argv`.

This preserves Jaguar identifiers without changing their semantics.

## 16. Reflection with overloaded constructors

Reflection/factory registration was tied to the first constructor declaration. After constructor overloading was made explicit, this became a second-order bug: a registered class could have a valid zero-argument/defaultable constructor after another overloaded constructor.

The factory registration path now asks the constructor resolver whether a zero-argument construction is actually valid, then registers the selected constructor symbol. The generated factory call therefore follows the same constructor semantics as normal source code.

## 17. Regression verification

### Targeted correction suite

A new targeted suite covers the corrected failure modes in both normal and `--c89` modes.

**50/50 checks passed.**

These include:

- const class objects;
- const class pointer parameters;
- mutable const-pointer variables;
- duplicate methods;
- declaration-order-independent method overloads;
- overloaded/default constructors;
- duplicate/parameterized destructors;
- `@extern` overload rejection;
- nested owning collection rejection;
- scalar map keys;
- infinite-loop control flow;
- nested-loop break handling;
- sibling lexical scopes;
- generated-main name collisions;
- class parameters/returns;
- function-pointer aliases carrying class types;
- const method calls and const mutation rejection.

### Existing Jaguar regression suite

The existing large regression matrix was rerun after the final changes:

**24/24 normal/C89 checks passed.**

This includes the previously important combined programs containing classes, inheritance, virtual methods, overrides, constness, constructors/destructors, overloads, enums, structs, unions, nested namespaces, `new`, `=>`, list/map/dynamic_list, reflection and collection APIs.

Representative execution outputs remained unchanged for the existing regression programs.

### Syntax check

`python -m py_compile jcc_fixed_round2.py` also passes.

## 18. Result

The corrected compiler is provided as `jcc_fixed_round3.py`.

The changes were made at the resolver/parser/CodeGen representation boundaries rather than by special-casing the individual regression examples. The final verification therefore checks both the original regression corpus and newly constructed tests derived from the discovered failure mechanisms.
