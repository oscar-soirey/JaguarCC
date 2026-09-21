<!--
JAGUAR: THE COMPLETE GUIDE - single-file Markdown source (fully expanded)

This file is the exact text the PDF was typeset from. Content taken from the original
JaguarCC_docs_EN.md has already been merged in, so the file is self-contained.

Custom conventions (standard Markdown otherwise):
  @@part Title | tagline         start of a book part (divider page); "{.appendix}" marks the appendices
  # Title {#slug}                chapter (H1); "{.front}" = front matter, "{.appendix}" = appendix
  ## / ### / ####                section / subsection / small heading (H2 is auto-numbered N.M)
  [[ch:slug]]                    cross-reference, rendered as "Chapter N" / "Appendix X"
  @@lead                         the next paragraph is styled as the chapter's introduction
  @@diagram pipeline|toolchain|inherit   inserts a drawn diagram
  @@ix term; term                adds entries to the index at this position
  :::kind Optional title ... :::  callout box; kind = note, tip, warning, important, design, cfam, try
  ```jaguar / bash / jbs / c / text   fenced code with syntax highlighting per language
-->

# Preface {.front #preface label="Before you begin"}

@@lead
Jaguar is a compiled programming language with a familiar C-like face and a deliberately small, explicit core. This book is the whole story: how to use it, how it works underneath, where its design came from, and where it can go next.

## Who this book is for

You do not need to know C to read this book, but if you do, you will feel at home quickly: Jaguar keeps the braces, the semicolons and the explicit types, and it removes a good part of the sharp edges. The book is written for three kinds of readers:

- **newcomers** who want to learn the language from a first program to a multi-file project;
- **C and C++ programmers** who want to know exactly what is the same, what is different, and why;
- **contributors and tool authors** who need a precise picture of the compiler, the build system and the binding generator.

## How this book is organized

The book is divided into six parts, followed by appendices and an index.

- **Part I, Getting Started**, introduces the language, walks you through compiling a first program and offers a guided tour of every major feature.
- **Part II, The Language** is the reference for the language itself: types, functions, control flow, classes, collections, namespaces and reflection.
- **Part III, The Standard Library** documents the two built-in libraries, `sys` and `jcc`.
- **Part IV, Interoperability and Tooling** covers calling C, generating bindings with BindGen, building projects with JBS and how the compiler works internally.
- **Part V, Guides** contains step-by-step tutorials, short recipes, a C/C++ comparison and a troubleshooting chapter.
- **Part VI, History and Roadmap** tells the design story of the language and proposes a development plan.

You can read the book front to back, but each reference chapter is written to stand on its own. If you are in a hurry, read the tour in [[ch:tour]] and then jump to the guides.

## Conventions used in this book

Code appears in monospaced type. Short fragments such as `sys:print` or `for_loop` appear inline. Complete examples are set in blocks, and each block carries a small label in its upper-right corner:

```jaguar
// Jaguar source code
void main(string param) {
    sys:print("Hello");
}
```

Commands that you type in a terminal are shown on a dark background:

```bash
python jcc.py main.ja -o game
```

Project files and other text such as file listings and diagrams appear on the same light background, labelled accordingly. Occasionally a highlighted box draws attention to something particular:

:::note
Notes add context or point to related material.
:::

:::tip
Tips suggest a better way of doing something.
:::

:::warning
Warnings flag code that will not compile or behavior that is easy to get wrong.
:::

:::design Design note
Design notes explain *why* the language works the way it does.
:::

:::cfam
These boxes compare Jaguar with C and C++ for readers who know those languages.
:::

## About the documentation this book is built on

:::important A reference to the current implementation
The reference chapters of this book describe the compiler's **current implementation**, not a future specification. Some features may be intentionally limited. For any feature not described here, refer to the actual behavior of `jcc.py` rather than assuming that it is inherited from C or C++.
:::


@@part Getting Started | A first look at the language: what it is, how to compile a program, and a guided tour of its main ideas.

# Meet Jaguar {#meet}

@@lead
Jaguar is a compiled language that reads like C, but with explicit types, classes, namespaces, simple built-in collections and a small standard library that keeps you away from raw pointers unless you ask for them.

## What is Jaguar?

**Jaguar** is a compiled language that is translated to C by **JaguarCC** (`jcc.py`), then compiled with GCC. In other words, Jaguar is a source-to-source language: your `.ja` files become plain C, and the C compiler turns that into a native executable.

@@diagram pipeline

Every stage has a clear job. The lexer breaks the text into tokens, the parser builds a tree of the program, the resolver checks names, types, overloads and access rules, and the code generator writes the C. GCC does the rest. We look at each stage in detail in [[ch:internals]].





Jaguar deliberately borrows several ideas from C/C++ while simplifying
certain aspects:

-   syntax close to C;
-   explicit types;
-   classes and inheritance;
-   function overloading;
-   namespaces;
-   simple collections;
-   automatic management of certain objects;
-   limited reflection;
-   `jcc` standard library;
-   C generation compatible with a C89 mode;
-   interoperability with C APIs;
-   Jaguar Headers (`.jah`);
-   C binding generation with BindGen;
-   JBS build system for multi-file projects and libraries.

------------------------------------------------------------------------



## Design philosophy


Jaguar tries to keep a balance between:

-   **ease of use**;
-   **syntax close to C/C++**;
-   **performance of a compiled language**;
-   **explicit type control**;
-   **practical modern features**;
-   **minimal runtime**;
-   **interoperability with C**.

The compiler handles low-level details as much as possible while leaving
the language's essential features explicit.

------------------------------------------------------------------------



Those goals pull in different directions, and much of Jaguar's character comes from how it settles the tension. The result is a language where the common thing is short and the dangerous thing is explicit.

:::design Explicit by design
Jaguar has explicit types, explicit casts (in C syntax only), explicit pointer syntax and an explicit `nullptr`. When something unusual happens, you can see it in the source.
:::

## What Jaguar deliberately leaves out


The general Jaguar language does not directly expose several low-level
C/C++ mechanisms:

-   general pointer arithmetic;
-   `malloc`/`free` as a general Jaguar API;
-   `FILE*`;
-   `memcpy` and other memory primitives as a general Jaguar API;
-   C++ templates;
-   complex C++ features;
-   lambdas;
-   exceptions;
-   multiple inheritance.

However, C interoperability provides a controlled set of low-level
operations and types:

``` text
T*
fn(T1, T2, ...) -> R
&
*
nullptr
```

They exist to allow using real C libraries without turning Jaguar into a
general pointer-oriented language.

The details are documented in the C interoperability section.

Features requiring more complex C mechanisms can be implemented in the C
runtime or exposed via BindGen.

------------------------------------------------------------------------



This list is not a to-do list. It is a set of boundaries, and it is what lets the rest of the language stay small.

## The toolchain at a glance

Three command-line tools make up the Jaguar toolchain, and each one has a single responsibility:

| Tool | Role | Input | Output |
|---|---|---|---|
| `jcc.py` | The compiler (JaguarCC) | `.ja`, `.jah` | C code or an executable |
| `jbs.py` | The build system (JBS) | a `.jbs` project file | executables and libraries |
| `jbg.py` | The binding generator (BindGen) | a C header `.h` | a Jaguar header `.jah` |

@@diagram toolchain

The compiler works on one compilation unit at a time. The build system gathers files, expands imports, calls the compiler and links the result. The binding generator reads C headers so that Jaguar programs can use existing C libraries safely. You will meet each of them in Part IV.


# Compiling Your First Program {#first}

@@lead
In this chapter you will write a two-line program, compile it, run it and understand what the compiler did on your behalf.

## What you need

The Jaguar tools are Python scripts, so the first requirement is a working **Python 3** installation. Beyond that, each tool has its own needs:

- **`jcc.py`** translates Jaguar to C and, when you give it an output name, calls **GCC** automatically to produce the executable.
- **`jbs.py`** looks for a bundled MinGW toolchain (`gcc` and `ar`) relative to its own location, so it does not rely on a separately configured GCC in your `PATH`.
- **`jbg.py`** parses C headers with the `pycparser` Python package.

:::note
This book assumes that the tools (`jcc.py`, `jbs.py`, `jbg.py`) are already available on your machine. The examples run them from a terminal with the `python` command.
:::

## Hello, Jaguar

Create a file named `hello.ja`:

```jaguar
void main(string param) {
    sys:print("Hello, Jaguar!");
}
```

Compile it:

```bash
python jcc.py hello.ja -o hello
```

and run the result. It prints:

```text
Hello, Jaguar!
```

That is the whole workflow. The compiler wrote `hello.c` next to your source, called GCC to build an executable named `hello`, and left both files in place.

### Anatomy of the program

Even this tiny program shows several of Jaguar's habits.

- **`void main(string param)`** is the program's entry point. Jaguar translates this function into a standard C `main`; it never emits a non-standard C `main(string)`. A form returning an integer is also accepted.
- **`sys:print(...)`** calls a function from the built-in `sys` library. The colon is Jaguar's namespace separator, where C++ would write `::`.
- **Braces and semicolons.** Blocks use `{}` and statements generally end with `;`. Jaguar is not sensitive to whitespace or newlines.

## Three ways to run the compiler

### Compile straight to an executable

``` bash
python jcc.py main.ja -o game
```

The compiler generates:

``` text
game.c
game
```

Then calls GCC automatically.

The output name **must not** end with `.c`:

``` bash
python jcc.py main.ja -o game
```

and not:

``` bash
python jcc.py main.ja -o game.c
```

------------------------------------------------------------------------



### Generate C only

Without `-o`, the C is written to standard output:

``` bash
python jcc.py main.ja > main.c
```

------------------------------------------------------------------------



### C89 mode

``` bash
python jcc.py main.ja --c89 -o game
```

In normal mode, declarations may appear after statements, as in C99+.

With `--c89`, Jaguar moves declarations to the beginning of blocks and
leaves initialization at its logical location.

Jaguar semantics remain identical.

------------------------------------------------------------------------



:::tip
Get into the habit of reading the C that Jaguar produces. Run `python jcc.py hello.ja > hello.c` once and open the file: it is the most direct way to understand what a construct means.
:::

## What just happened?

When you ran `jcc.py`, your source went through four stages before GCC ever saw it.

@@diagram pipeline

The **lexer** turns text into tokens (comments are removed here). The **parser** organizes the tokens into a tree and records line numbers for diagnostics. The **resolver** looks up names, chooses function overloads, applies the numeric conversions the language allows and checks access rules. The **code generator** writes C: methods receive an implicit `self`, `string` and the collections are handled by a small runtime, and names are mangled when namespaces or overloads require it.

If any stage finds a problem, you get an error pointing at the relevant line, and no executable is produced.

## Command-line summary

| Command | What it does |
|---|---|
| `python jcc.py main.ja -o game` | Compiles to an executable named `game` and keeps `game.c` |
| `python jcc.py main.ja > main.c` | Writes the generated C to standard output |
| `python jcc.py main.ja --c89 -o game` | Same, with declarations moved to the start of blocks |
| `python jbs.py project.jbs` | Builds every target described in a JBS project |
| `python jbg.py --c api.h` | Generates `api.jah` from a C header |


## Where to go next

If you would like a fast overview of the whole language, continue with the tour in [[ch:tour]]. If you prefer to go step by step, skip to Part II and start with [[ch:syntax]].


# A Tour of Jaguar {#tour}

@@lead
Here is the whole language in a dozen short stops. Every snippet in this tour is taken from, or built directly on, the reference material in Part II, so you can jump to the matching chapter whenever a stop makes you curious.

## Variables and types

Jaguar has explicit, C-like types. Each integer and floating-point type has a short alias (`i32`, `u8`, `f64`, and so on), and `auto` lets the compiler deduce a local variable's type from its initializer.

```jaguar
int health = 100;
f64 speed = 12.5;
bool alive = true;
string name = "Oscar";

const int max_health = 100;   // cannot be modified
auto ratio = 0.75;            // deduced as a decimal
```

More in [[ch:types]] and [[ch:strings]].

## Functions

Parameters can have default values, arguments can be passed by name, and several functions may share a name if their parameters differ.

```jaguar
int add(int a, int b = 10) {
    return a + b;
}

void show(i32 value) {
    sys:print("integer:");
    sys:print(value);
}

void show(f64 value) {
    sys:print("decimal:");
    sys:print(value);
}

void main(string param) {
    sys:print(add(5));             // 15
    sys:print(add(5, 20));         // 25
    sys:print(add(b = 1, a = 2));  // named arguments: 3
    show(10);                      // chooses show(i32)
    show(3.14);                    // chooses show(f64)
}
```

More in [[ch:functions]].

## Control flow

Conditions use the familiar `if` / `else if` / `else`, and braces are mandatory. Loops are where Jaguar differs most from C: `while` takes no condition, and `for_loop` runs from a first value to a last value, **including** the last.

```jaguar
void main(string param) {
    int health = 60;

    if (health > 75) {
        sys:print("high");
    } else if (health > 25) {
        sys:print("medium");
    } else {
        sys:print("low");
    }

    int i = for_loop(0, 3) {
        sys:print(i);          // prints 0, 1, 2 and 3
    }

    while {
        health = health - 20;
        if (health <= 0) {
            break;
        }
    }
}
```

More in [[ch:control]].

## Collections

`list<T>`, `map<K,V>`, `pair<K,V>` and `dynamic_list` are built into the language. Reading with `[]` is allowed; changes go through methods such as `push` and `emplace`. Two dedicated loops, `loop_list` and `loop_map`, walk a collection.

```jaguar
void main(string param) {
    list<int> numbers = {1, 2, 3, 4};
    numbers.push(5);

    map<string, int> scores = {
        "alice", 10,
        "bob", 20
    };
    scores.emplace("charlie", 30);

    auto n = loop_list(numbers) {
        sys:print(n);
    }

    auto entry = loop_map(scores) {
        sys:print(entry.first);
        sys:print(entry.second);
    }
}
```

More in [[ch:collections]].

## Classes

Classes have fields, methods, constructors (`constr`) and destructors (`destr`). Access control uses one-character markers: `$` for public and `%` for protected, with private as the default.

```jaguar
class Player {
    $int health = 100;

    constr(int initial_health) {
        health = initial_health;
    }

    void damage(int amount) {
        health = health - amount;
    }

    bool alive() const {
        return health > 0;
    }
}

void main(string param) {
    Player player = Player(100);
    player.damage(25);
    if (player.alive()) {
        sys:print("Player alive");
    }
}
```

## Inheritance and virtual methods

A derived class names its base class after a comma. A `virtual` method can be replaced by an `override`.

```jaguar
class Enemy {
    virtual void attack() {
        sys:print("enemy attack");
    }
}

class Zombie, Enemy {
    void attack() override {
        sys:print("zombie attack");
    }
}
```

More on both in [[ch:classes]].

## Namespaces

Namespaces group functions and types. The separator is a colon, and namespaces can be nested.

```jaguar
namespace math {
    int add(int a, int b) {
        return a + b;
    }
}

void main(string param) {
    int value = math:add(10, 20);
    sys:print(value);
}
```

More in [[ch:modules]].

## The standard library

Two libraries are built in. `sys` talks to the system (printing, console colors, files, running programs) and `jcc` is a simplified, libc-inspired library for math, strings, characters and the environment.

```jaguar
void main(string param) {
    f64 distance = jcc:sqrt(3.0 * 3.0 + 4.0 * 4.0);
    sys:print(distance);

    string text = jcc:i32_to_string(42);
    sys:print(jcc:string_concat("answer: ", text));
}
```

More in [[ch:sys]] and [[ch:jcc]].

## Talking to C

Jaguar can call C functions with `@extern`, which keeps the exact C name. For larger APIs, BindGen turns a C header into a Jaguar header that you import with `using`.

```jaguar
@extern
int add(int a, int b);
```

More in [[ch:interop]] and [[ch:bindgen]].

## Building projects

Once a program outgrows one file, describe it in a `.jbs` file and let JBS do the work.

```jbs
version 1.0

