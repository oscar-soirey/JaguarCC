#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""jbg.py - Jaguar BindGen.

C API header -> Jaguar API header (.jah).

The C input is parsed with pycparser instead of regular expressions.  The
output is deliberately restricted to constructs understood by jcc.py:
structs, enums, type aliases, function prototypes and function-pointer types.
Unsupported C constructs are reported as warnings rather than silently being
turned into broken Jaguar declarations.

Usage:
    python jbg.py --c api.h
    python jbg.py --c api.h -o api.jah
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

try:
    from pycparser import c_parser, c_ast
except ImportError as exc:  # pragma: no cover
    raise SystemExit("jbg requires pycparser. Install it with: python -m pip install pycparser") from exc


# ---------------------------------------------------------------------------
# C parser preparation
# ---------------------------------------------------------------------------

_PREPROC_LINE = re.compile(r"^[ \t]*#.*?(?:\n|$)", re.M)

def strip_c_comments(src: str) -> str:
    # Keep strings intact while removing C comments.  This is intentionally
    # small; pycparser handles the actual C grammar afterwards.
    out = []
    i = 0
    n = len(src)
    state = "normal"
    while i < n:
        c = src[i]
        if state == "normal":
            if c == '"':
                state = "string"; out.append(c); i += 1; continue
            if c == "'":
                state = "char"; out.append(c); i += 1; continue
            if c == '/' and i + 1 < n and src[i + 1] == '/':
                j = src.find('\n', i + 2)
                if j < 0: break
                out.append('\n'); i = j + 1; continue
            if c == '/' and i + 1 < n and src[i + 1] == '*':
                j = src.find('*/', i + 2)
                if j < 0: raise ValueError("unterminated C comment")
                out.append('\n' * src[i:j + 2].count('\n'))
                i = j + 2; continue
            out.append(c); i += 1
        elif state == "string":
            out.append(c); i += 1
            if c == '\\' and i < n:
                out.append(src[i]); i += 1
            elif c == '"':
                state = "normal"
        else:
            out.append(c); i += 1
            if c == '\\' and i < n:
                out.append(src[i]); i += 1
            elif c == "'":
                state = "normal"
    return ''.join(out)


def _collect_object_macros(src: str) -> tuple[list[tuple[str, str]], set[str]]:
    """Collect simple object-like macros and declaration-only annotation macros.

    Annotation status is propagated through simple macro aliases so aliases
    such as GLAPIENTRY -> APIENTRY are not emitted as API constants.
    """
    clean = strip_c_comments(src)
    macros: list[tuple[str, str]] = []
    annotations: set[str] = set()
    lines = clean.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        m = re.match(r"^[ \t]*#[ \t]*define[ \t]+([A-Za-z_][A-Za-z0-9_]*)(.*)$", line)
        if not m:
            i += 1
            continue

        name = m.group(1)
        remainder = m.group(2)
        # A function-like macro has the opening '(' immediately after the
        # macro name, with no whitespace.
        if remainder.startswith("("):
            i += 1
            while i <= len(lines) and lines[i - 1].rstrip().endswith("\\"):
                i += 1
            continue

        value_parts = [remainder.strip()]
        while value_parts[-1].endswith("\\") and i + 1 < len(lines):
            value_parts[-1] = value_parts[-1][:-1].rstrip()
            i += 1
            value_parts.append(lines[i].strip())

        value = " ".join(value_parts).strip()
        if value:
            macros.append((name, value))

        if (
            not value
            or "__declspec" in value
            or "__attribute__" in value
            or value in {"__stdcall", "__cdecl", "__fastcall", "__vectorcall"}
        ):
            annotations.add(name)

        i += 1

    # Propagate annotation status through simple aliases, e.g.
    # `#define APIENTRY ...` followed by `#define GLAPIENTRY APIENTRY`.
    # Such aliases are declaration syntax, not API constants.
    macro_values = dict(macros)
    changed = True
    while changed:
        changed = False
        for name, value in macro_values.items():
            if name in annotations:
                continue
            tokens = re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\b", value)
            if len(tokens) == 1 and tokens[0] in annotations and value.strip() == tokens[0]:
                annotations.add(name)
                changed = True

    return macros, annotations


