#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
jcc-c++.py — Backend Jaguar IR -> C++

Ce backend consomme exclusivement l'IR produit par jcc.py.
Il ne repasse jamais par le code C : les namespaces, classes, héritages,
constructeurs/destructeurs, méthodes, surcharge et opérateurs sont émis comme
leurs équivalents C++ natifs.

Usage :
    python3 jcc.py exemple.ja -o exemple.jir
    python3 jcc-c++.py exemple.jir
    python3 jcc-c++.py exemple.jir -o exemple       # écrit exemple.cpp
    python3 jcc-c++.py exemple.jir --emit-cpp       # génération sans g++
"""

from __future__ import annotations

import importlib.util
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import jcc
from jcc import *


# ---------------------------------------------------------------------------
# Charge jcc-c.py uniquement pour réutiliser ses outils sémantiques/backend-
# neutralisés (inférence, résolution des appels, contrôles de types, etc.).
# Aucune fonction de génération C n'est appelée par ce fichier.
# ---------------------------------------------------------------------------

def _load_c_backend_module():
    path = Path(__file__).with_name("jcc-c.py")
    spec = importlib.util.spec_from_file_location("_jaguar_c_backend", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load C backend: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_C = _load_c_backend_module()

CppCodeGenError = _C.CodeGenError


CPP_SCALAR_TYPES = {
    "void": "void",
    "int": "int",
    "uint": "unsigned int",
    "short": "short",
    "ushort": "unsigned short",
    "long": "long long",
    "ulong": "unsigned long long",
    "char": "signed char",
    "uchar": "unsigned char",
    "sbyte": "std::int8_t",
    "byte": "std::uint8_t",
    "i8": "std::int8_t",
    "u8": "std::uint8_t",
    "i16": "std::int16_t",
    "u16": "std::uint16_t",
    "i32": "std::int32_t",
    "u32": "std::uint32_t",
    "i64": "std::int64_t",
    "u64": "std::uint64_t",
    "float": "float",
    "f32": "float",
    "double": "double",
    "f64": "double",
    "bool": "bool",
    "string": "std::string",
    "nullptr": "std::nullptr_t",
}

CPP_OPERATOR_NAMES = {
    "operator+": "+",
    "operator-": "-",
    "operator*": "*",
    "operator/": "/",
    "operator%": "%",
    "operator==": "==",
    "operator!=": "!=",
    "operator<": "<",
    "operator>": ">",
    "operator<=": "<=",
    "operator>=": ">=",
}


class CppCodeGen(_C.CodeGen):
    """Backend Jaguar -> C++17.

    L'héritage de CodeGen C sert uniquement aux opérations sémantiques :
    résolution des surcharges, inférence de type, validations d'accès/const,
    découverte des classes, etc. Les méthodes de génération sont entièrement
    réécrites pour produire du C++ natif.
    """

    def __init__(self, program, groups, c89=False):
        super().__init__(program, groups, c89=False)
        self._cpp_current_namespace = None
        self._cpp_local_namespace_stack = []
        self._cpp_generated_factory = False
        self._cpp_registered_classes = []
        self._cpp_dynamic_list_type = "_JaguarDynamicList"
        self._cpp_tmp_id = 0
        self._cpp_indent = 0

        self._name_info = {}
        for item in self.program.items:
            if isinstance(item, (ClassDecl, StructDecl, UnionDecl, EnumDecl)):
                ns = getattr(item, "namespace", None)
                qname = item.name
                if ns:
                    prefix = ns.replace(":", "_") + "_"
                    local = qname[len(prefix):] if qname.startswith(prefix) else qname
                else:
                    local = qname
                self._name_info[qname] = (ns, local)

        self._functions_by_key = {}
        for item in self.program.items:
            if isinstance(item, FunctionDecl):
                self._functions_by_key.setdefault((item.namespace, item.name), []).append(item)

        self._decorators = dict(getattr(program, "_decorators", {}))

    # ------------------------------------------------------------------
    # Naming / types
    # ------------------------------------------------------------------

    def _namespace_parts(self, namespace):
        return namespace.split(":") if namespace else []

    def _namespace_cpp(self, namespace):
        return "::".join(self._namespace_parts(namespace))

    def _qualify_symbol(self, namespace, name):
        if not namespace or namespace == self._cpp_current_namespace:
            return name
        return f"{self._namespace_cpp(namespace)}::{name}"

    def _local_type_name(self, qname):
        info = self._name_info.get(qname)
        return info[1] if info else qname

    def _type_namespace(self, qname):
        info = self._name_info.get(qname)
        return info[0] if info else None

    def _cpp_user_type(self, qname):
        info = self._name_info.get(qname)
        if not info:
            return qname
        ns, local = info
        if ns == self._cpp_current_namespace:
            return local
        return self._qualify_symbol(ns, local)

    def _split_pointer(self, t):
        if not isinstance(t, str):
            return t, 0
        n = len(t) - len(t.rstrip("*"))
        return t.rstrip("*"), n

    def _generic_parts(self, t):
        return _C.CodeGen._generic_parts(t)

    def _split_generic_args(self, inner):
        return super()._split_generic_args(inner)

    def _cpp_type(self, t):
        if not isinstance(t, str):
            return t
        if t == "auto":
            return "auto"
        if t.startswith("fn("):
            return self._cpp_function_type(t)

        gp = self._generic_parts(t)
        if gp:
            kind, inner = gp
            if kind == "dynamic_list":
                return self._cpp_dynamic_list_type
            if kind == "list":
                return f"std::vector<{self._cpp_type(inner)}>"
            if kind == "map":
                a, b = self._split_generic_args(inner)
                return f"std::unordered_map<{self._cpp_type(a)}, {self._cpp_type(b)}>"
            if kind == "pair":
                a, b = self._split_generic_args(inner)
                return f"std::pair<{self._cpp_type(a)}, {self._cpp_type(b)}>"
            if kind == "container":
                return f"_JaguarContainer<{self._cpp_type(inner)}>"

        base, depth = self._split_pointer(t)
        if base in CPP_SCALAR_TYPES:
            name = CPP_SCALAR_TYPES[base]
        elif base in self.classes:
            # Jaguar keeps class values pointer-backed.  The C++ backend uses
            # real C++ classes, but preserves that source-level ownership
            # convention for bare class types.
            name = self._cpp_user_type(base)
            if depth == 0:
                depth = 1
        elif base in self._name_info:
            name = self._cpp_user_type(base)
        elif base in self.structs or base in self.unions:
            name = self._cpp_user_type(base)
        elif base.startswith("std::"):
            name = base
        else:
            name = base

        if depth:
            name += " " + "*" * depth
        return name

    def _cpp_function_type(self, t):
        parts = _C._function_type_parts(t)
        if not parts:
            return t
        params, ret = parts
        variadic = bool(params and params[-1] == "...")
        if variadic:
            params = params[:-1]
        p = ", ".join(self._cpp_type(x) for x in params) if params else ""
        if variadic:
            p = (p + ", ...") if p else "..."
        return f"{self._cpp_type(ret)} (*)({p})"

    def _cpp_decl_type(self, t):
        return self._cpp_type(t)

    def _cpp_param_decl(self, p: Param):
        typ = self._cpp_type(p.type)
        if p.pointee_const and isinstance(p.type, str) and p.type.endswith("*"):
            base = self._cpp_type(p.type[:-1])
            typ = f"const {base} *"
        elif p.is_const:
            # Pour les types valeur, const en C++ s'exprime naturellement ici.
            typ = f"const {typ}"
        return f"{typ} {p.name}"

    def _cpp_field_decl(self, f):
        typ = self._cpp_type(f.type)
        if getattr(f, "pointee_const", False) and isinstance(f.type, str) and f.type.endswith("*"):
            typ = f"const {self._cpp_type(f.type[:-1])} *"
        elif getattr(f, "is_const", False):
            typ = f"const {typ}"
        text = f"{typ} {f.name}"
        return text

    def _cpp_var_decl(self, v, with_init=True):
        typ = self._cpp_type(v.type)
        if getattr(v, "pointee_const", False) and isinstance(v.type, str) and v.type.endswith("*"):
            typ = f"const {self._cpp_type(v.type[:-1])} *"
        elif getattr(v, "is_const", False):
            typ = f"const {typ}"
        text = f"{typ} {v.name}"
        if with_init and v.init is not None:
            text += f" = {self.gen_expr(v.init, {})}"
        return text

    def _cpp_namespace_open(self, namespace):
        if not namespace:
            return []
        parts = self._namespace_parts(namespace)
        return [f"namespace {p} {{" for p in parts]

    def _cpp_namespace_close(self, namespace):
        if not namespace:
            return []
        return ["}" for _ in self._namespace_parts(namespace)]

    # ------------------------------------------------------------------
    # Runtime C++ léger
    # ------------------------------------------------------------------

    def _runtime_preamble(self):
        return r'''// Generated by JaguarCC C++ backend.
#include <algorithm>
#include <any>
#include <cassert>
#include <chrono>
#include <cctype>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <memory>
#include <mutex>
#include <random>
#include <stdexcept>
#include <string>
#include <thread>
#include <type_traits>
#include <typeinfo>
#include <unordered_map>
#include <utility>
#include <vector>

namespace jaguar_runtime {

using DynamicValue = std::any;
using DynamicList = std::vector<DynamicValue>;

template<class T>
struct Container {
    std::shared_ptr<T> data;
    Container() = default;
    explicit Container(const T& value) : data(std::make_shared<T>(value)) {}
    explicit Container(T&& value) : data(std::make_shared<T>(std::move(value))) {}
    explicit Container(T* value) : data(value) {}
    T& get() {
        if (!data) throw std::runtime_error("Jaguar runtime error: empty container access");
        return *data;
    }
    const T& get() const {
        if (!data) throw std::runtime_error("Jaguar runtime error: empty container access");
        return *data;
    }
};

inline void sys_print(const std::string& v) { std::cout << v; }
inline void sys_print(bool v) { std::cout << (v ? "true" : "false"); }
inline void sys_print(char v) { std::cout << v; }
inline void sys_print(unsigned char v) { std::cout << static_cast<unsigned int>(v); }
inline void sys_print(signed char v) { std::cout << static_cast<int>(v); }
inline void sys_print(float v) { std::cout << v; }
inline void sys_print(double v) { std::cout << v; }
template<class T, std::enable_if_t<std::is_integral_v<T> && !std::is_same_v<T, bool> && !std::is_same_v<T, char> && !std::is_same_v<T, signed char> && !std::is_same_v<T, unsigned char>, int> = 0>
inline void sys_print(T v) { std::cout << v; }

auto string_to_upper(std::string value) -> std::string {
    for (char& c : value) c = static_cast<char>(std::toupper(static_cast<unsigned char>(c)));
    return value;
}

auto string_to_lower(std::string value) -> std::string {
    for (char& c : value) c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
    return value;
}

inline bool string_starts_with(const std::string& value, const std::string& prefix) {
    return value.size() >= prefix.size() && value.compare(0, prefix.size(), prefix) == 0;
}
inline bool string_ends_with(const std::string& value, const std::string& suffix) {
    return value.size() >= suffix.size() && value.compare(value.size() - suffix.size(), suffix.size(), suffix) == 0;
}

inline void console_set_color(const std::string& value) { std::cout << value; }
inline void console_reset_color() { std::cout << "\033[0m"; }
inline int execute(const std::string& program, const std::string& path) {
    std::string command = "cd \"" + path + "\" && \"" + program + "\"";
    return std::system(command.c_str());
}
inline std::string fs_read(const std::string& path) {
    std::ifstream file(path, std::ios::binary);
    if (!file) throw std::runtime_error("Jaguar runtime error: cannot open file for reading");
    return std::string((std::istreambuf_iterator<char>(file)), std::istreambuf_iterator<char>());
}
inline void fs_write(const std::string& path, const std::string& data) {
    std::ofstream file(path, std::ios::binary);
    if (!file) throw std::runtime_error("Jaguar runtime error: cannot open file for writing");
    file.write(data.data(), static_cast<std::streamsize>(data.size()));
}

inline std::thread* thread_start(void (*fn)()) { return new std::thread(fn); }
inline void thread_join(std::thread* t) { if (t) { t->join(); delete t; } }
inline void thread_detach(std::thread* t) { if (t) { t->detach(); delete t; } }
inline void thread_sleep(std::uint64_t ms) { std::this_thread::sleep_for(std::chrono::milliseconds(ms)); }
inline void thread_yield() { std::this_thread::yield(); }

inline int abs_i32(int v) { return std::abs(v); }
inline int min_i32(int a, int b) { return std::min(a, b); }
inline int max_i32(int a, int b) { return std::max(a, b); }
inline int clamp_i32(int v, int lo, int hi) { return std::clamp(v, lo, hi); }
inline int random_i32(int lo, int hi) {
    static thread_local std::mt19937 rng(std::random_device{}());
    std::uniform_int_distribution<int> dist(lo, hi);
    return dist(rng);
}
inline std::int64_t time_ms() {
    return std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::system_clock::now().time_since_epoch()).count();
}

inline void assert_value(bool value, const std::string& message) {
    if (!value) throw std::runtime_error(message);
}

inline bool file_exists(const std::string& path) { return std::ifstream(path).good(); }

inline void dynamic_push(DynamicList& list, DynamicValue value) { list.push_back(std::move(value)); }
inline DynamicValue* dynamic_get(DynamicList& list, std::size_t index) {
    if (index >= list.size()) throw std::out_of_range("Jaguar dynamic_list index out of range");
    return &list[index];
}
inline const char* dynamic_type(const DynamicValue& value) {
    if (value.type() == typeid(bool)) return "bool";
    if (value.type() == typeid(std::int32_t) || value.type() == typeid(int)) return "i32";
    if (value.type() == typeid(std::int64_t)) return "i64";
    if (value.type() == typeid(float)) return "f32";
    if (value.type() == typeid(double)) return "f64";
    if (value.type() == typeid(std::string)) return "string";
    return value.type().name();
}

template<class T>
inline T* dynamic_cast_ptr(DynamicValue* value) {
    return value ? std::any_cast<T>(value) : nullptr;
}

using FactoryFn = void* (*)();
inline auto& factory_map() {
    static std::unordered_map<std::string, FactoryFn> value;
    return value;
}
struct FactoryRegister {
    FactoryRegister(const char* name, FactoryFn fn) { factory_map()[name] = fn; }
};
inline void* factory_construct(const std::string& name) {
    auto it = factory_map().find(name);
    if (it == factory_map().end()) throw std::runtime_error("Jaguar runtime error: class is not registered: " + name);
    return it->second();
}

} // namespace jaguar_runtime

using _JaguarDynamicList = jaguar_runtime::DynamicList;
template<class T> using _JaguarContainer = jaguar_runtime::Container<T>;
'''

    # ------------------------------------------------------------------
    # Top-level generation / namespaces
    # ------------------------------------------------------------------

    def gen(self, split_runtime=False):
        self._validate_parameter_defaults()
        lines = [self._runtime_preamble().rstrip()]

        # Préprocesseur utilisateur : conservé tel quel.
        top_preproc = [x.text for x in self.program.items if isinstance(x, PreprocLine)]
        if top_preproc:
            lines.extend(top_preproc)
            lines.append("")

        # Forward declarations utiles pour les types.
        forward = [x for x in self.program.items if isinstance(x, ForwardDecl)]
        if forward:
            for item in forward:
                name = self._cpp_user_type(item.name)
                keyword = "class" if item.kind == "class" else item.kind
                lines.append(f"{keyword} {name};")
            lines.append("")

        # Imports / aliases globaux Jaguar.
        for item in self.program.items:
            if isinstance(item, UsingNamespaceDecl):
                lines.append(f"using namespace {self._namespace_cpp(item.namespace)};")
            elif isinstance(item, UsingSymbolDecl):
                lines.append(f"using {self._namespace_cpp(item.namespace)}::{item.name};")
            elif isinstance(item, UsingImportDecl):
                # Les imports de modules sont consommés par JBS/Crimson et ne
                # constituent pas une construction C++ à eux seuls.
                pass
            elif isinstance(item, TypeAliasDecl):
                lines.append(self._gen_type_alias(item))
        if any(isinstance(x, (UsingNamespaceDecl, UsingSymbolDecl, TypeAliasDecl)) for x in self.program.items):
            lines.append("")

        # Enum/struct/union/class/function/variable par namespace. Les noms
        # Jaguar ont déjà été résolus vers les bons symboles IR.
        namespaces = []
        grouped = {}
        for item in self.program.items:
            if isinstance(item, (PreprocLine, ForwardDecl, UsingNamespaceDecl, UsingSymbolDecl, UsingImportDecl, TypeAliasDecl)):
                continue
            ns = getattr(item, "namespace", None)
            if ns not in grouped:
                grouped[ns] = []
                namespaces.append(ns)
            grouped[ns].append(item)

        # Place le namespace global d'abord, puis les namespaces dans l'ordre
        # d'apparition dans le fichier.
        for ns in namespaces:
            items = grouped[ns]
            self._cpp_current_namespace = ns
            if ns:
                lines.extend(self._cpp_namespace_open(ns))
            for item in items:
                text = self.gen_item(item)
                if text:
                    lines.append(self._indent_text(text, len(self._namespace_parts(ns))))
                    lines.append("")
            if ns:
                lines.extend(self._cpp_namespace_close(ns))
                lines.append("")

        factory = self._gen_factory_registration()
        if factory:
            lines.append(factory)

        return "\n".join(lines).rstrip() + "\n"

    def _indent_text(self, text, level):
        if level <= 0:
            return text
        prefix = "    " * level
        return "\n".join(prefix + line if line else line for line in text.splitlines())

    def _gen_type_alias(self, item):
        target = item.target
        if target.startswith("fn("):
            name = item.name
            parts = _C._function_type_parts(target)
            if parts:
                params, ret = parts
                variadic = bool(params and params[-1] == "...")
                if variadic:
                    params = params[:-1]
                p = ", ".join(self._cpp_type(x) for x in params)
                if variadic:
                    p = (p + ", ...") if p else "..."
                return f"using {name} = {self._cpp_type(ret)} (*)({p});"
        return f"using {item.name} = {self._cpp_type(target)};"

    def gen_item(self, item):
        self._current_namespace = getattr(item, "namespace", None)
        self._current_source_line = getattr(item, "_jaguar_line", 1)
        if isinstance(item, EnumDecl):
            return self.gen_enum(item)
        if isinstance(item, StructDecl):
            return self.gen_struct(item)
        if isinstance(item, UnionDecl):
            return self.gen_union(item)
        if isinstance(item, ClassDecl):
            return self.gen_class(item)
        if isinstance(item, FunctionDecl):
            return self.gen_function(item)
        if isinstance(item, VarDecl):
            return self.gen_global_var(item)
        if isinstance(item, DecoratorDecl):
            return ""
        if isinstance(item, TopExprStmt):
            return self.gen_expr(item.expr, {}) + ";"
        return ""

    # ------------------------------------------------------------------
    # Declarations
    # ------------------------------------------------------------------

    def gen_enum(self, e):
        lines = [f"enum {self._local_type_name(e.name)} {{"]
        for i, name in enumerate(e.values):
            init = ""
            if getattr(e, "initializers", None) and name in e.initializers:
                init = f" = {self.gen_expr(e.initializers[name], {})}"
            comma = "," if i + 1 < len(e.values) else ""
            lines.append(f"    {name}{init}{comma}")
        lines.append("};")
        return "\n".join(lines)

    def _class_field_list(self, cls):
        out = []
        if cls.base:
            base = self.classes.get(cls.base)
            if base:
                out.extend(self._class_field_list(base))
        out.extend(cls.fields)
        return out

    def gen_struct(self, s):
        lines = [f"struct {self._local_type_name(s.name)} {{"]
        for f in s.fields:
            lines.append(f"    {self._cpp_field_decl(f)};")
        lines.append("};")
        return "\n".join(lines)

    def gen_union(self, u):
        name = self._local_type_name(u.name)
        lines = [f"union {name} {{"]
        for f in u.fields:
            lines.append(f"    {self._cpp_field_decl(f)};")
        lines.append("};")
        # Même convention Jaguar : la déclaration de union nommée fournit
        # également un stockage global portant son ancien nom logique.
        lines.append(f"{name} _j_union_{name};")
        return "\n".join(lines)

    def _access_sections(self, members):
        sections = []
        current = None
        bucket = []
        for access, text in members:
            if access != current:
                if bucket:
                    sections.append((current, bucket))
                current = access
                bucket = []
            bucket.append(text)
        if bucket:
            sections.append((current, bucket))
        return sections

    def _cpp_method_decl(self, cls, m):
        name = m.name
        if m.is_constructor:
            name = self._local_type_name(cls.name)
            ret = ""
        elif m.is_destructor:
            name = "~" + self._local_type_name(cls.name)
            ret = ""
        else:
            ret = self._cpp_type(m.ret_type) + " "
        params = [self._cpp_param_decl(p) for p in m.params]
        if getattr(m, "is_variadic", False):
            params.append("...")
        prefix = "virtual " if m.is_virtual and not m.is_constructor and not m.is_destructor else ""
        signature = f"{prefix}{ret}{name}({', '.join(params)})".replace("  ", " ").strip()
        if m.is_const and not m.is_constructor and not m.is_destructor:
            signature += " const"
        if m.is_override:
            signature += " override"
        return signature

    def gen_class(self, cls: ClassDecl):
        local_name = self._local_type_name(cls.name)
        base = ""
        if cls.base:
            base_type = self._cpp_user_type(cls.base)
            base = f" : public {base_type}"
        lines = [f"class {local_name}{base} {{"]

        members = []
        # C++ constructors are always public for Jaguar, regardless of the
        # access marker used for ordinary members.
        for m in cls.methods:
            access = "public" if (m.is_constructor or m.is_destructor) else m.access
            decl = self._cpp_method_decl(cls, m) + ";"
            members.append((access, decl))
        for f in cls.fields:
            members.append((f.access, f"{self._cpp_field_decl(f)};"))

        # Le parser Jaguar conserve l'ordre des membres. Regroupe seulement
        # les changements d'accès nécessaires au langage C++.
        if not members:
            lines.append("public:")
            lines.append("    " + local_name + "() = default;")
        else:
            for access, bucket in self._access_sections(members):
                lines.append(f"{access}:")
                for text in bucket:
                    lines.append("    " + text)
        # Les classes @register exposent une simple factory native C++.
        if cls.is_registered:
            lines.append("public:")
            lines.append("    static void* _jaguar_factory_construct();")
        lines.append("};")

        old = self._current_class
        self._current_class = cls
        defs = []
        for m in cls.methods:
            defs.append(self._gen_method_definition(cls, m))
        if cls.is_registered:
            defs.append(self._gen_factory_method(cls))
        self._current_class = old
        if defs:
            lines.append("")
            lines.extend(defs)
        return "\n".join(lines)

    def _constructor_initializer(self, cls, m):
        init = []
        # Bases use the Jaguar constructor resolution when possible. In C++
        # an inherited base ctor is selected naturally; pass matching Jaguar
        # constructor arguments in the same order.
        if cls.base:
            base_cls = self.classes.get(cls.base)
            if base_cls:
                try:
                    base_ctor = self.resolve_class_constructor_call(base_cls.name, [Ident(p.name) for p in m.params], {p.name: p.type for p in m.params})
                except Exception:
                    base_ctor = None
                if base_ctor:
                    ordered = self._ordered_call_args([Ident(p.name) for p in m.params], base_ctor.params, f"constructor '{base_cls.name}'")
                    init.append(f"{self._cpp_user_type(base_cls.name)}({', '.join(self.gen_expr(a, {p.name:p.type for p in m.params}) for a in ordered)})")
        return init

    def _gen_method_definition(self, cls, m):
        self._current_namespace = cls.namespace
        local_name = self._local_type_name(cls.name)
        self._current_class_method_const = m.is_const
        self._current_return_type = m.ret_type
        self._current_source_line = getattr(m, "_jaguar_line", self._current_source_line)
        local_types = {p.name: p.type for p in m.params}
        self._current_function_local_types = local_types
        self._readonly_vars = {p.name for p in m.params if p.is_const}
        self._const_object_vars = {p.name for p in m.params if p.is_const and p.type in self.classes}
        self._pointee_const_vars = {p.name for p in m.params if p.pointee_const}
        self._change_handlers = self._collect_class_change_handlers(cls)

        params = ", ".join(self._cpp_param_decl(p) for p in m.params)
        if getattr(m, "is_variadic", False):
            params += (", " if params else "") + "..."
        if m.is_constructor:
            signature = f"{local_name}::{local_name}({params})"
            init_list = self._constructor_initializer(cls, m)
            const_fields = []
            for f in cls.fields:
                if getattr(f, "is_const", False) and f.init is not None:
                    const_fields.append(f"{f.name}({self.gen_expr(f.init, local_types)})")
            init_list.extend(const_fields)
            for f in cls.fields:
                if getattr(f, "is_const", False) and f.init is None:
                    raise CppCodeGenError(f"const field '{f.name}' of class '{local_name}' must be initialized")
            if init_list:
                signature += " : " + ", ".join(init_list)
        elif m.is_destructor:
            signature = f"{local_name}::~{local_name}()"
        else:
            signature = f"{self._cpp_type(m.ret_type)} {local_name}::{m.name}({params})"
            if m.is_const:
                signature += " const"
            if m.is_override:
                # override is already part of the class declaration; it does
                # not belong on an out-of-class definition.
                pass

        body = self._gen_cpp_block(m.body, local_types)
        return f"{signature} {body}"

    def _collect_class_change_handlers(self, cls):
        result = {}
        for sig in getattr(cls, "signals", []):
            result[sig.name] = sig.body
        return result

    def _gen_factory_method(self, cls):
        local_name = self._local_type_name(cls.name)
        try:
            self.resolve_class_constructor_call(cls.name, [], {})
        except Exception:
            return ""
        return "\\n".join([
            f"void* {local_name}::_jaguar_factory_construct() {{",
            f"    return static_cast<void*>(new {local_name}());",
            "}",
        ]).replace("\\n", "\n")

    def _gen_factory_registration(self):
        registered = []
        for cls in self.classes.values():
            if cls.name == "string" or not cls.is_registered:
                continue
            try:
                self.resolve_class_constructor_call(cls.name, [], {})
            except Exception:
                continue
            qualified = self._cpp_user_type(cls.name)
            registered.append((qualified, self._type_namespace(cls.name)))
        if not registered:
            return ""
        lines = []
        for qualified, ns in registered:
            # Qualified name is needed outside any source namespace because
            # this block is emitted at global scope.
            escaped = qualified.replace("::", "_")
            lines.append(
                f"static ::jaguar_runtime::FactoryRegister _jaguar_register_{escaped}"
                f"(\"{qualified}\", []() -> void* {{ return static_cast<void*>(new {qualified}()); }});"
            )
        return "\n".join(lines)

    def gen_function(self, fn):
        self._current_namespace = fn.namespace
        self._current_source_line = getattr(fn, "_jaguar_line", 1)
        if self._is_special_main(fn):
            return self._gen_cpp_main(fn)
        if fn.is_variadic and not fn.is_prototype:
            raise CppCodeGenError("variadic Jaguar functions must currently be prototypes/@extern; Jaguar does not expose va_list yet")
        if fn.decorators and (fn.is_prototype or fn.is_extern or fn.ret_type != "void"):
            raise CppCodeGenError("decorators currently require a non-extern, non-prototype void function")

        if fn.is_prototype:
            params = [self._cpp_param_decl(p) for p in fn.params]
            if fn.is_variadic:
                params.append("...")
            prefix = "extern " if fn.is_extern else ""
            return f"{prefix}{self._cpp_type(fn.ret_type)} {self._cpp_function_name(fn)}({', '.join(params)});"

        implementation_name = fn.implementation_name or fn.name
        params = ", ".join(self._cpp_param_decl(p) for p in fn.params)
        if fn.is_variadic:
            params += (", " if params else "") + "..."
        prefix = "extern " if fn.is_extern else ""
        header_name = implementation_name
        if fn.name.startswith("operator") and fn.name in CPP_OPERATOR_NAMES:
            header_name = fn.name if self._cpp_operator_is_native(fn) else self._cpp_operator_function_name(fn)
        signature = f"{prefix}{self._cpp_type(fn.ret_type)} {header_name}({params})"

        local_types = {p.name: p.type for p in fn.params}
        self._current_function_local_types = local_types
        self._readonly_vars = {p.name for p in fn.params if p.is_const}
        self._const_object_vars = {p.name for p in fn.params if p.is_const and p.type in self.classes}
        self._pointee_const_vars = {p.name for p in fn.params if p.pointee_const}
        self._current_return_type = fn.ret_type
        self._current_cpp_function = fn
        self._change_handlers = {}
        body = self._gen_cpp_block(fn.body, local_types)
        if fn.ret_type != "void" and not self._block_guarantees_return(fn.body):
            raise CppCodeGenError(f"non-void function '{fn.name}' may exit without returning a value of type '{fn.ret_type}'")
        result = f"{signature} {body}"

        if fn.decorators:
            # Le corps original devient une implémentation interne, et les
            # décorateurs enveloppent la fonction sous son nom Jaguar public.
            impl = implementation_name
            if impl == fn.name:
                impl = f"{fn.name}__decor_impl"
            result = result.replace(f" {header_name}(", f" {impl}(", 1)
            wrapped = []
            current_target = impl
            for i, use in enumerate(reversed(fn.decorators), 1):
                wrapped.append(self._gen_cpp_decorator_wrapper(fn, current_target, use, i))
                current_target = fn.name if i == len(fn.decorators) else f"{fn.name}__decor_{len(fn.decorators)-i}"
            result += "\n\n" + "\n\n".join(reversed(wrapped))
        return result

    def _cpp_function_name(self, fn):
        if fn.name.startswith("operator") and fn.name in CPP_OPERATOR_NAMES:
            return CPP_OPERATOR_NAMES[fn.name]
        return fn.name

    def _gen_cpp_decorator_wrapper(self, fn, target_name, use, index):
        dec = self._decorators.get((fn.namespace, use.name)) or self._decorators.get((None, use.name))
        if dec is None:
            raise CppCodeGenError(f"unknown decorator '@{use.name}'")
        ordered = self._ordered_call_args(use.args, dec.params, f"decorator '@{use.name}'")
        target_types = {p.name: p.type for p in fn.params}
        for arg, p in zip(ordered, dec.params):
            self._check_assignable(p.type, self.infer_type(arg, target_types), f"argument '{p.name}' of decorator '@{use.name}'", arg)
        wrapper_name = fn.name if index == 1 else f"{fn.name}__decor_{index-1}"
        params = ", ".join(self._cpp_param_decl(p) for p in fn.params)
        local_types = dict(target_types)
        local_types.update({p.name: p.type for p in dec.params})
        old_target = getattr(self, "_decorator_call_target_name", None)
        old_params = getattr(self, "_decorator_target_params", [])
        self._decorator_call_target_name = target_name
        self._decorator_target_params = list(fn.params)
        try:
            decl_lines = [f"{self._cpp_type(p.type)} {p.name} = {self.gen_expr(arg, target_types)};" for p, arg in zip(dec.params, ordered)]
            body_lines = self._gen_cpp_body_lines(dec.body.statements, local_types)
        finally:
            self._decorator_call_target_name = old_target
            self._decorator_target_params = old_params
        return "\n".join([f"void {wrapper_name}({params}) {{"] + ["    " + x for x in decl_lines + body_lines] + ["}"])

    def gen_global_var(self, v):
        prefix = "extern " if v.is_extern else ""
        if v.init is None and v.type in self.classes and not v.is_extern:
            return f"{prefix}{self._cpp_type(v.type)} {v.name} = new {self._local_type_name(v.type)}();"
        if v.init is not None and self._is_factory_construct_call(v.init) and v.type in self.classes:
            expr = self.gen_expr(v.init, {})
            expr = f"static_cast<{self._cpp_type(v.type)}>({expr})"
            return f"{prefix}{self._cpp_type(v.type)} {v.name} = {expr};"
        if v.init is None:
            return f"{prefix}{self._cpp_var_decl(v, with_init=False)};"
        return f"{prefix}{self._cpp_var_decl(v)};"

    @staticmethod
    def _is_factory_construct_call(expr):
        return (
            isinstance(expr, Call)
            and isinstance(expr.callee, NamespacedIdent)
            and expr.callee.namespace == "factory"
            and expr.callee.name == "construct"
        )

    # ------------------------------------------------------------------
    # Expressions
    # ------------------------------------------------------------------

    def _find_enum_value(self, e: NamespacedIdent):
        enums = getattr(self.program, "_enums", {})
        for _, enum in enums.items():
            if enum.namespace == e.namespace and e.name in enum.values:
                return enum
            if enum.name == e.namespace and e.name in enum.values:
                return enum
        return None

    def _cpp_named_args(self, args, params, callee_name):
        ordered = self._ordered_call_args(args, params, callee_name)
        return ", ".join(self.gen_expr(a, self._current_function_local_types) for a in ordered)

    def _cpp_operator_function_name(self, fn):
        return "_jaguar_" + (fn.mangled_name or fn.name)

    def _cpp_operator_is_native(self, fn):
        if not fn.name.startswith("operator") or fn.name not in CPP_OPERATOR_NAMES:
            return False
        enums = getattr(self.program, "_enums", {})
        for p in fn.params:
            base = p.type.rstrip("*") if isinstance(p.type, str) else p.type
            if base in self.classes or base in self.structs or base in self.unions:
                return True
            if base in enums or any(getattr(e, "name", None) == base for e in enums.values()):
                return True
        return False

    def _string_method_expr(self, obj, name, args, local_types):
        ordered = args
        if name in ("equals", "contains", "starts_with", "ends_with", "concat"):
            ordered = self._ordered_call_args(args, [Param("string", "other")], f"string::{name}")
        elif name == "substring":
            ordered = self._ordered_call_args(args, [Param("i32", "start"), Param("i32", "length")], f"string::{name}")
        elif name == "char_at":
            ordered = self._ordered_call_args(args, [Param("i32", "index")], f"string::{name}")
        a = [self.gen_expr(x, local_types) for x in ordered]
        if name == "length":
            return f"static_cast<std::int32_t>({obj}.size())"
        if name == "empty":
            return f"{obj}.empty()"
        if name == "equals":
            return f"({obj} == {a[0]})"
        if name == "contains":
            return f"({obj}.find({a[0]}) != std::string::npos)"
        if name == "starts_with":
            return f"jaguar_runtime::string_starts_with({obj}, {a[0]})"
        if name == "ends_with":
            return f"jaguar_runtime::string_ends_with({obj}, {a[0]})"
        if name == "concat":
            return f"({obj} + {a[0]})"
        if name == "substring":
            return f"{obj}.substr(static_cast<std::size_t>({a[0]}), static_cast<std::size_t>({a[1]}))"
        if name == "char_at":
            return f"static_cast<std::int32_t>(static_cast<unsigned char>({obj}.at(static_cast<std::size_t>({a[0]}))))"
        if name == "to_upper":
            return f"jaguar_runtime::string_to_upper({obj})"
        if name == "to_lower":
            return f"jaguar_runtime::string_to_lower({obj})"
        raise CppCodeGenError(f"unknown string::{name} method")

    def gen_expr(self, e, local_types: dict) -> str:
        if e is None:
            return ""
        if isinstance(e, NullPtrLit):
            return "nullptr"
        if isinstance(e, IntLit):
            return e.value
        if isinstance(e, FloatLit):
            return e.value
        if isinstance(e, StringLit):
            return e.value
        if isinstance(e, BoolLit):
            return "true" if e.value else "false"
        if isinstance(e, Ident):
            if e.name == "this":
                return "this"
            if e.name in getattr(self, "union_globals", {}):
                return f"_j_union_{e.name}"
            return e.name
        if isinstance(e, NamespacedIdent):
            enum = self._find_enum_value(e)
            if enum is not None:
                enum_name = self._local_type_name(enum.name)
                if enum.namespace:
                    return f"{self._namespace_cpp(enum.namespace)}::{e.name}"
                return e.name
            if e.namespace == "factory" and e.name == "construct":
                return "jaguar_runtime::factory_construct"
            return f"{self._namespace_cpp(e.namespace)}::{e.name}"
        if isinstance(e, CastExpr):
            if isinstance(e.operand, IndexAccess):
                ot = self.infer_type(e.operand.obj, local_types)
                gp = self._generic_parts(ot)
                if gp and gp[0] == "dynamic_list":
                    idx = self.gen_expr(e.operand.index, local_types)
                    target = self._cpp_type(e.target_type)
                    return f"std::any_cast<{target}>(*jaguar_runtime::dynamic_get(&{self.gen_expr(e.operand.obj, local_types)}, static_cast<std::size_t>({idx})))"
            return f"static_cast<{self._cpp_type(e.target_type)}>({self.gen_expr(e.operand, local_types)})"
        if isinstance(e, UnaryOp):
            inner = self.gen_expr(e.operand, local_types)
            if isinstance(e.operand, (BinOp, UnaryOp)):
                inner = f"({inner})"
            return f"{e.op}{inner}"
        if isinstance(e, BinOp):
            left_type = self.infer_type(e.left, local_types)
            right_type = self.infer_type(e.right, local_types)
            custom = self._resolve_operator(e.op, left_type, right_type)
            # En C++, l'opérateur peut être émis directement : la surcharge
            # native sera choisie par le compilateur.
            if custom is not None:
                if self._cpp_operator_is_native(custom) or getattr(self, "_current_cpp_function", None) is custom:
                    prec = _C._BINOP_PREC[e.op]
                    left = self._gen_cpp_operand(e.left, prec, local_types, False)
                    right = self._gen_cpp_operand(e.right, prec, local_types, True)
                    return f"{left} {e.op} {right}"
                return f"{self._qualify_symbol(custom.namespace, self._cpp_operator_function_name(custom))}({self.gen_expr(e.left, local_types)}, {self.gen_expr(e.right, local_types)})"
            prec = _C._BINOP_PREC[e.op]
            left = self._gen_cpp_operand(e.left, prec, local_types, False)
            right = self._gen_cpp_operand(e.right, prec, local_types, True)
            return f"{left} {e.op} {right}"
        if isinstance(e, MemberAccess):
            return self.gen_member_access(e, local_types)
        if isinstance(e, IndexAccess):
            obj = self.gen_expr(e.obj, local_types)
            idx = self.gen_expr(e.index, local_types)
            ot = self.infer_type(e.obj, local_types)
            gp = self._generic_parts(ot)
            if gp and gp[0] == "list":
                return f"{obj}.at(static_cast<std::size_t>({idx}))"
            if gp and gp[0] == "map":
                return f"{obj}.at({idx})"
            if gp and gp[0] == "dynamic_list":
                return f"*jaguar_runtime::dynamic_get(&{obj}, static_cast<std::size_t>({idx}))"
            return f"{obj}[{idx}]"
        if isinstance(e, NewExpr):
            target = self._cpp_user_type(e.type) if e.type in self._name_info else self._cpp_type(e.type)
            args = ", ".join(self.gen_expr(a.expr if isinstance(a, NamedArg) else a, local_types) for a in e.args)
            return f"new {target}({args})"
        if isinstance(e, ListLiteral):
            items = ", ".join(self.gen_expr(x, local_types) for x in e.items)
            return "{" + items + "}"
        if isinstance(e, Call):
            if isinstance(e.callee, Ident) and e.callee.name == "func" and getattr(self, "_decorator_call_target_name", None):
                args = ", ".join(p.name for p in self._decorator_target_params)
                return f"{self._decorator_call_target_name}({args})"

            # Jaguar constructor calls such as `Foo(1)` are pointer-backed
            # class construction in the existing language. C++ uses `new` for
            # the same source-level operation. Struct calls remain value types.
            if isinstance(e.callee, Ident):
                class_name = self._resolve_class_name(e.callee.name)
                struct_name = self._resolve_struct_name(e.callee.name)
            elif isinstance(e.callee, NamespacedIdent):
                class_name = self._resolve_class_name(e.callee.name, e.callee.namespace)
                struct_name = self._resolve_struct_name(e.callee.name, e.callee.namespace)
            else:
                class_name = struct_name = None

            if class_name is not None:
                ctor = self.resolve_class_constructor_call(class_name, e.args, local_types)
                ordered = self._ordered_call_args(e.args, ctor.params if ctor else [], f"constructor '{class_name}'")
                qname = self._cpp_user_type(class_name)
                return f"new {qname}({', '.join(self.gen_expr(a, local_types) for a in ordered)})"

            if struct_name is not None:
                struct_decl = self.structs[struct_name]
                if any(isinstance(a, NamedArg) for a in e.args):
                    raise CppCodeGenError(f"struct '{struct_name}' construction only accepts positional arguments")
                if len(e.args) not in (0, len(struct_decl.fields)):
                    raise CppCodeGenError(f"struct '{struct_name}' construction expects {len(struct_decl.fields)} argument(s), {len(e.args)} provided")
                args = [self.gen_expr(a, local_types) for a in e.args]
                return f"{self._cpp_user_type(struct_name)}{{{', '.join(args)}}}"

            # factory:construct(name)
            if isinstance(e.callee, NamespacedIdent) and e.callee.namespace == "factory" and e.callee.name == "construct":
                if len(e.args) != 1:
                    raise CppCodeGenError("factory:construct() expects exactly one argument")
                return f"jaguar_runtime::factory_construct({self.gen_expr(e.args[0].expr if isinstance(e.args[0], NamedArg) else e.args[0], local_types)})"

            if isinstance(e.callee, MemberAccess):
                ot = self.infer_type(e.callee.obj, local_types)
                raw_ot = ot
                pointer = isinstance(ot, str) and ot.endswith("*")
                if pointer:
                    ot = ot.rstrip("*")
                elif isinstance(ot, str) and ot in self.classes:
                    # Bare Jaguar class values are pointer-backed in this
                    # backend, matching the existing Jaguar ABI semantics.
                    pointer = True
                gp = self._generic_parts(ot)
                obj = self.gen_expr(e.callee.obj, local_types)
                if gp:
                    kind, inner = gp
                    if kind == "list":
                        if e.callee.name == "size":
                            if e.args: raise CppCodeGenError("list::size expects 0 arguments")
                            return f"static_cast<std::int32_t>({obj}.size())"
                        if e.callee.name == "get":
                            if len(e.args) != 1: raise CppCodeGenError("list::get expects 1 argument")
                            return f"{obj}.at(static_cast<std::size_t>({self.gen_expr(e.args[0], local_types)}))"
                        if e.callee.name == "push":
                            if len(e.args) != 1: raise CppCodeGenError("list::push expects 1 argument")
                            return f"{obj}.push_back({self.gen_expr(e.args[0], local_types)})"
                    if kind == "map":
                        if e.callee.name == "size":
                            if e.args: raise CppCodeGenError("map::size expects 0 arguments")
                            return f"static_cast<std::int32_t>({obj}.size())"
                        if e.callee.name == "emplace":
                            if len(e.args) != 2: raise CppCodeGenError("map::emplace expects 2 arguments")
                            k = self.gen_expr(e.args[0], local_types)
                            v = self.gen_expr(e.args[1], local_types)
                            return f"{obj}.insert_or_assign({k}, {v})"
                    if kind == "pair":
                        return f"{obj}.{e.callee.name}"
                    if kind == "container" and e.callee.name == "get":
                        return f"{obj}.get()"
                    if kind == "dynamic_list":
                        if e.callee.name == "push":
                            if len(e.args) != 1: raise CppCodeGenError("dynamic_list::push expects 1 argument")
                            return f"jaguar_runtime::dynamic_push({obj}, {self.gen_expr(e.args[0], local_types)})"
                        if e.callee.name == "get":
                            if len(e.args) != 1: raise CppCodeGenError("dynamic_list::get expects 1 argument")
                            return f"jaguar_runtime::dynamic_get({obj}, static_cast<std::size_t>({self.gen_expr(e.args[0], local_types)}))"
                        if e.callee.name == "type":
                            if len(e.args) != 1: raise CppCodeGenError("dynamic_list::type expects 1 argument")
                            expr = self.gen_expr(e.args[0], local_types)
                            return f"std::string(jaguar_runtime::dynamic_type(*jaguar_runtime::dynamic_get({obj}, static_cast<std::size_t>({expr}))))"
                        if e.callee.name == "size":
                            if e.args: raise CppCodeGenError("dynamic_list::size expects 0 arguments")
                            return f"static_cast<std::int32_t>({obj}.size())"
                if ot == "string":
                    return self._string_method_expr(obj, e.callee.name, e.args, local_types)

                # Appel de méthode C++ natif. On laisse la résolution Jaguar
                # contrôler les arguments, puis le langage gère la surcharge.
                if ot in self.classes:
                    owner, method = self.resolve_class_method_call(ot, e.callee.name, e.args, local_types, self._expr_is_const_receiver(e.callee.obj, local_types))
                    if method is not None:
                        self._check_member_access(owner, method, e.callee.name)
                        ordered = self._ordered_call_args(e.args, method.params, f"'{e.callee.name}'")
                        return f"{obj}.{method.name}({', '.join(self.gen_expr(a, local_types) for a in ordered)})" if not pointer else f"{obj}->{method.name}({', '.join(self.gen_expr(a, local_types) for a in ordered)})"
                use_arrow = pointer or (isinstance(e.callee.obj, Ident) and e.callee.obj.name == "this")
                return f"{obj}->{e.callee.name}({', '.join(self.gen_expr(a.expr if isinstance(a, NamedArg) else a, local_types) for a in e.args)})" if use_arrow else f"{obj}.{e.callee.name}({', '.join(self.gen_expr(a.expr if isinstance(a, NamedArg) else a, local_types) for a in e.args)})"

            callee_type = self.infer_type(e.callee, local_types)
            args = e.args
            if isinstance(e.callee, Ident) and self._current_class:
                owner, method = self.resolve_class_method_call(self._current_class.name, e.callee.name, e.args, local_types, self._current_class_method_const)
                if method is not None:
                    self._check_member_access(owner, method, e.callee.name)
                    ordered = self._ordered_call_args(e.args, method.params, f"'{e.callee.name}'")
                    return f"{method.name}({', '.join(self.gen_expr(a, local_types) for a in ordered)})"

            if isinstance(e.callee, NamespacedIdent):
                if e.callee.namespace == "factory":
                    return f"jaguar_runtime::{e.callee.name}({', '.join(self.gen_expr(a.expr if isinstance(a, NamedArg) else a, local_types) for a in e.args)})"
                system = self._system_builtin(e.callee, e)
                if system is not None:
                    return self._gen_system_call(system, e, local_types)
                target = self.resolve_call_target(e, local_types)
                if target is not None:
                    ordered = self._ordered_call_args(e.args, target.params, f"'{e.callee.name}'", target.is_variadic)
                    return f"{self._qualify_symbol(target.namespace, target.name)}({', '.join(self.gen_expr(a, local_types) for a in ordered)})"
                return f"{self._namespace_cpp(e.callee.namespace)}::{self._cpp_function_name_from_name(e.callee.name)}({', '.join(self.gen_expr(a.expr if isinstance(a, NamedArg) else a, local_types) for a in e.args)})"

            if isinstance(e.callee, Ident):
                system = self._system_builtin(e.callee, e)
                if system is not None:
                    return self._gen_system_call(system, e, local_types)
                target = self.resolve_call_target(e, local_types)
                if target is not None:
                    ordered = self._ordered_call_args(e.args, target.params, f"'{e.callee.name}'", target.is_variadic)
                    return f"{self._cpp_function_name(target)}({', '.join(self.gen_expr(a, local_types) for a in ordered)})"
                if callee_type and isinstance(callee_type, str) and callee_type.startswith("fn("):
                    return f"{self.gen_expr(e.callee, local_types)}({', '.join(self.gen_expr(a.expr if isinstance(a, NamedArg) else a, local_types) for a in e.args)})"
                return f"{e.callee.name}({', '.join(self.gen_expr(a.expr if isinstance(a, NamedArg) else a, local_types) for a in e.args)})"

            return f"{self.gen_expr(e.callee, local_types)}({', '.join(self.gen_expr(a.expr if isinstance(a, NamedArg) else a, local_types) for a in e.args)})"

        raise NotImplementedError(f"expression non gérée par le backend C++: {e!r}")

    def _cpp_function_name_from_name(self, name):
        return name

    def _cpp_function_name(self, fn):
        return self._cpp_function_name_from_name(fn.name)

    def _gen_cpp_operand(self, e, parent_prec, local_types, is_right):
        s = self.gen_expr(e, local_types)
        if isinstance(e, BinOp):
            p = _C._BINOP_PREC[e.op]
            if p < parent_prec or (p == parent_prec and is_right):
                return f"({s})"
        return s

    def gen_member_access(self, e, local_types):
        raw = self.infer_type(e.obj, local_types)
        pointer = isinstance(raw, str) and raw.endswith("*")
        typ = raw.rstrip("*") if pointer else raw
        if not pointer and isinstance(typ, str) and typ in self.classes:
            pointer = True
        obj = self.gen_expr(e.obj, local_types)

        gp = self._generic_parts(typ)
        if gp:
            if gp[0] == "pair":
                return f"{obj}.{e.name}"
            if gp[0] == "container" and e.name == "get":
                return f"{obj}.get()"
            raise CppCodeGenError(f"member '{e.name}' is not available on {typ}")

        if typ in self.unions or typ in self.structs:
            owner_fields = self.unions.get(typ, self.structs.get(typ)).fields
            if not any(f.name == e.name for f in owner_fields):
                raise CppCodeGenError(f"member '{e.name}' is absent from '{typ}'")
            return f"{obj}{'->' if pointer else '.'}{e.name}"

        if typ not in self.classes:
            raise CppCodeGenError(f"'{typ}' is not a class")
        owner, member = self._find_class_member(typ, e.name, "field")
        if member is None:
            owner, member = self._find_class_member(typ, e.name, "method")
        if member is None:
            raise CppCodeGenError(f"member '{e.name}' is absent from '{typ}'")
        if not getattr(member, "is_exposed", False):
            self._check_member_access(owner, member, e.name)
        if isinstance(member, ClassMethod):
            self._check_const_receiver_method(member, self._expr_is_const_receiver(e.obj, local_types), e.name)
        op = "->" if pointer or (isinstance(e.obj, Ident) and e.obj.name == "this") else "."
        return f"{obj}{op}{e.name}"

    # ------------------------------------------------------------------
    # Statements / blocks
    # ------------------------------------------------------------------

    def _gen_cpp_body_lines(self, statements, local_types):
        lines = []
        for s in statements:
            self._current_source_line = getattr(s, "_jaguar_line", self._current_source_line)
            lines.extend(self.gen_stmt(s, local_types))
        return lines

    def _gen_cpp_block(self, block, local_types):
        inner = dict(local_types)
        lines = self._gen_cpp_body_lines(block.statements, inner)
        return "{\n" + "\n".join("    " + x for x in lines) + "\n}"

    def _gen_if_cpp(self, s, local_types):
        lines = [f"if ({self.gen_expr(s.cond, local_types)}) {self._gen_cpp_block(s.then_block, dict(local_types))}"]
        branch = s.else_branch
        while isinstance(branch, IfStmt):
            lines.append(f"else if ({self.gen_expr(branch.cond, local_types)}) {self._gen_cpp_block(branch.then_block, dict(local_types))}")
            branch = branch.else_branch
        if isinstance(branch, Block):
            lines.append(f"else {self._gen_cpp_block(branch, dict(local_types))}")
        return lines

    def _gen_while_cpp(self, s, local_types):
        return [f"while ({self.gen_expr(s.cond, local_types)}) {self._gen_cpp_block(s.body, dict(local_types))}"]

    def _gen_loop_cpp(self, s, local_types):
        return [f"while (true) {self._gen_cpp_block(s.body, dict(local_types))}"]

    def _gen_for_loop_cpp(self, s, local_types):
        name = s.var_name
        start = self.gen_expr(s.start, local_types)
        end = self.gen_expr(s.end, local_types)
        inner = dict(local_types)
        inner[name] = s.var_type
        self._readonly_vars.add(name)
        body = self._gen_cpp_block(s.body, inner)
        self._readonly_vars.discard(name)
        n = self._cpp_tmp_id
        self._cpp_tmp_id += 1
        t = self._cpp_type(s.var_type)
        # Même comportement Jaguar que le backend C : borne évaluée une fois
        # et aucune incrémentation après la valeur finale.
        return [
            "{",
            f"    {t} {name} = {start};",
            f"    {t} _j_end_{n} = {end};",
            f"    bool _j_more_{n} = ({name} <= _j_end_{n});",
            f"    for (; _j_more_{n}; _j_more_{n} = ({name} != _j_end_{n}), ++{name}) {body}",
            "}",
        ]

    def _gen_collection_loop_cpp(self, s, local_types):
        ct = self.infer_type(s.collection, local_types)
        gp = self._generic_parts(ct)
        obj = self.gen_expr(s.collection, local_types)
        inner = dict(local_types)
        if s.kind == "loop_list":
            if not gp or gp[0] != "list":
                raise CppCodeGenError("loop_list expects a list<T>")
            elem = gp[1]
            inner[s.var_name] = elem
            body = self._gen_cpp_block(s.body, inner)
            return [f"for (auto& {s.var_name} : {obj}) {body}"]
        if not gp or gp[0] != "map":
            raise CppCodeGenError("loop_map expects a map<K,V>")
        parts = self._split_generic_args(gp[1])
        inner[s.var_name] = f"pair<{parts[0]},{parts[1]}>"
        body = self._gen_cpp_block(s.body, inner)
        return [f"for (const auto& {s.var_name} : {obj}) {body}"]

    def gen_stmt(self, s, local_types):
        if isinstance(s, (UsingNamespaceStmt, UsingSymbolStmt, TypeAliasStmt, VariableChangeHandler)):
            return []
        if isinstance(s, ReturnStmt):
            if s.expr is None:
                return ["return;"]
            return [f"return {self.gen_expr(s.expr, local_types)};"]
        if isinstance(s, BreakStmt):
            self._check_in_loop("break")
            return ["break;"]
        if isinstance(s, ContinueStmt):
            self._check_in_loop("continue")
            return ["continue;"]
        if isinstance(s, VarDecl):
            if s.name in local_types:
                raise CppCodeGenError(f"variable '{s.name}' is already declared")
            if s.name in self.global_types:
                raise CppCodeGenError(f"local variable '{s.name}' shadows a global variable")
            if s.type == "auto":
                s.type = self._resolve_auto_type(s.init, local_types)
                cpp = "auto"
            else:
                cpp = self._cpp_type(s.type)
            gp = self._generic_parts(s.type)
            local_types[s.name] = s.type
            if s.is_const:
                cpp = "const " + cpp
            if s.init is None and s.type in self.classes:
                return [f"{cpp} {s.name} = new {self._local_type_name(s.type)}();"]
            if s.init is not None and self._is_factory_construct_call(s.init) and s.type in self.classes:
                expr = self.gen_expr(s.init, local_types)
                expr = f"static_cast<{self._cpp_type(s.type)}>({expr})"
                return [f"{cpp} {s.name} = {expr};"]
            if gp and gp[0] == "map" and isinstance(s.init, ListLiteral):
                parts = self._split_generic_args(gp[1])
                if len(parts) != 2 or len(s.init.items) % 2:
                    raise CppCodeGenError("invalid map initializer: use {key, value, ...}")
                out = [f"{cpp} {s.name};"]
                for i in range(0, len(s.init.items), 2):
                    out.append(f"{s.name}.insert_or_assign({self.gen_expr(s.init.items[i], local_types)}, {self.gen_expr(s.init.items[i + 1], local_types)});")
                return out
            if gp:
                init = f" = {self.gen_expr(s.init, local_types)}" if s.init is not None else "{}"
            else:
                init = f" = {self.gen_expr(s.init, local_types)}" if s.init is not None else ""
            return [f"{cpp} {s.name}{init};"]
        if isinstance(s, AssignStmt):
            if s.name not in local_types and s.name not in self.global_types:
                if self._current_class:
                    owner, member = self._find_class_member(self._current_class.name, s.name, "field")
                    if member is not None:
                        return self.gen_stmt(MemberAssignStmt(MemberAccess(Ident("this"), s.name), s.expr), local_types)
                raise CppCodeGenError(f"assignment to '{s.name}': variable is not declared")
            if s.name in self._readonly_vars or s.name in self.global_const:
                raise CppCodeGenError(f"const/read-only variable '{s.name}' cannot be modified")
            self._check_expression_types(s.expr, local_types)
            rhs = self.gen_expr(s.expr, local_types)
            if self._is_factory_construct_call(s.expr) and s.name in local_types and local_types[s.name] in self.classes:
                rhs = f"static_cast<{self._cpp_type(local_types[s.name])}>({rhs})"
            elif self._is_factory_construct_call(s.expr) and s.name in self.global_types and self.global_types[s.name] in self.classes:
                rhs = f"static_cast<{self._cpp_type(self.global_types[s.name])}>({rhs})"
            return [f"{s.name} = {rhs};"]
        if isinstance(s, MemberAssignStmt):
            target_type = self.infer_type(s.target, local_types)
            value_type = self._check_expression_types(s.expr, local_types)
            self._check_assignable(target_type, value_type, f"assignment to member '{s.target.name}'", s.target)
            if self._expr_is_const_receiver(s.target.obj, local_types):
                raise CppCodeGenError(f"cannot modify member '{s.target.name}' through const object")
            return [f"{self.gen_member_access(s.target, local_types)} = {self.gen_expr(s.expr, local_types)};"]
        if isinstance(s, PointerAssignStmt):
            self._check_expression_types(s.expr, local_types)
            return [f"{self.gen_expr(s.target, local_types)} = {self.gen_expr(s.expr, local_types)};"]
        if isinstance(s, ExprStmt):
            self._check_expression_types(s.expr, local_types)
            return [f"{self.gen_expr(s.expr, local_types)};"]
        if isinstance(s, IfStmt):
            ct = self._check_expression_types(s.cond, local_types)
            if ct != "bool" and not (isinstance(ct, str) and ct.endswith("*")):
                raise CppCodeGenError(f"if condition must have type 'bool' or a pointer, got '{ct}'")
            return self._gen_if_cpp(s, local_types)
        if isinstance(s, WhileStmt):
            ct = self._check_expression_types(s.cond, local_types)
            if ct != "bool" and not (isinstance(ct, str) and ct.endswith("*")):
                raise CppCodeGenError(f"while condition must have type 'bool' or a pointer, got '{ct}'")
            return self._gen_while_cpp(s, local_types)
        if isinstance(s, LoopStmt):
            return self._gen_loop_cpp(s, local_types)
        if isinstance(s, ForLoopStmt):
            return self._gen_for_loop_cpp(s, local_types)
        if isinstance(s, CollectionLoopStmt):
            return self._gen_collection_loop_cpp(s, local_types)
        raise NotImplementedError(f"instruction non gérée par le backend C++: {s!r}")

    # ------------------------------------------------------------------
    # System builtins
    # ------------------------------------------------------------------

    def _gen_system_call(self, system, call, local_types):
        key = None
        if isinstance(call.callee, NamespacedIdent):
            key = (call.callee.namespace, call.callee.name)
        name = call.callee.name
        args = [a.expr if isinstance(a, NamedArg) else a for a in call.args]
        rendered = [self.gen_expr(x, local_types) for x in args]

        if key == ("sys", "print") or (key is None and name == "print"):
            return f"jaguar_runtime::sys_print({rendered[0]})"
        if key == ("sys:console", "set_color"):
            return f"jaguar_runtime::console_set_color({rendered[0]})"
        if key == ("sys:console", "reset_color"):
            return "jaguar_runtime::console_reset_color()"
        if key == ("sys", "execute"):
            return f"jaguar_runtime::execute({rendered[0]}, {rendered[1]})"
        if key == ("sys:fs", "read"):
            return f"jaguar_runtime::fs_read({rendered[0]})"
        if key == ("sys:fs", "write"):
            return f"jaguar_runtime::fs_write({rendered[0]}, {rendered[1]})"
        if key == ("thread", "start"):
            return f"static_cast<void*>(jaguar_runtime::thread_start({rendered[0]}))"
        if key == ("thread", "join"):
            return f"jaguar_runtime::thread_join(static_cast<std::thread*>({rendered[0]}))"
        if key == ("thread", "detach"):
            return f"jaguar_runtime::thread_detach(static_cast<std::thread*>({rendered[0]}))"
        if key == ("thread", "sleep"):
            return f"jaguar_runtime::thread_sleep(static_cast<std::uint64_t>({rendered[0]}))"
        if key == ("thread", "yield"):
            return "jaguar_runtime::thread_yield()"

        mapping = {
            ("jcc", "exit"): lambda: f"std::exit({rendered[0]})",
            ("jcc", "abort"): lambda: "std::abort()",
            ("jcc", "abs_i32"): lambda: f"jaguar_runtime::abs_i32({rendered[0]})",
            ("jcc", "min_i32"): lambda: f"jaguar_runtime::min_i32({rendered[0]}, {rendered[1]})",
            ("jcc", "max_i32"): lambda: f"jaguar_runtime::max_i32({rendered[0]}, {rendered[1]})",
            ("jcc", "clamp_i32"): lambda: f"jaguar_runtime::clamp_i32({rendered[0]}, {rendered[1]}, {rendered[2]})",
            ("jcc", "random_i32"): lambda: f"jaguar_runtime::random_i32({rendered[0]}, {rendered[1]})",
            ("jcc", "time_ms"): lambda: "jaguar_runtime::time_ms()",
            ("jcc", "assert"): lambda: f"jaguar_runtime::assert_value({rendered[0]}, {rendered[1]})",
            ("jcc", "sqrt"): lambda: f"std::sqrt({rendered[0]})",
            ("jcc", "pow"): lambda: f"std::pow({rendered[0]}, {rendered[1]})",
            ("jcc", "sin"): lambda: f"std::sin({rendered[0]})",
            ("jcc", "cos"): lambda: f"std::cos({rendered[0]})",
            ("jcc", "tan"): lambda: f"std::tan({rendered[0]})",
            ("jcc", "asin"): lambda: f"std::asin({rendered[0]})",
            ("jcc", "acos"): lambda: f"std::acos({rendered[0]})",
            ("jcc", "atan"): lambda: f"std::atan({rendered[0]})",
            ("jcc", "atan2"): lambda: f"std::atan2({rendered[0]}, {rendered[1]})",
            ("jcc", "floor"): lambda: f"std::floor({rendered[0]})",
            ("jcc", "ceil"): lambda: f"std::ceil({rendered[0]})",
            ("jcc", "round"): lambda: f"std::round({rendered[0]})",
            ("jcc", "log"): lambda: f"std::log({rendered[0]})",
            ("jcc", "log10"): lambda: f"std::log10({rendered[0]})",
            ("jcc", "exp"): lambda: f"std::exp({rendered[0]})",
            ("jcc", "fmod"): lambda: f"std::fmod({rendered[0]}, {rendered[1]})",
            ("jcc", "is_digit"): lambda: f"std::isdigit(static_cast<unsigned char>({rendered[0]})) != 0",
            ("jcc", "is_alpha"): lambda: f"std::isalpha(static_cast<unsigned char>({rendered[0]})) != 0",
            ("jcc", "is_alnum"): lambda: f"std::isalnum(static_cast<unsigned char>({rendered[0]})) != 0",
            ("jcc", "is_space"): lambda: f"std::isspace(static_cast<unsigned char>({rendered[0]})) != 0",
            ("jcc", "is_upper"): lambda: f"std::isupper(static_cast<unsigned char>({rendered[0]})) != 0",
            ("jcc", "is_lower"): lambda: f"std::islower(static_cast<unsigned char>({rendered[0]})) != 0",
            ("jcc", "to_upper_char"): lambda: f"std::toupper(static_cast<unsigned char>({rendered[0]}))",
            ("jcc", "to_lower_char"): lambda: f"std::tolower(static_cast<unsigned char>({rendered[0]}))",
            ("jcc", "file_exists"): lambda: f"jaguar_runtime::file_exists({rendered[0]})",
        }
        fn = mapping.get(key)
        if fn:
            return fn()
        raise CppCodeGenError(f"unsupported system builtin: {key}")

    # ------------------------------------------------------------------
    # main Jaguar -> main C++
    # ------------------------------------------------------------------

    def _gen_cpp_main(self, fn):
        # Le front-end conserve la forme historique void main(string param)
        # et les deux formes sont traduites vers l'ABI standard C++.
        params = fn.params
        if len(params) == 0:
            body = self._gen_cpp_block(fn.body, {})
            return f"int main() {body}"
        if len(params) == 1:
            p = params[0]
            local_types = {p.name: p.type}
            body_lines = self._gen_cpp_body_lines(fn.body.statements, local_types)
            signature = "int main(int argc, char** argv)"
            preamble = ["    std::string " + p.name + " = (argc > 1 ? std::string(argv[1]) : std::string());"]
            return signature + " {\n" + "\n".join(preamble + ["    " + x for x in body_lines] + ["    return 0;", "}"])
        raise CppCodeGenError("main() expects zero or one parameter")


# ---------------------------------------------------------------------------
# IR API / diagnostics
# ---------------------------------------------------------------------------

def _load_program_from_ir_text(ir_text):
    ir = jcc.deserialize_ir(ir_text)
    program = jcc.program_from_ir(ir)
    groups = jcc.groups_from_program(program)
    return ir, program, groups


def generate_ir(ir_text, split_runtime=False):
    ir, program, groups = _load_program_from_ir_text(ir_text)
    cg = CppCodeGen(program, groups)
    return cg.gen()


def transpile(source: str) -> str:
    return generate_ir(jcc.transpile(source))


def diagnose_source(source: str):
    try:
        ir = jcc.transpile(source)
        generate_ir(ir)
    except (LexError, ParseError, ResolverError, CppCodeGenError, ValueError) as exc:
        source_text = source
        if not hasattr(exc, "_jaguar_line"):
            exc._jaguar_line = 1
        return [jcc._diagnostic_from_exception(source_text, exc)]
    return []


def main(argv):
    out_path = None
    in_path = None
    emit_cpp = False
    args = argv[1:]
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "-o" and i + 1 < len(args):
            out_path = args[i + 1]
            i += 2
        elif arg in ("--emit-cpp", "--emit-c"):
            emit_cpp = True
            i += 1
        else:
            in_path = arg
            i += 1

    if in_path:
        ir_text = Path(in_path).read_text(encoding="utf-8")
    else:
        ir_text = sys.stdin.read()

    try:
        generated = generate_ir(ir_text)
    except (LexError, ParseError, ResolverError, CppCodeGenError, ValueError) as exc:
        source = ""
        try:
            ir = jcc.deserialize_ir(ir_text)
            source = ir.get("source", {}).get("text", "")
        except Exception:
            pass
        if isinstance(exc, (LexError, ParseError, ResolverError, CppCodeGenError)):
            d = jcc._diagnostic_from_exception(source, exc)
            print(jcc.format_diagnostic(d, in_path), file=sys.stderr)
        else:
            print(f"Jaguar Error: {exc}", file=sys.stderr)
        return 1

    if out_path:
        base = Path(out_path)
        if base.suffix.lower() == ".cpp":
            cpp_path = base
            exe_path = base.with_suffix("")
        else:
            cpp_path = Path(str(base) + ".cpp")
            exe_path = base
        cpp_path.parent.mkdir(parents=True, exist_ok=True)
        cpp_path.write_text(generated, encoding="utf-8")
        print(f"Jaguar: C++ generated at {cpp_path}")
        if emit_cpp:
            return 0

        compiler = os.environ.get("JAGUAR_CXX")
        if compiler:
            compiler_path = Path(compiler)
            compiler_cmd = str(compiler_path) if compiler_path.is_file() else compiler
        else:
            bundled = Path(__file__).resolve().parent / "toolchain" / "bin" / ("g++.exe" if os.name == "nt" else "g++")
            compiler_cmd = str(bundled) if bundled.is_file() else "g++"
        cmd = [compiler_cmd, "-std=c++17", str(cpp_path), "-o", str(exe_path)]
        try:
            result = subprocess.run(cmd, check=False)
        except OSError as exc:
            print(f"Jaguar Error: failed to launch C++ compiler: {exc}", file=sys.stderr)
            return 1
        if result.returncode != 0:
            print(f"Jaguar Error: C++ compiler failed with exit code {result.returncode}", file=sys.stderr)
            return result.returncode
        print(f"Jaguar: C++ compilation -> {exe_path}")
    else:
        sys.stdout.write(generated)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