out build

compile Main {
    main.ja
}
```

```bash
python jbs.py project.jbs
```

More in [[ch:jbs]].

## Reflection

A class marked `@register` can be created from its name at runtime, and its `@exposed` fields can be read and written dynamically.

```jaguar
@register
class Enemy {
    @exposed
    $int health = 100;
}

void main(string param) {
    auto enemy = factory:construct("Enemy");
    enemy.SetMember("health", 25);
    sys:print((int)enemy.GetMember("health"));
}
```

More in [[ch:reflection]].

:::tip Keep going
The best way to learn Jaguar is to type these examples in, compile them, and change one thing at a time. The guides in Part V walk you through five complete programs.
:::


@@part The Language | The reference for Jaguar itself: types, functions, control flow, classes, collections, namespaces and reflection.

# Program Structure and Lexical Elements {#syntax}

@@lead
Before types and functions, a few ground rules about what a Jaguar source file looks like and how the compiler reads it.

## General syntax

Jaguar is **not** whitespace/newline sensitive.

Blocks use `{}` and statements generally end with `;`.

Example:

``` jaguar
int main(string param) {
    int x = 10;
    int y = 20;

    if (x < y) {
        sys:print("x is smaller");
    }

    return 0;
}
```

------------------------------------------------------------------------



## Source files

Jaguar mainly uses two extensions:

-   `.ja`: Jaguar source file;
-   `.jah`: **Jaguar Header**, a Jaguar interface file.

Technically, a `.jah` uses the same syntax as Jaguar. The extension
simply indicates that it is an interface meant to be reused with
`using`.

Example:

``` text
include/
    math.jah
src/
    main.ja
```

Then:

``` jaguar
using math;

void main(string param) {
    math:add(10, 20);
}
```

`.jah` files are especially used for C API bindings generated by
BindGen.

------------------------------------------------------------------------



## Comments

### Single-line comment

``` jaguar
// This is a comment
int x = 10;
```

### Multi-line comment

``` jaguar
/*
   Comment
   spanning multiple lines
*/
```

Documentation comments `/** ... */` are also stripped by the lexer.

------------------------------------------------------------------------



## Literals

### Integers

``` jaguar
0
42
-10
```

### Decimals

``` jaguar
3.14
0.5
10.0
```

### Booleans

``` jaguar
true
false
```

### Strings

``` jaguar
"Hello world"
```

------------------------------------------------------------------------



## The preprocessor

Jaguar keeps certain C preprocessor directives and passes them through
to the generated C. **`#include` is not supported**: C headers must be
brought in with BindGen/Jaguar headers.

The supported directives are:

``` text
#define
#undef

#if
#ifdef
#ifndef
#elif
#else
#endif

#pragma
#error
#warning
#line
```

Example:

``` jaguar
#define PI 3.14159265
#define GAME_VERSION 1

#ifdef JAGUAR_DEBUG
    // debug code
#elif defined(JAGUAR_RELEASE)
    // release code
#else
    // other configuration
#endif
```

Jaguar also accepts `#elseif` as an alternative spelling of `#elif`; it
is normalized to `#elif` in the generated C.

Conditions are evaluated by the C preprocessor during GCC compilation.
Blocks can be nested.

`#include` is deliberately forbidden:

``` jaguar
#include <stdio.h> // invalid
```

To use a C API, use a `.jah` file generated by BindGen along with
`using`.

Macros are not Jaguar variables and their type is not inferred by the
compiler.

``` jaguar
#define START_HEALTH 100

int default_health = START_HEALTH;
```


------------------------------------------------------------------------




## Top-level expressions

The current parser accepts a top-level expression statement, notably a
call:

``` jaguar
initialize();
```

or:

``` jaguar
engine:start();
```

JCC emits the corresponding call at global scope when the expression is
valid in the generated C context.

This is separate from normal function bodies.




# Types, Variables and Operators {#types}

@@lead
Jaguar is statically typed, with a small set of built-in types that map directly onto C types, plus a few types that are managed by the runtime.

## Core types

Every numeric type has a short alias that spells out its size. The compiler normalizes aliases, so `int` and `i32` are the same logical type.

| Jaguar | Alias | Approximate C type |
|---|---|---|
| `void` | none | `void` |
| `int` | `i32` | `int` |
| `uint` | `u32` | `unsigned int` |
| `short` | `i16` | `short` |
| `ushort` | `u16` | `unsigned short` |
| `long` | `i64` | `long long` |
| `ulong` | `u64` | `unsigned long long` |
| `char` | `i8` | `signed char` |
| `uchar` | `u8` | `unsigned char` |
| `sbyte` | `i8` | `signed char` |
| `byte` | `u8` | `unsigned char` |
| `float` | `f32` | `float` |
| `double` | `f64` | `double` |
| `bool` | none | `_jBool` |
| `string` | none | Jaguar string object |

```jaguar
int a = 10;
i32 b = 20;    // exactly the same logical type as int
```

:::design Sized names for portable code
Prefer the sized aliases (`i32`, `u64`, `f64`) when the width matters, for example when talking to C code. Use the C-like names (`int`, `long`, `double`) when it does not. Both spellings are always equivalent.
:::

## Variables

### Declaration

``` jaguar
int x;
f64 speed;
bool alive;
string name;
```

### Initialization

``` jaguar
int x = 42;
f64 speed = 12.5;
bool alive = true;
string name = "Oscar";
```

A local variable can be declared with any known type.

------------------------------------------------------------------------



## Constants with `const`

`const` makes a variable or parameter non-modifiable.

``` jaguar
const int max_health = 100;
```

A parameter can also be `const`:

``` jaguar
void print_value(const int value) {
    sys:print(value);
}
```

Methods can also be declared `const`:

``` jaguar
int get_health() const {
    return health;
}
```

A local `const` variable must be initialized immediately.

``` jaguar
const int x = 10;
```

------------------------------------------------------------------------



## Type inference with `auto`

`auto` deduces the type of a local variable from its initializer.

``` jaguar
auto x = 42;
auto value = 3.14;
auto name = "hello";
```

An `auto` variable must be initialized.

``` jaguar
auto x; // invalid
```

`auto` is intended for local variables and the loop constructs provided
by Jaguar.

------------------------------------------------------------------------



## Global variables

A variable can be declared at global scope:

``` jaguar
int max_health = 100;
f64 gravity = 9.81;
```

A global initializer must be a constant expression:

-   literal;
-   `#define` macro;
-   operation between constants.

This is valid:

``` jaguar
#define MAX_HEALTH 100
int max_health = MAX_HEALTH;
```

This is not valid as a global initialization:

``` jaguar
int x = get_value();
```

Global variables must also be declared before use.

`list`, `map`, and `container` are currently not usable as global
variables.

------------------------------------------------------------------------



## Operators

### Arithmetic

``` text
+   -   *   /   %
```

Example:

``` jaguar
int result = (10 + 5) * 2;
```

### Comparisons

``` text
==  !=  <  >  <=  >=
```

Comparisons produce a `bool`.

``` jaguar
bool result = health <= 0;
```

### Logical

``` text
&&  ||  !
```

Example:

``` jaguar
if (alive && health > 0) {
    sys:print("alive");
}
```

### Precedence

Precedence is close to C's:

``` text
||
&&
== !=
< > <= >=
+ -
* / %
- !
```

Parentheses can be used to make an expression explicit.

------------------------------------------------------------------------



## Casts

Jaguar deliberately uses C cast syntax:

``` jaguar
f64 value = (f64)10;
i32 integer = (i32)3.14;
```

The following form is **not** a Jaguar cast:

``` jaguar
i32(3.14); // this is not cast syntax
```

------------------------------------------------------------------------



## Implicit numeric conversion in calls

The resolver can use simple numeric conversions to choose an overload:

-   integer → other integer type;
-   integer → float;
-   float → other float type.

Example:

``` jaguar
void test(i32 value) {
    sys:print(value);
}

void test(f64 value) {
    sys:print(value);
}

test(10);
test(3.14);
```

If several overloads remain equally valid, the call is considered
ambiguous.

------------------------------------------------------------------------




# Strings {#strings}

@@lead
`string` is a built-in type with its own methods. It is managed by the Jaguar runtime, which means you never allocate or free a string by hand.

## Methods at a glance

| Method | Returns | Purpose |
|---|---|---|
| `length()` | `int` | Number of characters |
| `empty()` | `bool` | True when the string has no characters |
| `equals(other)` | `bool` | Compares the contents of two strings |
| `contains(text)` | `bool` | Tests whether `text` appears inside the string |
| `starts_with(text)` | `bool` | Tests the beginning of the string |
| `ends_with(text)` | `bool` | Tests the end of the string |
| `concat(other)` | `string` | Returns the two strings joined |
| `substring(...)` | `string` | Extracts part of the string |
| `char_at(index)` | `i32` | Character code at an index, or `-1` if the index is invalid |
| `to_upper()` / `to_lower()` | `string` | Returns a case-converted copy |

Every method is described with an example below.

## The `string` type

`string` is Jaguar's native string type.

``` jaguar
string name = "Jaguar";
```

It is not a plain `char*` exposed to the Jaguar program.

### Available methods

#### `length()`

``` jaguar
int n = name.length();
```

#### `empty()`

``` jaguar
bool empty = name.empty();
```

#### `equals()`

``` jaguar
if (name.equals("Jaguar")) {
    sys:print("OK");
}
```

#### `contains()`

``` jaguar
bool found = name.contains("gua");
```

#### `starts_with()`

``` jaguar
bool result = name.starts_with("Jag");
```

#### `ends_with()`

``` jaguar
bool result = name.ends_with("ar");
```

#### `concat()`

``` jaguar
string full = name.concat("CC");
```

#### `substring()`

``` jaguar
string part = name.substring(0, 3);
```

#### `char_at()`

``` jaguar
i32 c = name.char_at(0);
```

The result is the character code, or `-1` if the index is invalid.

#### `to_upper()` / `to_lower()`

``` jaguar
string upper = name.to_upper();
string lower = name.to_lower();
```

------------------------------------------------------------------------



## Constructing an empty string

The identifier `string` has a special zero-argument construction form:

``` jaguar
string text = string();
```

The current implementation maps this to the Jaguar runtime string
constructor.

A non-empty argument list is rejected; use a string literal or the
documented string operations instead.



:::cfam
A Jaguar `string` is not a `char*`. When you need a C string for a native API, use the `i8*` type described in [[ch:interop]].
:::


# Functions {#functions}

@@lead
Functions are the workhorse of a Jaguar program. They look like C functions, and they add default parameters, named arguments and overloading.

## Declaring and calling functions

### Declaration

``` jaguar
int add(int a, int b) {
    return a + b;
}
```

### Call

``` jaguar
int result = add(10, 20);
```

### `void`

``` jaguar
void say_hello() {
    sys:print("Hello");
}
```

------------------------------------------------------------------------



## Default parameters

A parameter can have a default value:

``` jaguar
int add(int a, int b = 10) {
    return a + b;
}
```

Both of the following calls are valid:

``` jaguar
add(5);
add(5, 20);
```

------------------------------------------------------------------------



## Named arguments

Arguments can be passed by name:

``` jaguar
int move(int x, int y, int speed = 1) {
    return x + y + speed;
}

move(y = 20, x = 10);
move(x = 10, y = 20, speed = 5);
```

Once a named argument is used, a positional argument can no longer
follow.

``` jaguar
move(x = 10, 20); // invalid
```

The built-in `jcc:*` and `sys:*` functions do not accept named
arguments.

------------------------------------------------------------------------



## Prototypes

A function can be declared without a body:

``` jaguar
int add(int a, int b);
```

Then defined later:

``` jaguar
int add(int a, int b) {
    return a + b;
}
```

The prototype and the definition must have exactly the same signature.

Two identical prototypes or two identical definitions cause an error.

------------------------------------------------------------------------



## Overloading

Jaguar allows several functions with the same name and different
parameters:

``` jaguar
void print_value(i32 value) {
    sys:print(value);
}

void print_value(f64 value) {
    sys:print(value);
}
```

The compiler chooses the appropriate overload.

Name mangling uses the parameter types when the name is actually
overloaded.

------------------------------------------------------------------------



## How a call is resolved

When a call is encountered, Jaguar looks up:

1.  the namespace and the name;
2.  the candidate functions;
3.  default parameters;
4.  named arguments;
5.  the argument types;
6.  the allowed numeric conversions;
7.  the best-matching overload.

An ambiguous call causes an error.

------------------------------------------------------------------------



## The `main` function

The recommended special form is:

``` jaguar
void main(string param) {
    sys:print("Hello");
}
```

or a form returning an integer, depending on the functions supported by
the program.

Jaguar translates this function into a standard C `main`.

The compiler avoids emitting a non-standard C `main(string)`.

------------------------------------------------------------------------



## Returning values

``` jaguar
int square(int x) {
    return x * x;
}
```

For a `void` function:

``` jaguar
void stop() {
    return;
}
```

------------------------------------------------------------------------



## Native functions with `@extern`

`@extern` prevents name mangling.

``` jaguar
@extern
int my_native_function(int value);
```

The C name stays exactly `my_native_function`.

This notably allows calling functions defined elsewhere in the project
or in a native library.

------------------------------------------------------------------------



:::tip
Named arguments and default parameters work together nicely: give a function sensible defaults, then override only the arguments you care about, by name.
:::


# Control Flow and Scope {#control}

@@lead
Conditions look like C. Loops are where Jaguar goes its own way: `while` has no condition, and `for_loop` includes its last value.

## Conditions

### `if`

``` jaguar
if (health > 0) {
    sys:print("alive");
}
```

### `else`

``` jaguar
if (health > 0) {
    sys:print("alive");
} else {
    sys:print("dead");
}
```

### `else if`

``` jaguar
if (health > 75) {
    sys:print("high");
} else if (health > 25) {
    sys:print("medium");
} else {
    sys:print("low");
}
```

Braces are mandatory.

------------------------------------------------------------------------



## The `while` loop

Jaguar's `while` is deliberately different from C's: it takes **no
condition**.

``` jaguar
while {
    if (health <= 0) {
        break;
    }

    health = health - 1;
}
```

Exiting the loop is done with `break` or `return`.

The following form is forbidden:

``` jaguar
while (health > 0) {
}
```

------------------------------------------------------------------------



:::cfam The condition moves inside the loop
In C, `while (health > 0) { ... }` tests the condition before each iteration. In Jaguar, `while` takes no condition. You write the exit test yourself, and leave with `break`:

```jaguar
while {
    health = health - 10;
    if (health <= 0) {
        break;
    }
}
```
:::

## `break` and `continue`

``` jaguar
while {
    if (value == 10) {
        break;
    }

    if (value == 5) {
        continue;
    }
}
```

They are only valid inside a loop.

------------------------------------------------------------------------



## The `for_loop` loop

Jaguar provides a simplified numeric loop:

``` jaguar
int i = for_loop(0, 10) {
    sys:print(i);
}
```

The final bound is **included**.

So:

``` text
0 1 2 3 4 5 6 7 8 9 10
```

If the start is greater than the end, no iteration is performed.

The index type must be an integer:

``` text
int / i8 / u8 / i16 / u16 / i32 / u32 / i64 / u64
```

The index is read-only inside the loop.

------------------------------------------------------------------------