def _pp_eval(expr: str, defined_names: set[str]) -> bool:
    """Evaluate the small #if expression subset used by C API headers."""
    expr = expr.strip()
    expr = re.sub(
        r"\bdefined\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)",
        lambda m: "1" if m.group(1) in defined_names else "0",
        expr,
    )
    expr = re.sub(
        r"\bdefined\s+([A-Za-z_][A-Za-z0-9_]*)",
        lambda m: "1" if m.group(1) in defined_names else "0",
        expr,
    )
    expr = expr.replace("&&", " and ").replace("||", " or ")
    expr = re.sub(r"(?<![=!<>])!(?!=)", " not ", expr)
    # Undefined identifiers evaluate as zero for preprocessor #if purposes.
    expr = re.sub(
        r"\b[A-Za-z_][A-Za-z0-9_]*\b",
        lambda m: m.group(0) if m.group(0) in {"and", "or", "not"} else
        ("1" if m.group(0) in defined_names else "0"),
        expr,
    )
    try:
        return bool(eval(expr, {"__builtins__": {}}, {}))
    except Exception:
        # Unknown/non-trivial expressions are conservatively disabled rather
        # than leaked into pycparser where they can corrupt the AST.
        return False


def _strip_preprocessor(
    src: str,
    *,
    predefined: Optional[set[str]] = None,
) -> str:
    """Remove/evaluate simple C preprocessor conditionals while preserving lines."""
    defined_names = set(predefined or set())
    out: list[str] = []

    # Each frame stores (parent_active, current_active, branch_already_taken).
    stack: list[tuple[bool, bool, bool]] = []
    active = True

    lines = src.splitlines(keepends=True)
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.lstrip()

        if not stripped.startswith("#"):
            out.append(line if active else ("\n" if line.endswith("\n") else ""))
            i += 1
            continue

        # Gather a multiline directive, retaining one blank physical line per
        # source line in the output.
        directive_lines = [line]
        while directive_lines[-1].rstrip().endswith("\\") and i + 1 < len(lines):
            i += 1
            directive_lines.append(lines[i])

        directive = "".join(directive_lines)
        directive = directive.replace("\\\n", " ").replace("\\\r\n", " ")
        m = re.match(r"^[ \t]*#[ \t]*([A-Za-z_][A-Za-z0-9_]*)(?:[ \t]+(.*?))?[ \t]*$",
                     directive.strip())
        kind = m.group(1).lower() if m else ""
        arg = (m.group(2) or "").strip() if m else ""

        if kind == "if":
            cond = _pp_eval(arg, defined_names) if active else False
            frame = (active, active and cond, active and cond)
            stack.append(frame)
            active = frame[1]
        elif kind == "ifdef":
            cond = bool(re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", arg) and arg in defined_names)
            frame = (active, active and cond, active and cond)
            stack.append(frame)
            active = frame[1]
        elif kind == "ifndef":
            cond = bool(re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", arg) and arg not in defined_names)
            frame = (active, active and cond, active and cond)
            stack.append(frame)
            active = frame[1]
        elif kind == "elif":
            if stack:
                parent, _, taken = stack[-1]
                cond = _pp_eval(arg, defined_names) if parent and not taken else False
                taken_now = taken or (parent and cond)
                stack[-1] = (parent, parent and not taken and cond, taken_now)
                active = stack[-1][1]
        elif kind == "else":
            if stack:
                parent, _, taken = stack[-1]
                stack[-1] = (parent, parent and not taken, True)
                active = stack[-1][1]
        elif kind == "endif":
            if stack:
                parent, _, _ = stack.pop()
                active = parent
        elif kind == "define":
            if active:
                mm = re.match(r"([A-Za-z_][A-Za-z0-9_]*)(.*)$", arg)
                if mm:
                    name, remainder = mm.group(1), mm.group(2)
                    # Function-like macro if '(' is adjacent to the name.
                    if not remainder.startswith("("):
                        defined_names.add(name)
        elif kind == "undef":
            if active:
                mm = re.match(r"([A-Za-z_][A-Za-z0-9_]*)", arg)
                if mm:
                    defined_names.discard(mm.group(1))
        # All other directives (#include, #pragma, #error, #warning, etc.) are
        # intentionally omitted from the pycparser input.

        out.extend("\n" if l.endswith(("\n", "\r\n")) else "" for l in directive_lines)
        i += 1

    return "".join(out)


def prepare_c(
    src: str,
    *,
    predefined: Optional[set[str]] = None,
) -> str:
    _, annotation_macros = _collect_object_macros(src)

    src = strip_c_comments(src)

    # GLFW and many C library headers use an optional include tree guarded by
    # macros. The parser has no reason to ingest OpenGL/Vulkan system headers;
    # by default we select GLFW's no-GL/no-Vulkan branch.
    pp_defines = set(predefined or set())
    # GLFW includes OpenGL/Vulkan system headers by default. For GLFW itself,
    # select the documented no-GL/no-Vulkan branch so JBG can operate on the
    # standalone glfw3.h without needing the platform graphics headers.
    # Do not impose this define on unrelated C headers.
    if re.search(r"\bGLFW_INCLUDE_(?:VULKAN|NONE|GLCOREARB|GLU|ES[123])\b", src) or "_glfw3_h_" in src:
        pp_defines.add("GLFW_INCLUDE_NONE")
    src = _strip_preprocessor(src, predefined=pp_defines)

    # pycparser parses C, not C++ linkage specifications. Handle the common
    # top-level `extern "C" { ... }` wrapper without touching nested braces.
    if re.search(r'(?m)^[ \t]*extern[ \t]+"C"[ \t]*\{[ \t]*$', src):
        src = re.sub(
            r'(?ms)^[ \t]*extern[ \t]+"C"[ \t]*\{\s*(.*)\s*\}[ \t]*\Z',
            r"\1",
            src,
            count=1,
        )

    # Remove declaration-only ABI annotation macros (GLFWAPI,
    # __declspec(...), __attribute__(...), calling convention keywords).
    for name in sorted(annotation_macros, key=len, reverse=True):
        src = re.sub(
            rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])",
            "",
            src,
        )

    # Seed common libc typedefs so standalone headers using size_t/int*_t can
    # be parsed without requiring the platform's full system headers.
    prelude = (
        "typedef unsigned long size_t;\n"
        "typedef long ssize_t;\n"
        "typedef long intptr_t;\n"
        "typedef unsigned long uintptr_t;\n"
        "typedef signed char int8_t;\n"
        "typedef unsigned char uint8_t;\n"
        "typedef short int16_t;\n"
        "typedef unsigned short uint16_t;\n"
        "typedef int int32_t;\n"
        "typedef unsigned int uint32_t;\n"
        "typedef long long int64_t;\n"
        "typedef unsigned long long uint64_t;\n"
    )
    return prelude + src



