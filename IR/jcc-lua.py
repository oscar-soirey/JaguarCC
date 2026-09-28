#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
jcc-lua.py — Backend Jaguar IR -> Lua 5.4

Le frontend Jaguar reste jcc.py. Ce backend consomme uniquement le .jir
résolu et traduit l'AST/IR vers du Lua, sans passer par C ou C++.

Usage:
    python jcc.py exemple.ja -o exemple.jir
    python jcc-lua.py exemple.jir
    python jcc-lua.py exemple.jir -o exemple

Le backend vise du Lua 5.4 standard :
- namespaces -> tables imbriquées
- classes -> tables + metatables + héritage par __index
- structs/unions -> constructeurs de tables
- enums -> tables de constantes
- string -> chaînes Lua natives
- listes/maps -> tables Lua
- boucles et conditions -> syntaxe Lua native
- sys:* / jcc:* -> bibliothèques Lua standard quand l'équivalent existe

Certaines primitives Jaguar très bas niveau (notamment l'arithmétique réelle
sur pointeurs) n'ont pas d'équivalent direct en Lua. Le backend les représente
par une petite couche runtime Lua quand c'est possible.
"""
from __future__ import annotations

import importlib.util
import math
import os
import re
import sys
from pathlib import Path

import jcc
from jcc import *


def _load_c_backend_module():
    path = Path(__file__).with_name("jcc-c.py")
    spec = importlib.util.spec_from_file_location("_jaguar_c_backend_for_lua", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load semantic backend helpers: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_C = _load_c_backend_module()
CodeGenError = _C.CodeGenError


class LuaCodeGen(_C.CodeGen):
    """Semantic engine inherited from the C backend, Lua-only emitter."""

    IND = "    "

    def __init__(self, program, groups):
        super().__init__(program, groups, c89=False)
        self._current_class = None
        self._current_namespace = None
        self._current_function_local_types = {}
        self._change_handlers = {}
        self._in_change_handler = False
        self._loop_depth = 0
        self._tmp_id = 0
        self._continue_labels = []

        self._namespace_set = set()
        self._class_by_short = {}
        self._struct_by_short = {}
        self._enum_by_short = {}
        for item in program.items:
            ns = getattr(item, "namespace", None)
            if ns:
                parts = ns.split(":")
                for i in range(1, len(parts) + 1):
                    self._namespace_set.add(":".join(parts[:i]))
            if isinstance(item, ClassDecl):
                self._class_by_short[(ns, self._short_decl_name(item.name, ns))] = item
            elif isinstance(item, StructDecl):
                self._struct_by_short[(ns, self._short_decl_name(item.name, ns))] = item
            elif isinstance(item, EnumDecl):
                self._enum_by_short[(ns, item.name)] = item

    # ------------------------------------------------------------------
    # Names / namespaces
    # ------------------------------------------------------------------
    @staticmethod
    def _short_decl_name(full_name, namespace):
        if namespace:
            prefix = namespace.replace(":", "_") + "_"
            if full_name.startswith(prefix):
                return full_name[len(prefix):]
        return full_name

    @staticmethod
    def _lua_ident(name):
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name or ""):
            return name
        return "[" + LuaCodeGen._lua_string(name) + "]"

    @staticmethod
    def _lua_string(value):
        # JSON produces an unambiguous quoted Lua string for ordinary source
        # strings and is sufficient for all Jaguar source literals.
        import json
        return json.dumps(value, ensure_ascii=False)

    def _ns_expr(self, namespace):
        if not namespace:
            return None
        parts = namespace.split(":")
        return ".".join(self._lua_ident(p) for p in parts)

    def _ensure_namespace_lines(self):
        lines = []
        # parents first
        def depth(ns):
            return len(ns.split(":"))
        seen_paths = set()
        for ns in sorted(self._namespace_set, key=lambda x: (depth(x), x)):
            parts = ns.split(":")
            cur = None
            path_parts = []
            for part in parts:
                path_parts.append(part)
                path = ":".join(path_parts)
                if path in seen_paths:
                    cur = self._ns_expr(path)
                    continue
                if cur is None:
                    cur = self._lua_ident(part)
                else:
                    cur = cur + "." + self._lua_ident(part)
                lines.append(f"{cur} = {cur} or {{}}")
                seen_paths.add(path)
        if lines:
            lines.append("")
        return lines

    def _decl_ref(self, name, namespace=None):
        if namespace:
            return self._ns_expr(namespace) + "." + self._lua_ident(name)
        return self._lua_ident(name)

    def _function_ref(self, fn):
        public = fn.mangled_name or fn.name
        return self._decl_ref(public, fn.namespace)

    def _find_function_value(self, name, namespace=None):
        candidates = self.groups.get((namespace, name), [])
        if len(candidates) == 1:
            return candidates[0]
        return None

    def _resolve_function_for_call(self, call, local_types):
        if isinstance(call.callee, (Ident, NamespacedIdent)):
            return self.resolve_call_target(call, local_types)
        return None

    # ------------------------------------------------------------------
    # Lua runtime
    # ------------------------------------------------------------------
    def _runtime(self):
        return r'''-- Jaguar Lua runtime (generated automatically).
local __j = {}

function __j.truth(v) return not not v end
function __j.ptr(v) return { value = v } end
function __j.deref(v) return v and v.value or nil end
function __j.setptr(v, x) v.value = x end
function __j.copy_table(v)
    if type(v) ~= "table" then return v end
    local r = {}
    for k, x in pairs(v) do r[k] = x end
    return r
end
function __j.concat(a, b) return tostring(a) .. tostring(b) end
function __j.startswith(s, p) return s:sub(1, #p) == p end
function __j.endswith(s, p) return p == "" or s:sub(-#p) == p end
function __j.contains(s, p) return s:find(p, 1, true) ~= nil end
function __j.substring(s, start, len)
    start = tonumber(start) or 0
    len = tonumber(len)
    local a = start + 1
    if len == nil then return s:sub(a) end
    return s:sub(a, a + len - 1)
end
function __j.char_at(s, i) return string.byte(s, (tonumber(i) or 0) + 1) end
function __j.list_new(...) return {...} end
function __j.map_new() return {} end
function __j.list_push(t, v) t[#t + 1] = v end
function __j.list_get(t, i) return t[(tonumber(i) or 0) + 1] end
function __j.list_set(t, i, v) t[(tonumber(i) or 0) + 1] = v end
function __j.list_size(t) return #t end
function __j.map_size(t)
    local n = 0
    for _ in pairs(t) do n = n + 1 end
    return n
end
function __j.map_emplace(t, k, v) t[k] = v end
function __j.pair(a, b) return {first = a, second = b} end
function __j.dynamic_get(t, i) return t[(tonumber(i) or 0) + 1] end
function __j.dynamic_push(t, v) t[#t + 1] = v end
function __j.same(a, b) return a == b end
function __j.string_value(v) return v == nil and "" or tostring(v) end
function __j.fs_read(path)
    local f, err = io.open(path, "rb")
    if not f then error(err) end
    local s = f:read("*a")
    f:close()
    return s
end
function __j.fs_write(path, data)
    local f, err = io.open(path, "wb")
    if not f then error(err) end
    f:write(data)
    f:close()
end
function __j.execute(program, cwd)
    if cwd and cwd ~= "" then
        local sep = package.config:sub(1,1) == "\\" and "\\" or "/"
        if sep == "\\" then
            return os.execute('cd /d "' .. cwd .. '" && ' .. program)
        end
        return os.execute('cd "' .. cwd .. '" && ' .. program)
    end
    return os.execute(program)
end
function __j.printf(v) io.write(tostring(v)) end
function __j.print(v) print(v) end
function __j.set_color(v) io.write(tostring(v or "")) end
function __j.reset_color() io.write("\027[0m") end
function __j.assert(v, message) assert(v, message or "assertion failed") end
function __j.sleep_ms(ms)
    local sec = (tonumber(ms) or 0) / 1000
    local ok, socket = pcall(require, "socket")
    if ok and socket.sleep then socket.sleep(sec); return end
    if sec <= 0 then return end
    local t0 = os.clock()
    while os.clock() - t0 < sec do end
end

'''

    # ------------------------------------------------------------------
    # Types / constructors
    # ------------------------------------------------------------------
    def _strip_ptr(self, t):
        return t[:-1] if isinstance(t, str) and t.endswith("*") else t

    def _is_class_type(self, t):
        if not isinstance(t, str):
            return False
        base = t.rstrip("*")
        return base in self.classes

    def _type_default(self, t):
        base = self._strip_ptr(t)
        if base == "bool": return "false"
        if base in INTEGER_TYPES or base in FLOAT_TYPES: return "0"
        if base == "string": return '""'
        if base in self.classes: return "nil"
        if base in self.structs or base in self.unions: return "{}"
        gp = self._generic_parts(base)
        if gp:
            return "{}"
        return "nil"

    def _emit_class_decl(self, cls):
        name = self._short_decl_name(cls.name, cls.namespace)
        ref = self._decl_ref(name, cls.namespace)
        base_ref = None
        if cls.base:
            base = self._resolve_class_name(cls.base, cls.namespace)
            if base:
                base_cls = self.classes.get(base)
                base_name = self._short_decl_name(base, getattr(base_cls, "namespace", None)) if base_cls else base
                base_ref = self._decl_ref(base_name, getattr(base_cls, "namespace", None) if base_cls else None)
        lines = [f"{ref} = {{}}", f"{ref}.__name = {self._lua_string(name)}"]
        lines.append(f"{ref}.__index = {ref}")
        if base_ref:
            lines.append(f"setmetatable({ref}, {{ __index = {base_ref} }})")
        lines.append("")

        # Constructor/factory. Lua represents a Jaguar class value as an
        # object table carrying the class metatable.
        lines.append(f"function {ref}.new(...)")
        lines.append(self.IND + f"local self = setmetatable({{}}, {ref})")
        for field in cls.fields:
            # Fields are per-instance; initialize explicit Jaguar defaults.
            if field.init is not None:
                try:
                    value = self.gen_expr(field.init, {"this": cls.name})
                except Exception:
                    value = self._type_default(field.type)
            else:
                value = self._type_default(field.type)
            lines.append(self.IND + f"self.{self._lua_ident(field.name)} = {value}")
        ctor = next((m for m in cls.methods if m.is_constructor), None)
        if ctor:
            ordered = list(ctor.params)
            args = ", ".join(p.name for p in ordered)
            # We cannot reuse `...` and named constructor params simultaneously,
            # so construct a local wrapper that accepts the declared parameters.
            sig = ", ".join(p.name for p in ctor.params)
            lines = lines[:-1] if False else lines
            # Replace the variadic constructor body generated below by storing
            # a helper in the class; constructor gets actual arguments.
        lines.append(self.IND + "if " + ref + ".__construct then")
        lines.append(self.IND * 2 + ref + ".__construct(self, ...)")
        lines.append(self.IND + "end")
        lines.append(self.IND + "return self")
        lines.append("end")
        lines.append("")

        if ctor:
            params = ", ".join(p.name for p in ctor.params)
            lines.append(f"function {ref}.__construct(self{', ' if params else ''}{params})")
            old = self._current_class
            self._current_class = cls
            self._current_namespace = cls.namespace
            local_types = {p.name: p.type for p in ctor.params}
            local_types["this"] = cls.name
            self._current_function_local_types = local_types
            self._change_handlers = {}
            body = self._gen_block_statements(ctor.body.statements, local_types, 1, constructor_return=False)
            lines.extend(body)
            lines.append("end")
            lines.append("")
            self._current_class = old
        for method in cls.methods:
            if method.is_constructor or method.is_destructor:
                continue
            params = ", ".join(p.name for p in method.params)
            signature = f"{self._lua_ident(method.name)}({params})"
            lines.append(f"function {ref}:{signature}")
            old = self._current_class
            old_ns = self._current_namespace
            self._current_class = cls
            self._current_namespace = cls.namespace
            local_types = {p.name: p.type for p in method.params}
            local_types["this"] = cls.name
            self._current_function_local_types = local_types
            self._current_return_type = method.ret_type
            self._change_handlers = self._collect_change_handlers_lua(method.body.statements, local_types)
            lines.extend(self._gen_block_statements(method.body.statements, local_types, 1))
            lines.append("end")
            lines.append("")
            self._current_class = old
            self._current_namespace = old_ns
        dtor = next((m for m in cls.methods if m.is_destructor), None)
        if dtor:
            lines.append(f"function {ref}:destroy()")
            old = self._current_class
            self._current_class = cls
            local_types = {"this": cls.name}
            self._current_function_local_types = local_types
            lines.extend(self._gen_block_statements(dtor.body.statements, local_types, 1))
            self._current_class = old
            lines.append("end")
            lines.append("")
        return lines

    def _emit_struct_decl(self, s):
        name = self._short_decl_name(s.name, s.namespace)
        ref = self._decl_ref(name, s.namespace)
        lines = [f"{ref} = {{}}", ""]
        params = ", ".join(f.name for f in s.fields)
        lines.append(f"function {ref}.new({params})")
        lines.append(self.IND + "local self = {}")
        for i, f in enumerate(s.fields, 1):
            value = f.name
            if not value:
                value = self._type_default(f.type)
            lines.append(self.IND + f"self.{self._lua_ident(f.name)} = {value}")
        lines.append(self.IND + "return self")
        lines.append("end")
        lines.append("")
        return lines

    def _enum_ref(self, en, value):
        name = self._short_decl_name(en.name, en.namespace)
        return self._decl_ref(name, en.namespace) + "." + self._lua_ident(value)

    def _emit_enum_decl(self, en):
        name = self._short_decl_name(en.name, en.namespace)
        ref = self._decl_ref(name, en.namespace)
        lines = [f"{ref} = {{}}"]
        current = -1
        for v in en.values:
            init = (en.initializers or {}).get(v)
            if init is not None:
                expr = self.gen_expr(init, {})
                # The generated Lua value is authoritative; keep the integer
                # fallback only for simple implicit enum increments.
                try:
                    if isinstance(init, IntLit): current = int(init.value)
                except Exception:
                    pass
            else:
                current += 1
                expr = str(current)
            lines.append(f"{ref}.{self._lua_ident(v)} = {expr}")
        lines.append("")
        return lines

    # ------------------------------------------------------------------
    # Expressions
    # ------------------------------------------------------------------
    def _lua_index(self, e):
        idx = self.gen_expr(e.index, {})
        # Jaguar indexes are zero based for list/array access.
        return f"({idx}) + 1"

    def _expr_obj_type(self, e, local_types):
        return self.infer_type(e, local_types)

    def _call_args(self, call, params, local_types, variadic=False):
        if params is None:
            return list(call.args)
        return self._ordered_call_args(call.args, params, "function", variadic=variadic)

    def _system_call_expr(self, call, local_types):
        info = self._system_builtin(call.callee, call)
        if info is None:
            return None
        ns = call.callee.namespace if isinstance(call.callee, NamespacedIdent) else None
        name = call.callee.name if hasattr(call.callee, "name") else ""
        args = [a.expr if isinstance(a, NamedArg) else a for a in call.args]
        vals = [self.gen_expr(a, local_types) for a in args]
        if ns == "sys" and name == "print":
            return f"__j.print({vals[0]})"
        if ns == "sys:console" and name == "set_color":
            return f"__j.set_color({vals[0]})"
        if ns == "sys:console" and name == "reset_color":
            return "__j.reset_color()"
        if ns == "sys" and name == "execute":
            return f"__j.execute({vals[0]}, {vals[1]})"
        if ns == "sys:fs" and name == "read":
            return f"__j.fs_read({vals[0]})"
        if ns == "sys:fs" and name == "write":
            return f"__j.fs_write({vals[0]}, {vals[1]})"
        if ns == "thread" and name == "sleep":
            return f"__j.sleep_ms({vals[0]})"
        if ns == "thread" and name == "yield":
            return "coroutine.yield()"
        if ns == "thread" and name in ("join", "detach"):
            return "nil"
        if ns == "thread" and name == "start":
            return f"coroutine.create(function() {vals[0]}() end)"
        if ns == "jcc":
            if name == "exit": return f"os.exit({vals[0]})"
            if name == "abort": return "error('abort')"
            if name == "abs_i32": return f"math.abs({vals[0]})"
            if name == "min_i32": return f"math.min({vals[0]}, {vals[1]})"
            if name == "max_i32": return f"math.max({vals[0]}, {vals[1]})"
            if name == "clamp_i32": return f"math.max({vals[1]}, math.min({vals[2]}, {vals[0]}))"
            if name == "random_i32": return f"math.random({vals[0]}, {vals[1]})"
            if name == "time_ms": return "math.floor(os.clock() * 1000)"
            if name == "assert": return f"__j.assert({vals[0]}, {vals[1]})"
            if name in {"sqrt","pow","sin","cos","tan","asin","acos","atan","floor","ceil","exp"}:
                return f"math.{name}({', '.join(vals)})"
            if name == "atan2": return f"math.atan({vals[0]}, {vals[1]})"
            if name == "log": return f"math.log({vals[0]})"
            if name == "log10": return f"math.log10({vals[0]})"
            if name == "fmod": return f"math.fmod({vals[0]}, {vals[1]})"
            if name == "round": return f"math.floor({vals[0]} + 0.5)"
            if name == "is_digit": return f"__j.startswith(string.char({vals[0]}), '')" if False else f"({vals[0]} >= 48 and {vals[0]} <= 57)"
            if name == "is_alpha": return f"(({vals[0]} >= 65 and {vals[0]} <= 90) or ({vals[0]} >= 97 and {vals[0]} <= 122))"
            if name == "is_alnum": return f"(({vals[0]} >= 48 and {vals[0]} <= 57) or ({vals[0]} >= 65 and {vals[0]} <= 90) or ({vals[0]} >= 97 and {vals[0]} <= 122))"
            if name == "is_space": return f"({vals[0]} == 32 or {vals[0]} == 9 or {vals[0]} == 10 or {vals[0]} == 13)"
            if name == "is_upper": return f"({vals[0]} >= 65 and {vals[0]} <= 90)"
            if name == "is_lower": return f"({vals[0]} >= 97 and {vals[0]} <= 122)"
            if name == "to_upper_char": return f"({vals[0]} >= 97 and {vals[0]} <= 122) and ({vals[0]} - 32) or {vals[0]}"
            if name == "to_lower_char": return f"({vals[0]} >= 65 and {vals[0]} <= 90) and ({vals[0]} + 32) or {vals[0]}"
            if name == "file_exists": return f"(io.open({vals[0]}, 'rb') ~= nil)"
            if name == "remove_file": return f"os.remove({vals[0]})"
            if name == "rename_file": return f"os.rename({vals[0]}, {vals[1]})"
            if name == "env_get": return f"os.getenv({vals[0]})"
        return None

    def gen_expr(self, e, local_types):
        if isinstance(e, NullPtrLit):
            return "nil"
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
                return "self"
            if self._current_class and e.name not in local_types and e.name not in self.global_types:
                owner, field = self._find_class_member(self._current_class.name, e.name, "field")
                if field is not None:
                    self._check_member_access(owner, field, e.name)
                    return f"self.{self._lua_ident(e.name)}"
                owner, method = self._find_class_member(self._current_class.name, e.name, "method")
                if method is not None:
                    self._check_member_access(owner, method, e.name)
                    return f"function(...) return self:{self._lua_ident(e.name)}(...) end"
            # Function identifier used as a value.
            fn = self._find_function_value(e.name, None)
            if fn:
                return self._function_ref(fn)
            imported = getattr(self.program, "_using_symbols", {}).get(e.name)
            if imported:
                fn = self._find_function_value(imported[1], imported[0])
                if fn:
                    return self._function_ref(fn)
            for ns in getattr(self.program, "_using_namespaces", []):
                fn = self._find_function_value(e.name, ns)
                if fn:
                    return self._function_ref(fn)
            # enum value
            for en in getattr(self.program, "_enums", {}).values():
                if en.namespace is None and e.name in en.values:
                    return self._enum_ref(en, e.name)
                for value in en.values:
                    if value == e.name and en.namespace in getattr(self.program, "_using_namespaces", []):
                        return self._enum_ref(en, e.name)
            return self._lua_ident(e.name)

        if isinstance(e, NamespacedIdent):
            en = getattr(self.program, "_enums", {}).get(f"{e.namespace}:{e.name}")
            # Namespaced enum constants are represented as Enum.Value, so find
            # the enum that owns this value.
            for item in self.program.items:
                if isinstance(item, EnumDecl) and e.name in item.values and (item.namespace == e.namespace or item.name == e.namespace):
                    return self._enum_ref(item, e.name)
            fn = self._find_function_value(e.name, e.namespace)
            if fn:
                return self._function_ref(fn)
            if e.name in self.global_types:
                return self._decl_ref(e.name, e.namespace)
            # namespace-qualified type/object symbol
            q = self._decl_ref(e.name, e.namespace)
            return q

        if isinstance(e, IndexAccess):
            obj_t = self.infer_type(e.obj, local_types)
            obj = self.gen_expr(e.obj, local_types)
            idx = self.gen_expr(e.index, local_types)
            gp = self._generic_parts(obj_t)
            if gp:
                return f"{obj}[({idx}) + 1]" if gp[0] in ("list", "dynamic_list", "container") else f"{obj}[{idx}]"
            arr = self._fixed_array_parts(obj_t) if isinstance(obj_t, str) else None
            if arr:
                return f"{obj}[({idx}) + 1]"
            if isinstance(obj_t, str) and obj_t.endswith("*"):
                return f"{obj}[({idx}) + 1]"
            raise CodeGenError(f"'[]' cannot be used on '{obj_t}'")

        if isinstance(e, MemberAccess):
            ot = self.infer_type(e.obj, local_types)
            obj = self.gen_expr(e.obj, local_types)
            base = ot.rstrip("*") if isinstance(ot, str) else ot
            gp = self._generic_parts(base)
            if gp:
                kind, inner = gp
                if kind == "list":
                    if e.name == "push": return f"function(v) __j.list_push({obj}, v) end"
                    if e.name == "get": return f"function(i) return __j.list_get({obj}, i) end"
                    if e.name == "size": return f"function() return __j.list_size({obj}) end"
                if kind == "map":
                    if e.name == "emplace": return f"function(k, v) __j.map_emplace({obj}, k, v) end"
                    if e.name == "size": return f"function() return __j.map_size({obj}) end"
                if kind == "dynamic_list":
                    if e.name == "push": return f"function(v) __j.dynamic_push({obj}, v) end"
                    if e.name == "get": return f"function(i) return __j.dynamic_get({obj}, i) end"
                    if e.name == "size": return f"function() return #({obj}) end"
                    if e.name == "type": return f"function(i) return type(__j.dynamic_get({obj}, i)) end"
                if kind == "pair":
                    return f"{obj}.{self._lua_ident(e.name)}"
            if base == "string":
                if e.name == "length": return f"#{obj}"
                if e.name == "empty": return f"({obj} == '')"
                if e.name == "equals": return f"function(v) return {obj} == v end"
                if e.name == "contains": return f"function(v) return __j.contains({obj}, v) end"
                if e.name == "starts_with": return f"function(v) return __j.startswith({obj}, v) end"
                if e.name == "ends_with": return f"function(v) return __j.endswith({obj}, v) end"
                if e.name == "concat": return f"function(v) return {obj} .. v end"
                if e.name == "substring": return f"function(a, b) return __j.substring({obj}, a, b) end"
                if e.name == "char_at": return f"function(i) return __j.char_at({obj}, i) end"
                if e.name == "to_upper": return f"function() return string.upper({obj}) end"
                if e.name == "to_lower": return f"function() return string.lower({obj}) end"
            if self._current_class:
                owner, member = self._find_class_member(base, e.name, "field")
                if member is not None:
                    self._check_member_access(owner, member, e.name)
                    return f"{obj}.{self._lua_ident(e.name)}"
                owner, method = self._find_class_member(base, e.name, "method")
                if method is not None:
                    self._check_member_access(owner, method, e.name)
                    return f"function(...) return {obj}:{self._lua_ident(e.name)}(...) end"
            if base in self.structs or base in self.unions:
                return f"{obj}.{self._lua_ident(e.name)}"
            if base in self.classes:
                owner, field = self._find_class_member(base, e.name, "field")
                if field is not None:
                    self._check_member_access(owner, field, e.name)
                    return f"{obj}.{self._lua_ident(e.name)}"
                owner, method = self._find_class_member(base, e.name, "method")
                if method is not None:
                    self._check_member_access(owner, method, e.name)
                    return f"function(...) return {obj}:{self._lua_ident(e.name)}(...) end"
            return f"{obj}.{self._lua_ident(e.name)}"

        if isinstance(e, NewExpr):
            if e.type in self.classes:
                args = list(e.args)
                if len(args) == 1 and isinstance(args[0], Call):
                    c = args[0]
                    if ((isinstance(c.callee, Ident) and self._resolve_class_name(c.callee.name) == e.type) or
                        (isinstance(c.callee, NamespacedIdent) and self._resolve_class_name(c.callee.name, c.callee.namespace) == e.type)):
                        args = list(c.args)
                return self._class_new_expr(e.type, args, local_types)
            if e.type in self.structs:
                args = list(e.args)
                if len(args) == 1 and isinstance(args[0], Call) and not args[0].args:
                    args = []
                if args:
                    raise CodeGenError(f"new {e.type} expects an empty constructor")
                return self._struct_new_ref(e.type) + "()"
            if e.type in INTEGER_TYPES or e.type in FLOAT_TYPES or e.type == "bool" or e.type in BUILTIN_TYPEDEFS:
                if len(e.args) != 1:
                    raise CodeGenError(f"new {e.type}(value) expects exactly one initializer")
                val = e.args[0].expr if isinstance(e.args[0], NamedArg) else e.args[0]
                return self.gen_expr(val, local_types)
            raise CodeGenError(f"cannot allocate value of unknown type '{e.type}' in Lua backend")

        if isinstance(e, ListLiteral):
            return "{" + ", ".join(self.gen_expr(x, local_types) for x in e.items) + "}"

        if isinstance(e, CastExpr):
            # Lua is dynamically typed; validate via the shared semantic engine
            # but emit the operand itself. Numeric conversions are explicit where
            # Lua's number model needs a concrete integer operation.
            return self.gen_expr(e.operand, local_types)

        if isinstance(e, UnaryOp):
            inner = self.gen_expr(e.operand, local_types)
            if e.op == "!": return f"(not ({inner}))"
            if e.op == "-": return f"(-({inner}))"
            if e.op == "+": return f"(+({inner}))"
            if e.op == "*": return f"__j.deref({inner})"
            if e.op == "&": return f"__j.ptr({inner})"
            return f"({e.op}({inner}))"

        if isinstance(e, BinOp):
            lt = self.infer_type(e.left, local_types)
            rt = self.infer_type(e.right, local_types)
            custom = self._resolve_operator(e.op, lt, rt)
            if custom is not None:
                fn = custom
                return f"{self._function_ref(fn)}({self.gen_expr(e.left, local_types)}, {self.gen_expr(e.right, local_types)})"
            l = self.gen_expr(e.left, local_types)
            r = self.gen_expr(e.right, local_types)
            if e.op == "+" and lt == "string" and rt == "string": return f"({l} .. {r})"
            op = {"&&": "and", "||": "or", "==": "==", "!=": "~=", "/": "/", "%": "%"}.get(e.op, e.op)
            return f"(({l}) {op} ({r}))"

        if isinstance(e, Call):
            system = self._system_call_expr(e, local_types)
            if system is not None:
                return system
            if isinstance(e.callee, Ident) and e.callee.name == "func" and self._decorator_call_target_name is not None:
                args = ", ".join(p.name for p in self._decorator_target_params)
                return f"{self._decorator_call_target_name}({args})"

            # Type constructor call.
            if isinstance(e.callee, Ident):
                class_name = self._resolve_class_name(e.callee.name)
                if class_name is not None:
                    return self._class_new_expr(class_name, e.args, local_types)
                struct_name = self._resolve_struct_name(e.callee.name)
                if struct_name is not None:
                    return self._struct_new_expr(struct_name, e.args, local_types)
            elif isinstance(e.callee, NamespacedIdent):
                class_name = self._resolve_class_name(e.callee.name, e.callee.namespace)
                if class_name is not None:
                    return self._class_new_expr(class_name, e.args, local_types)
                struct_name = self._resolve_struct_name(e.callee.name, e.callee.namespace)
                if struct_name is not None:
                    return self._struct_new_expr(struct_name, e.args, local_types)

            if isinstance(e.callee, Ident) and self._current_class:
                resolved_method = self.resolve_class_method_call(self._current_class.name, e.callee.name, e.args, local_types, receiver_const=False)
                method = resolved_method[1] if resolved_method else None
                if method is not None:
                    ordered = self._ordered_call_args(e.args, method.params, f"method '{e.callee.name}'")
                    vals = ", ".join(self.gen_expr(a.expr if isinstance(a, NamedArg) else a, local_types) for a in ordered)
                    return f"self:{self._lua_ident(e.callee.name)}({vals})"

            if isinstance(e.callee, MemberAccess):
                obj = self.gen_expr(e.callee.obj, local_types)
                ot = self.infer_type(e.callee.obj, local_types)
                base = ot.rstrip("*") if isinstance(ot, str) else ot
                # container/string member calls are regular functions returned
                # by gen_expr; call them with ordinary Lua syntax.
                if base in self.classes:
                    resolved_method = self.resolve_class_method_call(base, e.callee.name, e.args, local_types, receiver_const=self._expr_is_const_receiver(e.callee.obj, local_types))
                    method = resolved_method[1] if resolved_method else None
                    if method:
                        ordered = self._ordered_call_args(e.args, method.params, f"method '{e.callee.name}'")
                    else:
                        ordered = e.args
                    vals = ", ".join(self.gen_expr(a.expr if isinstance(a, NamedArg) else a, local_types) for a in ordered)
                    return f"{obj}:{self._lua_ident(e.callee.name)}({vals})"
                callee = self.gen_expr(e.callee, local_types)
                vals = ", ".join(self.gen_expr(a.expr if isinstance(a, NamedArg) else a, local_types) for a in e.args)
                return f"({callee})({vals})"

            fn = self._resolve_function_for_call(e, local_types)
            if fn:
                ordered = self._ordered_call_args(e.args, fn.params, f"function '{fn.name}'", variadic=fn.is_variadic)
                vals = []
                fixed = fn.params
                for arg, param in zip(ordered, fixed):
                    vals.append(self.gen_expr(arg, local_types))
                if len(ordered) > len(fixed):
                    vals.extend(self.gen_expr(x, local_types) for x in ordered[len(fixed):])
                return f"{self._function_ref(fn)}({', '.join(vals)})"

            callee = self.gen_expr(e.callee, local_types)
            vals = ", ".join(self.gen_expr(a.expr if isinstance(a, NamedArg) else a, local_types) for a in e.args)
            return f"({callee})({vals})"

        raise NotImplementedError(f"Lua expression not handled: {e!r}")

    def _class_ref(self, full_name):
        cls = self.classes.get(full_name)
        if cls:
            return self._decl_ref(self._short_decl_name(full_name, cls.namespace), cls.namespace)
        # fallback when the IR only gives the qualified C-style class name
        return self._lua_ident(full_name)

    def _class_new_expr(self, full_name, args, local_types):
        cls = self.classes[full_name]
        ctor = next((m for m in cls.methods if m.is_constructor), None)
        if ctor:
            ordered = self._ordered_call_args(args, ctor.params, f"constructor '{full_name}'")
            vals = ", ".join(self.gen_expr(a.expr if isinstance(a, NamedArg) else a, local_types) for a in ordered)
        else:
            if args:
                raise CodeGenError(f"constructor '{full_name}' takes no arguments")
            vals = ""
        return f"{self._class_ref(full_name)}.new({vals})"

    def _struct_ref(self, full_name):
        s = self.structs[full_name]
        return self._decl_ref(self._short_decl_name(full_name, s.namespace), s.namespace)

    def _struct_new_ref(self, full_name):
        return self._struct_ref(full_name) + ".new"

    def _struct_new_expr(self, full_name, args, local_types):
        s = self.structs[full_name]
        if any(isinstance(a, NamedArg) for a in args):
            raise CodeGenError(f"struct '{full_name}' construction only accepts positional arguments")
        if len(args) not in (0, len(s.fields)):
            raise CodeGenError(f"struct '{full_name}' construction expects {len(s.fields)} argument(s), {len(args)} provided")
        vals = [self.gen_expr(a, local_types) for a in args]
        if not vals:
            vals = [self._type_default(f.type) for f in s.fields]
        return f"{self._struct_ref(full_name)}.new({', '.join(vals)})"

    # ------------------------------------------------------------------
    # Statements
    # ------------------------------------------------------------------
    def _collect_change_handlers_lua(self, statements, local_types):
        handlers = {}
        for st in statements:
            if isinstance(st, VariableChangeHandler):
                if st.name in handlers:
                    raise CodeGenError(f"signal: multiple handlers for variable '{st.name}' in the same function")
                handlers[st.name] = st.body
        return handlers

    def _signal_after_assignment(self, name, local_types, indent):
        if name not in self._change_handlers or self._in_change_handler:
            return []
        old = f"__j_old_{self._tmp_id}"
        self._tmp_id += 1
        # Signals need an old value. At assignment sites we save it before the
        # assignment; this helper is only called when the caller has already
        # emitted __j_old immediately before it.
        body = self._change_handlers[name]
        self._in_change_handler = True
        try:
            body_lines = self._gen_block_statements(body.statements, local_types, indent)
        finally:
            self._in_change_handler = False
        cond = f"({old} ~= {self.gen_expr(Ident(name), local_types)})"
        pad = self.IND * indent
        return [pad + f"if {cond} then"] + [self.IND + x for x in body_lines] + [pad + "end"]

    def _gen_var_decl(self, s, local_types):
        if s.type == "auto":
            real = self._resolve_auto_type(s.init, local_types)
        else:
            real = s.type
        local_types[s.name] = real
        if self._generic_parts(real):
            gp = self._generic_parts(real)
            kind, inner = gp
            if kind in ("list", "dynamic_list", "container"):
                if s.init is not None and isinstance(s.init, ListLiteral):
                    value = self.gen_expr(s.init, local_types)
                else:
                    value = "{}"
            elif kind == "map":
                value = "{}"
            elif kind == "pair":
                value = "{}"
            else:
                value = self._type_default(real)
        else:
            if s.init is not None:
                value = self.gen_expr(s.init, local_types)
            elif real in self.classes:
                value = self._class_new_expr(real, [], local_types)
            elif real in self.structs:
                value = self._struct_new_expr(real, [], local_types)
            else:
                value = self._type_default(real)
        return f"local {self._lua_ident(s.name)} = {value}"

    def _gen_block_statements(self, statements, local_types, indent, constructor_return=True):
        out = []
        for s in statements:
            lines = self._gen_stmt(s, local_types, indent, constructor_return=constructor_return)
            out.extend(lines)
        return out

    def _gen_stmt(self, s, local_types, indent, constructor_return=True):
        pad = self.IND * indent
        if isinstance(s, VariableChangeHandler):
            return []
        if isinstance(s, (UsingNamespaceStmt, UsingSymbolStmt, TypeAliasStmt)):
            return []
        if isinstance(s, VarDecl):
            return [pad + self._gen_var_decl(s, local_types)]
        if isinstance(s, ReturnStmt):
            if s.expr is None:
                return [pad + ("return" if not (self._current_function_local_types.get("__is_main") or False) else "return")]
            return [pad + f"return {self.gen_expr(s.expr, local_types)}"]
        if isinstance(s, ExprStmt):
            return [pad + self.gen_expr(s.expr, local_types)]
        if isinstance(s, AssignStmt):
            old_name = None
            if s.name in self._change_handlers and not self._in_change_handler:
                old_name = f"__j_old_{self._tmp_id}"; self._tmp_id += 1
                out = [pad + f"local {old_name} = {self.gen_expr(Ident(s.name), local_types)}"]
            else:
                out = []
            out.append(pad + f"{self.gen_expr(Ident(s.name), local_types)} = {self.gen_expr(s.expr, local_types)}")
            if old_name:
                body = self._change_handlers[s.name]
                self._in_change_handler = True
                try:
                    body_lines = self._gen_block_statements(body.statements, dict(local_types), indent + 1)
                finally:
                    self._in_change_handler = False
                out.append(pad + f"if {old_name} ~= {self.gen_expr(Ident(s.name), local_types)} then")
                out.extend(body_lines)
                out.append(pad + "end")
            return out
        if isinstance(s, PointerAssignStmt):
            return [pad + f"__j.setptr({self.gen_expr(s.target, local_types)}, {self.gen_expr(s.expr, local_types)})"]
        if isinstance(s, MemberAssignStmt):
            target = s.target
            obj = self.gen_expr(target.obj, local_types)
            lhs = f"{obj}.{self._lua_ident(target.name)}"
            return [pad + f"{lhs} = {self.gen_expr(s.expr, local_types)}"]
        if isinstance(s, IfStmt):
            out = [pad + f"if {self.gen_expr(s.cond, local_types)} then"]
            out.extend(self._gen_block_statements(s.then_block.statements, dict(local_types), indent + 1))
            branch = s.else_branch
            while isinstance(branch, IfStmt):
                out.append(pad + f"elseif {self.gen_expr(branch.cond, local_types)} then")
                out.extend(self._gen_block_statements(branch.then_block.statements, dict(local_types), indent + 1))
                branch = branch.else_branch
            if isinstance(branch, Block):
                out.append(pad + "else")
                out.extend(self._gen_block_statements(branch.statements, dict(local_types), indent + 1))
            out.append(pad + "end")
            return out
        if isinstance(s, WhileStmt):
            self._loop_depth += 1
            label = f"__j_continue_{self._tmp_id}"; self._tmp_id += 1
            self._continue_labels.append(label)
            try:
                out = [pad + f"while {self.gen_expr(s.cond, local_types)} do"]
                out.extend(self._gen_block_statements(s.body.statements, dict(local_types), indent + 1))
                out.append(self.IND * (indent + 1) + f"::{label}::")
                out.append(pad + "end")
                return out
            finally:
                self._continue_labels.pop(); self._loop_depth -= 1
        if isinstance(s, LoopStmt):
            self._loop_depth += 1
            label = f"__j_continue_{self._tmp_id}"; self._tmp_id += 1
            self._continue_labels.append(label)
            try:
                out = [pad + "while true do"]
                out.extend(self._gen_block_statements(s.body.statements, dict(local_types), indent + 1))
                out.append(self.IND * (indent + 1) + f"::{label}::")
                out.append(pad + "end")
                return out
            finally:
                self._continue_labels.pop(); self._loop_depth -= 1
        if isinstance(s, ForLoopStmt):
            self._loop_depth += 1
            label = f"__j_continue_{self._tmp_id}"; self._tmp_id += 1
            self._continue_labels.append(label)
            try:
                start = self.gen_expr(s.start, local_types)
                end = self.gen_expr(s.end, local_types)
                out = [pad + f"for {self._lua_ident(s.var_name)} = ({start}), ({end}) do"]
                inner = dict(local_types); inner[s.var_name] = s.var_type
                out.extend(self._gen_block_statements(s.body.statements, inner, indent + 1))
                out.append(self.IND * (indent + 1) + f"::{label}::")
                out.append(pad + "end")
                return out
            finally:
                self._continue_labels.pop(); self._loop_depth -= 1
        if isinstance(s, CollectionLoopStmt):
            self._loop_depth += 1
            label = f"__j_continue_{self._tmp_id}"; self._tmp_id += 1
            self._continue_labels.append(label)
            try:
                obj = self.gen_expr(s.collection, local_types)
                inner = dict(local_types)
                if s.kind == "loop_map" or s.kind == "map":
                    out = [pad + f"for __k, __v in pairs({obj}) do", self.IND * (indent + 1) + f"local {self._lua_ident(s.var_name)} = __j.pair(__k, __v)"]
                    out.extend(self._gen_block_statements(s.body.statements, inner, indent + 1))
                else:
                    out = [pad + f"for _, {self._lua_ident(s.var_name)} in ipairs({obj}) do"]
                    out.extend(self._gen_block_statements(s.body.statements, inner, indent + 1))
                out.append(self.IND * (indent + 1) + f"::{label}::")
                out.append(pad + "end")
                return out
            finally:
                self._continue_labels.pop(); self._loop_depth -= 1
        if isinstance(s, BreakStmt):
            if self._loop_depth <= 0: raise CodeGenError("break used outside a loop")
            return [pad + "break"]
        if isinstance(s, ContinueStmt):
            if self._loop_depth <= 0 or not self._continue_labels:
                raise CodeGenError("continue used outside a loop")
            return [pad + f"goto {self._continue_labels[-1]}"]
        raise NotImplementedError(f"Lua statement not handled: {s!r}")

    # ------------------------------------------------------------------
    # Functions / globals / top-level
    # ------------------------------------------------------------------
    def _function_params(self, fn):
        return ", ".join(p.name for p in fn.params)

    def _gen_function(self, fn):
        if self._is_special_main(fn):
            # Lua script execution is the equivalent of the C `main` entry
            # point. We keep a normal `main` function to preserve Jaguar's API
            # shape, then dispatch to it at the bottom of the generated file.
            self._current_class = None
            self._current_namespace = fn.namespace
            local_types = {p.name: p.type for p in fn.params}
            self._current_return_type = fn.ret_type
            self._current_function_local_types = local_types
            params = self._function_params(fn)
            if len(fn.params) == 1 and fn.params[0].type == "string":
                # Lua `arg` is a table; Jaguar's single string main parameter
                # corresponds to the first command-line argument.
                pre = f"local {fn.params[0].name} = (arg and arg[1]) or \"\""
            else:
                pre = None
            lines = ["function main(" + params + ")"]
            if pre: lines.append(self.IND + pre)
            lines.extend(self._gen_block_statements(fn.body.statements, local_types, 1))
            lines.append(self.IND + "return 0")
            lines.append("end")
            return lines

        self._current_class = None
        self._current_namespace = fn.namespace
        local_types = {p.name: p.type for p in fn.params}
        self._current_function_local_types = local_types
        self._current_return_type = fn.ret_type
        self._change_handlers = self._collect_change_handlers_lua(fn.body.statements, local_types)
        name = fn.mangled_name or fn.name
        # If decorators exist, emit a base implementation and wrapper chain.
        impl = f"function {self._decl_ref(name, fn.namespace)}({self._function_params(fn)})"
        lines = [impl]
        lines.extend(self._gen_block_statements(fn.body.statements, local_types, 1))
        lines.append("end")
        lines.append("")
        if fn.decorators:
            # Decorator bodies execute with `func()` mapped back to the target
            # function. For Lua we can generate the same wrapper concept using
            # local functions and captured decorator parameters.
            target = self._function_ref(fn)
            for idx, use in reversed(list(enumerate(fn.decorators))):
                dec = self._find_decorator(use.name, fn.namespace)
                if dec is None:
                    raise CodeGenError(f"unknown decorator '@{use.name}'")
                wrapper_name = fn.mangled_name if idx == 0 else f"{fn.mangled_name}__decor_{idx}"
                if idx == 0:
                    # overwrite public function only after target exists
                    target_alias = f"__j_target_{self._tmp_id}"; self._tmp_id += 1
                    lines.append(f"local {target_alias} = {target}")
                    target = target_alias
                    wrapper_ref = self._decl_ref(wrapper_name, fn.namespace)
                else:
                    target_alias = f"__j_target_{self._tmp_id}"; self._tmp_id += 1
                    lines.append(f"local {target_alias} = {target}")
                    target = target_alias
                    wrapper_ref = self._decl_ref(wrapper_name, fn.namespace)
                params = self._function_params(fn)
                lines.append(f"function {wrapper_ref}({params})")
                ordered = self._ordered_call_args(use.args, dec.params, f"decorator '@{use.name}'")
                for p, a in zip(dec.params, ordered):
                    lines.append(self.IND + f"local {p.name} = {self.gen_expr(a, {x.name:x.type for x in fn.params})}")
                self._decorator_call_target_name = target
                self._decorator_target_params = list(fn.params)
                self._current_namespace = dec.namespace
                dec_types = {p.name:p.type for p in fn.params}
                dec_types.update({p.name:p.type for p in dec.params})
                lines.extend(self._gen_block_statements(dec.body.statements, dec_types, 1))
                self._decorator_call_target_name = None
                self._decorator_target_params = []
                lines.append("end")
                lines.append("")
        return lines

    def _gen_global(self, v):
        ref = self._decl_ref(v.name, v.namespace)
        value = self.gen_expr(v.init, {}) if v.init is not None else self._type_default(v.type)
        if v.is_extern:
            # Lua has no separate extern storage; leave a documented placeholder.
            return [f"-- extern {ref}"]
        return [f"{ref} = {value}"]

    def _gen_top_expr(self, item):
        return [self.gen_expr(item.expr, {})]

    def generate(self):
        self._validate_parameter_defaults()
        lines = ["-- Generated by JaguarCC: Lua 5.4 backend", "-- Source IR: Jaguar .jir", "", self._runtime().rstrip(), "", "-- Namespaces"]
        lines.extend(self._ensure_namespace_lines())

        # Forward decls are unnecessary in Lua.
        for item in self.program.items:
            if isinstance(item, EnumDecl):
                lines.extend(self._emit_enum_decl(item))
            elif isinstance(item, StructDecl):
                lines.extend(self._emit_struct_decl(item))
            elif isinstance(item, ClassDecl):
                lines.extend(self._emit_class_decl(item))
            elif isinstance(item, UnionDecl):
                # A union is represented as a plain table. The IR already knows
                # its fields; no memory-layout semantics exist in Lua.
                ref = self._decl_ref(self._short_decl_name(item.name, item.namespace), item.namespace)
                lines.append(f"{ref} = {{}}")
                lines.append("")

        # Globals before functions, matching Jaguar source order as closely as
        # possible while ensuring constructors/classes are already available.
        for item in self.program.items:
            if isinstance(item, VarDecl):
                lines.extend(self._gen_global(item))
                lines.append("")

        for item in self.program.items:
            if isinstance(item, FunctionDecl):
                if item.is_prototype:
                    lines.append(f"-- prototype: {item.name}")
                    continue
                lines.extend(self._gen_function(item))
            elif isinstance(item, TopExprStmt):
                lines.extend(self._gen_top_expr(item))

        mains = [x for x in self.program.items if isinstance(x, FunctionDecl) and self._is_special_main(x)]
        if mains:
            lines.append("-- Jaguar entry point")
            lines.append("os.exit(main(arg and arg[1] or nil) or 0)")
        return "\n".join(lines).rstrip() + "\n"


def _load_program_from_ir_text(ir_text):
    ir = jcc.deserialize_ir(ir_text)
    program = jcc.program_from_ir(ir)
    groups = jcc.groups_from_program(program)
    return ir, program, groups


def generate_lua(ir_text):
    _, program, groups = _load_program_from_ir_text(ir_text)
    return LuaCodeGen(program, groups).generate()


def main(argv):
    out_path = None
    in_path = None
    args = argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "-o" and i + 1 < len(args):
            out_path = args[i + 1]
            i += 2
        elif args[i] == "--emit-lua":
            i += 1
        else:
            in_path = args[i]
            i += 1

    if in_path:
        with open(in_path, "r", encoding="utf-8") as f:
            ir_text = f.read()
        input_name = in_path
    else:
        ir_text = sys.stdin.read()
        input_name = None

    try:
        generated = generate_lua(ir_text)
    except (LexError, ParseError, ResolverError, CodeGenError, ValueError, TypeError) as e:
        source = ""
        try:
            ir = jcc.deserialize_ir(ir_text)
            source = ir.get("source", {}).get("text", "")
        except Exception:
            pass
        if isinstance(e, (LexError, ParseError, ResolverError, CodeGenError)):
            try:
                d = _C._diagnostic_from_exception(source, e)
                location = f"{input_name}:{d['line']}:{d['column'] + 1}" if input_name else f"<stdin>:{d['line']}:{d['column'] + 1}"
                print(f"Jaguar Error: {location}: {d['message']}", file=sys.stderr)
            except Exception:
                print(f"Jaguar Error: {e}", file=sys.stderr)
        else:
            print(f"Jaguar Error: {e}", file=sys.stderr)
        return 1

    if out_path:
        if out_path.endswith(".lua"):
            print("Jaguar Error: output name must be given without the .lua extension (e.g. -o out)", file=sys.stderr)
            return 1
        base = Path(out_path)
        base.parent.mkdir(parents=True, exist_ok=True)
        lua_path = base.with_suffix(base.suffix + ".lua") if base.suffix else Path(str(base) + ".lua")
        lua_path.write_text(generated, encoding="utf-8")
        print(f"Jaguar: Lua generated at {lua_path}")
        return 0

    sys.stdout.write(generated)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