:::warning The last value is included
`for_loop(0, 10)` runs eleven times: 0, 1, ..., 10. When you walk over a string or a list by index, remember to stop at `length - 1`.
:::

## Variable scope

Each block has its own scope.

``` jaguar
void test() {
    int x = 10;

    if (true) {
        int y = 20;
        sys:print(y);
    }

    // y no longer exists here
}
```

Two sibling blocks can use the same name:

``` jaguar
if (true) {
    int x = 10;
}

if (true) {
    int x = 20;
}
```

On the other hand, shadowing a variable visible from an enclosing scope
is forbidden.

------------------------------------------------------------------------

------------------------------------------------------------------------




# Structs, Enums, Unions and Aliases {#data}

@@lead
Beyond classes, Jaguar has the classic C data-definition tools: plain structs, enumerations, unions and type aliases. They matter most when you work with C APIs.

## Structs

Jaguar structures are simple data structures.

``` jaguar
struct Vector2 {
    f32 x;
    f32 y;
}
```

Usage:

``` jaguar
Vector2 position;
position.x = 10.0;
position.y = 20.0;
```

They are generated as C `typedef struct`.

------------------------------------------------------------------------



## Enumerations

Jaguar supports sequential enums:

``` jaguar
enum Color {
    Red,
    Green,
    Blue
}
```

Values are automatically numbered sequentially by the generated C enum.

Explicit enum initializers are not currently accepted:

``` jaguar
enum Color {
    Red = 10 // invalid
}
```

Enums can also be declared inside namespaces:

``` jaguar
namespace graphics {
    enum Format {
        RGB,
        RGBA
    }
}
```

The generated C enum and its values receive the namespace prefix needed
to avoid collisions.



## Unions

Jaguar supports named unions:

``` jaguar
union Value {
    int integer;
    f32 real;
}
```

A named union also provides its implicit global union storage, so this
form is valid:

``` jaguar
union Value {
    int integer;
    f32 real;
}

void main(string param) {
    Value.integer = 42;
    sys:print((int)Value);
}
```

The union storage is emitted internally with a private C name, while
Jaguar code accesses it through the union name.

A union cast is special: when casting a union value, the target type
must match one of the union members.

``` jaguar
sys:print((int)Value);
sys:print((f32)Value);
```

Casting the union to a type that is not one of its members is a compiler
error.



## Forward declarations

The current parser accepts forward declarations for classes, structs,
and unions:

``` jaguar
class Player;
struct Node;
union Value;
```

These are useful when a pointer or prototype needs to refer to a type
before its full definition.



## Type aliases with `using`

A type alias can be declared with:

``` jaguar
using Number = f64;
```

Aliases can be used anywhere a normal type is accepted.

Aliases can also point to generic types:

``` jaguar
using Scores = map<string, i32>;
```

Circular aliases are rejected.

Function-pointer aliases use the same mechanism:

``` jaguar
using Callback = fn(i32) -> void;
```




# Classes and Objects {#classes}

@@lead
Classes bundle data and behavior. Jaguar's class system is compact: fields, methods, constructors, destructors, single inheritance and virtual dispatch, with access control written as a single character.

## Declaring a class

Jaguar has a class system with:

-   fields;
-   methods;
-   constructors;
-   destructors;
-   inheritance;
-   virtual methods;
-   `override`;
-   access control.

Example:

``` jaguar
class Player {
    $int health = 100;

    void take_damage(int amount) {
        health = health - amount;
    }

    int get_health() const {
        return health;
    }
}
```

------------------------------------------------------------------------



## Access control

Members are private by default.

### Public: `$`

``` jaguar
class Player {
    $int health;
}
```

### Protected: `%`

``` jaguar
class Player {
    %int health;
}
```

### Private

Without a marker:

``` jaguar
class Player {
    int secret_value;
}
```

Access control is checked by the compiler.

------------------------------------------------------------------------



## Methods

``` jaguar
class Player {
    $int health;

    void damage(int amount) {
        health = health - amount;
    }
}
```

Call:

``` jaguar
Player player = Player();
player.damage(10);
```

A method implicitly has a `self` in the generated C.

------------------------------------------------------------------------



## The `this` keyword

Inside a class, `this` refers to the current instance.

``` jaguar
class Player {
    $int health;

    void reset() {
        this.health = 100;
    }
}
```

In the generated C, `this` corresponds to `self`.

`this` is only available inside a class.

------------------------------------------------------------------------



## Constructors with `constr`

``` jaguar
class Player {
    $int health;

    constr(int initial_health) {
        health = initial_health;
    }
}
```

Creation:

``` jaguar
Player player = Player(100);
```

The compiler also generates the object allocation.

------------------------------------------------------------------------



## Destructors with `destr`

``` jaguar
class Player {
    destr() {
        sys:print("destroyed");
    }
}
```

Every class has a destructor entry point generated by the compiler, even
if no `destr()` is written.

With inheritance, the base class's destructor is called automatically.

------------------------------------------------------------------------



## Inheritance

The current syntax is:

``` jaguar
class Enemy {
    $int health;
}

class Zombie, Enemy {
    void attack() {
        health = health - 10;
    }
}
```

The derived class contains the part corresponding to its base class.

------------------------------------------------------------------------



@@diagram inherit

## Virtual methods

A method can be virtual:

``` jaguar
class Enemy {
    virtual void attack() {
        sys:print("enemy attack");
    }
}
```

A derived class can override it:

``` jaguar
class Zombie, Enemy {
    void attack() override {
        sys:print("zombie attack");
    }
}
```

`override` must match a `virtual` method of the base class with an exact
signature.

------------------------------------------------------------------------



## `const` methods

``` jaguar
class Player {
    $int health;

    int get_health() const {
        return health;
    }
}
```

Parameters can also be `const`.

------------------------------------------------------------------------



:::cfam
Class syntax will look familiar, with a few substitutions: `constr` and `destr` replace the class-named constructor and the `~` destructor, the one-character markers `$` and `%` replace the `public:` and `protected:` labels, a base class follows a comma (`class Zombie, Enemy`), and `override` comes after the parameter list.
:::


# Collections and Object Ownership {#collections}

@@lead
Jaguar has its collections built in. You do not import a library or write template arguments by hand: `list`, `map`, `pair` and friends are part of the language, and the runtime manages their memory.

## The collection types

| Type | Holds | Typical use |
|---|---|---|
| `list<T>` | An ordered sequence of `T` | Sequences of numbers, names, IDs |
| `map<K,V>` | Key/value entries | Lookups, scoreboards, settings |
| `pair<K,V>` | Two values, `first` and `second` | The entries produced by `loop_map` |
| `dynamic_list` | Values of several different types | Mixed data such as `{42, "hello", true}` |
| `container<T>` | One value whose data the container owns | Objects created with `new`, destroyed automatically |

:::note
Collections are **created with literals, changed with methods, read with indexing and walked with dedicated loops**. Indexing is read-only, so `numbers[2] = 10;` is not valid; see the section on indexing below. In the current implementation, collections are kept as local variables.
:::

## Lists

`list<T>` is a homogeneous collection.

``` jaguar
list<int> numbers = {1, 2, 3, 4};
```

Adding an element:

``` jaguar
numbers.push(5);
```

Reading an element:

``` jaguar
int value = numbers[2];
```

Indexing is **read-only**.

The following syntax is not allowed:

``` jaguar
numbers[2] = 10;
```

To modify/add values, use the operations provided by the collection.

------------------------------------------------------------------------



## Maps

`map<K,V>` is a key/value collection.

``` jaguar
map<string, int> scores = {
    "alice", 10,
    "bob", 20
};
```

Adding or replacing an entry:

``` jaguar
scores.emplace("charlie", 30);
```

Reading a value:

``` jaguar
int score = scores["alice"];
```

Indexing is read-only:

``` jaguar
scores["alice"] = 100; // invalid
```

To write into the map, use `emplace()`.

The `string` key has content-based comparison.

------------------------------------------------------------------------



## Pairs

A pair contains two values: `first` and `second`.

``` jaguar
pair<string, int> result = {"score", 42};

sys:print(result.first);
sys:print(result.second);
```

`pair` is notably used by `loop_map`.

------------------------------------------------------------------------



## Dynamic lists

`dynamic_list` allows storing several types in the same collection.

``` jaguar
dynamic_list values = {
    42,
    "hello",
    true,
    3.14
};
```

Adding:

``` jaguar
values.push(123);
values.push("world");
```

Size:

``` jaguar
int count = values.size();
```

Type of a value:

``` jaguar
string type = values.type(1);
```

Raw access:

``` jaguar
auto value = values.get(0);
```

Indexing is also available:

``` jaguar
sys:print(values[0]);
```

To extract a primitive value with a known type, a cast can be used:

``` jaguar
i32 number = (i32)values[0];
f64 decimal = (f64)values[3];
```

For objects/classes, the cast keeps the pointer to the stored object.

------------------------------------------------------------------------



## Creating collections with `{}`

Braces can create collection literals.

List:

``` jaguar
list<int> values = {1, 2, 3};
```

Map:

``` jaguar
map<string, int> values = {
    "one", 1,
    "two", 2
};
```

Pair:

``` jaguar
pair<string, int> value = {"score", 42};
```

`dynamic_list`:

``` jaguar
dynamic_list values = {1, "hello", true};
```

------------------------------------------------------------------------



## Walking a list with `loop_list`

`loop_list` iterates over a `list<T>`.

``` jaguar
list<int> numbers = {1, 2, 3, 4};

auto item = loop_list(numbers) {
    sys:print(item);
}
```

During the loop, the collection is treated as read-only.

The following is therefore forbidden:

``` jaguar
auto item = loop_list(numbers) {
    numbers.push(10); // forbidden
}
```

`loop_list` does not work on `dynamic_list`.

------------------------------------------------------------------------



## Walking a map with `loop_map`

`loop_map` iterates over a `map<K,V>` and provides a `pair<K,V>`.

``` jaguar
map<string, int> scores = {
    "alice", 10,
    "bob", 20
};

auto item = loop_map(scores) {
    sys:print(item.first);
    sys:print(item.second);
}
```

The map is read-only during the loop.

------------------------------------------------------------------------



## Indexing

`[]` is available on certain collections.

``` jaguar
int x = numbers[0];
int score = scores["player"];
auto value = values[0];
```

It is deliberately read-only.

`container<T>` values are not indexable.

------------------------------------------------------------------------



## Creating objects with `new`

Jaguar has the `new` expression:

``` jaguar
new Player(100)
```

It can be used in `container` ownership mechanisms.

------------------------------------------------------------------------



## Containers

`container<T>` represents a value whose data is owned by the container.

``` jaguar
container<int> value = new int(42);
```

A short-hand syntax is available:

``` jaguar
container<int> value => 42;
```

Reading:

``` jaguar
int x = value.get();
```

For a class:

``` jaguar
container<Player> player = new Player(100);
player.get().damage(10);
```

The container automatically destroys the object it owns.

`container` values cannot be indexed with `[]`.

------------------------------------------------------------------------



## Memory management

Jaguar deliberately does not give direct access to the entire
memory-related part of libc.

The runtime notably manages:

-   strings;
-   classes;
-   containers;
-   lists;
-   maps;
-   dynamic lists.

Internal structures use C `malloc`, `calloc`, `realloc`, `free`, etc.,
but these pointers are not exposed as a general Jaguar API.

This keeps Jaguar syntax safer and simpler.

------------------------------------------------------------------------



## Where collections can and cannot be used

The collection types are compiler/runtime features rather than C++
templates:

``` text
list<T>
map<K,V>
pair<K,V>
container<T>
dynamic_list
```

The current implementation keeps these collections as local variables.
In particular, generic collection types are not currently valid as
global variables.




# Namespaces and Modules {#modules}

@@lead
Namespaces keep names apart, and `using` brings code from other files and namespaces into scope. Together they let a Jaguar project grow past a single file.

## Namespaces

Namespaces use `:`.

``` jaguar
namespace math {
    int add(int a, int b) {
        return a + b;
    }
}
```

Call:

``` jaguar
int value = math:add(10, 20);
```

Namespaces can be nested:

``` jaguar
namespace engine {
    namespace math {
        int add(int a, int b) {
            return a + b;
        }
    }
}
```

Call:

``` jaguar
engine:math:add(10, 20);
```

The generated C name is mangled to avoid collisions.

Namespaces currently support functions, structs, classes, and nested
namespaces according to the compiler's rules. Global variables directly
inside a namespace are not supported.

------------------------------------------------------------------------



## Importing a namespace

``` jaguar
using namespace math;
```

After this declaration:

``` jaguar
int value = add(10, 20);
```

can resolve to a function in `math` when the namespace lookup is
unambiguous.

Nested namespaces can be imported:

``` jaguar
using namespace engine:math;
```



## Importing one symbol, with an alias

A specific symbol can be imported:

``` jaguar
using math:add;
```

It can also be renamed:

``` jaguar
using math:add as sum;
```

Then:

``` jaguar
int value = sum(10, 20);
```

resolves to the imported function.

The same mechanism is used by the resolver for imported enum symbols.



## Importing a complete Jaguar file

The form:

``` jaguar
using math;
```

requests a Jaguar file named `math.ja` or `math.jah` when processed by
JBS.

The form is different from:

``` jaguar
using namespace math;
```

which imports namespace lookup into the current compilation unit.



:::note
A `using` line can mean three different things: importing a file, opening a namespace, or importing a single symbol. Jaguar header files (`.jah`), which are the usual target of a file import, are covered in [[ch:bindgen]].
:::


# Reflection, Attributes and Signals {#reflection}

@@lead
Reflection lets a program create objects by name and read or write their fields at runtime. It is opt-in: a class must declare itself with `@register`, and each field it exposes must say so with `@exposed`.

## Overview

Jaguar has a deliberately limited reflection system.

A class can be registered with `@register`:

``` jaguar
@register
class Player {
    $int health = 100;
}
```

A public field can be exposed with `@exposed`:

``` jaguar
@register
class Player {
    @exposed
    $int health = 100;
}
```

`@exposed` can only be used on a public field.

------------------------------------------------------------------------



## Creating objects with `factory:construct`

A registered class can be constructed dynamically by name:

``` jaguar
string class_name = "Player";
auto object = factory:construct(class_name);
```

The class must be registered with `@register`.

The name is resolved at runtime.

If the class is not registered, the runtime produces an error.

------------------------------------------------------------------------



## Reading a member with `GetMember`

An exposed member can be retrieved dynamically:

``` jaguar
string member = "health";
int health = (int)object.GetMember(member);
```

The member name is a `string`.

If the member does not exist or is not exposed, the runtime raises an
error.

The cast is important to get a typed value.

------------------------------------------------------------------------



## Testing a member with `MemberExists`

Before a dynamic access:

``` jaguar
string name = "health";

if (object.MemberExists(name)) {
    int health = (int)object.GetMember(name);
}
```

This allows checking whether a member is exposed.

------------------------------------------------------------------------



## Writing a member with `SetMember`

An exposed member can be modified dynamically:

``` jaguar
object.SetMember("health", 50);
```

Primitive values and `string` are supported by the reflection runtime.

------------------------------------------------------------------------



## A complete reflection example

``` jaguar
@register
class Enemy {
    @exposed
    $int health = 100;

    $string name = "Enemy";
}

void main(string param) {
    string class_name = "Enemy";
    auto enemy = factory:construct(class_name);

    if (enemy.MemberExists("health")) {
        sys:print((int)enemy.GetMember("health"));
        enemy.SetMember("health", 25);
        sys:print((int)enemy.GetMember("health"));
    }
}
```