# Number of lines injected by prepare_c(). These declarations exist only to
# help pycparser understand common libc types; they must never be emitted
# into the generated .jah file because the real C headers may already define
# them (for example ssize_t/intptr_t on MinGW).
PRELUDE_TYPEDEF_LINE_COUNT = 12

PRELUDE_TYPEDEFS = {
    "size_t", "ssize_t", "intptr_t", "uintptr_t",
    "int8_t", "uint8_t", "int16_t", "uint16_t",
    "int32_t", "uint32_t", "int64_t", "uint64_t",
}


# ---------------------------------------------------------------------------
# Jaguar type representation
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class JType:
    text: str
    valid: bool = True
    reason: str = ""


# Keep this list synchronized with jcc.py's lexer.  C identifiers are not
# required to avoid Jaguar keywords (for example GLFW has a parameter named
# `string`), so emitted parameter/field names must be sanitized.
JAGUAR_KEYWORDS = {
    "void", "int", "float", "char", "uint", "short", "ushort", "long",
    "ulong", "sbyte", "byte", "bool", "i8", "u8", "i16", "u16", "i32",
    "u32", "i64", "u64", "f32", "f64", "string",
    "dynamic_list", "list", "map", "container", "pair",
    "struct", "union", "enum", "namespace", "class", "virtual", "override",
    "constr", "destr", "return", "true", "false", "nullptr", "const",
    "using", "as", "loop", "if", "else", "while", "break", "continue",
    "for_loop", "this", "auto", "signal", "new",
}


def safe_jaguar_identifier(name: str, used: set[str]) -> str:
    candidate = name or "arg"
    if candidate in JAGUAR_KEYWORDS:
        candidate += "_"
    if candidate in used:
        base = candidate
        index = 2
        while f"{base}_{index}" in used:
            index += 1
        candidate = f"{base}_{index}"
    used.add(candidate)
    return candidate


C_BUILTINS = {
    "void": "void",
    "char": "i8",
    "signed char": "i8",
    "unsigned char": "u8",
    "short": "i16",
    "short int": "i16",
    "signed short": "i16",
    "signed short int": "i16",
    "unsigned short": "u16",
    "unsigned short int": "u16",
    "int": "int",
    "signed": "int",
    "signed int": "int",
    "unsigned": "u32",
    "unsigned int": "u32",
    "long": "i64",
    "signed long": "i64",
    "signed long int": "i64",
    "unsigned long": "u64",
    "unsigned long int": "u64",
    "long long": "i64",
    "signed long long": "i64",
    "signed long long int": "i64",
    "unsigned long long": "u64",
    "unsigned long long int": "u64",
    "float": "f32",
    "double": "f64",
    "long double": "f64",
    "_Bool": "bool",
    "bool": "bool",
    "size_t": "u64",
    "ssize_t": "i64",
    "int8_t": "i8",
    "uint8_t": "u8",
    "int16_t": "i16",
    "uint16_t": "u16",
    "int32_t": "i32",
    "uint32_t": "u32",
    "int64_t": "i64",
    "uint64_t": "u64",
    "intptr_t": "i64",
    "uintptr_t": "u64",
}


def normalize_quals(quals) -> list[str]:
    return [str(q) for q in (quals or []) if q not in {"restrict", "__restrict", "__restrict__"}]


def is_const_ptr_base(node) -> bool:
    return isinstance(node, c_ast.PtrDecl) and "const" in normalize_quals(node.type.quals)


def identifier_type(node: c_ast.IdentifierType) -> str:
    return ' '.join(node.names)


def strip_tag_prefix(name: str) -> str:
    return re.sub(r'^(struct|enum|union)\s+', '', name)


class TypeConverter:
    def __init__(self):
        self.typedef_names: set[str] = set()
        self.struct_names: set[str] = set()
        self.enum_names: set[str] = set()
        self.warnings: list[str] = []

    def convert(self, node, *, parameter=False, allow_c_string=True) -> JType:
        if isinstance(node, c_ast.TypeDecl):
            if isinstance(node.type, c_ast.IdentifierType):
                raw = identifier_type(node.type)
                mapped = C_BUILTINS.get(raw)
                if mapped:
                    return JType(mapped)
                return JType(raw)
            if isinstance(node.type, c_ast.Struct):
                return JType(node.type.name or "_anonymous_struct")
            if isinstance(node.type, c_ast.Enum):
                return JType(node.type.name or "_anonymous_enum")
            if isinstance(node.type, c_ast.Union):
                return JType(node.type.name or "_anonymous_union")
            return JType("", False, f"unsupported TypeDecl {type(node.type).__name__}")

        if isinstance(node, c_ast.PtrDecl):
            # A pointer to a function is a Jaguar function type, not `fn(...) -> T*`.
            if isinstance(node.type, c_ast.FuncDecl):
                return self.function_type(node.type)
            inner = self.convert(node.type, parameter=parameter, allow_c_string=False)
            if not inner.valid:
                return inner
            # Keep C pointer ABI exact. In particular, const char* is NOT
            # Jaguar `string`: Jaguar string is a runtime struct pointer and
            # would be ABI-incompatible with a C char buffer. Qualifiers do
            # not change the ABI, so const char* becomes i8* as well.
            return JType(inner.text + "*")

        if isinstance(node, c_ast.ArrayDecl):
            # In a C function parameter (including a callback typedef), an
            # array parameter is adjusted to a pointer by the C type system.
            # Converting it to a pointer therefore preserves the ABI.
            if parameter:
                inner = self.convert(node.type, parameter=True, allow_c_string=False)
                if not inner.valid:
                    return inner
                return JType(inner.text + "*")

            # Jaguar currently has no fixed-array declaration syntax. Never
            # replace a struct/global array with a pointer because that would
            # change the object layout.
            return JType(
                "",
                False,
                "C array types are not representable in a non-parameter declaration by current Jaguar syntax",
            )

        if isinstance(node, c_ast.FuncDecl):
            return self.function_type(node)

        if isinstance(node, c_ast.Struct):
            return JType(node.name or "_anonymous_struct")
        if isinstance(node, c_ast.Enum):
            return JType(node.name or "_anonymous_enum")
        if isinstance(node, c_ast.Union):
            return JType(node.name or "_anonymous_union", False, "Jaguar jcc has no union declaration")

        return JType("", False, f"unsupported C type node {type(node).__name__}")

    def function_type(self, node: c_ast.FuncDecl) -> JType:
        ret = self.convert(node.type)
        if not ret.valid:
            return ret
        params = []
        if node.args and node.args.params:
            if len(node.args.params) == 1 and isinstance(node.args.params[0], c_ast.Typename):
                p = node.args.params[0]
                if isinstance(p.type, c_ast.TypeDecl) and isinstance(p.type.type, c_ast.IdentifierType) and identifier_type(p.type.type) == "void":
                    return JType(f"fn() -> {ret.text}")
            for p in node.args.params:
                if isinstance(p, c_ast.EllipsisParam):
                    return JType("", False, "variadic C functions (...) are not representable by current Jaguar function syntax")
                ptype = self.convert(p.type, parameter=True)
                if not ptype.valid:
                    return ptype
                params.append(ptype.text)
        return JType(f"fn({', '.join(params)}) -> {ret.text}")

    def decl_type(self, decl: c_ast.Decl) -> JType:
        return self.convert(decl.type)


# ---------------------------------------------------------------------------
# AST -> Jaguar declarations
# ---------------------------------------------------------------------------