Only members marked `@exposed` are accessible via reflection.

------------------------------------------------------------------------



## Attributes

The attributes currently recognized by the compiler are:

``` text
@extern
@register
@exposed
```

Their use depends on context:


An unknown attribute produces a compilation error.

------------------------------------------------------------------------



The three attributes and their targets are summarized here.

| Attribute | Applies to |
|---|---|
| `@extern` | a function or a global variable |
| `@register` | a class |
| `@exposed` | a public class field |

## Signals: reacting to a variable change

Jaguar has a `signal:` syntax for attaching a block to a variable:

``` jaguar
signal:health {
    sys:print("Health changed");
}
```

This feature is meant to attach a reaction to changes in a variable.

> **Note:** the exact behavior depends on the code generation currently
> implemented in `jcc.py`. This syntax is part of the compiler's AST and
> should be regarded as a Jaguar-specific feature, not a standard C
> construct.

------------------------------------------------------------------------




@@part The Standard Library | Two built-in libraries: sys for talking to the operating system, and jcc for math, strings, characters and the environment.

# The `sys` Library {#sys}

@@lead
`sys` is Jaguar's window on the operating system: printing to the console, coloring output, running other programs and reading or writing files. Everything is reached through the `sys:` prefix.

## Printing

`sys` provides system functions built directly into JaguarCC.

------------------------------------------------------------------------

### `sys:print`

``` jaguar
sys:print("Hello");
sys:print(42);
sys:print(3.14);
sys:print(true);
```

Automatically printable types:

-   `string`
-   `int`
-   `i8`
-   `u8`
-   `i16`
-   `u16`
-   `i32`
-   `u32`
-   `i64`
-   `u64`
-   `float`
-   `f32`
-   `f64`
-   `bool`
-   certain `dynamic_list` values.

Each call prints a value followed by a newline.

------------------------------------------------------------------------



## Console colors

### `sys:console:set_color`

``` jaguar
sys:console:set_color("\\033[31m");
sys:print("Red");
sys:console:reset_color();
```

The function expects an ANSI sequence.

### `sys:console:reset_color`

``` jaguar
sys:console:reset_color();
```

------------------------------------------------------------------------



## Running a program

``` jaguar
int result = sys:execute("program", ".");
```

The second argument represents the working directory.

The result corresponds to the code returned by the system execution.

------------------------------------------------------------------------



## File system

### Reading a file

``` jaguar
string data = sys:fs:read("save.txt");
```

### Writing a file

``` jaguar
sys:fs:write("save.txt", "hello");
```

These functions use the C file API internally without exposing `FILE*`
to the Jaguar language.

------------------------------------------------------------------------



## `sys` at a glance

| Function | Purpose |
|---|---|
| `sys:print(value)` | Prints a value to standard output |
| `sys:console:set_color(code)` | Changes the console text color |
| `sys:console:reset_color()` | Restores the default console color |
| `sys:execute(command)` | Runs an external program |
| `sys:fs:read(path)` | Reads a file |
| `sys:fs:write(path, content)` | Writes a file |

@@ix sys:print; sys:console:set_color; sys:console:reset_color; sys:execute; sys:fs:read; sys:fs:write


# The `jcc` Library {#jcc}

@@lead
`jcc` is a compact, libc-inspired library that ships with the compiler. It covers process control, integer helpers, math, strings, characters, files and the environment, with names chosen to be explicit about types.

:::note Two ways to work with strings
Strings offer methods (`name.length()`) and the `jcc` library offers matching functions (`jcc:string_length(name)`). Both do the same job; use whichever reads better in your code.
:::

## Process control and integer helpers

`jcc` is JaguarCC's simplified standard library.

It exposes functions inspired by libc, but adapted to Jaguar's types and
conventions.

Pointers and overly low-level libc APIs are deliberately not exposed
directly.

------------------------------------------------------------------------

### Process

#### `jcc:exit`

``` jaguar
jcc:exit(0);
```

Terminates the program with the given code.

#### `jcc:abort`

``` jaguar
jcc:abort();
```

Immediately stops the program.

------------------------------------------------------------------------

### Integers

#### `jcc:abs_i32`

``` jaguar
i32 x = jcc:abs_i32(-42);
```

#### `jcc:min_i32`

``` jaguar
i32 x = jcc:min_i32(10, 20);
```

#### `jcc:max_i32`

``` jaguar
i32 x = jcc:max_i32(10, 20);
```

#### `jcc:clamp_i32`

``` jaguar
i32 x = jcc:clamp_i32(value, 0, 100);
```

#### `jcc:random_i32`

``` jaguar
i32 x = jcc:random_i32(0, 100);
```

#### `jcc:time_ms`

``` jaguar
i64 now = jcc:time_ms();
```

Returns a time in milliseconds.

#### `jcc:assert`

``` jaguar
jcc:assert(health >= 0, "health must not be negative");
```

------------------------------------------------------------------------



## Math

All of the following functions primarily use `f64`.


Example:

``` jaguar
f64 distance = jcc:sqrt(x * x + y * y);
f64 angle = jcc:atan2(y, x);
f64 power = jcc:pow(2.0, 8.0);
```

------------------------------------------------------------------------



| Function | Signature |
|---|---|
| `sqrt` | `f64 -> f64` |
| `pow` | `f64, f64 -> f64` |
| `sin`, `cos`, `tan` | `f64 -> f64` |
| `asin`, `acos`, `atan` | `f64 -> f64` |
| `atan2` | `f64, f64 -> f64` |
| `floor`, `ceil`, `round` | `f64 -> f64` |
| `log`, `log10`, `exp` | `f64 -> f64` |
| `fmod` | `f64, f64 -> f64` |

@@ix jcc:sqrt; jcc:pow; jcc:sin; jcc:cos; jcc:tan; jcc:asin; jcc:acos; jcc:atan; jcc:atan2; jcc:floor; jcc:ceil; jcc:round; jcc:log; jcc:log10; jcc:exp; jcc:fmod

## String functions

`jcc` also exposes simple wrappers around string operations.

``` jaguar
string a = "Hello";
string b = " World";

int length = jcc:string_length(a);
bool same = jcc:string_equals(a, b);
string result = jcc:string_concat(a, b);
```

Functions:

``` text
string_length
string_equals
string_compare
string_contains
string_starts_with
string_ends_with
string_concat
string_substring
string_char_at
string_find
string_to_upper
string_to_lower
```

Example:

``` jaguar
if (jcc:string_contains("Hello world", "world")) {
    sys:print("found");
}
```

------------------------------------------------------------------------

------------------------------------------------------------------------



@@ix jcc:string_length; jcc:string_equals; jcc:string_compare; jcc:string_contains; jcc:string_starts_with; jcc:string_ends_with; jcc:string_concat; jcc:string_substring; jcc:string_char_at; jcc:string_find; jcc:string_to_upper; jcc:string_to_lower

## String conversions

String → number:

``` jaguar
i32 a = jcc:string_to_i32("42");
i64 b = jcc:string_to_i64("100000");
f64 c = jcc:string_to_f64("3.14");
```

Number → string:

``` jaguar
string a = jcc:i32_to_string(42);
string b = jcc:i64_to_string(100000);
string c = jcc:f64_to_string(3.14);
```

------------------------------------------------------------------------



@@ix jcc:string_to_i32; jcc:string_to_i64; jcc:string_to_f64; jcc:i32_to_string; jcc:i64_to_string; jcc:f64_to_string

## Character functions

Functions inspired by `ctype.h` use integer character codes.

``` jaguar
bool digit = jcc:is_digit('0');
```

Available functions:

``` text
is_digit
is_alpha
is_alnum
is_space
is_upper
is_lower
to_upper_char
to_lower_char
```

They can be used on the result of `string.char_at()`.

Example:

``` jaguar
i32 c = name.char_at(0);
if (jcc:is_alpha(c)) {
    sys:print("letter");
}
```

------------------------------------------------------------------------



@@ix jcc:is_digit; jcc:is_alpha; jcc:is_alnum; jcc:is_space; jcc:is_upper; jcc:is_lower; jcc:to_upper_char; jcc:to_lower_char

## Files and environment

### `file_exists`

``` jaguar
bool exists = jcc:file_exists("save.dat");
```

### `remove_file`

``` jaguar
bool success = jcc:remove_file("save.dat");
```

### `rename_file`

``` jaguar
bool success = jcc:rename_file("old.txt", "new.txt");
```

### `env_get`

``` jaguar
string home = jcc:env_get("HOME");
```

These functions avoid directly manipulating `FILE*`, `char*`, etc.

------------------------------------------------------------------------



@@ix jcc:file_exists; jcc:remove_file; jcc:rename_file; jcc:env_get

## Reserved libc names

The compiler is aware of several libc names in order to avoid collisions
with Jaguar functions.

For example, the following names are reserved when used as ordinary
Jaguar functions:

``` text
malloc
free
memcpy
memset
printf
scanf
fopen
fclose
strlen
strcmp
strcpy
qsort
rand
srand
system
...
```

The goal is to prevent a Jaguar function from accidentally generating a
C symbol that collides with libc.

When a libc feature is useful, it should ideally be exposed through a
suitable `jcc:*` Jaguar API rather than through raw C pointers.

------------------------------------------------------------------------




@@part Interoperability and Tooling | Calling C, generating bindings, building projects, and a look inside the compiler.

# C Interoperability {#interop}

@@lead
Jaguar compiles to C, so talking to C is a first-class feature rather than an afterthought. This chapter covers the language features that make it possible: `@extern`, pointer types, `nullptr`, C strings, function pointers and ABI-preserving numeric types.

## The big picture


Jaguar can call native C APIs directly. The current compiler uses Jaguar
pointer types and function-pointer types rather than separate `cptr`,
`cstr`, or `cfuncptr` keywords.





@@diagram toolchain

In practice you will mostly declare native functions in one of two ways: by hand with `@extern` for a handful of functions, or by letting BindGen ([[ch:bindgen]]) generate a whole `.jah` header from a C header.

## `@extern`

An external C function can be declared manually:

``` jaguar
@extern
int add(int a, int b);
```

`@extern` prevents Jaguar name mangling and keeps the native C symbol
name.

`@extern` can also be used on a global variable:

``` jaguar
@extern
u32 native_counter;
```

The declaration is emitted as an external C declaration and cannot have
an initializer.



## Pointer types

Pointers use `*` directly on the Jaguar type:

``` jaguar
i32* value;
u32* buffer;
MyStruct* object;
```

Multiple pointer levels are allowed:

``` jaguar
i8** strings;
void** userdata;
```

Pointers are useful primarily for C interoperability and low-level APIs.

The address-of operator `&` produces a pointer:

``` jaguar
u32 buffer = 0;
gl:glGenBuffers(1, &buffer);
```

The unary `*` operator dereferences a pointer:

``` jaguar
i32 value = 10;
i32* ptr = &value;
i32 copy = *ptr;
```

Dereferencing a non-pointer is a compiler error.



## `nullptr`

Use `nullptr` for a null pointer:

``` jaguar
void* handle = nullptr;
```

C-style `NULL` is not the Jaguar null-pointer literal for declarations
such as:

``` jaguar
void* handle = NULL; // invalid
```

This distinction is especially important for global pointer
initializers.



## C strings

A C string such as `const char*` is represented by a pointer type,
normally:

``` jaguar
i8* text;
```

Do not confuse this with Jaguar's native `string` type.

`string` is a Jaguar runtime object, while `i8*` is a raw C character
pointer. BindGen deliberately keeps this ABI distinction.

For example, a C declaration:

``` c
const char* get_name(void);
```

is generated approximately as:

``` jaguar
@extern i8* get_name();
```



## Function-pointer types

Jaguar supports C-compatible function-pointer types with:

``` text
fn(T1, T2, ...) -> ReturnType
```

Example:

``` jaguar
using Callback = fn(i32, i8*) -> void;
```

A function-pointer global can be declared:

``` jaguar
@extern fn() -> void callback;
```

A callback can then be assigned and called:

``` jaguar
void my_callback() {
    sys:print("called");
}

void main(string param) {
    callback = my_callback;
    callback();
}
```

Function-pointer typedefs generated by BindGen use the same
`fn(...) -> ...` syntax.



## ABI-preserving numeric types

Jaguar source should use Jaguar types such as:

``` text
i8  u8
i16 u16
i32 u32
i64 u64
f32 f64
```

JCC converts these to their C ABI representation when generating C. For
example:

``` text
u32  → uint32_t
i64  → int64_t
f32  → float
```

The C spellings such as `unsigned long long` are not Jaguar source
types.



## `auto` and the `=>` pointer shorthand

`auto` remains limited to variables that can be inferred from an
initializer:

``` jaguar
auto value = 42;
```

A pointer declaration can use `=>` as an allocation-and-initialize
shorthand:

``` jaguar
i32* value => 42;
```

This is equivalent in intent to allocating one `i32` initialized with
`42`.

The shorthand is not an arbitrary aliasing operator.



## `const` pointer semantics

Jaguar distinguishes a const pointer value from a pointer to const data.

Examples:

``` jaguar
const i32 value = 10;
const i32* data;
i32* const ptr = &value;
```

For parameters, the compiler also tracks whether the pointed-to object
or the pointer itself is const.

The exact generated C qualifiers preserve this distinction.



## Global `@extern` variables

BindGen can generate external global declarations such as:

``` jaguar
@extern u32 global_counter;
```

Function-pointer globals are also supported:

``` jaguar
@extern fn() -> void callback;
```

An `@extern` global cannot contain a Jaguar initializer.



## A practical C API example

Given:

``` c
typedef void (*ResourceCallback)(void* resource, const void* data, size_t size);

void resource_set_callback(void* resource, ResourceCallback callback);
```

BindGen can generate Jaguar declarations using:

``` jaguar
using resource;

void main(string param) {
    // use the generated API here
}
```

The generated binding preserves pointer and callback ABI information
instead of converting C pointers into Jaguar `string` objects.

------------------------------------------------------------------------



## C to Jaguar cheat sheet

| In C | In Jaguar |
|---|---|
| `NULL` | `nullptr` (writing `NULL` is not valid) |
| `int *p` | `i32* p` |
| `char *text` | `i8* text` (a Jaguar `string` is not a `char*`) |
| `&x` and `*p` | `&x` and `*p` |
| `void (*cb)(int)` | `fn(i32) -> void` |
| `#include "api.h"` | `using api;` with a `.jah` generated by BindGen |

## Generated C and compiler compatibility

Jaguar generates C intended mainly for GCC and modern C compilers.

The mode:

``` bash
--c89
```

asks the generator to produce a layout compatible with C89.

Notably, the runtime avoids using `_Bool` for `bool` and generates its
own `_jBool` type.

------------------------------------------------------------------------




# Jaguar Headers and BindGen {#bindgen}

@@lead
A large C library can have hundreds of declarations. Writing them out by hand would be tedious and error-prone. BindGen reads a C header and writes the Jaguar equivalent for you.

## Jaguar headers (`.jah`)

A `.jah` is a Jaguar interface file. It uses normal Jaguar syntax, but
is intended to be imported and reused.

Example:

``` text
include/
    math.jah
    graphics.jah
src/
    main.ja
```

A source file can request an interface with:

``` jaguar
using math;
using graphics;
```

The current JBS implementation resolves `using name;` by locating
either:

``` text
name.ja
name.jah
```

relative to the `.jbs` file or in an `include` directory.

Imports are recursive. A file imported more than once is only included
once in the combined compilation unit.

`using` is therefore a source/module inclusion mechanism in the current
JBS implementation, not a C `#include`.

------------------------------------------------------------------------



## Generating a `.jah` from a C header