def _extract_c_comments(src: str):
    """Return C comments with source start/end line positions, preserving text."""
    comments = []
    i = 0
    n = len(src)
    state = "normal"
    while i < n:
        c = src[i]
        if state == "normal":
            if c == '"': state = "string"; i += 1; continue
            if c == "'": state = "char"; i += 1; continue
            if c == '/' and i + 1 < n and src[i+1] == '/':
                start = i; start_line = src.count("\n", 0, i) + 1
                j = src.find("\n", i + 2)
                if j < 0: j = n
                comments.append((start_line, start_line, src[start:j]))
                i = j; continue
            if c == '/' and i + 1 < n and src[i+1] == '*':
                start = i; start_line = src.count("\n", 0, i) + 1
                j = src.find("*/", i + 2)
                if j < 0: break
                end = j + 2
                end_line = src.count("\n", 0, end) + 1
                comments.append((start_line, end_line, src[start:end]))
                i = end; continue
            i += 1
        elif state == "string":
            if c == '\\': i += 2
            else:
                if c == '"': state = "normal"
                i += 1
        else:
            if c == '\\': i += 2
            else:
                if c == "'": state = "normal"
                i += 1
    return comments


def _comment_lines(text: str):
    return text.splitlines() or [text]


class BindGen:
    def __init__(self, ast: c_ast.FileAST):
        self.ast = ast
        self.tc = TypeConverter()
        self.out: list[str] = []
        self.errors: list[str] = []
        self.seen: set[str] = set()
        self.anon_struct_aliases: dict[str, c_ast.Struct] = {}
        self.anon_enum_aliases: dict[str, c_ast.Enum] = {}
        self.generated_inline_types: set[str] = set()
        self.typedef_targets: dict[str, str] = {}
        self.comments = []
        self.source_lines: list[str] = []
        self.used_comments: set[int] = set()
        self._collect_names()

    def add_comments_before(self, node):
        """Emit only comments that are immediately leading the AST node."""
        coord = getattr(node, "coord", None)
        if not coord or not coord.line or not self.comments:
            return
        line = coord.line - PRELUDE_TYPEDEF_LINE_COUNT
        if line <= 0:
            return

        for idx in range(len(self.comments) - 1, -1, -1):
            if idx in self.used_comments:
                continue
            start_line, end_line, text = self.comments[idx]
            if end_line >= line:
                continue
            # Everything between the end of this comment and the declaration
            # must be whitespace. This prevents a file-level doc comment from
            # being incorrectly attached to the first field of a struct.
            if self.source_lines:
                gap = self.source_lines[end_line:line - 1]
                if any(part.strip() for part in gap):
                    break
            # A small blank-line allowance keeps normal Doxygen formatting,
            # while still requiring the comment to be the nearest source item.
            for ln in _comment_lines(text):
                self.emit(ln)
            self.used_comments.add(idx)
            self.emit("")
            return

    def add_comments_before_decl(self, node):
        target = node
        typ = getattr(node, "type", None)
        if isinstance(typ, c_ast.TypeDecl) and isinstance(typ.type, (c_ast.Struct, c_ast.Enum, c_ast.Union)):
            target = typ.type
        self.add_comments_before(target)

    def _collect_names(self):
        for ext in self.ast.ext:
            if isinstance(ext, c_ast.Typedef):
                self.tc.typedef_names.add(ext.name)
            elif isinstance(ext, c_ast.Decl):
                if isinstance(ext.type, c_ast.Struct) and ext.type.name:
                    self.tc.struct_names.add(ext.type.name)
                if isinstance(ext.type, c_ast.Enum) and ext.type.name:
                    self.tc.enum_names.add(ext.type.name)

    @staticmethod
    def _comment(text: str) -> str:
        return "// " + text

    def warn(self, node, message: str):
        coord = getattr(node, "coord", None)
        where = f"line {coord.line}" if coord and coord.line else "unknown line"
        self.errors.append(f"{where}: {message}")

    def emit(self, line=""):
        # Structural lines such as `}` legitimately repeat. Global string
        # de-duplication corrupts nested aggregates, so only append here;
        # run() handles redundant blank lines separately.
        self.out.append(line)

    def _inline_named_type(self, node, context: str) -> JType:
        if isinstance(node, c_ast.TypeDecl):
            inner = node.type
            if isinstance(inner, c_ast.Struct):
                if inner.name: return JType(inner.name)
                self.convert_struct(inner, context)
                return JType(context)
            if isinstance(inner, c_ast.Union):
                if inner.name: return JType(inner.name)
                self.convert_union(inner, context)
                return JType(context)
            if isinstance(inner, c_ast.Enum):
                if inner.name: return JType(inner.name)
                self.convert_enum(inner, context)
                return JType(context)
        if isinstance(node, c_ast.PtrDecl):
            if isinstance(node.type, c_ast.TypeDecl) and isinstance(node.type.type, (c_ast.Struct, c_ast.Union, c_ast.Enum)) and not node.type.type.name:
                base = self._inline_named_type(node.type, context)
                return JType(base.text + "*") if base.valid else base
        return self.tc.convert(node)

    def convert_union(self, un: c_ast.Union, forced_name: Optional[str] = None):
        name = forced_name or un.name
        if not name:
            self.warn(un, "anonymous union without a field context is skipped")
            return

        fields = []
        unsupported = False
        for decl in un.decls or []:
            self.add_comments_before(decl)
            if not isinstance(decl, c_ast.Decl) or not decl.name:
                self.warn(decl or un, "anonymous union member is not representable")
                unsupported = True
                continue
            jt = self._inline_named_type(decl.type, f"{name}_{decl.name}")
            if not jt.valid:
                self.warn(decl, f"union field '{decl.name}': {jt.reason}")
                unsupported = True
                continue
            field_name = safe_jaguar_identifier(decl.name, used_names)
            fields.append((jt.text, field_name))

        if unsupported:
            self.emit(f"union {name};")
            self.emit("")
            self.warn(un, f"union '{name}' emitted as a forward declaration because its exact layout is not representable")
            return

        self.emit(f"union {name} {{")
        for typ, field in fields:
            self.emit(f"    {typ} {field};")
        self.emit("}")
        self.emit("")

    def convert_struct(self, st: c_ast.Struct, forced_name: Optional[str] = None):
        name = forced_name or st.name
        if not name:
            self.warn(st, "anonymous struct without a typedef name is skipped")
            return

        fields = []
        used_names: set[str] = set()
        unsupported = False
        for decl in st.decls or []:
            self.add_comments_before(decl)
            if not isinstance(decl, c_ast.Decl):
                unsupported = True
                continue
            if not decl.name:
                self.warn(decl, "anonymous struct field is not representable")
                unsupported = True
                continue
            jt = self._inline_named_type(decl.type, f"{name}_{decl.name}")
            if not jt.valid:
                self.warn(decl, f"field '{decl.name}': {jt.reason}")
                unsupported = True
                continue
            fields.append((jt.text, decl.name))

        if unsupported:
            # Emitting a partial struct would silently corrupt its C ABI layout.
            # jcc currently cannot semantically resolve forward declarations,
            # so use the same one-byte opaque placeholder as opaque typedefs.
            # This is only ABI-safe for APIs that expose the type through
            # pointers, which is how GLFW exposes GLFWgamepadstate.
            self.emit(f"struct {name} {{")
            self.emit("    u8 _jbg_opaque;")
            self.emit("}")
            self.emit("")
            self.warn(st, f"struct '{name}' emitted as an opaque placeholder because its exact layout is not representable")
            return

        self.emit(f"struct {name} {{")
        for typ, field in fields:
            self.emit(f"    {typ} {field};")
        self.emit("}")
        self.emit("")

    def convert_enum(self, en: c_ast.Enum, forced_name: Optional[str] = None):
        name = forced_name or en.name
        if not name:
            self.warn(en, "anonymous enum without a typedef name is skipped")
            return
        values = []
        for e in en.values.enumerators if en.values else []:
            if e.value is not None:
                # jcc's enum parser currently accepts names only, so do not
                # silently discard explicit numeric/string assignments.
                self.warn(e, f"enum value '{e.name}' has an explicit initializer; current Jaguar enum syntax does not support it")
                continue
            values.append(e.name)
        self.emit(f"enum {name} {{ {', '.join(values)} }}")
        self.emit("")

    def convert_typedef(self, td: c_ast.Typedef):
        # Typedefs injected by prepare_c() are parser-only shims. Emitting
        # them would create duplicate/conflicting typedefs when the generated
        # C includes the real platform headers (notably MinGW ssize_t).
        # These names were injected by prepare_c() only so pycparser can
        # understand common libc types.  They are represented directly by
        # Jaguar fixed-width types (u32, i64, ...), so never emit them as
        # Jaguar aliases.  This also avoids redeclaring MinGW's real typedefs.
        if td.name in PRELUDE_TYPEDEFS:
            return
        target = td.type
        name = td.name

        # typedef struct { ... } Name;
        if isinstance(target, c_ast.TypeDecl) and isinstance(target.type, c_ast.Struct):
            st = target.type
            if st.decls is not None:
                self.convert_struct(st, name)
            elif st.name:
                if name == st.name:
                    # Current jcc validation does not resolve forward-declared
                    # structs when they are used through pointers/function types.
                    # For opaque C handles such as GLFWwindow, emit a one-byte
                    # placeholder struct: GLFW only exposes these types through
                    # pointers, so pointer ABI remains exact while JCC has a
                    # complete Jaguar type it can resolve.
                    self.emit(f"struct {st.name} {{")
                    self.emit("    u8 _jbg_opaque;")
                    self.emit("}")
                else:
                    self.typedef_targets[name] = st.name
                    self.emit(f"using {name} = {st.name};")
                self.emit("")
            return

        # typedef enum { ... } Name;
        if isinstance(target, c_ast.TypeDecl) and isinstance(target.type, c_ast.Enum):
            en = target.type
            if en.values is not None:
                self.convert_enum(en, name)
            elif en.name:
                self.typedef_targets[name] = en.name
                self.emit(f"using {name} = {en.name};")
                self.emit("")
            return

        if isinstance(target, c_ast.TypeDecl) and isinstance(target.type, c_ast.Union):
            un = target.type
            if un.decls is not None:
                self.convert_union(un, name)
            elif un.name:
                if name == un.name: self.emit(f"union {un.name};")
                else:
                    self.typedef_targets[name] = un.name
                    self.emit(f"using {name} = {un.name};")
                self.emit("")
            return

        jt = self.tc.decl_type(td)
        if not jt.valid:
            self.warn(td, f"typedef '{name}': {jt.reason}")
            return

        # Jaguar's `using A = fn(...) -> T;` is supported by jcc.  All other
        # typedefs are also represented with using aliases, preserving ABI.
        self.typedef_targets[name] = jt.text
        self.emit(f"using {name} = {jt.text};")
        self.emit("")

    def function_decl(self, decl: c_ast.Decl):
        if not isinstance(decl.type, c_ast.FuncDecl):
            return False
        if not decl.name:
            self.warn(decl, "unnamed function declaration skipped")
            return True
        # C permits a declaration whose identifier is a keyword only through
        # invalid source; pycparser normally rejects it. No special recovery.
        ret = self.tc.convert(decl.type.type)
        if not ret.valid:
            self.warn(decl, f"function '{decl.name}': {ret.reason}")
            return True
        params = []
        used_names: set[str] = set()
        args = decl.type.args.params if decl.type.args and decl.type.args.params else []
        if len(args) == 1 and isinstance(args[0], c_ast.Typename):
            p = args[0]
            if isinstance(p.type, c_ast.TypeDecl) and isinstance(p.type.type, c_ast.IdentifierType) and identifier_type(p.type.type) == "void":
                args = []
        for i, p in enumerate(args):
            if isinstance(p, c_ast.EllipsisParam):
                self.warn(decl, f"function '{decl.name}' is variadic and cannot be represented by current Jaguar syntax")
                return True
            jt = self.tc.convert(p.type, parameter=True)
            if not jt.valid:
                self.warn(p, f"parameter '{getattr(p, 'name', None) or f'arg{i}'}': {jt.reason}")
                return True
            pname = getattr(p, "name", None) or f"arg{i}"
            pname = safe_jaguar_identifier(pname, used_names)
            params.append((jt.text, pname))
        self.emit(f"@extern {ret.text} {decl.name}({', '.join(f'{t} {n}' for t, n in params)});")
        return True

    def convert_decl(self, decl: c_ast.Decl):
        # Top-level function prototypes / declarations.
        if isinstance(decl.type, c_ast.FuncDecl):
            self.function_decl(decl)
            return
        # Function-pointer global declarations are representable as Jaguar
        # variables only if jcc's global function-pointer declaration works;
        # it does. `extern` is required because this is an API header.
        if isinstance(decl.type, c_ast.PtrDecl) and isinstance(decl.type.type, c_ast.FuncDecl):
            jt = self.tc.convert(decl.type)
            if not jt.valid:
                self.warn(decl, f"global '{decl.name}': {jt.reason}")
                return
            self.emit(f"@extern {jt.text} {decl.name};")
            return
        # Plain global variables are legal C APIs but jcc has global variable
        # support. Emit them as extern declarations; no initializer is copied.
        if decl.name:
            jt = self.tc.decl_type(decl)
            if jt.valid:
                safe_name = safe_jaguar_identifier(decl.name, set())
                self.emit(f"@extern {jt.text} {safe_name};")
            else:
                self.warn(decl, f"global '{decl.name}': {jt.reason}")

    def run(self) -> str:
        self.emit("// Generated by Jaguar BindGen (jbg).")
        self.emit("// Source language: C")
        self.emit("")

        # First pass: definitions and aliases. This is important because an
        # API often uses a typedef before a function prototype.
        for ext in self.ast.ext:
            if isinstance(ext, c_ast.Typedef):
                self.add_comments_before_decl(ext)
                self.convert_typedef(ext)
            elif isinstance(ext, c_ast.Decl):
                typ = ext.type
                if isinstance(typ, c_ast.Struct) and typ.decls is not None and typ.name:
                    self.add_comments_before_decl(ext)
                    self.convert_struct(typ)
                elif isinstance(typ, c_ast.Enum) and typ.values is not None and typ.name:
                    self.add_comments_before_decl(ext)
                    self.convert_enum(typ)
                elif isinstance(typ, c_ast.Union) and typ.decls is not None and typ.name:
                    self.add_comments_before_decl(ext)
                    self.convert_union(typ)

        # Second pass: functions and API globals.
        for ext in self.ast.ext:
            if isinstance(ext, c_ast.Decl):
                self.add_comments_before(ext)
                self.convert_decl(ext)

        # Remove excessive blank lines without losing section readability.
        cleaned = []
        blank = False
        for line in self.out:
            if line == "":
                if blank:
                    continue
                blank = True
            else:
                blank = False
            cleaned.append(line)
        return "\n".join(cleaned).rstrip() + "\n"