`jbg.py` converts a C header into a Jaguar Header (`.jah`).

Basic usage:

``` bash
python jbg.py --c api.h
```

By default this creates:

``` text
api.jah
```

Specify an output path:

``` bash
python jbg.py --c api.h -o include/api.jah
```

Write the generated binding to standard output:

``` bash
python jbg.py --c api.h --stdout
```

Treat unsupported declarations as a hard failure:

``` bash
python jbg.py --c api.h --strict
```

The output file must use the `.jah` extension.



## How BindGen works

The current JBG implementation parses C with `pycparser`.

Its pipeline is:

``` text
C header
   ↓
comment/preprocessor preparation
   ↓
pycparser AST
   ↓
Jaguar declaration generation
   ↓
.jah
```

Simple object-like `#define` constants are preserved in the generated
Jaguar header.

JBG does not blindly copy C declarations. It converts C ABI types into
Jaguar types understood by the current JCC.

For example:

``` text
C                  Jaguar
--------------------------------
int                int / i32
unsigned int       u32
int64_t            i64
uint64_t           u64
float              f32
double             f64
const char*        i8*
void*              void*
```

JCC then converts the Jaguar ABI types back to the appropriate C
representation during code generation.



## Supported C declarations

The current JBG implementation can generate bindings for:

-   function prototypes;
-   `typedef` aliases;
-   structs;
-   unions;
-   enums with sequential values;
-   pointers;
-   multiple pointer levels;
-   function-pointer types;
-   callback typedefs;
-   function-pointer global variables;
-   ordinary external global variables;
-   forward declarations;
-   nested/anonymous inline structs and unions when a stable field
    context can be generated;
-   compatible object-like macros.

Example callback:

``` c
typedef void (*Callback)(void* userdata);
```

becomes approximately:

``` jaguar
using Callback = fn(void*) -> void;
```

Example function:

``` c
void register_callback(Callback callback);
```

becomes:

``` jaguar
@extern void register_callback(Callback callback);
```



## C strings and ABI preservation

JBG deliberately does not convert `const char*` into Jaguar `string`.

For C ABI compatibility:

``` c
const char* name;
```

becomes approximately:

``` jaguar
i8* name;
```

Jaguar `string` is a runtime-managed Jaguar object and is therefore not
an ABI-compatible replacement for a C `char*`.



## Anonymous aggregate types

When a C header contains inline aggregates such as:

``` c
struct Resource {
    union {
        struct {
            const void* data;
            size_t size;
        } binary;
    } value;
};
```

JBG can synthesize stable Jaguar type names from the containing type and
member names.

This allows the resulting `.jah` to remain expressible using Jaguar's
named `struct` and `union` syntax.



## Unsupported C constructs

The current JCC/JBG syntax does not represent every C declaration.

JBG currently refuses or warns about constructs including:

-   C array declaration types where a Jaguar declaration cannot preserve
    the ABI;
-   variadic functions using `...`;
-   explicit enum member initializers;
-   unsupported C type AST nodes;
-   certain anonymous declarations that have no usable field context;
-   struct fields that are C function declarations rather than supported
    function-pointer types.

JBG reports these as warnings when possible.

With:

``` bash
python jbg.py --c api.h --strict
```

any generated warning causes the command to fail.



## Invalid-header recovery

JBG contains a conservative recovery for one common malformed C pattern:
a function-pointer declarator using a C reserved keyword as its
identifier.

The recovery skips that invalid declaration and emits a warning rather
than allowing the malformed declaration to prevent useful bindings from
the rest of the header.

This recovery is intentionally narrow; JBG does not attempt to guess
arbitrary invalid C syntax because doing so could silently create an
ABI-breaking binding.



## A complete example

Input C:

``` c
typedef struct Resource Resource;

typedef void (*ResourceCallback)(
    Resource* resource,
    const void* data,
    size_t size,
    void* userdata
);

typedef struct ResourceDescriptor {
    const char* name;
    size_t size;
    ResourceCallback callback;
} ResourceDescriptor;

Resource* resource_create(
    const ResourceDescriptor* descriptor,
    Resource** dependencies,
    size_t dependency_count
);
```

Typical generated Jaguar declarations:

``` jaguar
struct Resource;

using ResourceCallback = fn(Resource*, void*, u64, void*) -> void;

struct ResourceDescriptor {
    i8* name;
    u64 size;
    ResourceCallback callback;
}

@extern Resource* resource_create(
    ResourceDescriptor* descriptor,
    Resource** dependencies,
    u64 dependency_count
);
```

The generated file can then be imported through JBS:

``` jaguar
using resource;
```

and the generated C calls retain the C ABI through JCC's type lowering.




# The JBS Build System {#jbs}

@@lead
The compiler translates one program at a time. JBS turns a project into finished executables and libraries: it reads a small project file, gathers the sources, expands imports, calls the compiler and links the result.

## Overview

Jaguar has a separate build system: **JBS (`jbs.py`)**.

The current JBS format is version `1.0`.

A `.jbs` file describes:

-   the output directory;
-   Jaguar source/header files belonging to each target;
-   preprocessor definitions;
-   include directories used to resolve `using`;
-   whether C89 generation is requested;
-   whether generated `.c` files should be kept;
-   libraries and linker arguments;
-   executable, static-library, and shared-library targets.

JBS does not currently run BindGen through a `bindgen` directive.
BindGen is a separate tool described in the **Tools** section.



## Minimal project

``` jbs
version 1.0

out build

compile Main {
    main.ja
}
```

JBS combines the listed Jaguar files, expands their `using` imports,
runs JCC to generate C, then invokes the bundled GCC toolchain.


## `version`

The only supported version is currently:

``` jbs
version 1.0
```

A missing version or another version is rejected.


## `out`

Defines the output directory:

``` jbs
out build
```

The command-line `-o` option overrides the `out` directive:

``` bash
python jbs.py game.jbs -o other_build
```


## `include`

Adds directories searched when resolving:

``` jaguar
using graphics;
```

Example:

``` jbs
include include
```

JBS searches the project directory first, then the configured include
directories.

For `using graphics;`, JBS accepts:

``` text
graphics.ja
graphics.jah
```

It does not treat `include` as a C compiler `-I` directive.


## `define`

Adds a C preprocessor definition to the generated compilation unit:

``` jbs
define GAME_VERSION 2
define ENABLE_FEATURE
define PI 3.14
```

The resulting combined Jaguar source begins with equivalent definitions:

``` c
#define GAME_VERSION 2
#define ENABLE_FEATURE
#define PI 3.14
```

This is useful with Jaguar's supported preprocessor directives.


## `c89`

The directive:

``` jbs
c89
```

asks JCC to generate C89-compatible block declaration layout.

It has the same semantic goal as:

``` bash
python jcc.py main.ja --c89
```


## `keep_c`

By default, JBS removes the intermediate `.c` file after the final
output has been produced.

Use:

``` jbs
keep_c
```

to keep the generated C file for inspection or debugging.


## `compile`

Builds an executable:

``` jbs
compile Main {
    src/main.ja
    src/player.ja
    include/game.jah
}
```

The files must use `.ja` or `.jah`.

JBS performs:

``` text
.ja / .jah
      ↓
expand using
      ↓
     JCC
      ↓
     .c
      ↓
    bundled GCC
      ↓
 executable
```

Several targets may exist in one `.jbs` file.

Without `--target`, targets are built in the order in which they appear
in the project file.


## `compile_static`

Builds a static library:

``` jbs
compile_static MyLib {
    src/math.ja
    src/player.ja
}
```

The normal result is:

``` text
libMyLib.a
```

A static-library target does not require `main`.

JBS first generates C, compiles it to an object file, then archives the
object with `ar`.


## `compile_shared`

Builds a shared library:

``` jbs
compile_shared MyLib {
    src/math.ja
}
```

On Windows/MinGW the output is a DLL plus an import library:

``` text
MyLib.dll
MyLib.dll.a
```

On other supported environments the generated shared-library filename
follows the platform convention used by the current JBS implementation.


## `link`

A target can specify libraries or linker arguments:

``` jbs
link Main {
    MyLib
    SDL2
}
```

Entries beginning with `-` are passed as linker arguments.

Examples:

``` jbs
link Main {
    -lSDL2
    -Lthird_party/lib
}
```

JBS also resolves common library names and paths, including:

``` text
MyLib
MyLib.a
libMyLib.a
MyLib.lib
libMyLib.so
MyLib.dll.a
```

It searches the output directory and project directory when resolving
library files.


## `--target`

Build only one target:

``` bash
python jbs.py game.jbs --target Main
```

If the target does not exist, JBS reports an error.

Without `--target`, all targets are built in file order.

This is useful when a project defines a library before an executable
that links it.


## JBS command line

Current command-line forms are:

``` bash
python jbs.py project.jbs
python jbs.py project.jbs -o build
python jbs.py project.jbs --target Main
```

Unknown command-line options are rejected.

The project file must have the `.jbs` extension.

JBS automatically looks for `jcc.py` next to `jbs.py`.


## Toolchain

The current JBS implementation resolves the bundled MinGW toolchain
relative to `jbs.py`:

``` text
toolchain/
└── mingw64/
    └── bin/
        ├── gcc
        └── ar
```

JBS therefore does not rely on a separately configured GCC in `PATH` for
its normal build steps.

The exact executable suffix depends on the host platform.


## `using` expansion

JBS expands imports before invoking JCC.

For:

``` jaguar
using math;
```

it searches for `math.ja` or `math.jah`, inserts that file's contents,
and removes the `using` directive from the combined compilation unit.

Imports can themselves contain `using` directives.

Circular imports are detected and reported.

Already-loaded files are not inserted twice.


## Full project example

``` text
MyGame/
├── project.jbs
├── include/
│   ├── graphics.jah
│   └── engine.jah
├── src/
│   ├── main.ja
│   └── game.ja
├── lib/
│   └── libMyEngine.a
└── build/
```

`project.jbs`:

``` jbs
version 1.0

out build
include include

c89
keep_c

define GAME_VERSION 1

compile Main {
    src/main.ja
    src/game.ja
    include/graphics.jah
}

link Main {
    MyEngine
}
```

The resulting build flow is:

``` text
project.jbs
    ↓
JBS
    ↓
expand .ja / .jah + using
    ↓
JCC
    ↓
Main.c
    ↓
GCC + libraries
    ↓
build/Main
```

------------------------------------------------------------------------



## Recommended project organization

A typical organization can be:

``` text
Project/
├── build/
├── include/
│   ├── engine.jah
│   └── glad.jah
├── lib/
│   ├── libMyEngine.a
│   └── ...
├── src/
│   ├── main.ja
│   └── game.ja
└── project.jbs
```

Reusable interfaces are placed in `.jah` files, implementations in `.ja`
files, and external C APIs are generally introduced via `jbg.py`.

------------------------------------------------------------------------




# Under the Hood: How JaguarCC Works {#internals}

@@lead
You can use Jaguar without knowing how the compiler works, but a little knowledge goes a long way when you read generated C, debug a linker error or write an editor plugin.

## From source to executable

@@diagram pipeline

JaguarCC is a Python program (`jcc.py`) organized as four stages, followed by the C compiler:

1. The **lexer** reads the source text and produces tokens. Comments, including documentation comments written `/** ... */`, are removed here.
2. The **parser** builds a syntax tree and keeps track of source lines in its nodes, so that diagnostics can point to the right place.
3. The **resolver** looks up names, chooses function overloads, applies the allowed numeric conversions and checks access control.
4. The **code generator** emits C, plus the small runtime that backs strings, classes, containers, lists, maps and dynamic lists.

GCC then compiles the C, and JBS (when you use it) links in your libraries.

## What ends up in the C

The mapping from Jaguar to C follows a few simple rules. Knowing them makes generated code much easier to read.

| Jaguar | In the generated C |
|---|---|
| `void main(string param)` | A standard C `main` (never a non-standard `main(string)`) |
| `bool` | The runtime's own `_jBool` type instead of `_Bool` |
| `struct` | A C `typedef struct` |
| A method | A function with an implicit `self` parameter |
| `math:add` (namespaced function) | A mangled name, for example `math_add` |
| An overloaded function | A name that also includes the parameter types |
| `@extern` function | The exact C symbol name, unmangled |

## Name mangling

Jaguar generates C names compatible with namespaces and overloading.

A simple function:

``` jaguar
int add(int a, int b) {
    return a + b;
}
```

generally stays `add` on the C side when it is not overloaded.

A function inside a namespace:

``` jaguar
namespace math {
    int add(int a, int b) {
        return a + b;
    }
}
```

is mangled to avoid collisions, for example in a form like:

``` text
math_add
```

An overload also uses the parameter types in its C name.

------------------------------------------------------------------------



## Diagnostics and source locations

JCC tracks source lines in parser AST nodes. Parser errors include the
relevant line in their diagnostics.

Semantic/code-generation diagnostics also use the best available source
line when the exact AST location is not directly available.

This is especially useful to editor integrations and the Jaguar language
server.

------------------------------------------------------------------------



## One unit, many files

The compiler itself sees a single compilation unit. When a project has several files, JBS resolves every `using name;` by locating `name.ja` or `name.jah` relative to the project file or in an `include` directory, and combines them into one unit before calling the compiler. An imported file is included only once, however many files import it.

## Tool responsibilities

The tools intentionally have separate responsibilities:

``` text
jbg.py
  C .h
   ↓
  Jaguar .jah

jcc.py
  Jaguar .ja/.jah
   ↓
  C
   ↓
  executable/output

jbs.py
  project .jbs
   ↓
  combines .ja/.jah
   ↓
  JCC
   ↓
  bundled GCC
   ↓
  final project outputs
```

JBG is therefore a binding generator, JCC is the compiler, and JBS is
the project build orchestrator.

------------------------------------------------------------------------



:::note
Call resolution, the rules that pick one overload among several, is described with functions in [[ch:functions]].
:::


@@part Guides and Cookbook | Hands-on tutorials, ready-to-use recipes, a comparison with C and C++, and a troubleshooting checklist.

# Guide: A Temperature Table {#guide-first}

@@lead
Your first real program: a Celsius-to-Fahrenheit conversion table. It is small enough to write in ten minutes and it exercises functions, casts, loops, numeric types and the standard library.

## What we are building

The program prints one line per step, from 0 to 100 degrees Celsius in steps of ten, showing the matching Fahrenheit value. Along the way you will practice:

- writing a function with a decimal parameter and result;
- the inclusive `for_loop`;
- explicit C-style casts;
- turning numbers into strings with the `jcc` library.

## Step 1: the conversion function

Start with the arithmetic. A function takes a Celsius value and returns Fahrenheit.

```jaguar
f64 to_fahrenheit(f64 celsius) {
    return celsius * 9.0 / 5.0 + 32.0;
}
```

Notice that the literals are written `9.0`, `5.0` and `32.0`. Decimal literals are `f64`, so the whole expression stays in floating point.

## Step 2: the loop

`for_loop(0, 10)` walks from 0 to 10 **included**, so it produces the eleven steps we need. The index is an `int` and it is read-only inside the loop.

```jaguar
void main(string param) {
    int step = for_loop(0, 10) {
        f64 celsius = (f64)(step * 10);
        f64 fahrenheit = to_fahrenheit(celsius);
        sys:print(fahrenheit);
    }
}
```

The cast `(f64)(step * 10)` converts the integer to a decimal. Jaguar only accepts C cast syntax, so `f64(step * 10)` would not compile.

## Step 3: readable output

Printing bare numbers is not very friendly. The `jcc` library converts numbers to strings and joins strings.