def _recover_known_invalid_decls(src: str) -> tuple[str, list[str]]:
    """Remove declarations that are unambiguously invalid C, so one typo does
    not prevent useful bindings from the rest of a large header.

    This is intentionally conservative.  We only recover a function-pointer
    declarator whose identifier is a C keyword (for example `void (*int)(...)`).
    Everything else is left to pycparser, because guessing a declaration can
    silently produce an ABI-breaking binding.
    """
    keywords = {
        "auto", "break", "case", "char", "const", "continue", "default",
        "do", "double", "else", "enum", "extern", "float", "for", "goto",
        "if", "inline", "int", "long", "register", "restrict", "return",
        "short", "signed", "sizeof", "static", "struct", "switch", "typedef",
        "union", "unsigned", "void", "volatile", "while", "_Bool",
    }
    warnings = []
    pattern = re.compile(
        r"(?m)^[ \t]*(?P<ret>[A-Za-z_][A-Za-z0-9_ \t]*?)\(\s*\*(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\)\s*\([^;{}]*\)\s*;"
    )
    def repl(m):
        name = m.group("name")
        if name in keywords:
            warnings.append(
                f"recovered invalid C declaration with reserved identifier '{name}'; declaration skipped"
            )
            return ""
        return m.group(0)
    return pattern.sub(repl, src), warnings