```jaguar
f64 to_fahrenheit(f64 celsius) {
    return celsius * 9.0 / 5.0 + 32.0;
}

void main(string param) {
    int step = for_loop(0, 10) {
        f64 celsius = (f64)(step * 10);
        f64 fahrenheit = to_fahrenheit(celsius);

        string left = jcc:string_concat(jcc:f64_to_string(celsius), " C = ");
        string right = jcc:string_concat(jcc:f64_to_string(fahrenheit), " F");
        sys:print(jcc:string_concat(left, right));
    }
}
```

## Step 4: compile and run

Save the file as `temperatures.ja`, then:

```bash
python jcc.py temperatures.ja -o temperatures
```

Running the program prints eleven lines, one for each step.

:::note Why so many variables?
Each `string_concat` call joins exactly two strings, so building a longer message takes a few steps. Giving each intermediate result a name keeps the code easy to read.
:::

## What you practiced

- Functions with typed parameters and a return value ([[ch:functions]]).
- The inclusive `for_loop` and its read-only index ([[ch:control]]).
- C-style casts ([[ch:types]]).
- The `jcc` conversion and string functions ([[ch:jcc]]).

:::try Extend it
Turn the table into a two-way converter by adding a second function, `to_celsius`, and print both columns. Then try changing the step size: what happens to the number of lines when you change the last bound of `for_loop`?
:::


# Guide: Modeling a Game with Classes {#guide-game}

@@lead
Classes shine when a program has things that have state and behavior. In this guide you will build a tiny turn-based fight between a player and a zombie, using inheritance and a virtual method.

## Design first

We need three kinds of objects. A `Player` has health and can take damage. An `Enemy` is a generic opponent with health and an `attack` behavior that can be replaced. A `Zombie` is a particular kind of enemy that attacks in its own way.

@@diagram inherit

## Step 1: the player

The player has a public `health` field, a method that reduces it, and a `const` method that answers a question without changing anything.

```jaguar
class Player {
    $int health = 100;

    void damage(int amount) {
        health = health - amount;
    }

    bool alive() const {
        return health > 0;
    }
}
```

## Step 2: a base class with a virtual method

`Enemy` declares `attack` as `virtual`, which allows derived classes to replace it. Its `health` field is public, so the code in `main` can read it as well as the derived classes.

```jaguar
class Enemy {
    $int health;

    virtual void attack() {
        sys:print("The enemy attacks!");
    }
}
```

## Step 3: a derived class

A derived class names its base after a comma. `override` marks the replacement, and it must match the virtual method's signature exactly. The derived class can read and write the inherited `health` field.

```jaguar
class Zombie, Enemy {
    constr(int start_health) {
        health = start_health;
    }

    void attack() override {
        sys:print("The zombie claws at you!");
    }

    void hurt(int amount) {
        health = health - amount;
    }

    bool alive() const {
        return health > 0;
    }
}
```

## Step 4: the fight

The fight is a loop with no condition. Each turn, the zombie attacks, both sides lose health, and we test for a winner. `break` leaves the loop.

```jaguar
void main(string param) {
    Player player = Player();
    Zombie zombie = Zombie(60);

    int turn = for_loop(1, 20) {
        zombie.attack();
        player.damage(jcc:random_i32(5, 15));
        zombie.hurt(jcc:random_i32(10, 20));

        sys:print(jcc:string_concat("Player health: ", jcc:i32_to_string(player.health)));
        sys:print(jcc:string_concat("Zombie health: ", jcc:i32_to_string(zombie.health)));

        if (!player.alive()) {
            sys:print("You were defeated.");
            break;
        }
        if (!zombie.alive()) {
            sys:print("The zombie is destroyed!");
            break;
        }
    }
}
```

The loop is bounded by `for_loop(1, 20)` rather than by `while`, which guarantees that the fight ends even if nobody wins. Each turn also uses `jcc:random_i32` to vary the damage.

## What you practiced

- Classes with fields, methods and `const` methods ([[ch:classes]]).
- Access control with `$` markers.
- Inheritance, `virtual` and `override`.
- Using `break` inside a loop, and the standard library for random numbers and string building.

:::try Extend it
Add a second enemy type, `Skeleton`, that overrides `attack` differently. Give `Player` a constructor that takes a starting health value, using a default parameter so that `Player()` still works.
:::


# Guide: A Scoreboard with Collections {#guide-collections}

@@lead
Collections are the everyday data structures of a Jaguar program. In this guide you will build a small scoreboard with a `list`, a `map` and both of the collection loops, and discover the one rule that catches most newcomers: collections are changed with methods, never by indexing.

## Step 1: a list of scores

A `list<int>` is created with braces and grows with `push`.

```jaguar
void main(string param) {
    list<int> scores = {30, 45, 12};
    scores.push(58);

    int first = scores[0];
    sys:print(first);
}
```

Reading with `scores[0]` is fine. Writing with `scores[0] = 99;` is not allowed, because indexing is read-only by design.

## Step 2: walking the list

`loop_list` visits every element in order. The loop variable, declared with `auto`, receives each value in turn. Here we sum the scores in a variable declared **before** the loop.

```jaguar
void main(string param) {
    list<int> scores = {30, 45, 12};
    scores.push(58);

    int total = 0;
    auto score = loop_list(scores) {
        total = total + score;
    }

    sys:print(jcc:string_concat("Total: ", jcc:i32_to_string(total)));
}
```

During the loop the list is read-only: calling `scores.push(...)` inside `loop_list` is forbidden. If you need to add elements based on what you see, collect them first, and add them afterwards.

## Step 3: names and scores in a map

A `map<string, int>` associates a name with a score. Braces list the entries as alternating keys and values, and `emplace` adds or replaces an entry.

```jaguar
void main(string param) {
    map<string, int> board = {
        "alice", 30,
        "bob", 45
    };
    board.emplace("charlie", 12);
    board.emplace("alice", 35);    // replaces alice's score

    int alice = board["alice"];
    sys:print(alice);
}
```

String keys are compared by their content, so `board["alice"]` finds the entry no matter where the key string came from.

## Step 4: walking the map

`loop_map` gives you a `pair<string, int>` for every entry. The pair has two members, `first` and `second`.

```jaguar
void main(string param) {
    map<string, int> board = {
        "alice", 30,
        "bob", 45
    };
    board.emplace("charlie", 12);

    int best = 0;
    auto entry = loop_map(board) {
        string line = jcc:string_concat(entry.first, ": ");
        sys:print(jcc:string_concat(line, jcc:i32_to_string(entry.second)));
        best = jcc:max_i32(best, entry.second);
    }

    sys:print(jcc:string_concat("Best: ", jcc:i32_to_string(best)));
}
```

## Step 5: mixed data

Sometimes a value does not have one type. A `dynamic_list` stores values of several types together, and casts recover them.

```jaguar
void main(string param) {
    dynamic_list record = {"alice", 30, true};

    string kind = record.type(1);
    sys:print(kind);

    i32 score = (i32)record[1];
    sys:print(score);
}
```

## What you practiced

- `list`, `map`, `pair` and `dynamic_list` ([[ch:collections]]).
- Literals with braces, `push` and `emplace`.
- `loop_list` and `loop_map`, and their read-only rule.
- Read-only indexing.

:::warning Collections are local variables
In the current implementation, collection types such as `list` and `map` cannot be global variables. Declare them inside a function and pass them where they are needed.
:::


# Guide: A Multi-File Project with JBS {#guide-project}

@@lead
One file is enough for a tutorial, but real programs are split up. In this guide you will move a piece of code into a Jaguar header, import it with `using`, and build the whole thing with JBS.

## The layout

Create a project directory with this structure:

```text
Geometry/
├── include/
│   └── geometry.jah
├── src/
│   └── main.ja
└── project.jbs
```

Reusable declarations go in `.jah` files under `include/`. The program itself stays in `src/`.

## Step 1: the reusable code

A `.jah` file uses ordinary Jaguar syntax. Put a small namespace in `include/geometry.jah`:

```jaguar
namespace geometry {
    f64 area(f64 width, f64 height) {
        return width * height;
    }

    f64 perimeter(f64 width, f64 height) {
        return 2.0 * (width + height);
    }
}
```

## Step 2: the program

`src/main.ja` asks for the header with `using`, then calls the functions through their namespace.

```jaguar
using geometry;

void main(string param) {
    f64 a = geometry:area(3.0, 4.5);
    f64 p = geometry:perimeter(3.0, 4.5);

    sys:print(a);
    sys:print(p);
}
```

## Step 3: the project file

The `.jbs` file tells JBS where to write the output, where to look for imports, and what to build.

```jbs
version 1.0

out build
include include

compile Main {
    src/main.ja
}
```

`include include` adds the `include/` directory to the places where JBS looks when it resolves `using geometry;`. For that line, JBS accepts `geometry.ja` or `geometry.jah`.

## Step 4: build

```bash
python jbs.py project.jbs
```

JBS expands the `using` line by inserting the contents of `geometry.jah` into the combined compilation unit, runs JCC to produce C, and calls the bundled GCC toolchain. The executable appears in `build/` under the target name, `Main`.

## Step 5: look inside

Add one line to `project.jbs` and rebuild to keep the generated C file after the build:

```jbs
keep_c
```

Open it and find the namespaced functions. Because they live in a namespace, their C names are mangled, in a form like `geometry_area`.

## Step 6: configure the build

JBS directives can be combined freely. For example, this project file requests C89-compatible output, keeps the C, and passes a macro that your code can test with `#ifdef`:

```jbs
version 1.0

out build
include include

c89
keep_c
define GEOMETRY_DEBUG 1

compile Main {
    src/main.ja
}
```

## What you practiced

- A project layout with `include/` and `src/` ([[ch:jbs]]).
- Jaguar headers and `using` ([[ch:bindgen]] and [[ch:modules]]).
- The `version`, `out`, `include`, `compile`, `keep_c`, `c89` and `define` directives.

:::tip Build one target at a time
When a project defines several targets, `python jbs.py project.jbs --target Main` builds only the one you name.
:::


# Guide: Calling C from Jaguar {#guide-c}

@@lead
Most useful libraries are written in C. This guide shows the two ways to call them: declaring a function by hand with `@extern`, and generating a whole Jaguar header with BindGen.

## The C side

We will call a tiny C library. Create `mathx.h` and `mathx.c`:

```c
/* mathx.h */
int add(int a, int b);
```

```c
/* mathx.c */
#include "mathx.h"

int add(int a, int b) {
    return a + b;
}
```

Compile it into a static library with the usual tools:

```bash
gcc -c mathx.c
ar rcs libmathx.a mathx.o
```

## Way 1: declare the function by hand

For one or two functions, `@extern` is enough. It tells JCC that the function is defined elsewhere and that its C name must be kept exactly as written.

```jaguar
@extern
int add(int a, int b);

void main(string param) {
    int result = add(2, 3);
    sys:print(result);
}
```

Now tell JBS to link the library. A `link` entry can be a plain library name, and JBS resolves common forms such as `libmathx.a` by searching the output directory and the project directory.

```jbs
version 1.0

out build

compile Main {
    main.ja
}

link Main {
    mathx
}
```

```bash
python jbs.py project.jbs
```

## Way 2: generate the header with BindGen

For a real library with dozens of functions, structs and callbacks, write nothing by hand. Ask BindGen to turn the C header into a Jaguar header:

```bash
python jbg.py --c mathx.h -o include/mathx.jah
```

BindGen parses the header, converts each C declaration to its Jaguar equivalent and writes an `.jah` file. Open it to see what was generated: you will find `@extern` declarations, plus structs, aliases and constants for anything else the header declared.

Then import the header in your program and drop the hand-written declaration:

```jaguar
using mathx;

void main(string param) {
    int result = add(2, 3);
    sys:print(result);
}
```

And tell JBS where to find the generated header:

```jbs
version 1.0

out build
include include

compile Main {
    main.ja
}

link Main {
    mathx
}
```

## Things to remember about C types

- A C string (`const char*`) becomes `i8*`, **not** Jaguar's `string`. BindGen keeps this distinction on purpose.
- Pointers are written with `*` after the type, the address-of operator is `&`, and the null pointer is `nullptr`.
- A C function-pointer type becomes `fn(...) -> ...`.
- The C `int` maps to `int` (or `i32`), `unsigned int` to `u32`, and so on. The table in [[ch:bindgen]] lists the full mapping.

:::tip Strict mode
BindGen reports unsupported declarations as warnings when it can. Add `--strict` to the `jbg.py` command so that any warning makes the command fail. It is a good default for automated builds.
:::

## What you practiced

- `@extern` declarations ([[ch:interop]]).
- Linking with a static library through JBS ([[ch:jbs]]).
- Generating a `.jah` file with BindGen ([[ch:bindgen]]).


# Recipes {#recipes}

@@lead
Short, self-contained answers to questions that come up again and again. Each recipe uses only features documented in this book.

## Walk over the characters of a string

`for_loop` includes its last bound, so stop at `length() - 1`. `char_at` returns the character code as an `i32`. If the string is empty, the loop starts after it ends and does nothing.

```jaguar
string word = "Jaguar";
int last = word.length() - 1;

int i = for_loop(0, last) {
    sys:print(word.char_at(i));
}
```

## Count the digits in a string

The character functions in `jcc` take integer character codes, which is exactly what `char_at` returns.

```jaguar
string text = "room 101";
int digits = 0;

int i = for_loop(0, text.length() - 1) {
    if (jcc:is_digit(text.char_at(i))) {
        digits = digits + 1;
    }
}
sys:print(digits);
```

## Keep a value inside a range

```jaguar
int health = 90;
int healed = jcc:clamp_i32(health + 30, 0, 100);   // 100
```

## Roll a die

```jaguar
i32 roll = jcc:random_i32(1, 6);
sys:print(roll);
```

## Time a piece of code

`jcc:time_ms` returns milliseconds as an `i64`.

```jaguar
i64 start = jcc:time_ms();

// ... the work you want to measure ...

i64 elapsed = jcc:time_ms() - start;
sys:print(jcc:string_concat("Elapsed ms: ", jcc:i64_to_string(elapsed)));
```

## Convert between text and numbers

```jaguar
i32 count = jcc:string_to_i32("42");
f64 ratio = jcc:string_to_f64("3.14");
string label = jcc:i32_to_string(count);
```

## Compare strings by content

Use `equals` (or `jcc:string_equals`) for the contents of two strings, and `contains`, `starts_with` and `ends_with` for partial matches.

```jaguar
string name = "Jaguar";

if (name.equals("Jaguar")) {
    sys:print("exact match");
}
if (name.starts_with("Jag")) {
    sys:print("prefix match");
}
```

## Color the console output

The color function expects an ANSI escape sequence, and the reset function restores the default.

```jaguar
sys:console:set_color("\\033[31m");
sys:print("Red");
sys:console:reset_color();
```

## Read or create a save file

```jaguar
if (jcc:file_exists("save.txt")) {
    string data = sys:fs:read("save.txt");
    sys:print(data);
} else {
    sys:fs:write("save.txt", "level=1");
}
```

## Read an environment variable

```jaguar
string home = jcc:env_get("HOME");
sys:print(home);
```

## Stop early with an error code

```jaguar
if (!jcc:file_exists("config.txt")) {
    sys:print("missing configuration");
    jcc:exit(1);
}
```

## Check an assumption while developing

```jaguar
int health = 10;
jcc:assert(health >= 0, "health must not be negative");
```

## Enable code only in debug builds

Define a macro in the JBS project file, then test it in the source.

```jbs
define DEBUG 1
```

```jaguar
#ifdef DEBUG
    sys:print("debug build");
#endif
```

## Give a constructor a default

Default parameters work on constructors, so `Player()` and `Player(50)` are both valid.

```jaguar
#define MAX_HEALTH 100

class Player {
    $int health = MAX_HEALTH;

    constr(int initial_health = MAX_HEALTH) {
        health = initial_health;
    }
}
```

## Run another program

`sys:execute` takes the program and a working directory, and returns the exit code.

```jaguar
int code = sys:execute("program", ".");
sys:print(code);
```


# Coming from C and C++ {#from-c}

@@lead
If you write C or C++, most of Jaguar will feel immediately familiar, and a handful of things will trip you up until you have seen them once. This chapter puts them all in one place.

## What stays the same

- Braces for blocks, semicolons for statements, and explicit types on every declaration.
- C operators and C-like precedence, and **C cast syntax**: `(f64)value`.
- `#define`, `#if`, `#ifdef` and friends, passed through to the generated C.
- Structs, enums, unions and function pointers, with C-compatible layouts.
- Fixed-width integers, spelled `i8` to `i64` and `u8` to `u64`.
- Compilation to native code through GCC, so performance is that of C.

## What is different

| Topic | C / C++ | Jaguar |
|---|---|---|
| `while` loop | `while (x > 0) { ... }` | `while { ... }` with an explicit `break` |
| Counting loop | `for (int i = 0; i <= 10; i++)` | `int i = for_loop(0, 10) { ... }` (last bound **included**, index read-only) |
| Namespaces | `math::add(1, 2)` | `math:add(1, 2)` |
| Null pointer | `NULL` or `nullptr` | `nullptr` only |
| C string | `const char*` | `i8*`; Jaguar's `string` is a runtime object |
| Including a header | `#include "api.h"` | `using api;` with a `.jah` from BindGen |
| Public / protected | `public:` / `protected:` sections | `$` and `%` markers on each member |
| Constructors | `Player(int h)` | `constr(int h)` |
| Destructors | `~Player()` | `destr()` |
| Inheritance | `class Zombie : public Enemy` | `class Zombie, Enemy` |
| Generic containers | Templates (`std::vector<int>`) | Built-in `list<T>`, `map<K,V>`, `pair<K,V>` |
| Element assignment | `v[2] = 10;` | Not allowed; use methods such as `push` and `emplace` |
| Casting | `static_cast<int>(x)` | `(int)x` |
| Memory | `malloc` / `free`, `new` / `delete` | Managed by the runtime; `container<T>` owns its object |
| Boolean type | `bool` (`_Bool` in C99) | `bool`, generated as the runtime's `_jBool` |
| Default arguments | C++ only | Built in, plus **named arguments** |

## What is missing on purpose

Several C and C++ features are deliberately not part of the language. You will not find:

- general pointer arithmetic;
- `malloc`, `free`, `memcpy` and other libc memory functions as a general API;
- `FILE*`; file access goes through `sys:fs` and `jcc`;
- C++ templates and other complex C++ features;
- lambdas;
- exceptions;
- multiple inheritance.

:::design Why leave them out?
Every item on this list is either a major source of bugs (raw memory management) or a large source of language complexity (templates, exceptions). Jaguar keeps a small core and offers controlled escape hatches: pointer types, `@extern` and `.jah` bindings are there when you need to talk to C.
:::

## A quick translation

Here is a small C++ snippet and its Jaguar equivalent.

```text
// C++
class Player {
public:
    int health = 100;
    Player(int h) : health(h) {}
    void damage(int amount) { health -= amount; }
    bool alive() const { return health > 0; }
};
```

```jaguar
// Jaguar
class Player {
    $int health = 100;

    constr(int h) {
        health = h;
    }

    void damage(int amount) {
        health = health - amount;
    }

    bool alive() const {
        return health > 0;
    }
}
```

:::note Compound assignment
Every example in the reference writes updates in the long form, `health = health - amount;`. This book does the same.
:::


# Pitfalls and Troubleshooting {#pitfalls}

@@lead
Most compile errors in Jaguar come from a small set of mistakes, and nearly all of them come from expecting C behavior where Jaguar deliberately does something else. Here are the common ones, each with the fix.

## Loops

### `while` with a condition

```jaguar
while (health > 0) {     // invalid
}
```

`while` takes no condition. Test inside the loop and leave with `break`:

```jaguar
while {
    if (health <= 0) {
        break;
    }
    health = health - 1;
}
```

### One iteration too many

`for_loop(0, list_length)` includes `list_length` itself. To visit indexes `0` to `length - 1`, stop at `length - 1`.

### Changing a collection inside its loop

```jaguar
auto item = loop_list(numbers) {
    numbers.push(10);     // forbidden
}
```

Both `loop_list` and `loop_map` treat the collection as read-only while the loop runs. Collect what you need to add, and add it after the loop.

## Collections

### Assigning through an index

```jaguar
numbers[2] = 10;          // invalid
scores["alice"] = 100;    // invalid
```

Indexing only reads. Use the collection's methods, such as `push` for a list and `emplace` for a map.

### Collections as globals

`list`, `map`, `pair`, `container` and `dynamic_list` are not currently valid as global variables. Declare them as locals.

### Indexing a container

`container<T>` values cannot be indexed with `[]`. Use `get()` to read the value it owns.

## Types and casts

### Function-style casts

```jaguar
i32(3.14);                // not a cast
```

Jaguar only accepts C-style casts: `(i32)3.14`.

### `NULL` instead of `nullptr`

```jaguar
void* handle = NULL;      // invalid
void* handle = nullptr;   // valid
```

### `auto` without an initializer

```jaguar
auto x;                   // invalid: nothing to deduce from
auto x = 42;              // valid
```

### A Jaguar `string` where C expects `char*`

A `string` is a runtime object and a C string is an `i8*`. They are different types on purpose, and BindGen keeps declarations from C headers in terms of `i8*`.

## Functions

### A positional argument after a named one

```jaguar
move(x = 10, 20);         // invalid
move(x = 10, y = 20);     // valid
```

### Named arguments to built-in functions

`jcc:*` and `sys:*` functions do not accept named arguments. Pass their arguments by position.

### Overloads that are equally good

When several overloads remain equally valid after the numeric conversions are applied, the call is considered ambiguous. Cast an argument, or rename one of the functions.

### Reserved libc names

Names such as `malloc`, `free`, `printf`, `strlen`, `rand` and `system` are reserved when used as ordinary Jaguar function names, to avoid collisions with libc symbols. Choose another name, or reach the feature through a `jcc:*` function.

## Classes

### Mismatched `override`

`override` must match a `virtual` method of the base class, with an **exact** signature. A small difference in parameter types is enough to make it fail.

### Exposing a non-public field

`@exposed` can only be used on a public (`$`) field, and `@register` on a class. An unknown attribute is a compile error.

## Scope and globals

### Shadowing

Two sibling blocks can reuse a name, but a block cannot redeclare a variable that is visible from an enclosing scope.

### Non-constant global initializers

```jaguar
int x = get_value();      // invalid at global scope
```

A global initializer must be a literal, a macro or an operation between constants.

### Variables in a namespace

Namespaces support functions, structs, classes, enums and nested namespaces, but a global variable directly inside a namespace is not supported.

## Enums and interop

### Explicit enum values

```jaguar
enum Color {
    Red = 10              // invalid
}
```

Enums are numbered sequentially and explicit initializers are not accepted. BindGen refuses headers that use them.

### Initializing an `@extern` global

An `@extern` global declaration cannot have an initializer. It only announces a variable that lives in C.

## Build and tooling

### `#include`

```jaguar
#include <stdio.h>        // invalid
```

Generate a `.jah` with BindGen and import it with `using`.

### An output name ending in `.c`

`python jcc.py main.ja -o game.c` is wrong: `-o` takes an output base name. Use `-o game`.

### An unknown JBS option

JBS rejects unknown command-line options, and the project file must have the `.jbs` extension.

:::tip When the message is unclear
Errors from the parser include the relevant source line. If a semantic error seems to point to the wrong place, look at the declaration a few lines above, and generate the C with `python jcc.py file.ja > file.c` to see how the compiler understood it.
:::


@@part History and Roadmap | Where Jaguar comes from, the decisions that shaped it, and a proposed plan for what comes next.

# The Story of Jaguar {#history}

@@lead
Every language is a collection of decisions. This chapter tells the story of Jaguar through the decisions its documentation records: what the language chose to do, what it chose not to do, and how its tools came to be separate.

:::note About this chapter
This history is reconstructed from the language documentation and from the current implementation. It concentrates on decisions and capabilities rather than dates: the source material describes what Jaguar *is*, and does not record when each part was added.
:::

## The starting idea: a language that compiles to C

The central idea of Jaguar, as its documentation presents it, is to keep the performance and reach of C while smoothing many of its sharp edges. The mechanism is a **source-to-source compiler**: a Jaguar program is translated to C by JaguarCC, and the C is compiled by GCC.

That single choice helps explain much of the rest. Because the output is C, Jaguar programs run at native speed, can be built almost anywhere a C compiler exists (down to a C89 mode for older toolchains) and can call any C library. Because the front end is its own language, it can offer things that C cannot: classes, namespaces, overloading, default and named arguments, built-in collections and reflection.

The language's stated goals capture the balance: ease of use, syntax close to C and C++, the performance of a compiled language, explicit type control, practical modern features, a minimal runtime and interoperability with C.

## A compiler in four stages

JaguarCC is organized as a classic pipeline: a lexer, a parser, a resolver and a code generator. Each stage owns one kind of decision. The lexer decides what the tokens are, the parser decides what the program's structure is, the resolver decides what every name and call means, and the code generator decides what C to write.

The pipeline is worth noticing for a second reason: because the parser records source lines in its syntax tree, the compiler can report **where** a problem is. The documentation explicitly mentions editor integrations and a language server as consumers of that information.

## The signature decisions

The documentation singles out a set of choices as "particularly specific to the current implementation". They are the closest thing Jaguar has to a personality:

| Decision | What it looks like | The idea behind it |
|---|---|---|
| Conditionless `while` | `while { ... break; }` | The exit test is written where it happens, and loops that can end have a visible `break` |
| Inclusive `for_loop` | `for_loop(0, 10)` runs 0 to 10 | A counting loop that says what it counts, with a read-only index |
| Collections without templates | `list<T>`, `map<K,V>` built in | Common containers are part of the language and its runtime, not a library puzzle |
| Read-only iteration | No changes inside `loop_list` / `loop_map` | Rules out a whole family of iterator bugs |
| Read-only indexing | `numbers[2] = 10;` is invalid | Writes go through named methods, so they are easy to find |
| `container<T>` | `container<Player> p = new Player(100);` | Ownership is explicit, and the container destroys what it owns |
| Attribute-driven reflection | `@register`, `@exposed` | Dynamic access exists, but only where you opt in |
| C89 generation strategy | `--c89`, `_jBool` | Portability down to very old C compilers |

## How C interoperability grew up

The documentation tells the interoperability story in layers, and it is instructive to read them in order.

**Declare.** The simplest layer is `@extern`: a function or variable is defined elsewhere, and its C name is preserved exactly.

**Unify.** The current compiler expresses C types with Jaguar's own type syntax (`T*`, `T**`, `fn(...) -> R`, `nullptr`) rather than with separate special-purpose keywords such as `cptr`, `cstr` or `cfuncptr`. That is a deliberate simplification: pointers and callbacks look like the rest of the language.

**Preserve.** Along the way, a rule appears that matters more than any syntax: a C string is `i8*`, never Jaguar's runtime `string`, and numeric types map to ABI-exact Jaguar types. The bindings keep the C ABI intact, and the compiler lowers types back to C when it generates code.

**Generate.** Finally, a tool takes over the boring work. BindGen reads a C header with `pycparser` and writes a Jaguar header that is imported with `using`. It is honest about its limits: it refuses or warns about arrays it cannot represent, variadic functions and explicit enum initializers, and its recovery for malformed headers is intentionally narrow, because guessing at arbitrary invalid C could silently create an ABI-breaking binding.

The ban on `#include` completes the picture. C headers do not enter Jaguar through the preprocessor; they enter through bindings that the compiler understands.

## From one compiler to a toolchain

The last chapter of the story is about structure. Jaguar's tooling is deliberately split, and each tool has one responsibility:

- **JaguarCC** translates Jaguar to C and can call GCC directly for a quick build.
- **JBS** orchestrates projects: it reads a small project file, expands `using` imports, calls the compiler with the right options and links libraries, with a bundled toolchain so builds do not depend on the machine's configuration.
- **BindGen** turns C headers into Jaguar headers.

The split lets each tool evolve independently of the others. Notably, the build system does not run BindGen by itself yet; the tools cooperate through files.

## The principles behind the choices

Reading the decisions together, a handful of principles emerge.

1. **Make the common thing short and the dangerous thing explicit.** Types, casts, pointers and `nullptr` are all visible in the source.
2. **Prefer boundaries to breadth.** No exceptions, lambdas, templates, multiple inheritance or raw memory API: the language stays small on purpose.
3. **Preserve the C ABI, never guess.** Interoperability is exact or it is refused.
4. **One tool, one job.** The compiler, the build system and the binding generator meet at file boundaries.
5. **Be honest about the implementation.** The documentation says plainly that it describes the compiler's current behavior, and that anything unspecified is decided by `jcc.py`.

:::design Where the story goes next
A language whose documentation is this candid about its limits has a natural roadmap: the limits themselves. The next chapter turns them into a development plan.
:::


# A Development Plan {#roadmap}

@@lead
A language grows best in the direction its limits point. This chapter takes the boundaries and limitations that the documentation states plainly and arranges them into a plan: what to protect, what to finish and what to build next.

:::important A proposal, not a promise
This plan is derived from the limitations and boundaries recorded in the documentation. It is offered as a starting point for discussion. Priorities and phases are recommendations, meant to be adjusted by the people who build Jaguar.
:::

## Where Jaguar stands today

The implementation already covers a broad surface. In summary:

| Area | What is in place | Notable limits today |
|---|---|---|
| Core language | Sized numeric types, `auto`, `const`, casts, operators, functions with defaults, named arguments and overloads | Compound assignment is not shown in the reference |
| Data | Structs, sequential enums, named unions, aliases, forward declarations | Explicit enum initializers are not accepted |
| Classes | Fields, methods, `constr`, `destr`, single inheritance, `virtual`, `override`, `const` methods, access control | No multiple inheritance |
| Collections | `list`, `map`, `pair`, `container`, `dynamic_list`, literals, `loop_list`, `loop_map` | Read-only indexing; not valid as globals |
| Reflection | `@register`, `@exposed`, `factory:construct`, `GetMember`, `SetMember`, `MemberExists` | Opt-in and intentionally limited |
| Libraries | `sys` (print, console, files, execute), `jcc` (math, strings, characters, files, environment) | Math is `f64`; integer helpers are `i32` |
| C interop | `@extern`, pointers, `nullptr`, function pointers, ABI-preserving types, `.jah` | No variadic functions or C arrays in bindings |
| Build | JBS 1.0: executables, static and shared libraries, `link`, `define`, `c89`, `keep_c` | BindGen is not run from a JBS directive |
| Tooling | `jcc.py`, `jbs.py`, `jbg.py`, source-line diagnostics | Language server and editor integrations are referenced, not yet described here |

## Boundaries to protect

Some limits are not gaps. The documentation lists what the language deliberately leaves out, and a healthy roadmap protects that list rather than eroding it:

- general pointer arithmetic;
- `malloc` and `free` as a general API, and `FILE*`;
- `memcpy` and other memory primitives as a general API;
- C++ templates and other complex C++ features;
- lambdas, exceptions and multiple inheritance.

Any proposal that touches this list should be argued as a change to Jaguar's identity, not as a missing feature.