def generate(
    src: str,
    *,
    predefined: Optional[set[str]] = None,
) -> tuple[str, list[str]]:
    # Preserve simple object-like API constants. They are valid Jaguar
    # preprocessor lines and retain the original C macro semantics.
    macros, annotation_macros = _collect_object_macros(src)
    macros = [
        (name, value)
        for name, value in macros
        if name not in annotation_macros
        and not name.startswith("_glfw3_")
        and not name.endswith("_DEFINED")
    ]
    prepared = prepare_c(src, predefined=predefined)
    recovered, recovery_warnings = _recover_known_invalid_decls(prepared)
    parser = c_parser.CParser()
    try:
        ast = parser.parse(recovered, filename="<api.h>")
    except Exception as exc:
        # Keep the original diagnostic, but do not emit bogus Jaguar.
        raise ValueError(f"C parse error: {exc}") from exc
    gen = BindGen(ast)
    gen.comments = _extract_c_comments(src)
    gen.source_lines = src.splitlines()
    text = gen.run()
    if macros:
        macro_block = "\n".join(f"#define {name} {value}" for name, value in macros)
        marker = "// Source language: C\n"
        text = text.replace(marker, marker + "\n" + macro_block + "\n", 1)
    return text, recovery_warnings + gen.errors


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Jaguar BindGen - C API/header to .jah")
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--c", metavar="FILE", help="convert a C header")
    ap.add_argument("-o", "--output", metavar="FILE", help="output .jah file (default: same basename as input)")
    ap.add_argument("--stdout", action="store_true", help="write the generated .jah to stdout instead of creating a file")
    ap.add_argument("--strict", action="store_true", help="fail if any C declaration cannot be represented by current jcc syntax")
    ap.add_argument(
        "-D", "--define",
        action="append",
        default=[],
        metavar="NAME[=VALUE]",
        help="define a preprocessor symbol while preparing the C header (repeatable)",
    )
    args = ap.parse_args(argv)

    src_path = Path(args.c)
    try:
        src = src_path.read_text(encoding="utf-8")
        predefined = {
            item.split("=", 1)[0].strip()
            for item in args.define
            if item.split("=", 1)[0].strip()
        }
        text, warnings = generate(src, predefined=predefined)
    except Exception as exc:
        print(f"jbg: error: {exc}", file=sys.stderr)
        return 1

    if warnings:
        for warning in warnings:
            print(f"jbg: warning: {warning}", file=sys.stderr)
        if args.strict:
            return 2

    if args.stdout:
        sys.stdout.write(text)
    else:
        out_path = Path(args.output) if args.output else src_path.with_suffix(".jah")
        if out_path.suffix.lower() != ".jah":
            print("jbg: error: output file must use the .jah extension", file=sys.stderr)
            return 1
        out_path.write_text(text, encoding="utf-8")
        print(f"jbg: generated {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