## Candidate work items

These are the concrete limitations that the documentation records, each paired with a proposed direction. The priorities are suggestions.

| # | Area | Today | Proposed direction | Priority |
|---|---|---|---|---|
| 1 | Enums | Explicit initializers are rejected, and BindGen refuses headers that use them | Accept explicit values, which real C headers rely on | High |
| 2 | Build automation | BindGen is a separate step; JBS has no `bindgen` directive | Add a directive so header conversion is part of the build | High |
| 3 | Diagnostics | Parser errors carry lines; some semantic errors use the best available line | Precise locations for every diagnostic, and stable error codes | High |
| 4 | Conformance tests | The reference is the specification | Turn every example in the reference into an automated test | High |
| 5 | Variadic functions | Refused by BindGen | Define a safe strategy, such as typed wrappers | Medium |
| 6 | C arrays | Refused when the ABI cannot be preserved | Support fixed-size arrays in fields and parameters | Medium |
| 7 | Global collections | `list`, `map` and others must be local | Allow globals with runtime initialization | Medium |
| 8 | Namespace globals | Not supported directly inside a namespace | Support them with mangled names | Medium |
| 9 | Toolchain portability | JBS finds a bundled MinGW next to `jbs.py` | Fall back to a system compiler and configurable paths | Medium |
| 10 | Signals | Behavior depends on the current code generation | Specify the semantics, document them and test them | Medium |
| 11 | Collection API | The documented surface is small | Document and extend removal, size and lookup helpers | Medium |
| 12 | Built-in ergonomics | `jcc` and `sys` functions take no named arguments | Allow named arguments for built-ins | Low |
| 13 | Loops | `loop_list` does not work on `dynamic_list` | Add support | Low |
| 14 | Library breadth | Integer helpers are `i32`; math is `f64` | Add `i64` and `f32` variants where useful | Low |

## Proposed phases

### Phase 1: solidify the foundation

Turn the current behavior into something that cannot silently regress. Convert the reference examples into an automated test suite (item 4), improve diagnostics (item 3) and freeze the reference as the specification for version 1. This phase adds no features, and it makes every later phase safer.

### Phase 2: complete C interoperability

Interoperability is Jaguar's strongest selling point, so finish it. Accept explicit enum values (item 1), add a BindGen step to JBS (item 2), then tackle arrays and variadic functions (items 5 and 6) and make the toolchain portable (item 9).

### Phase 3: broaden the language and library

With a stable base, remove the ergonomic limits: global collections and namespace globals (items 7 and 8), a fuller collection API (item 11), a specified `signal` feature (item 10), and the smaller library and loop gaps (items 12 to 14).

### Phase 4: grow the ecosystem

Build on the compiler's source-line tracking. A language server and editor integrations, a formatter, conventions for distributing `.jah` headers with their libraries, a test runner built on `jcc:assert`, and `#line`-based mapping so that debuggers and errors from GCC can point back to Jaguar source.

## How to know a phase is done

Every item in this plan should be closed the same way: the behavior is implemented, a test proves it, the reference documents it, and the example in this book compiles. Documentation and code should move together, because the documentation is how Jaguar describes itself.

:::tip Make the plan your own
This chapter is deliberately editable. Replace the priorities, add real milestones and dates, and drop any item you disagree with. What matters is that each limit in the reference has a named owner and a next step.
:::


@@part Appendices {.appendix} | Quick references, complete example programs, the implementation checklist and a glossary.

# Language Quick Reference {.appendix #quickref}

@@lead
A compact reminder of the syntax and the library, for when you know what you want and need to see how it is spelled.

## Types

``` text
void

int / i32
uint / u32
short / i16
ushort / u16
long / i64
ulong / u64
char / i8
uchar / u8
sbyte / i8
byte / u8
float / f32
double / f64
bool
string

T*
fn(T1, T2, ...) -> R

list<T>
map<K,V>
pair<K,V>
container<T>
dynamic_list
```


## Control flow

``` text
if / else
while
for_loop
break
continue
return
```


## Classes

``` text
class
constr
destr
virtual
override
this
$
%
const
```


## Namespaces

``` text
namespace
namespace:function()
```


## Attributes

``` text
@extern
@register
@exposed
```


## C interop

``` text
T*
T**
fn(T1, T2, ...) -> R
&
*
nullptr
@extern
```


## Preprocessor

``` text
#define
#undef
#if
#ifdef
#ifndef
#elif
#else
#endif
#pragma
#error
#warning
#line
```

`#elseif` is accepted as a Jaguar alias for `#elif`.

`#include` is not supported.


## Collections

``` text
list.push()
list[index]

map.emplace()
map[key]

pair.first
pair.second

container.get()

 dynamic_list.push()
 dynamic_list.get()
 dynamic_list.type()
 dynamic_list.size()
 dynamic_list[index]

loop_list()
loop_map()
```


## System

``` text
sys:print()
sys:console:set_color()
sys:console:reset_color()
sys:execute()
sys:fs:read()
sys:fs:write()
```


## `jcc` standard library

``` text
jcc:exit()
jcc:abort()
jcc:abs_i32()
jcc:min_i32()
jcc:max_i32()
jcc:clamp_i32()
jcc:random_i32()
jcc:time_ms()
jcc:assert()

jcc:sqrt()
jcc:pow()
jcc:sin()
jcc:cos()
jcc:tan()
jcc:asin()
jcc:acos()
jcc:atan()
jcc:atan2()
jcc:floor()
jcc:ceil()
jcc:round()
jcc:log()
jcc:log10()
jcc:exp()
jcc:fmod()

jcc:string_length()
jcc:string_equals()
jcc:string_compare()
jcc:string_contains()
jcc:string_starts_with()
jcc:string_ends_with()
jcc:string_concat()
jcc:string_substring()
jcc:string_char_at()
jcc:string_find()
jcc:string_to_upper()
jcc:string_to_lower()

jcc:string_to_i32()
jcc:string_to_i64()
jcc:string_to_f64()
jcc:i32_to_string()
jcc:i64_to_string()
jcc:f64_to_string()

jcc:is_digit()
jcc:is_alpha()
jcc:is_alnum()
jcc:is_space()
jcc:is_upper()
jcc:is_lower()
jcc:to_upper_char()
jcc:to_lower_char()

jcc:file_exists()
jcc:remove_file()
jcc:rename_file()
jcc:env_get()
```

------------------------------------------------------------------------



## Syntax summary

``` text
// comment
/* comment */

#define NAME VALUE

const int x = 10;
auto y = 20;

int add(int a, int b) {
    return a + b;
}

int add(int a, int b);

if (condition) {
} else if (other) {
} else {
}

while {
    break;
    continue;
}

int i = for_loop(0, 10) {
}

struct Vector2 {
    f32 x;
    f32 y;
}

class Player {
    $int health;
    %int protected_value;
    int private_value;

    constr() {
    }

    virtual void update() {
    }

    void update_child() override {
    }

    destr() {
    }
}

namespace game {
    int start() {
        return 0;
    }
}

list<int> values = {1, 2, 3};
map<string, int> scores = {"a", 10};
pair<string, int> result = {"score", 42};
dynamic_list data = {42, "hello", true};
container<int> value => 42;

sys:print("Hello");
jcc:sqrt(25.0);
```

------------------------------------------------------------------------




# Command-Line and JBS Reference {.appendix #cli}

@@lead
The three tools at a glance: their command lines, and the complete list of JBS directives.

## `jcc.py`, the compiler

`jcc.py` is the Jaguar compiler.

Basic compilation:

``` bash
python jcc.py main.ja -o game
```

Generate C only:

``` bash
python jcc.py main.ja > main.c
```

Generate C in C89-compatible block layout:

``` bash
python jcc.py main.ja --c89 > main.c
```

With `-o`, JCC invokes the C compiler/linker as part of direct
compilation. Without `-o`, it writes generated C to standard output.

The output name supplied to `-o` is an executable/output base name, not
a `.c` filename.



## `jbs.py`, the build system

`jbs.py` manages multi-file Jaguar projects.

``` bash
python jbs.py project.jbs
```

Select one target:

``` bash
python jbs.py project.jbs --target Main
```

Override the configured output directory:

``` bash
python jbs.py project.jbs -o build
```

JBS combines `.ja` and `.jah` files, expands `using` imports, calls JCC,
then uses the bundled GCC toolchain.

See the **Build System** section for the complete `.jbs` syntax.



## `jbg.py`, the binding generator

`jbg.py` converts a C header into a Jaguar Header (`.jah`).

Basic usage:

``` bash
python jbg.py --c api.h
```

By default this creates:

``` text
api.jah
```

Specify an output path:

``` bash
python jbg.py --c api.h -o include/api.jah
```

Write the generated binding to standard output:

``` bash
python jbg.py --c api.h --stdout
```

Treat unsupported declarations as a hard failure:

``` bash
python jbg.py --c api.h --strict
```

The output file must use the `.jah` extension.



## JBS quick reference

``` text
version 1.0
out
include
define
c89
keep_c

compile
compile_static
compile_shared
link
```

CLI:

``` text
python jbs.py project.jbs
python jbs.py project.jbs -o build
python jbs.py project.jbs --target Main
```

JBS expands `using` imports, uses JCC for Jaguar → C, and then uses the
bundled GCC toolchain for final compilation and linking.

------------------------------------------------------------------------




# Complete Example Programs {.appendix #examples}

@@lead
Two complete programs that use several features together. Read them, compile them and take them apart.

## A program that uses many features

Here is a small program using several features of the language:

``` jaguar
#define MAX_HEALTH 100

@register
class Player {
    @exposed
    $int health = MAX_HEALTH;

    constr(int initial_health = MAX_HEALTH) {
        health = initial_health;
    }

    void damage(int amount) {
        health = health - amount;
    }

    bool alive() const {
        return health > 0;
    }
}

int add(int a, int b = 0) {
    return a + b;
}

void main(string param) {
    Player player = Player(100);

    list<int> values = {10, 20, 30};

    auto item = loop_list(values) {
        sys:print(item);
    }

    player.damage(25);

    sys:print(player.health);

    if (player.alive()) {
        sys:print("Player alive");
    }

    f64 distance = jcc:sqrt(3.0 * 3.0 + 4.0 * 4.0);
    sys:print(distance);

    string text = jcc:i32_to_string(add(10, b = 20));
    sys:print(text);
}
```

------------------------------------------------------------------------



## A small game program

``` jaguar
class Player {
    $f32 x = 0.0;
    $f32 y = 0.0;
    $int health = 100;

    void move(f32 dx, f32 dy) {
        x = x + dx;
        y = y + dy;
    }

    void damage(int amount) {
        health = health - amount;
    }

    bool alive() const {
        return health > 0;
    }
}

void main(string param) {
    Player player = Player();

    int i = for_loop(0, 4) {
        player.move(1.0, 0.5);
        sys:print(i);
    }

    player.damage(20);

    if (player.alive()) {
        sys:print("Player is alive");
    }

    sys:print(player.x);
    sys:print(player.y);
}
```

------------------------------------------------------------------------




# Implementation Checklist {.appendix #checklist}

@@lead
What the current implementation includes, gathered in one list, and how to read the status of a feature.

## How to read the status of a feature

This documentation matches the behavior currently present in `jcc.py`.

Points to consider as particularly specific to the current
implementation are:

-   the conditionless form of `while`;
-   `for_loop` with an inclusive final bound;
-   collections without C++ templates;
-   the ban on modifying a collection during `loop_list` / `loop_map`;
-   `container<T>`;
-   `dynamic_list`;
-   the `@register` / `@exposed` / `factory:construct` system;
-   the `sys:*` functions;
-   the `jcc:*` library;
-   the C89 generation strategy;
-   name mangling and overload resolution.

For any feature not described here, refer to the actual behavior of
`jcc.py` rather than assuming it is inherited from C or C++.

------------------------------------------------------------------------



## Current syntax checklist

The current implementation includes, among other features:

``` text
Types:
    void
    int / i32
    uint / u32
    short / i16
    ushort / u16
    long / i64
    ulong / u64
    char / i8
    uchar / u8
    sbyte / i8
    byte / u8
    float / f32
    double / f64
    bool
    string
    T*
    fn(T1, T2, ...) -> R
    list<T>
    map<K,V>
    pair<K,V>
    container<T>
    dynamic_list

Declarations:
    variable
    global variable
    @extern global
    function
    prototype
    struct
    union
    enum
    class
    forward declaration
    using type alias

Functions:
    default parameters
    named arguments
    overloads
    const methods
    virtual
    override
    callbacks/function pointers

Control:
    if / else if / else
    while
    for_loop
    loop_list
    loop_map
    break
    continue
    return

Expressions:
    arithmetic
    comparisons
    logical operators
    C-style casts
    address-of
    dereference
    member access
    indexing
    calls
    new
    nullptr
    list/map/pair/dynamic_list literals

Modules:
    using file
    using namespace
    using symbol
    using symbol as alias
    namespace

Reflection:
    @register
    @exposed
    factory:construct
    MemberExists
    GetMember
    SetMember

C interoperability:
    @extern
    pointers
    pointer-to-pointer
    function pointers
    &
    *
    nullptr
    .jah bindings

Build:
    JBS 1.0
    compile
    compile_static
    compile_shared
    link
    include
    define
    c89
    keep_c

Tools:
    jcc.py
    jbs.py
    jbg.py
```

------------------------------------------------------------------------




# Glossary {.appendix #glossary}

@@lead
The vocabulary of Jaguar and its toolchain, in alphabetical order.

| Term | Meaning |
|---|---|
| ABI | The binary conventions for how types are laid out and functions are called. Jaguar preserves the C ABI when it talks to C. |
| AST | The abstract syntax tree that the parser builds from the token stream. |
| Attribute | An annotation that begins with `@`, such as `@extern`, `@register` or `@exposed`. |
| BindGen | The tool (`jbg.py`) that converts a C header into a Jaguar header. |
| C89 mode | A code generation mode, enabled with `--c89` or the JBS `c89` directive, that produces C89-compatible block layout. |
| Code generator | The compiler stage that writes C from the resolved program. |
| Compilation unit | What the compiler processes at once. With JBS, all listed files and their imports are combined into one. |
| Container | A `container<T>` value, whose data is owned and eventually destroyed by the container. |
| Function-pointer type | A C-compatible type written `fn(T1, T2) -> R`. |
| GCC | The C compiler that turns the generated C into an executable. |
| Jaguar header (`.jah`) | A Jaguar interface file, meant to be reused with `using`. |
| JaguarCC (`jcc.py`) | The Jaguar compiler. |
| JBS (`jbs.py`) | The Jaguar Build System, which builds projects from `.jbs` files. |
| Lexer | The compiler stage that turns source text into tokens. |
| Name mangling | Adapting a name for C so that namespaces and overloads do not collide, for example `math_add`. |
| Namespace | A named scope for functions, structs, classes and nested namespaces, with `:` as the separator. |
| Overload | One of several functions that share a name and differ in parameters. |
| Parser | The compiler stage that builds a syntax tree from tokens. |
| Prototype | A function declaration without a body. |
| Reflection | Creating objects by name and reading or writing their exposed members at runtime. |
| Resolver | The compiler stage that resolves names, overloads, conversions and access rules. |
| Runtime | The small support code generated with a program, which manages strings, classes, containers, lists, maps and dynamic lists. |
| Signal | The `signal:` syntax that attaches a block to a variable, to react to changes. |
| `using` | The keyword for importing a file, opening a namespace, importing one symbol, or declaring a type alias. |
| `_jBool` | The runtime's own boolean type used in generated C instead of `_Bool`. |
