#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
jcc-llvm.py — Backend Jaguar IR -> LLVM IR

Ce backend ne parse pas Jaguar. Il consomme exclusivement le
jaguar-ir produit par jcc.py.

Usage:
    python3 jcc.py main.ja -o main.jir
    python3 jcc-llvm.py main.jir
    python3 jcc-llvm.py main.jir -o main.ll
    python3 jcc-llvm.py main.jir --verify
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Optional

import jcc
from jcc import *
import importlib.util


def _load_sibling_c_backend():
    path = Path(__file__).with_name("jcc-c.py")
    if not path.exists():
        raise ImportError(f"cannot find sibling backend '{path.name}'")
    spec = importlib.util.spec_from_file_location("jaguar_jcc_c_backend", str(path))
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load sibling backend '{path.name}'")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


jcc_c = _load_sibling_c_backend()

try:
    from llvmlite import ir
    from llvmlite import binding as llvm
except ImportError as exc:
    raise SystemExit(
        "jcc-llvm.py requires 'llvmlite'. Install it with: python -m pip install llvmlite"
    ) from exc


# ---------------------------------------------------------------------------
# LLVM helpers
# ---------------------------------------------------------------------------

I1 = ir.IntType(1)
I8 = ir.IntType(8)
I16 = ir.IntType(16)
I32 = ir.IntType(32)
I64 = ir.IntType(64)
F32 = ir.FloatType()
F64 = ir.DoubleType()
VOID = ir.VoidType()
PTR = ir.PointerType()


INTEGER_TYPES = set(jcc.INTEGER_TYPES)
FLOAT_TYPES = set(jcc.FLOAT_TYPES)


class LLVMCodeGenError(Exception):
    pass


class _LoopContext:
    def __init__(self, break_block, continue_block):
        self.break_block = break_block
        self.continue_block = continue_block


class _FunctionState:
    def __init__(self, function, entry_builder):
        self.function = function
        self.builder = entry_builder
        self.allocas = {}
        self.local_types = {}
        self.loop_stack = []
        self.current_class = None
        self.current_class_method = None
        self.current_return_type = "void"
        self.signal_handlers = {}
        self.readonly = set()
        self.const_objects = set()
        self._string_tmp = 0


def _is_literal_type(t):
    return isinstance(t, tuple) and len(t) == 2 and t[0] == "literal"


def _canonical(t):
    if not isinstance(t, str):
        return t
    try:
        return jcc.canonical_type(t)
    except Exception:
        return t


def _function_type_parts(t):
    if not isinstance(t, str) or not t.startswith("fn("):
        return None
    close = t.rfind(") -> ")
    if close < 0:
        return None
    inner = t[3:close]
    ret = t[close + 5:].strip()
    return jcc._split_type_list(inner), ret


def _fixed_array_parts(t):
    if not isinstance(t, str):
        return None
    m = re.match(r"^(.*?)(?:\[(\d+)\])+$", t)
    if not m:
        return None
    return m.group(1), [int(x) for x in re.findall(r"\[(\d+)\]", t)]


class LLVMCodeGen:
    """
    LLVM backend built on the resolved Jaguar IR.

    The front-end remains the source of truth for names, overload resolution,
    type checking and class lookup. LLVMCodeGen only lowers the resolved AST.
    """

    def __init__(self, program: Program, groups, target_triple=None):
        self.program = program
        self.groups = groups

        self.semantic = jcc_c.CodeGen(program, groups)
        self.module = ir.Module(name="jaguar")
        self.module.triple = target_triple or llvm.get_default_triple()

        self.type_cache = {}
        self.enum_types = {}
        self.enum_values = {}
        self.function_values = {}
        self.functions = {}
        self.globals = {}
        self.string_globals = {}
        self.string_data_globals = {}
        self.runtime = {}
        self.struct_decls = {}
        self.union_decls = {}
        self.class_decls = {}
        self.class_vtables = {}
        self.class_vtable_methods = {}
        self.current_state = None
        self._string_id = 0
        self._tmp_id = 0

        self.aliases = {}
        for item in program.items:
            if isinstance(item, TypeAliasDecl):
                self.aliases[item.name] = item.target

        self.macros = {}
        for item in program.items:
            if isinstance(item, PreprocLine):
                m = re.match(
                    r"\s*#\s*define\s+([A-Za-z_]\w*)(?:\s+(.*?))?\s*$",
                    item.text,
                )
                if m and m.group(2):
                    self.macros[m.group(1)] = m.group(2).strip()

        for item in program.items:
            if isinstance(item, StructDecl):
                self.struct_decls[item.name] = item
            elif isinstance(item, UnionDecl):
                self.union_decls[item.name] = item
            elif isinstance(item, ClassDecl):
                self.class_decls[item.name] = item

        self._declare_named_types()
        self._declare_runtime()
        self._declare_enums()
        self._declare_globals()
        self._declare_functions()
        self._declare_class_vtables()

    # ------------------------------------------------------------------
    # Type system
    # ------------------------------------------------------------------

    def _resolve_alias(self, t):
        seen = set()
        while isinstance(t, str) and t in self.aliases and t not in seen:
            seen.add(t)
            t = self.aliases[t]
        return t

    def llvm_type(self, t):
        if isinstance(t, ir.Type):
            return t
        if isinstance(t, tuple):
            t = t[1] if len(t) > 1 else "int"

        if t is None:
            return VOID

        t = self._resolve_alias(t)

        if t == "void":
            return VOID
        if t in ("bool",):
            return I1
        if t in ("i8", "char", "sbyte"):
            return I8
        if t in ("u8", "uchar", "byte"):
            return I8
        if t in ("i16", "short"):
            return I16
        if t in ("u16", "ushort"):
            return I16
        if t in ("i32", "int"):
            return I32
        if t in ("u32", "uint"):
            return I32
        if t in ("i64", "long"):
            return I64
        if t in ("u64", "ulong"):
            return I64
        if t in ("f32", "float"):
            return F32
        if t in ("f64", "double"):
            return F64
        if t == "string":
            return self.string_type.as_pointer()
        if t == "nullptr":
            return PTR

        fp = _function_type_parts(t)
        if fp:
            params, ret = fp
            vararg = bool(params and params[-1] == "...")
            if vararg:
                params = params[:-1]
            return ir.FunctionType(
                self.llvm_type(ret),
                [self.llvm_type(x) for x in params],
                var_arg=vararg,
            ).as_pointer()

        arr = _fixed_array_parts(t)
        if arr:
            base, dims = arr
            ty = self.llvm_type(base)
            for n in reversed(dims):
                ty = ir.ArrayType(ty, n)
            return ty

        if t in self.class_decls:
            return self.type_cache[t].as_pointer()

        if t in self.struct_decls or t in self.union_decls:
            return self.type_cache[t]

        if t in self.enum_types:
            return I32

        if t.endswith("*"):
            base = t.rstrip("*")
            ty = self.llvm_type(base)
            return ty.as_pointer()

        gp = self._generic_parts(t)
        if gp:
            # Collections are represented by small opaque runtime values.
            kind, _ = gp
            if kind == "pair":
                a, b = self._split_generic_args(gp[1])
                return ir.LiteralStructType([self.llvm_type(a), self.llvm_type(b)])
            # The exact collection runtime is not ABI-stable yet; keep a
            # uniform aggregate so the IR remains well typed. Collection
            # operations are lowered through runtime helpers below.
            return self.collection_type

        raise LLVMCodeGenError(f"unsupported Jaguar type '{t}' in LLVM backend")

    @property
    def string_type(self):
        return self.type_cache["string"]

    @property
    def collection_type(self):
        return self.type_cache["jCollection"]

    def _generic_parts(self, t):
        if not isinstance(t, str):
            return None
        if t == "dynamic_list":
            return ("dynamic_list", "")
        for k in ("list", "map", "container", "pair"):
            prefix = k + "<"
            if t.startswith(prefix) and t.endswith(">"):
                return k, t[len(prefix):-1]
        return None

    def _split_generic_args(self, inner):
        return jcc._split_type_list(inner)

    def _declare_named_types(self):
        self.type_cache["string"] = self.module.context.get_identified_type("jString")
        self.type_cache["string"].set_body(I64, I8, ir.ArrayType(I8, 7), PTR)

        # Collection placeholders.
        coll = self.module.context.get_identified_type("jCollection")
        coll.set_body(PTR, I64, I64, I64)

        for name in sorted(set(self.struct_decls) | set(self.union_decls) | set(self.class_decls)):
            self.type_cache.setdefault(name, self.module.context.get_identified_type(name))

        # Structs.
        for name, s in self.struct_decls.items():
            fields = []
            for f in s.fields:
                fields.append(self.llvm_type(f.type))
            self.type_cache[name].set_body(*fields)

        # Unions: LLVM has no first-class C-style union type. Use an array of
        # bytes sized to the largest field, with conservative 8-byte alignment.
        for name, u in self.union_decls.items():
            sizes = [self._type_storage_size(self.llvm_type(f.type)) for f in u.fields]
            max_size = max(sizes or [1])
            self.type_cache[name].set_body(ir.ArrayType(I8, max_size))

        # Classes: layout mirrors the C backend conceptually:
        # vptr + embedded base + declared fields.
        for name, cls in self.class_decls.items():
            fields = [self._class_vtable_ptr_type(cls)]
            if cls.base:
                fields.append(self.type_cache[cls.base])
            fields.extend(self.llvm_type(f.type) for f in cls.fields)
            self.type_cache[name].set_body(*fields)

    def _type_storage_size(self, ty):
        # This is only used for unions/collection metadata. For aggregates,
        # use conservative estimates sufficient for runtime memcpy buffers.
        if isinstance(ty, ir.IntType):
            return max(1, ty.width // 8)
        if isinstance(ty, ir.FloatType):
            return 4
        if isinstance(ty, ir.DoubleType):
            return 8
        if isinstance(ty, ir.PointerType):
            return 8
        if isinstance(ty, ir.ArrayType):
            return ty.count * self._type_storage_size(ty.element)
        if isinstance(ty, ir.LiteralStructType):
            return sum(self._type_storage_size(x) for x in ty.elements)
        if isinstance(ty, ir.IdentifiedStructType):
            try:
                return sum(self._type_storage_size(x) for x in ty.elements)
            except Exception:
                return 8
        return 8

    # ------------------------------------------------------------------
    # Runtime / external declarations
    # ------------------------------------------------------------------

    def _declare_function(self, name, ret, args, *, var_arg=False, linkage=None):
        if name in self.runtime:
            return self.runtime[name]
        fty = ir.FunctionType(self.llvm_type(ret), [self.llvm_type(x) if isinstance(x, str) else x for x in args], var_arg=var_arg)
        fn = ir.Function(self.module, fty, name=name)
        if linkage:
            fn.linkage = linkage
        self.runtime[name] = fn
        return fn

    def _declare_runtime(self):
        # C/POSIX libc symbols used by the generated LLVM runtime.
        self._declare_function("malloc", PTR, [I64])
        self._declare_function("calloc", PTR, [I64, I64])
        self._declare_function("realloc", PTR, [PTR, I64])
        self._declare_function("free", VOID, [PTR])
        self._declare_function("memcpy", PTR, [PTR, PTR, I64])
        self._declare_function("memset", PTR, [PTR, I32, I64])
        self._declare_function("strlen", I64, [PTR])
        self._declare_function("strcmp", I32, [PTR, PTR])
        self._declare_function("strncmp", I32, [PTR, PTR, I64])
        self._declare_function("memcmp", I32, [PTR, PTR, I64])
        self._declare_function("strstr", PTR, [PTR, PTR])

        printf_ty = ir.FunctionType(I32, [PTR], var_arg=True)
        self.runtime["printf"] = ir.Function(self.module, printf_ty, name="printf")
        self.runtime["puts"] = self._declare_function("puts", I32, [PTR])
        self.runtime["exit"] = self._declare_function("exit", VOID, [I32])
        self.runtime["abort"] = self._declare_function("abort", VOID, [])
        self.runtime["system"] = self._declare_function("system", I32, [PTR])

        for n in ("sqrt", "sin", "cos", "tan", "asin", "acos", "atan", "floor", "ceil", "round", "log", "log10", "exp"):
            self.runtime[n] = ir.Function(self.module, ir.FunctionType(F64, [F64]), name=n)
        self.runtime["pow"] = ir.Function(self.module, ir.FunctionType(F64, [F64, F64]), name="pow")
        self.runtime["fmod"] = ir.Function(self.module, ir.FunctionType(F64, [F64, F64]), name="fmod")

        for n in ("isdigit", "isalpha", "isalnum", "isspace", "isupper", "islower", "toupper", "tolower"):
            ret = I32
            self.runtime[n] = ir.Function(self.module, ir.FunctionType(ret, [I32]), name=n)

        self._emit_string_runtime()

    def _emit_string_runtime(self):
        jst = self.string_type
        # string_alloc(i64) -> %jString*
        fn = ir.Function(self.module, ir.FunctionType(jst.as_pointer(), [I64]), name="j_string_alloc")
        entry = fn.append_basic_block("entry")
        b = ir.IRBuilder(entry)

        # Runtime layout is fixed to { i64, i8, [7 x i8], ptr } so the
        # string header is 24 bytes on the supported 32/64-bit targets.
        # Keeping the padding explicit avoids relying on typed-pointer GEP
        # sizeof tricks, which are rejected by newer LLVM parsers.
        sz = ir.Constant(I64, 24)
        total = b.add(sz, b.add(fn.args[0], ir.Constant(I64, 1)))
        raw = b.call(self.runtime["malloc"], [total])
        isnull = b.icmp_unsigned("==", raw, ir.Constant(PTR, None))
        fail = fn.append_basic_block("oom")
        cont = fn.append_basic_block("cont")
        b.cbranch(isnull, fail, cont)
        b.position_at_end(fail)
        b.call(self.runtime["abort"], [])
        b.unreachable()
        b.position_at_end(cont)

        s = self.typed_ptr_from_opaque(raw, jst, b)
        b.store(fn.args[0], b.gep(s, [ir.Constant(I32, 0), ir.Constant(I32, 0)]))
        b.store(ir.Constant(I8, 0), b.gep(s, [ir.Constant(I32, 0), ir.Constant(I32, 1)]))
        # GEP the inline-data member in the old C layout is replaced by a
        # direct pointer in LLVM's jString representation.
        data_slot = b.gep(s, [ir.Constant(I32, 0), ir.Constant(I32, 3)])
        data_int = b.add(b.ptrtoint(raw, I64), sz)
        data = b.inttoptr(data_int, I8.as_pointer())
        b.store(data, data_slot)
        b.store(ir.Constant(I8, 0), b.gep(data, [fn.args[0]], inbounds=False))
        b.ret(s)

        cstr = ir.Function(self.module, ir.FunctionType(jst.as_pointer(), [PTR]), name="j_string_from_cstr")
        e = cstr.append_basic_block("entry")
        b = ir.IRBuilder(e)
        ln = b.call(self.runtime["strlen"], [cstr.args[0]])
        s = b.call(fn, [ln])
        data = self.string_data(b, s)
        b.call(self.runtime["memcpy"], [data, cstr.args[0], b.add(ln, ir.Constant(I64, 1))])
        b.ret(s)

        destr = ir.Function(self.module, ir.FunctionType(VOID, [jst.as_pointer()]), name="j_string_destr")
        e = destr.append_basic_block("entry")
        b = ir.IRBuilder(e)
        null = b.icmp_unsigned("==", destr.args[0], ir.Constant(jst.as_pointer(), None))
        ret = destr.append_basic_block("ret")
        cont = destr.append_basic_block("cont")
        b.cbranch(null, ret, cont)
        b.position_at_end(ret)
        b.ret_void()
        b.position_at_end(cont)
        lit = b.icmp_unsigned("!=", b.load(b.gep(destr.args[0], [ir.Constant(I32, 0), ir.Constant(I32, 1)]), typ=I8), ir.Constant(I8, 0))
        freeb = destr.append_basic_block("free")
        done = destr.append_basic_block("done")
        b.cbranch(lit, done, freeb)
        b.position_at_end(freeb)
        b.call(self.runtime["free"], [self.string_data(b, destr.args[0])])
        b.call(self.runtime["free"], [b.bitcast(destr.args[0], PTR)])
        b.branch(done)
        b.position_at_end(done)
        b.ret_void()

        self.string_runtime = {
            "alloc": fn,
            "from_cstr": cstr,
            "destr": destr,
        }

        self.string_runtime["length"] = self._emit_string_unary(
            "j_string_length", I32, self._string_length_impl
        )
        self.string_runtime["empty"] = self._emit_string_unary(
            "j_string_empty", I1, self._string_empty_impl
        )
        self.string_runtime["equals"] = self._emit_string_binary(
            "j_string_equals", I1, self._string_equals_impl
        )
        self.string_runtime["contains"] = self._emit_string_binary(
            "j_string_contains", I1, self._string_contains_impl
        )
        self.string_runtime["starts_with"] = self._emit_string_binary(
            "j_string_starts_with", I1, self._string_starts_impl
        )
        self.string_runtime["ends_with"] = self._emit_string_binary(
            "j_string_ends_with", I1, self._string_ends_impl
        )
        self.string_runtime["concat"] = self._emit_string_binary(
            "j_string_concat", self.string_type.as_pointer(), self._string_concat_impl
        )

        self.string_runtime["substring"] = self._emit_string_substring()
        self.string_runtime["char_at"] = self._emit_string_char_at()
        self.string_runtime["to_upper"] = self._emit_string_case("j_string_to_upper", True)
        self.string_runtime["to_lower"] = self._emit_string_case("j_string_to_lower", False)
        self.string_runtime["ctor"] = self._emit_string_ctor()

    def _emit_string_unary(self, name, ret_ty, body_fn):
        fn = ir.Function(self.module, ir.FunctionType(ret_ty, [self.string_type.as_pointer()]), name=name)
        b = ir.IRBuilder(fn.append_basic_block("entry"))
        body_fn(b, fn)
        return fn

    def _emit_string_binary(self, name, ret_ty, body_fn):
        fn = ir.Function(self.module, ir.FunctionType(ret_ty, [self.string_type.as_pointer(), self.string_type.as_pointer()]), name=name)
        b = ir.IRBuilder(fn.append_basic_block("entry"))
        body_fn(b, fn)
        return fn

    def _string_length_impl(self, b, fn):
        p = b.gep(fn.args[0], [ir.Constant(I32, 0), ir.Constant(I32, 0)])
        b.ret(b.trunc(b.load(p, typ=I64), I32))

    def _string_empty_impl(self, b, fn):
        p = b.gep(fn.args[0], [ir.Constant(I32, 0), ir.Constant(I32, 0)])
        b.ret(b.icmp_unsigned("==", b.load(p, typ=I64), ir.Constant(I64, 0)))

    def _string_equals_impl(self, b, fn):
        a, c = fn.args
        ad, bd = self.string_data(b, a), self.string_data(b, c)
        aa = b.call(self.runtime["strcmp"], [ad, bd])
        b.ret(b.icmp_signed("==", aa, ir.Constant(I32, 0)))

    def _string_contains_impl(self, b, fn):
        ad, bd = self.string_data(b, fn.args[0]), self.string_data(b, fn.args[1])
        r = b.call(self.runtime["strstr"], [ad, bd])
        b.ret(b.icmp_unsigned("!=", r, ir.Constant(PTR, None)))

    def _string_starts_impl(self, b, fn):
        a, c = fn.args
        al = b.load(b.gep(a, [ir.Constant(I32, 0), ir.Constant(I32, 0)]), typ=I64)
        cl = b.load(b.gep(c, [ir.Constant(I32, 0), ir.Constant(I32, 0)]), typ=I64)
        too_long = b.icmp_unsigned(">", cl, al)
        fail = fn.append_basic_block("fail")
        test = fn.append_basic_block("test")
        b.cbranch(too_long, fail, test)
        b.position_at_end(fail)
        b.ret(ir.Constant(I1, 0))
        b.position_at_end(test)
        ad, cd = self.string_data(b, a), self.string_data(b, c)
        x = b.call(self.runtime["memcmp"], [ad, cd, cl])
        b.ret(b.icmp_signed("==", x, ir.Constant(I32, 0)))

    def _string_ends_impl(self, b, fn):
        a, c = fn.args
        al = b.load(b.gep(a, [ir.Constant(I32, 0), ir.Constant(I32, 0)]), typ=I64)
        cl = b.load(b.gep(c, [ir.Constant(I32, 0), ir.Constant(I32, 0)]), typ=I64)
        too_long = b.icmp_unsigned(">", cl, al)
        fail = fn.append_basic_block("fail")
        test = fn.append_basic_block("test")
        b.cbranch(too_long, fail, test)
        b.position_at_end(fail)
        b.ret(ir.Constant(I1, 0))
        b.position_at_end(test)
        ad, cd = self.string_data(b, a), self.string_data(b, c)
        off = b.sub(al, cl)
        ad2 = self.byte_gep(b, ad, off)
        x = b.call(self.runtime["memcmp"], [ad2, cd, cl])
        b.ret(b.icmp_signed("==", x, ir.Constant(I32, 0)))

    def _string_concat_impl(self, b, fn):
        a, c = fn.args
        al = b.load(b.gep(a, [ir.Constant(I32, 0), ir.Constant(I32, 0)]), typ=I64)
        cl = b.load(b.gep(c, [ir.Constant(I32, 0), ir.Constant(I32, 0)]), typ=I64)
        total = b.add(al, cl)
        out = b.call(self.string_runtime["alloc"], [total])
        od = self.string_data(b, out)
        ad, cd = self.string_data(b, a), self.string_data(b, c)
        b.call(self.runtime["memcpy"], [od, ad, al])
        od2 = self.byte_gep(b, od, al)
        b.call(self.runtime["memcpy"], [od2, cd, b.add(cl, ir.Constant(I64, 1))])
        b.ret(out)

    def _emit_string_substring(self):
        fn = ir.Function(
            self.module,
            ir.FunctionType(self.string_type.as_pointer(), [self.string_type.as_pointer(), I32, I32]),
            name="j_string_substring",
        )
        b = ir.IRBuilder(fn.append_basic_block("entry"))
        selfv, start, length = fn.args
        sl = b.load(b.gep(selfv, [ir.Constant(I32, 0), ir.Constant(I32, 0)]), typ=I64)
        start64 = b.zext(start, I64)
        len64 = b.zext(length, I64)
        bad1 = b.icmp_signed("<", start, ir.Constant(I32, 0))
        bad2 = b.icmp_signed("<", length, ir.Constant(I32, 0))
        bad3 = b.icmp_unsigned(">", start64, sl)
        bad = b.or_(bad1, b.or_(bad2, bad3))
        badb = fn.append_basic_block("bad")
        good = fn.append_basic_block("good")
        b.cbranch(bad, badb, good)
        b.position_at_end(badb)
        empty = b.call(self.string_runtime["alloc"], [ir.Constant(I64, 0)])
        b.ret(empty)
        b.position_at_end(good)
        remain = b.sub(sl, start64)
        use = b.select(b.icmp_unsigned(">", len64, remain), remain, len64)
        out = b.call(self.string_runtime["alloc"], [use])
        src = self.byte_gep(b, self.string_data(b, selfv), start64)
        b.call(self.runtime["memcpy"], [self.string_data(b, out), src, b.add(use, ir.Constant(I64, 1))])
        b.ret(out)
        return fn

    def _emit_string_char_at(self):
        fn = ir.Function(
            self.module,
            ir.FunctionType(I32, [self.string_type.as_pointer(), I32]),
            name="j_string_char_at",
        )
        b = ir.IRBuilder(fn.append_basic_block("entry"))
        selfv, index = fn.args
        ln = b.load(b.gep(selfv, [ir.Constant(I32, 0), ir.Constant(I32, 0)]), typ=I64)
        neg = b.icmp_signed("<", index, ir.Constant(I32, 0))
        hi = b.icmp_unsigned(">=", b.zext(index, I64), ln)
        bad = b.or_(neg, hi)
        bb = fn.append_basic_block("bad")
        ok = fn.append_basic_block("ok")
        b.cbranch(bad, bb, ok)
        b.position_at_end(bb)
        b.ret(ir.Constant(I32, -1))
        b.position_at_end(ok)
        ch = b.load(self.byte_gep(b, self.string_data(b, selfv), b.zext(index, I64)), typ=I8)
        b.ret(b.zext(ch, I32))
        return fn

    def _emit_string_case(self, name, upper):
        fn = ir.Function(self.module, ir.FunctionType(self.string_type.as_pointer(), [self.string_type.as_pointer()]), name=name)
        b = ir.IRBuilder(fn.append_basic_block("entry"))
        s = fn.args[0]
        ln = b.load(b.gep(s, [ir.Constant(I32, 0), ir.Constant(I32, 0)]), typ=I64)
        out = b.call(self.string_runtime["alloc"], [ln])
        b.call(self.runtime["memcpy"], [self.string_data(b, out), self.string_data(b, s), b.add(ln, ir.Constant(I64, 1))])
        i = b.alloca(I64); b.store(ir.Constant(I64, 0), i)
        loop = fn.append_basic_block("loop")
        done = fn.append_basic_block("done")
        b.branch(loop)
        b.position_at_end(loop)
        iv = b.load(i, typ=I64)
        cond = b.icmp_unsigned("<", iv, ln)
        body = fn.append_basic_block("body")
        b.cbranch(cond, body, done)
        b.position_at_end(body)
        chp = self.byte_gep(b, self.string_data(b, out), iv)
        ch = b.load(chp, typ=I8)
        lo = b.icmp_unsigned(">=", ch, ir.Constant(I8, ord("a")))
        hi = b.icmp_unsigned("<=", ch, ir.Constant(I8, ord("z")))
        inside = b.and_(lo, hi)
        bchan = fn.append_basic_block("change")
        nxt = fn.append_basic_block("next")
        b.cbranch(inside, bchan, nxt)
        b.position_at_end(bchan)
        delta = ir.Constant(I8, ord("A") - ord("a") if upper else ord("a") - ord("A"))
        # Only transform when the source byte belongs to the opposite case.
        # The branch condition is amended below.
        if upper:
            need = b.and_(b.icmp_unsigned(">=", ch, ir.Constant(I8, ord("a"))),
                          b.icmp_unsigned("<=", ch, ir.Constant(I8, ord("z"))))
        else:
            need = b.and_(b.icmp_unsigned(">=", ch, ir.Constant(I8, ord("A"))),
                          b.icmp_unsigned("<=", ch, ir.Constant(I8, ord("Z"))))
        do = fn.append_basic_block("do")
        b2 = fn.append_basic_block("skip")
        b.cbranch(need, do, b2)
        b.position_at_end(do)
        b.store(b.add(ch, delta), chp)
        b.branch(b2)
        b.position_at_end(b2)
        b.branch(nxt)
        b.position_at_end(nxt)
        b.store(b.add(iv, ir.Constant(I64, 1)), i)
        b.branch(loop)
        b.position_at_end(done)
        b.ret(out)
        return fn

    def _emit_string_ctor(self):
        fn = ir.Function(self.module, ir.FunctionType(self.string_type.as_pointer(), []), name="j_string_ctor")
        b = ir.IRBuilder(fn.append_basic_block("entry"))
        b.ret(b.call(self.string_runtime["alloc"], [ir.Constant(I64, 0)]))
        return fn

    def byte_gep(self, builder, ptr, offset):
        base = builder.ptrtoint(ptr, I64)
        addr = builder.add(base, offset)
        return builder.inttoptr(addr, I8.as_pointer())

    def string_data(self, builder, s):
        return builder.load(builder.gep(s, [ir.Constant(I32, 0), ir.Constant(I32, 3)]), typ=PTR)

    # ------------------------------------------------------------------
    # Enums / globals / functions
    # ------------------------------------------------------------------

    def _declare_enums(self):
        for item in self.program.items:
            if not isinstance(item, EnumDecl):
                continue
            name = f"{item.namespace}_{item.name}" if item.namespace else item.name
            self.enum_types[name] = item
            initializers = getattr(item, "initializers", None) or {}
            current = 0
            for value in item.values:
                if value in initializers:
                    cv = self.constant_expr(initializers[value])
                    if isinstance(cv, ir.Constant) and isinstance(cv.type, ir.IntType):
                        current = int(str(cv.constant), 10)
                self.enum_values[f"{name}_{value}"] = ir.Constant(I32, current)
                current += 1

    def _declare_globals(self):
        # Union declarations implicitly expose a global value with that name.
        for name, u in self.union_decls.items():
            gv = ir.GlobalVariable(self.module, self.type_cache[name], f"_j_union_{name}")
            gv.initializer = ir.Constant(self.type_cache[name], None)
            self.globals[name] = gv

        for item in self.program.items:
            if not isinstance(item, VarDecl):
                continue
            name = self._global_symbol_name(item)
            ty = self.llvm_type(item.type)
            gv = ir.GlobalVariable(self.module, ty, name)
            gv.linkage = "internal" if not item.is_extern else "external"
            if item.init is None:
                gv.initializer = ir.Constant(ty, None)
            else:
                cv = self.constant_expr(item.init, expected_type=item.type)
                if cv is None:
                    raise LLVMCodeGenError(
                        f"global initializer for '{item.name}' is not a constant expression supported by the LLVM backend"
                    )
                gv.initializer = cv
            self.globals[name] = gv

    def _declare_functions(self):
        for item in self.program.items:
            if isinstance(item, FunctionDecl):
                self._declare_function_decl(item)
        for cls in self.class_decls.values():
            for m in cls.methods:
                if m.is_constructor:
                    self._declare_class_ctor(m, cls)
                elif m.is_destructor:
                    self._declare_class_destr(cls)
                else:
                    self._declare_class_method(m, cls)
            if not any(m.is_constructor for m in cls.methods):
                self._declare_class_ctor(None, cls)
            if not any(m.is_destructor for m in cls.methods):
                self._declare_class_destr(cls)

    def _decl_ftype(self, fn: FunctionDecl):
        params = [self.llvm_type(p.type) for p in fn.params]
        return ir.FunctionType(self.llvm_type(fn.ret_type), params, var_arg=fn.is_variadic)

    def _declare_function_decl(self, fn):
        name = fn.mangled_name or self.semantic.default_mangle(fn.name, fn.namespace)
        if self._is_special_main(fn):
            # Final ABI is constructed in _build_function_body.
            if len(fn.params) == 1:
                fty = ir.FunctionType(I32, [I32, PTR])
            else:
                fty = ir.FunctionType(I32, [])
        else:
            fty = self._decl_ftype(fn)
        llvm_fn = ir.Function(self.module, fty, name=name)
        if fn.is_extern:
            llvm_fn.linkage = "external"
        self.functions[id(fn)] = llvm_fn

    def _declare_class_method(self, m, cls):
        self_param = self.type_cache[cls.name].as_pointer()
        params = [self_param] + [self.llvm_type(p.type) for p in m.params]
        ret = self.llvm_type(m.ret_type)
        name = m.mangled_name or f"{cls.name}_{m.name}"
        self.functions[id(m)] = ir.Function(self.module, ir.FunctionType(ret, params), name=name)

    def _declare_class_ctor(self, m, cls):
        params = [] if m is None else [self.llvm_type(p.type) for p in m.params]
        name = f"{cls.name}_ctor" if m is None else (m.mangled_name or f"{cls.name}_ctor")
        self.functions[id(m) if m is not None else ("ctor", cls.name)] = ir.Function(
            self.module,
            ir.FunctionType(self.type_cache[cls.name].as_pointer(), params),
            name=name,
        )

    def _declare_class_destr(self, cls):
        key = ("destr", cls.name)
        name = f"{cls.name}_destr"
        if key not in self.functions:
            self.functions[key] = ir.Function(
                self.module,
                ir.FunctionType(VOID, [self.type_cache[cls.name].as_pointer()]),
                name=name,
            )

    def _class_vtable_methods(self, cls):
        methods = []
        all_methods = self.semantic._all_virtual_methods(cls)
        for m in all_methods:
            methods.append(m)
        return methods

    def _class_vtable_ptr_type(self, cls):
        methods = self._class_vtable_methods(cls)
        fields = []
        for m in methods:
            fty = ir.FunctionType(
                self.llvm_type(m.ret_type),
                [self.type_cache[cls.name].as_pointer()] + [self.llvm_type(p.type) for p in m.params],
            )
            fields.append(fty.as_pointer())
        vt = self.type_cache.get(f"{cls.name}_vtable")
        if vt is None:
            vt = self.module.context.get_identified_type(f"{cls.name}_vtable")
            vt.set_body(*fields)
            self.type_cache[f"{cls.name}_vtable"] = vt
        return vt.as_pointer()

    def _declare_class_vtables(self):
        for name, cls in self.class_decls.items():
            methods = self._class_vtable_methods(cls)
            vt = self.type_cache[f"{name}_vtable"]
            vals = []
            for m in methods:
                fn = self.functions.get(id(m))
                if fn is None:
                    raise LLVMCodeGenError(f"internal error: missing virtual method '{name}::{m.name}'")
                vals.append(fn)
            arr = ir.Constant(vt, vals)
            gv = ir.GlobalVariable(self.module, vt, f"{name}_vtable_instance")
            gv.linkage = "internal"
            gv.global_constant = True
            gv.initializer = arr
            self.class_vtables[name] = gv
            self.class_vtable_methods[name] = methods

    # ------------------------------------------------------------------
    # Name resolution / constants
    # ------------------------------------------------------------------

    def _global_symbol_name(self, v):
        if v.namespace:
            return f"{v.namespace.replace(':','_')}_{v.name}"
        return v.name

    def _is_special_main(self, fn):
        return fn.name == "main" and not fn.is_extern and (len(fn.params) in (0, 1))

    def _enum_constant(self, name):
        return self.enum_values.get(name)

    def constant_expr(self, e, expected_type=None):
        if isinstance(e, IntLit):
            target = expected_type if expected_type and not _is_literal_type(expected_type) else "i32"
            return self._const_numeric_int(e.value, target)
        if isinstance(e, FloatLit):
            target = expected_type if expected_type and not _is_literal_type(expected_type) else "f64"
            return self._const_numeric_float(e.value, target)
        if isinstance(e, BoolLit):
            return ir.Constant(I1, int(e.value))
        if isinstance(e, NullPtrLit):
            return ir.Constant(self.llvm_type(expected_type) if expected_type else PTR, None)
        if isinstance(e, StringLit):
            return self.string_literal(e.value)
        if isinstance(e, Ident):
            if e.name in self.macros:
                return self._constant_from_text(self.macros[e.name], expected_type)
            if e.name in self.enum_values:
                return self.enum_values[e.name]
            if e.name in self.globals:
                gv = self.globals[e.name]
                return gv.initializer if getattr(gv, "initializer", None) is not None else None
            return None
        if isinstance(e, NamespacedIdent):
            q = f"{e.namespace.replace(':','_')}_{e.name}"
            if q in self.enum_values:
                return self.enum_values[q]
            if q in self.globals:
                gv = self.globals[q]
                return gv.initializer
            return None
        if isinstance(e, UnaryOp):
            x = self.constant_expr(e.operand, expected_type)
            if x is None:
                return None
            if e.op == "-":
                return self._const_neg(x)
            if e.op == "+":
                return x
            if e.op == "!":
                return ir.Constant(I1, int(not bool(int(str(x.constant)))))
        if isinstance(e, BinOp):
            a = self.constant_expr(e.left)
            b = self.constant_expr(e.right)
            if a is None or b is None:
                return None
            return self._const_binop(e.op, a, b)
        if isinstance(e, CastExpr):
            x = self.constant_expr(e.operand)
            if x is None:
                return None
            return self._const_cast(x, e.target_type)
        return None

    def _constant_from_text(self, text, expected_type=None):
        text = text.strip()
        if text in ("true", "false"):
            return ir.Constant(I1, int(text == "true"))
        if re.fullmatch(r"[+-]?\d+", text):
            return self._const_numeric_int(text, expected_type or "i32")
        if re.fullmatch(r"[+-]?(?:\d+\.\d*|\.\d+)(?:[eE][+-]?\d+)?", text):
            return self._const_numeric_float(text, expected_type or "f64")
        if len(text) >= 2 and text[0] == text[-1] == '"':
            return self.string_literal(text)
        return None

    def _const_numeric_int(self, text, target):
        ty = self.llvm_type(target or "i32")
        if isinstance(ty, ir.IntType):
            return ir.Constant(ty, int(text, 10))
        if isinstance(ty, (ir.FloatType, ir.DoubleType)):
            return ir.Constant(ty, float(text))
        raise LLVMCodeGenError(f"integer literal cannot initialize '{target}'")

    def _const_numeric_float(self, text, target):
        ty = self.llvm_type(target or "f64")
        if isinstance(ty, (ir.FloatType, ir.DoubleType)):
            return ir.Constant(ty, float(text))
        raise LLVMCodeGenError(f"float literal cannot initialize '{target}'")

    def _const_neg(self, x):
        if isinstance(x.type, (ir.FloatType, ir.DoubleType)):
            return ir.Constant(x.type, -float(str(x.constant)))
        if isinstance(x.type, ir.IntType):
            return ir.Constant(x.type, -int(str(x.constant)))
        raise LLVMCodeGenError("unsupported constant negation")

    def _const_binop(self, op, a, b):
        if isinstance(a.type, ir.IntType) and isinstance(b.type, ir.IntType):
            av = int(str(a.constant)); bv = int(str(b.constant))
            if op == "+": return ir.Constant(a.type, av + bv)
            if op == "-": return ir.Constant(a.type, av - bv)
            if op == "*": return ir.Constant(a.type, av * bv)
            if op == "/" and bv != 0: return ir.Constant(a.type, int(av / bv))
            if op == "%" and bv != 0: return ir.Constant(a.type, av % bv)
            if op == "==": return ir.Constant(I1, int(av == bv))
            if op == "!=": return ir.Constant(I1, int(av != bv))
            if op == "<": return ir.Constant(I1, int(av < bv))
            if op == ">": return ir.Constant(I1, int(av > bv))
            if op == "<=": return ir.Constant(I1, int(av <= bv))
            if op == ">=": return ir.Constant(I1, int(av >= bv))
        if isinstance(a.type, (ir.FloatType, ir.DoubleType)):
            av = float(str(a.constant)); bv = float(str(b.constant))
            if op == "+": return ir.Constant(a.type, av + bv)
            if op == "-": return ir.Constant(a.type, av - bv)
            if op == "*": return ir.Constant(a.type, av * bv)
            if op == "/": return ir.Constant(a.type, av / bv)
        return None

    def _const_cast(self, x, target):
        ty = self.llvm_type(target)
        if x.type == ty:
            return x
        if isinstance(x.type, ir.IntType) and isinstance(ty, ir.IntType):
            return ir.Constant(ty, int(str(x.constant)))
        if isinstance(x.type, ir.IntType) and isinstance(ty, (ir.FloatType, ir.DoubleType)):
            return ir.Constant(ty, float(int(str(x.constant))))
        if isinstance(x.type, (ir.FloatType, ir.DoubleType)) and isinstance(ty, (ir.FloatType, ir.DoubleType)):
            return ir.Constant(ty, float(str(x.constant)))
        return None

    # ------------------------------------------------------------------
    # String literals
    # ------------------------------------------------------------------

    def _decode_string(self, token):
        try:
            # Jaguar string tokens use C-like escapes.
            return bytes(token[1:-1], "utf-8").decode("unicode_escape").encode("utf-8")
        except Exception:
            return token[1:-1].encode("utf-8")

    def string_literal(self, token):
        raw = self._decode_string(token)
        key = raw
        if key in self.string_globals:
            return self.string_globals[key]

        arr = ir.ArrayType(I8, len(raw) + 1)
        dname = f".jstr.data.{self._string_id}"
        sname = f".jstr.{self._string_id}"
        self._string_id += 1

        cbytes = bytearray(raw)
        cbytes.append(0)
        data_const = ir.Constant(arr, [ir.Constant(I8, x) for x in cbytes])
        dglob = ir.GlobalVariable(self.module, arr, dname)
        dglob.linkage = "private"
        dglob.global_constant = True
        dglob.unnamed_addr = True
        dglob.initializer = data_const

        zero = ir.Constant(I64, len(raw))
        lit = ir.Constant(I8, 1)
        pad = ir.Constant(ir.ArrayType(I8, 7), [ir.Constant(I8, 0) for _ in range(7)])
        data_ptr = dglob.gep([ir.Constant(I32, 0), ir.Constant(I32, 0)])
        sconst = ir.Constant(self.string_type, [zero, lit, pad, data_ptr])
        sglob = ir.GlobalVariable(self.module, self.string_type, sname)
        sglob.linkage = "private"
        sglob.global_constant = True
        sglob.unnamed_addr = True
        sglob.initializer = sconst

        self.string_data_globals[key] = dglob
        self.string_globals[key] = sglob
        return sglob

    # ------------------------------------------------------------------
    # Function / block helpers
    # ------------------------------------------------------------------

    def alloca_entry(self, name, ty):
        state = self.current_state
        entry = state.function.entry_basic_block
        current_block = state.builder.block

        # Emit allocas in the entry block. If the entry block was empty, the
        # main builder has to be repositioned after inserting through a second
        # builder; otherwise later instructions can accidentally be inserted
        # before the new alloca.
        tmp = ir.IRBuilder(entry)
        if entry.instructions:
            tmp.position_before(entry.instructions[0])
        ptr = tmp.alloca(ty, name=name)
        state.allocas[name] = ptr

        if current_block.terminator is None:
            state.builder.position_at_end(current_block)
        else:
            state.builder.position_at_end(current_block)
        return ptr

    def current_value(self, name):
        if name in self.current_state.allocas:
            return self.current_state.builder.load(self.current_state.allocas[name], typ=self.llvm_type(self.current_state.local_types[name]), name=f"{name}.load")
        g = self._resolve_global(name)
        if g is not None:
            return self.current_state.builder.load(g, typ=g.type.pointee, name=f"{name}.load")
        raise LLVMCodeGenError(f"unknown variable '{name}'")

    def current_lvalue(self, name):
        if name in self.current_state.allocas:
            return self.current_state.allocas[name]
        g = self._resolve_global(name)
        if g is not None:
            return g
        raise LLVMCodeGenError(f"unknown variable '{name}'")

    def _resolve_global(self, name):
        gname = self.semantic._resolve_global_name(name)
        if gname and gname in self.globals:
            return self.globals[gname]
        if name in self.globals:
            return self.globals[name]
        return None

    def _set_function_state(self, state):
        self.current_state = state
        self.semantic._current_class = state.current_class
        self.semantic._current_class_method_const = bool(
            state.current_class_method and getattr(state.current_class_method, "is_const", False)
        )
        self.semantic._current_return_type = state.current_return_type
        self.semantic._current_function_local_types = state.local_types
        self.semantic._current_source_line = getattr(state.function, "_jaguar_line", 1)

    def _restore_semantic(self):
        self.semantic._current_class = None
        self.semantic._current_class_method_const = False

    def _branch_if_open(self, target):
        if self.current_state.builder.block.terminator is None:
            self.current_state.builder.branch(target)

    def _ensure_block_terminated(self, ret_type):
        b = self.current_state.builder
        if b.block.terminator is not None:
            return
        if ret_type == "void":
            b.ret_void()
        elif ret_type == "bool":
            b.ret(ir.Constant(I1, 0))
        elif ret_type in INTEGER_TYPES:
            b.ret(ir.Constant(self.llvm_type(ret_type), 0))
        elif ret_type in FLOAT_TYPES:
            b.ret(ir.Constant(self.llvm_type(ret_type), 0.0))
        elif isinstance(ret_type, str) and (ret_type.endswith("*") or ret_type in self.class_decls):
            b.ret(ir.Constant(self.llvm_type(ret_type), None))
        else:
            b.ret(ir.Constant(self.llvm_type(ret_type), None))

    # ------------------------------------------------------------------
    # Expression lowering
    # ------------------------------------------------------------------

    def emit_lvalue(self, e, local_types):
        b = self.current_state.builder

        if isinstance(e, Ident):
            if self.current_state.current_class and e.name == "this":
                return self.current_state.allocas["this"]
            return self.current_lvalue(e.name)

        if isinstance(e, MemberAccess):
            base_t = self.semantic.infer_type(e.obj, local_types)
            obj = self.emit_expr(e.obj, local_types)
            raw = base_t
            pointer_obj = isinstance(raw, str) and raw.endswith("*")
            owner_type = raw.rstrip("*") if pointer_obj else raw

            gp = self._generic_parts(owner_type)
            if gp:
                raise LLVMCodeGenError("collection element/member lvalues are not yet supported by the LLVM backend")

            if owner_type in self.class_decls:
                owner, field = self.semantic._find_class_member(owner_type, e.name, "field")
                if field is None:
                    raise LLVMCodeGenError(f"'{e.name}' is not a field of class '{owner_type}'")
                if owner.name != owner_type:
                    cur = obj
                    cur_cls = self.class_decls[owner_type]
                    # Walk embedded bases until the field owner is reached.
                    while cur_cls.name != owner.name:
                        if not cur_cls.base:
                            raise LLVMCodeGenError(f"cannot resolve inherited member '{e.name}'")
                        cur = b.gep(cur, [ir.Constant(I32, 0), ir.Constant(I32, 1)])
                        cur_cls = self.class_decls[cur_cls.base]
                    idx = self._field_index(owner, field.name)
                    return b.gep(cur, [ir.Constant(I32, 0), ir.Constant(I32, idx)])
                idx = self._class_field_index(owner_type, field.name)
                return b.gep(obj, [ir.Constant(I32, 0), ir.Constant(I32, idx)])

            if owner_type in self.struct_decls:
                idx = next(i for i,f in enumerate(self.struct_decls[owner_type].fields) if f.name == e.name)
                if pointer_obj:
                    return b.gep(obj, [ir.Constant(I32, 0), ir.Constant(I32, idx)])
                return b.gep(self._address_of_value(e.obj, local_types), [ir.Constant(I32, 0), ir.Constant(I32, idx)])

            if owner_type in self.union_decls:
                # Union fields share the same byte buffer. Return its storage.
                return self._union_field_ptr(obj, owner_type, e.name)

            if owner_type == "string":
                raise LLVMCodeGenError(f"string member '{e.name}' is not an lvalue")

            raise LLVMCodeGenError(f"cannot take the address of member '{e.name}'")

        if isinstance(e, IndexAccess):
            arrt = self.semantic.infer_type(e.obj, local_types)
            parts = _fixed_array_parts(arrt)
            idx = self.emit_expr(e.index, local_types)
            if parts:
                base, dims = parts
                objptr = self._address_of_value(e.obj, local_types)
                indices = [ir.Constant(I32, 0), idx]
                cur = self.llvm_type(arrt)
                # For multidimensional arrays only the first dimension can be
                # assigned as an index expression here.
                return b.gep(objptr, indices)
            raise LLVMCodeGenError("index assignment is only supported for fixed arrays in the LLVM backend")

        if isinstance(e, UnaryOp) and e.op == "*":
            return self.emit_expr(e.operand, local_types)

        raise LLVMCodeGenError("expression is not addressable")

    def _address_of_value(self, e, local_types):
        if isinstance(e, Ident):
            return self.current_lvalue(e.name)
        if isinstance(e, MemberAccess):
            return self.emit_lvalue(e, local_types)
        if isinstance(e, UnaryOp) and e.op == "*":
            return self.emit_expr(e.operand, local_types)
        if isinstance(e, IndexAccess):
            return self.emit_lvalue(e, local_types)
        raise LLVMCodeGenError("expression is not addressable")

    def emit_expr(self, e, local_types, expected_type=None):
        b = self.current_state.builder

        if isinstance(e, IntLit):
            target = expected_type if expected_type and not _is_literal_type(expected_type) else "i32"
            return self._const_to_target(self.constant_expr(e, target), expected_type)

        if isinstance(e, FloatLit):
            target = expected_type if expected_type and not _is_literal_type(expected_type) else "f64"
            return self._const_to_target(self.constant_expr(e, target), expected_type)

        if isinstance(e, BoolLit):
            return ir.Constant(I1, int(e.value))

        if isinstance(e, StringLit):
            return self.string_literal(e.value)

        if isinstance(e, NullPtrLit):
            return ir.Constant(self.llvm_type(expected_type) if expected_type else PTR, None)

        if isinstance(e, Ident):
            if e.name == "this":
                return b.load(self.current_state.allocas["this"], typ=self.type_cache[self.current_state.current_class.name].as_pointer())

            if e.name in self.enum_values:
                return self.enum_values[e.name]

            symbols = getattr(self.program, "_using_symbols", {})
            imported = symbols.get(e.name)
            if imported:
                ns, nm = imported
                for fn in self.groups.get((ns, nm), []):
                    return self.function_value(fn)

            if e.name in self.macros:
                cv = self.constant_expr(Ident(e.name), expected_type)
                if cv is not None:
                    return cv

            # Global enum values and imported enum values.
            for q, cv in self.enum_values.items():
                if q.endswith("_" + e.name) and q.rsplit("_", 1)[-1] == e.name:
                    # Avoid selecting the wrong enum if several namespaces have
                    # an identically named enumerator; semantic resolution has
                    # already rejected ambiguous uses.
                    try:
                        if self.semantic.infer_type(e, local_types):
                            return cv
                    except Exception:
                        pass

            if e.name in self.current_state.allocas or self._resolve_global(e.name):
                return self.current_value(e.name)

            # Bare class/function name as a function value.
            candidates = self.groups.get((None, e.name), [])
            if len(candidates) == 1:
                return self.function_value(candidates[0])

            cname = self.semantic._resolve_class_name(e.name)
            if cname:
                return self.class_type_global_value(cname)

            raise LLVMCodeGenError(f"unknown identifier '{e.name}'")

        if isinstance(e, NamespacedIdent):
            if e.namespace == "factory" and e.name == "construct":
                return None
            q = f"{e.namespace.replace(':','_')}_{e.name}"
            if q in self.enum_values:
                return self.enum_values[q]
            if q in self.globals:
                return self.current_state.builder.load(self.globals[q], typ=self.globals[q].type.pointee)
            candidates = self.groups.get((e.namespace, e.name), [])
            if len(candidates) == 1:
                return self.function_value(candidates[0])
            if q in self.class_decls:
                return self.class_type_global_value(q)
            raise LLVMCodeGenError(f"unknown namespaced identifier '{e.namespace}:{e.name}'")

        if isinstance(e, UnaryOp):
            x = self.emit_expr(e.operand, local_types)
            if e.op == "!":
                return b.icmp_unsigned("==", x, ir.Constant(I1, 0))
            if e.op == "-":
                if isinstance(x.type, (ir.FloatType, ir.DoubleType)):
                    return b.fneg(x)
                return b.neg(x)
            if e.op == "+":
                return x
            if e.op == "&":
                return self._address_of_value(e.operand, local_types)
            if e.op == "*":
                return b.load(x, typ=self.llvm_type(self.semantic.infer_type(e.operand, local_types)))
            raise LLVMCodeGenError(f"unsupported unary operator '{e.op}'")

        if isinstance(e, CastExpr):
            src = self.emit_expr(e.operand, local_types)
            return self.cast_value(src, self.llvm_type(e.target_type), e.target_type)

        if isinstance(e, IndexAccess):
            ptr = self.emit_lvalue(e, local_types)
            return b.load(ptr, typ=self.llvm_type(target_t))

        if isinstance(e, MemberAccess):
            ot = self.semantic.infer_type(e.obj, local_types)
            if isinstance(ot, str) and ot.endswith("*"):
                ot = ot.rstrip("*")
            gp = self._generic_parts(ot)
            if gp:
                raise LLVMCodeGenError("collection member expressions are not yet supported by the LLVM backend")
            if ot == "string":
                obj = self.emit_expr(e.obj, local_types)
                return self.string_member_value(e.name, obj)
            if ot in self.class_decls or ot in self.struct_decls or ot in self.union_decls:
                return b.load(self.emit_lvalue(e, local_types), typ=self.llvm_type(self.semantic.infer_type(e, local_types)))
            raise LLVMCodeGenError(f"member access on unsupported type '{ot}'")

        if isinstance(e, BinOp):
            lt = self.semantic.infer_type(e.left, local_types)
            rt = self.semantic.infer_type(e.right, local_types)
            custom = self.semantic._resolve_operator(e.op, lt, rt)
            if custom is not None:
                return self.emit_call_target(custom, [e.left, e.right], local_types)

            if e.op == "+" and lt == "string" and rt == "string":
                a = self.emit_expr(e.left, local_types, "string")
                c = self.emit_expr(e.right, local_types, "string")
                return b.call(self.string_runtime["concat"], [a, c])

            # Boolean short-circuiting.
            if e.op in ("&&", "||"):
                return self.emit_logical(e, local_types)

            common = self.common_numeric_type(lt, rt)
            left = self.emit_expr(e.left, local_types, common)
            right = self.emit_expr(e.right, local_types, common)

            if e.op in ("+", "-", "*", "/", "%"):
                if isinstance(left.type, (ir.FloatType, ir.DoubleType)):
                    if e.op == "+": return b.fadd(left, right)
                    if e.op == "-": return b.fsub(left, right)
                    if e.op == "*": return b.fmul(left, right)
                    if e.op == "/": return b.fdiv(left, right)
                    return b.frem(left, right)
                if e.op == "+": return b.add(left, right)
                if e.op == "-": return b.sub(left, right)
                if e.op == "*": return b.mul(left, right)
                if e.op == "/":
                    signed = self._signed_type(common)
                    return b.sdiv(left, right) if signed else b.udiv(left, right)
                if e.op == "%":
                    signed = self._signed_type(common)
                    return b.srem(left, right) if signed else b.urem(left, right)

            if e.op in ("==", "!="):
                if lt == "string" and rt == "string":
                    eq = b.call(self.string_runtime["equals"], [
                        self.emit_expr(e.left, local_types, "string"),
                        self.emit_expr(e.right, local_types, "string")
                    ])
                    return eq if e.op == "==" else b.xor(eq, ir.Constant(I1, 1))
                if self.llvm_type(common).is_pointer:
                    return b.icmp_unsigned(e.op, left, right)
                return b.icmp_signed(e.op, left, right) if not isinstance(left.type, (ir.FloatType, ir.DoubleType)) else b.fcmp_ordered(e.op, left, right)

            if e.op in ("<", ">", "<=", ">="):
                if isinstance(left.type, (ir.FloatType, ir.DoubleType)):
                    return b.fcmp_ordered(e.op, left, right)
                return b.icmp_signed(e.op, left, right) if self._signed_type(common) else b.icmp_unsigned(e.op, left, right)

            raise LLVMCodeGenError(f"unsupported binary operator '{e.op}'")

        if isinstance(e, NewExpr):
            class_name = self.semantic._resolve_class_name(e.type)
            if class_name:
                args = self._ordered_args_for_ctor(class_name, e.args, local_types)
                return self.emit_constructor(class_name, args, local_types)

            struct_name = self.semantic._resolve_struct_name(e.type)
            if struct_name:
                st = self.type_cache[struct_name]
                size = self.sizeof_type(st)
                raw = b.call(self.runtime["calloc"], [ir.Constant(I64, 1), size])
                obj = self.typed_ptr_from_opaque(raw, st)
                if e.args:
                    if len(e.args) != 1:
                        raise LLVMCodeGenError(
                            f"new {e.type}(...) currently accepts at most one argument"
                        )
                    # A struct's single-argument constructor form is lowered
                    # as initialization of its first field.
                    if not self.struct_decls[struct_name].fields:
                        raise LLVMCodeGenError(
                            f"cannot initialize empty struct '{struct_name}'"
                        )
                    first = self.struct_decls[struct_name].fields[0]
                    value = self.emit_expr(e.args[0], local_types, first.type)
                    field_ptr = b.gep(
                        obj, [ir.Constant(I32, 0), ir.Constant(I32, 0)]
                    )
                    b.store(self.cast_value_if_needed(value, first.type), field_ptr)
                return obj

            # Primitive allocation, e.g. `new int(5)`.
            ty = self.llvm_type(e.type)
            if isinstance(ty, (ir.IntType, ir.FloatType, ir.DoubleType)):
                size = ir.Constant(I64, self._type_storage_size(ty))
                raw = b.call(self.runtime["calloc"], [ir.Constant(I64, 1), size])
                ptr = self.typed_ptr_from_opaque(raw, ty)
                if e.args:
                    if len(e.args) != 1:
                        raise LLVMCodeGenError(
                            f"new {e.type}(...) expects exactly one argument"
                        )
                    value = self.emit_expr(e.args[0], local_types, e.type)
                    b.store(self.cast_value_if_needed(value, e.type), ptr)
                return ptr

            raise LLVMCodeGenError(f"new is not implemented for '{e.type}'")

        if isinstance(e, Call):
            return self.emit_call(e, local_types)

        raise LLVMCodeGenError(f"unsupported expression node {type(e).__name__}")

    def _const_to_target(self, val, expected):
        if val is None or expected is None:
            return val
        try:
            et = self.llvm_type(expected)
        except Exception:
            return val
        return val if val.type == et else self.cast_constant(val, et)

    def cast_constant(self, value, target):
        if value.type == target:
            return value
        if isinstance(value.type, ir.IntType) and isinstance(target, ir.IntType):
            return ir.Constant(target, int(str(value.constant)))
        if isinstance(value.type, ir.IntType) and isinstance(target, (ir.FloatType, ir.DoubleType)):
            return ir.Constant(target, float(int(str(value.constant))))
        if isinstance(value.type, (ir.FloatType, ir.DoubleType)) and isinstance(target, (ir.FloatType, ir.DoubleType)):
            return ir.Constant(target, float(str(value.constant)))
        return value

    def cast_value(self, value, target, target_name=None):
        b = self.current_state.builder
        if value.type == target:
            return value
        if isinstance(target, ir.IntType) and isinstance(value.type, ir.IntType):
            if target.width > value.type.width:
                if self._signed_type(target_name or ""):
                    return b.sext(value, target)
                return b.zext(value, target)
            if target.width < value.type.width:
                return b.trunc(value, target)
            return value
        if isinstance(target, (ir.FloatType, ir.DoubleType)):
            if isinstance(value.type, ir.IntType):
                return b.sitofp(value, target)
            if isinstance(value.type, (ir.FloatType, ir.DoubleType)):
                if isinstance(value.type, ir.FloatType) and isinstance(target, ir.DoubleType):
                    return b.fpext(value, target)
                if isinstance(value.type, ir.DoubleType) and isinstance(target, ir.FloatType):
                    return b.fptrunc(value, target)
        if isinstance(value.type, (ir.FloatType, ir.DoubleType)) and isinstance(target, ir.IntType):
            return b.fptosi(value, target)
        if isinstance(value.type, ir.PointerType) and isinstance(target, ir.PointerType):
            return b.bitcast(value, target)
        if isinstance(value.type, ir.IntType) and isinstance(target, ir.PointerType):
            return b.inttoptr(value, target)
        if isinstance(value.type, ir.PointerType) and isinstance(target, ir.IntType):
            return b.ptrtoint(value, target)
        raise LLVMCodeGenError(f"cannot cast LLVM value {value.type} to {target}")

    def common_numeric_type(self, a, c):
        if _is_literal_type(a):
            a = "i32" if a[1] == "int" else "f64"
        if _is_literal_type(c):
            c = "i32" if c[1] == "int" else "f64"
        if a in FLOAT_TYPES or c in FLOAT_TYPES:
            return "f64" if a == "f64" or c == "f64" else "f32"
        order = ["i8", "u8", "i16", "u16", "i32", "u32", "i64", "u64"]
        try:
            return order[max(order.index(a), order.index(c))]
        except ValueError:
            return a or c or "i32"

    def _signed_type(self, t):
        return t not in {"u8", "u16", "u32", "u64", "uint", "ushort", "ulong", "uchar", "byte"}

    def typed_ptr_from_opaque(self, value, pointee, builder=None):
        b = builder or (self.current_state.builder if self.current_state else None)
        if b is None:
            raise LLVMCodeGenError("internal error: typed pointer conversion requires an active LLVM builder")
        if getattr(value.type, "pointee", None) is not None and value.type.pointee == pointee:
            return value
        return b.inttoptr(b.ptrtoint(value, I64), pointee.as_pointer())

    def sizeof_type(self, ty):
        # Compute size with GEP + ptrtoint, so target pointer width is used.
        null = ir.Constant(ty.as_pointer(), None)
        tmp = self.current_state.builder if self.current_state else None
        if tmp is None:
            # Fallback for declaration-time helpers.
            return ir.Constant(I64, self._type_storage_size(ty))
        p = tmp.gep(null, [ir.Constant(I32, 1)])
        return tmp.ptrtoint(p, I64)

    # ------------------------------------------------------------------
    # Calls and member calls
    # ------------------------------------------------------------------

    def function_value(self, fn):
        return self.functions[id(fn)]

    def class_type_global_value(self, name):
        # Class type identifiers aren't runtime values; this exists only to
        # produce clearer diagnostics if accidentally used.
        raise LLVMCodeGenError(f"class type '{name}' is not a runtime expression")

    def _ordered_args_for_ctor(self, class_name, args, local_types):
        fn = self._find_ctor(class_name, args, local_types)
        if fn is None:
            raise LLVMCodeGenError(f"no matching constructor for '{class_name}'")
        return self.semantic._ordered_call_args(args, fn.params, f"constructor '{class_name}'")

    def _find_ctor(self, class_name, args, local_types):
        candidates = [m for m in self.class_decls[class_name].methods if m.is_constructor]
        if not candidates:
            return None
        matches = []
        for m in candidates:
            try:
                ordered = self.semantic._ordered_call_args(args, m.params, f"constructor '{class_name}'")
                for arg, p in zip(ordered, m.params):
                    at = self.semantic.infer_type(arg, local_types)
                    self.semantic._check_assignable(p.type, at, f"constructor '{class_name}'", arg)
                matches.append(m)
            except Exception:
                pass
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            # Use the front-end's canonical constructor resolver for the
            # ambiguity/error wording.
            self.semantic.resolve_class_constructor_call(class_name, args, local_types)
        return None

    def emit_constructor(self, class_name, args, local_types):
        # Constructors are real LLVM functions and are fully built in
        # _build_class_ctor(). Calling that function keeps construction,
        # field initialization and inheritance in one place.
        ctor = self._find_ctor(class_name, args, local_types)
        key = ("ctor", class_name) if ctor is None else id(ctor)
        fn = self.functions[key]
        ordered = self.semantic._ordered_call_args(
            args,
            ctor.params if ctor is not None else [],
            f"constructor '{class_name}'",
        )
        vals = []
        params = ctor.params if ctor is not None else []
        for arg, param in zip(ordered, params):
            vals.append(
                self.cast_value_if_needed(
                    self.emit_expr(arg, local_types, param.type),
                    param.type,
                )
            )
        return self.current_state.builder.call(fn, vals)

    def emit_call_target(self, fn, args, local_types):
        ordered = self.semantic._ordered_call_args(args, fn.params, f"'{fn.name}'", fn.is_variadic)
        llvm_fn = self.function_value(fn)
        vals = []
        for arg, p in zip(ordered, fn.params):
            vals.append(self.cast_value_if_needed(self.emit_expr(arg, local_types, p.type), p.type))
        if fn.is_variadic:
            for arg in ordered[len(fn.params):]:
                vals.append(self.emit_expr(arg, local_types))
        return self.current_state.builder.call(llvm_fn, vals)

    def emit_call(self, call, local_types):
        # Validate first through the resolved front-end logic.
        self.semantic.infer_type(call, local_types)

        if self.semantic._is_reflection_call(call):
            raise LLVMCodeGenError("factory/reflection calls are not implemented in the LLVM backend yet")
        if self.semantic._is_reflection_member_exists_call(call) or self.semantic._is_reflection_set_member_call(call):
            raise LLVMCodeGenError("native reflection calls are not implemented in the LLVM backend yet")

        if isinstance(call.callee, Ident) and call.callee.name == "func" and self.semantic._decorator_call_target_name is not None:
            target = self.semantic._decorator_call_target_name
            args = [Ident(p.name) for p in self.semantic._decorator_target_params]
            candidates = self.groups.get((None, target), [])
            if len(candidates) != 1:
                raise LLVMCodeGenError(f"cannot resolve decorator target '{target}'")
            return self.emit_call_target(candidates[0], args, local_types)

        if isinstance(call.callee, Ident) and self.current_state.current_class:
            owner, method = self.semantic.resolve_class_method_call(
                self.current_state.current_class.name,
                call.callee.name,
                call.args,
                local_types,
                receiver_const=bool(self.current_state.current_class_method and self.current_state.current_class_method.is_const),
            )
            if method is not None:
                ordered = self.semantic._ordered_call_args(call.args, method.params, f"'{call.callee.name}'")
                obj = self.current_value("this")
                if owner.name != self.current_state.current_class.name:
                    while owner.name != self.current_state.current_class.name:
                        # Resolve from current class to owner base.
                        cur_cls = self.current_state.current_class
                        cur = obj
                        while cur_cls.name != owner.name:
                            if not cur_cls.base:
                                raise LLVMCodeGenError("cannot resolve base-class receiver")
                            cur = self.current_state.builder.gep(cur, [ir.Constant(I32, 0), ir.Constant(I32, 1)])
                            cur_cls = self.class_decls[cur_cls.base]
                        obj = cur
                        break
                argsv = [obj]
                for arg, p in zip(ordered, method.params):
                    argsv.append(self.cast_value_if_needed(self.emit_expr(arg, local_types, p.type), p.type))
                if method.is_virtual:
                    idx = self.class_vtable_methods[self.current_state.current_class.name].index(method)
                    vtname = self.current_state.current_class.name + "_vtable"
                    vtptr = self.current_state.builder.load(
                        self.current_state.builder.gep(obj, [ir.Constant(I32,0), ir.Constant(I32,0)]),
                        typ=self.type_cache[vtname].as_pointer(),
                    )
                    slot_fn = self.class_vtable_methods[self.current_state.current_class.name][idx]
                    slot_ty = ir.FunctionType(
                        self.llvm_type(slot_fn.ret_type),
                        [self.type_cache[self.current_state.current_class.name].as_pointer()] +
                        [self.llvm_type(p.type) for p in slot_fn.params],
                    ).as_pointer()
                    fptr = self.current_state.builder.load(
                        self.current_state.builder.gep(vtptr, [ir.Constant(I32,0), ir.Constant(I32,idx)]),
                        typ=slot_ty,
                    )
                    return self.current_state.builder.call(fptr, argsv)
                return self.current_state.builder.call(self.function_value(method), argsv)

        if isinstance(call.callee, MemberAccess):
            ot = self.semantic.infer_type(call.callee.obj, local_types)
            if isinstance(ot, str) and ot.endswith("*"):
                ot = ot.rstrip("*")
            gp = self._generic_parts(ot)
            if gp:
                raise LLVMCodeGenError("list/map/container/dynamic_list calls are not yet implemented by the LLVM backend")
            if ot == "string":
                obj = self.emit_expr(call.callee.obj, local_types)
                name = call.callee.name
                fn = self.string_runtime.get(name)
                if fn is None:
                    raise LLVMCodeGenError(f"unknown string member '{name}'")
                vals = [obj]
                params = list(fn.function_type.args)[1:]
                for a, pty in zip(call.args, params):
                    vals.append(self.emit_expr(a, local_types))
                return self.current_state.builder.call(fn, vals)

            if ot in self.class_decls:
                owner, method = self.semantic.resolve_class_method_call(
                    ot,
                    call.callee.name,
                    call.args,
                    local_types,
                    receiver_const=self.semantic._expr_is_const_receiver(call.callee.obj, local_types),
                )
                if method is None:
                    raise LLVMCodeGenError(f"cannot resolve method '{call.callee.name}' on '{ot}'")
                obj = self.emit_expr(call.callee.obj, local_types)
                ordered = self.semantic._ordered_call_args(call.args, method.params, f"'{call.callee.name}'")
                if owner.name != ot:
                    cur = obj
                    cur_cls = self.class_decls[ot]
                    while cur_cls.name != owner.name:
                        if not cur_cls.base:
                            raise LLVMCodeGenError("cannot resolve inherited receiver")
                        cur = self.current_state.builder.gep(cur, [ir.Constant(I32, 0), ir.Constant(I32, 1)])
                        cur_cls = self.class_decls[cur_cls.base]
                    obj = cur
                vals = [obj]
                for arg, p in zip(ordered, method.params):
                    vals.append(self.cast_value_if_needed(self.emit_expr(arg, local_types, p.type), p.type))
                if method.is_virtual:
                    idx = self.class_vtable_methods[ot].index(method)
                    vtname = self.current_state.current_class.name + "_vtable"
                    vtptr = self.current_state.builder.load(
                        self.current_state.builder.gep(obj, [ir.Constant(I32,0), ir.Constant(I32,0)]),
                        typ=self.type_cache[vtname].as_pointer(),
                    )
                    slot_fn = self.class_vtable_methods[self.current_state.current_class.name][idx]
                    slot_ty = ir.FunctionType(
                        self.llvm_type(slot_fn.ret_type),
                        [self.type_cache[self.current_state.current_class.name].as_pointer()] +
                        [self.llvm_type(p.type) for p in slot_fn.params],
                    ).as_pointer()
                    fptr = self.current_state.builder.load(
                        self.current_state.builder.gep(vtptr, [ir.Constant(I32,0), ir.Constant(I32,idx)]),
                        typ=slot_ty,
                    )
                    return self.current_state.builder.call(fptr, vals)
                return self.current_state.builder.call(self.function_value(method), vals)

        if isinstance(call.callee, NamespacedIdent) and call.callee.namespace == "factory" and call.callee.name == "construct":
            raise LLVMCodeGenError("factory:construct() requires the native reflection runtime and is not implemented yet")

        # Built-in string constructor.
        if isinstance(call.callee, Ident) and call.callee.name == "string":
            if call.args:
                raise LLVMCodeGenError("string() takes no arguments")
            return self.current_state.builder.call(self.string_runtime["ctor"], [])

        # System/Jaguar runtime builtins.
        builtin = self.system_builtin(call)
        if builtin is not None:
            return builtin

        fn = self.semantic.resolve_call_target(call, local_types)
        if fn is not None:
            return self.emit_call_target(fn, call.args, local_types)

        # Function pointer call.
        callee_ty = self.semantic.infer_type(call.callee, local_types)
        fp = _function_type_parts(callee_ty)
        if fp:
            params, ret = fp
            fixed = params[:-1] if params and params[-1] == "..." else params
            callee = self.emit_expr(call.callee, local_types)
            args = [
                self.cast_value_if_needed(self.emit_expr(a, local_types, p), p)
                for a, p in zip(call.args, fixed)
            ]
            args += [self.emit_expr(a, local_types) for a in call.args[len(fixed):]]
            typed = callee
            return self.current_state.builder.call(typed, args)

        # Class/struct constructor calls written without `new`.
        if isinstance(call.callee, Ident):
            cname = self.semantic._resolve_class_name(call.callee.name)
            if cname:
                ordered = self._ordered_args_for_ctor(cname, call.args, local_types)
                return self.emit_constructor(cname, ordered, local_types)
            sname = self.semantic._resolve_struct_name(call.callee.name)
            if sname:
                args = call.args
                st = self.type_cache[sname]
                if not args:
                    return ir.Constant(st, None)
                vals = []
                for a, f in zip(args, self.struct_decls[sname].fields):
                    vals.append(self.cast_value_if_needed(self.emit_expr(a, local_types, f.type), f.type))
                return ir.Constant(st, vals)

        raise LLVMCodeGenError(f"cannot lower call expression '{call.callee}'")

    def system_builtin(self, call):
        if not isinstance(call.callee, NamespacedIdent):
            return None
        key = (call.callee.namespace, call.callee.name)
        b = self.current_state.builder

        if key == ("sys", "print"):
            if len(call.args) != 1:
                raise LLVMCodeGenError("sys:print expects one argument")
            arg = call.args[0]
            at = self.semantic.infer_type(arg, self.current_state.local_types)
            v = self.emit_expr(arg, self.current_state.local_types)
            fmt = self._format_for_type(at)
            format_ptr = self.c_string_global(fmt)
            vals = [format_ptr]
            if at == "string":
                vals.append(self.string_data(b, v))
            elif at == "bool":
                vals.append(v)
            else:
                vals.append(v)
            b.call(self.runtime["printf"], vals)
            return ir.Constant(I32, 0)

        if key == ("jcc", "exit"):
            v = self.emit_expr(call.args[0], self.current_state.local_types, "i32")
            b.call(self.runtime["exit"], [self.cast_value_if_needed(v, "i32")])
            return ir.Constant(I32, 0)

        if key == ("jcc", "abort"):
            b.call(self.runtime["abort"], [])
            return ir.Constant(I32, 0)

        math_names = {
            "sqrt":"sqrt","pow":"pow","sin":"sin","cos":"cos","tan":"tan","asin":"asin","acos":"acos","atan":"atan","floor":"floor","ceil":"ceil","round":"round","log":"log","log10":"log10","exp":"exp","fmod":"fmod"
        }
        if key[0] == "jcc" and key[1] in math_names:
            fn = self.runtime[math_names[key[1]]]
            vals = [self.cast_value_if_needed(self.emit_expr(a, self.current_state.local_types), "f64") for a in call.args]
            return b.call(fn, vals)

        if key == ("jcc", "abs_i32"):
            x = self.cast_value_if_needed(self.emit_expr(call.args[0], self.current_state.local_types), "i32")
            zero = ir.Constant(I32, 0)
            neg = b.icmp_signed("<", x, zero)
            return b.select(neg, b.neg(x), x)

        if key in (("jcc","min_i32"), ("jcc","max_i32"), ("jcc","clamp_i32")):
            vals = [self.cast_value_if_needed(self.emit_expr(a, self.current_state.local_types), "i32") for a in call.args]
            if key[1] == "min_i32":
                cond = b.icmp_signed("<", vals[0], vals[1]); return b.select(cond, vals[0], vals[1])
            if key[1] == "max_i32":
                cond = b.icmp_signed(">", vals[0], vals[1]); return b.select(cond, vals[0], vals[1])
            lo = b.icmp_signed("<", vals[0], vals[1])
            hi = b.icmp_signed(">", vals[0], vals[2])
            x = b.select(lo, vals[1], vals[0])
            return b.select(hi, vals[2], x)

        if key == ("jcc", "assert"):
            cond = self.emit_expr(call.args[0], self.current_state.local_types, "bool")
            good = self.current_state.function.append_basic_block("assert.ok")
            bad = self.current_state.function.append_basic_block("assert.fail")
            cont = self.current_state.function.append_basic_block("assert.cont")
            b.cbranch(cond, good, bad)
            b.position_at_end(bad)
            msg = self.emit_expr(call.args[1], self.current_state.local_types, "string")
            fmt = self.c_string_global("Jaguar assertion failed: %s\\n")
            b.call(self.runtime["printf"], [fmt, self.string_data(b, msg)])
            b.call(self.runtime["abort"], [])
            b.unreachable()
            b.position_at_end(good)
            b.branch(cont)
            b.position_at_end(cont)
            return ir.Constant(I32, 0)

        return None

    def _format_for_type(self, t):
        if t == "string": return "%s\n"
        if t == "bool": return "%s\n"
        if t in ("f32","float","f64","double"): return "%g\n"
        if t in ("u8","u16","u32","u64"): return "%llu\n"
        if t in ("i64","long"): return "%lld\n"
        return "%d\n"

    def c_string_global(self, text):
        raw = text.encode("utf-8") + b"\0"
        arr = ir.ArrayType(I8, len(raw))
        name = f".jcstr.{self._string_id}"
        self._string_id += 1
        gv = ir.GlobalVariable(self.module, arr, name)
        gv.linkage = "private"
        gv.unnamed_addr = True
        gv.global_constant = True
        gv.initializer = ir.Constant(arr, [ir.Constant(I8, x) for x in raw])
        return gv.gep([ir.Constant(I32,0),ir.Constant(I32,0)])

    def string_member_value(self, name, obj):
        b = self.current_state.builder
        fn = self.string_runtime.get(name)
        if fn is None:
            raise LLVMCodeGenError(f"unknown string member '{name}'")
        if name in ("length","empty","to_upper","to_lower"):
            return b.call(fn,[obj])
        raise LLVMCodeGenError(f"'{name}' is a method, not a value")

    def emit_logical(self, e, local_types):
        b = self.current_state.builder
        lhs = self.emit_expr(e.left, local_types, "bool")
        rhsbb = self.current_state.function.append_basic_block("logical.rhs")
        endbb = self.current_state.function.append_basic_block("logical.end")
        if e.op == "&&":
            b.cbranch(lhs, rhsbb, endbb)
            b.position_at_end(endbb)
            # Temporarily create a phi after putting a builder in rhs.
            rhs_block = rhsbb
            b.position_at_end(rhs_block)
            rhs = self.emit_expr(e.right, local_types, "bool")
            b.branch(endbb)
            b.position_at_end(endbb)
            phi = b.phi(I1)
            phi.add_incoming(ir.Constant(I1, 0), self._previous_block_before(endbb))
            phi.add_incoming(rhs, rhs_block)
            return phi
        else:
            b.cbranch(lhs, endbb, rhsbb)
            left_block = b.block
            b.position_at_end(rhsbb)
            rhs = self.emit_expr(e.right, local_types, "bool")
            b.branch(endbb)
            b.position_at_end(endbb)
            phi = b.phi(I1)
            phi.add_incoming(ir.Constant(I1, 1), left_block)
            phi.add_incoming(rhs, rhsbb)
            return phi

    def _previous_block_before(self, block):
        # Logical helper: choose the predecessor ending in the branch to block.
        for bb in self.current_state.function.blocks:
            if bb.terminator is not None and hasattr(bb.terminator, "operands"):
                if block in bb.terminator.operands:
                    return bb
        return self.current_state.function.entry_basic_block

    def cast_value_if_needed(self, v, target_type):
        if target_type is None or _is_literal_type(target_type):
            return v
        return self.cast_value(v, self.llvm_type(target_type), target_type)

    # ------------------------------------------------------------------
    # Statement lowering
    # ------------------------------------------------------------------

    def emit_stmt(self, s, local_types):
        b = self.current_state.builder

        if isinstance(s, VarDecl):
            if s.type == "auto":
                inferred = self.semantic._resolve_auto_type(s.init, local_types)
                s_type = inferred
            else:
                s_type = s.type
            ptr = self.alloca_entry(s.name, self.llvm_type(s_type))
            self.current_state.allocas[s.name] = ptr
            self.current_state.local_types[s.name] = s_type
            local_types[s.name] = s_type
            if s.init is not None:
                v = self.emit_expr(s.init, local_types, s_type)
                b.store(self.cast_value_if_needed(v, s_type), ptr)
            else:
                b.store(ir.Constant(self.llvm_type(s_type), None), ptr)
            return

        if isinstance(s, AssignStmt):
            if s.name not in local_types and not self._resolve_global(s.name):
                if self.current_state.current_class:
                    owner, field = self.semantic._find_class_member(self.current_state.current_class.name, s.name, "field")
                    if field:
                        target = MemberAssignStmt(MemberAccess(Ident("this"), s.name), s.expr)
                        self.emit_stmt(target, local_types)
                        return
                raise LLVMCodeGenError(f"assignment to undeclared variable '{s.name}'")
            target_t = local_types.get(s.name, self.semantic.global_types.get(s.name))
            v = self.emit_expr(s.expr, local_types, target_t)
            self.current_state.builder.store(self.cast_value_if_needed(v, target_t), self.current_lvalue(s.name))
            return

        if isinstance(s, PointerAssignStmt):
            ptr = self.emit_lvalue(s.target, local_types)
            target_t = self.semantic.infer_type(s.target, local_types)
            v = self.emit_expr(s.expr, local_types, target_t)
            b.store(self.cast_value_if_needed(v, target_t), ptr)
            return

        if isinstance(s, MemberAssignStmt):
            target_t = self.semantic.infer_type(s.target, local_types)
            ptr = self.emit_lvalue(s.target, local_types)
            v = self.emit_expr(s.expr, local_types, target_t)
            b.store(self.cast_value_if_needed(v, target_t), ptr)
            return

        if isinstance(s, ExprStmt):
            self.emit_expr(s.expr, local_types)
            return

        if isinstance(s, ReturnStmt):
            if s.expr is None:
                if self.current_state.current_return_type == "void":
                    b.ret_void()
                else:
                    if self._is_special_main_state():
                        b.ret(ir.Constant(I32,0))
                    else:
                        raise LLVMCodeGenError(f"non-void function requires a return value of '{self.current_state.current_return_type}'")
            else:
                v = self.emit_expr(s.expr, local_types, self.current_state.current_return_type)
                b.ret(self.cast_value_if_needed(v, self.current_state.current_return_type))
            return

        if isinstance(s, IfStmt):
            self.emit_if(s, local_types)
            return

        if isinstance(s, WhileStmt):
            self.emit_while(s, local_types)
            return

        if isinstance(s, LoopStmt):
            self.emit_loop(s, local_types)
            return

        if isinstance(s, ForLoopStmt):
            self.emit_for_loop(s, local_types)
            return

        if isinstance(s, BreakStmt):
            if not self.current_state.loop_stack:
                raise LLVMCodeGenError("break used outside of a loop")
            b.branch(self.current_state.loop_stack[-1].break_block)
            return

        if isinstance(s, ContinueStmt):
            if not self.current_state.loop_stack:
                raise LLVMCodeGenError("continue used outside of a loop")
            b.branch(self.current_state.loop_stack[-1].continue_block)
            return

        if isinstance(s, VariableChangeHandler):
            self.current_state.signal_handlers[s.name] = s.body
            return

        if isinstance(s, CollectionLoopStmt):
            raise LLVMCodeGenError("collection loops are not yet supported by the LLVM backend")

        raise LLVMCodeGenError(f"unsupported statement node {type(s).__name__}")

    def _emit_block(self, block, local_types):
        for s in block.statements:
            if self.current_state.builder.block.terminator is not None:
                break
            self.emit_stmt(s, local_types)

    def emit_if(self, s, local_types):
        b = self.current_state.builder
        cond = self.emit_condition(s.cond, local_types)
        thenbb = self.current_state.function.append_basic_block("if.then")
        elsebb = self.current_state.function.append_basic_block("if.else")
        endbb = self.current_state.function.append_basic_block("if.end")
        b.cbranch(cond, thenbb, elsebb)
        b.position_at_end(thenbb)
        self._emit_block(s.then_block, dict(local_types))
        if b.block.terminator is None: b.branch(endbb)
        b.position_at_end(elsebb)
        if isinstance(s.else_branch, IfStmt):
            self.emit_if(s.else_branch, dict(local_types))
            if b.block.terminator is None: b.branch(endbb)
        elif isinstance(s.else_branch, Block):
            self._emit_block(s.else_branch, dict(local_types))
            if b.block.terminator is None: b.branch(endbb)
        else:
            b.branch(endbb)
        if b.block.terminator is None:
            b.position_at_end(endbb)
        else:
            b.position_at_end(endbb)

    def emit_condition(self, e, local_types):
        v = self.emit_expr(e, local_types)
        if isinstance(v.type, ir.IntType) and v.type.width == 1:
            return v
        if isinstance(v.type, ir.PointerType):
            return self.current_state.builder.icmp_unsigned("!=", v, ir.Constant(v.type, None))
        raise LLVMCodeGenError("condition must be bool or pointer")

    def emit_while(self, s, local_types):
        b = self.current_state.builder
        head = self.current_state.function.append_basic_block("while.head")
        body = self.current_state.function.append_basic_block("while.body")
        end = self.current_state.function.append_basic_block("while.end")
        b.branch(head)
        b.position_at_end(head)
        cond = self.emit_condition(s.cond, local_types)
        b.cbranch(cond, body, end)
        b.position_at_end(body)
        self.current_state.loop_stack.append(_LoopContext(end, head))
        self._emit_block(s.body, dict(local_types))
        self.current_state.loop_stack.pop()
        if b.block.terminator is None: b.branch(head)
        b.position_at_end(end)

    def emit_loop(self, s, local_types):
        b = self.current_state.builder
        head = self.current_state.function.append_basic_block("loop.head")
        end = self.current_state.function.append_basic_block("loop.end")
        b.branch(head)
        b.position_at_end(head)
        self.current_state.loop_stack.append(_LoopContext(end, head))
        self._emit_block(s.body, dict(local_types))
        self.current_state.loop_stack.pop()
        if b.block.terminator is None: b.branch(head)
        b.position_at_end(end)

    def emit_for_loop(self, s, local_types):
        b = self.current_state.builder
        ptr = self.alloca_entry(s.var_name, self.llvm_type(s.var_type))
        start = self.emit_expr(s.start, local_types, s.var_type)
        endv = self.emit_expr(s.end, local_types, s.var_type)
        b.store(self.cast_value_if_needed(start, s.var_type), ptr)
        body_types = dict(local_types)
        body_types[s.var_name] = s.var_type
        old_local_type = self.current_state.local_types.get(s.var_name)
        self.current_state.local_types[s.var_name] = s.var_type

        head = self.current_state.function.append_basic_block("for.head")
        body = self.current_state.function.append_basic_block("for.body")
        inc = self.current_state.function.append_basic_block("for.inc")
        end = self.current_state.function.append_basic_block("for.end")
        b.branch(head)
        b.position_at_end(head)
        cur = b.load(ptr)
        cmp = b.icmp_signed("<=", cur, self.cast_value_if_needed(endv, s.var_type))
        b.cbranch(cmp, body, end)
        b.position_at_end(body)
        old = self.current_state.allocas.get(s.var_name)
        self.current_state.allocas[s.var_name] = ptr
        self.current_state.loop_stack.append(_LoopContext(end, inc))
        self._emit_block(s.body, body_types)
        self.current_state.loop_stack.pop()
        if b.block.terminator is None: b.branch(inc)
        b.position_at_end(inc)
        cur = b.load(ptr)
        one = ir.Constant(self.llvm_type(s.var_type), 1)
        b.store(b.add(cur, one), ptr)
        b.branch(head)
        self.current_state.allocas.pop(s.var_name, None)
        if old is not None:
            self.current_state.allocas[s.var_name] = old
        if old_local_type is not None:
            self.current_state.local_types[s.var_name] = old_local_type
        else:
            self.current_state.local_types.pop(s.var_name, None)
        b.position_at_end(end)

    # ------------------------------------------------------------------
    # Function generation
    # ------------------------------------------------------------------

    def _is_special_main_state(self):
        fn = self.current_state.function
        return fn.name == "main"

    def build(self):
        # Reject / flag a few features for which the LLVM ABI is not yet
        # defined rather than silently producing incorrect code.
        for item in self.program.items:
            if isinstance(item, FunctionDecl) and item.decorators:
                raise LLVMCodeGenError(
                    "decorators are not yet lowered by jcc-llvm.py; use jcc-c.py for decorated functions"
                )
            if isinstance(item, (UsingImportDecl, UsingNamespaceDecl, UsingSymbolDecl, TypeAliasDecl, ForwardDecl)):
                continue

        # Main stream: structs/unions/enums have already been declared.
        for item in self.program.items:
            if isinstance(item, FunctionDecl) and not item.is_prototype:
                self._build_function_body(item)
        for cls in self.class_decls.values():
            self._build_class(cls)
        # Global constructors are already materialized.
        return str(self.module)

    def _build_function_body(self, fn):
        llvm_fn = self.functions[id(fn)]
        if fn.is_extern or fn.is_prototype:
            return

        entry = llvm_fn.append_basic_block("entry")
        state = _FunctionState(llvm_fn, ir.IRBuilder(entry))
        self._set_function_state(state)

        if self._is_special_main(fn):
            if len(fn.params) == 1:
                p0 = llvm_fn.args[1]
                # llvmlite uses opaque pointers on recent LLVM versions;
                # cast argv to i8** before indexing argv[1].
                argv_ty = I8.as_pointer().as_pointer()
                p0_typed = state.builder.inttoptr(
                    state.builder.ptrtoint(p0, I64), argv_ty
                )
                # Jaguar's main(string) receives argv[1], empty string when
                # argc <= 1.
                empty = self.string_literal('""')
                has = state.builder.icmp_signed(">", llvm_fn.args[0], ir.Constant(I32, 1))
                yes = llvm_fn.append_basic_block("argv.yes")
                no = llvm_fn.append_basic_block("argv.no")
                join = llvm_fn.append_basic_block("argv.join")
                state.builder.cbranch(has, yes, no)
                state.builder.position_at_end(yes)
                argv1ptr = state.builder.gep(p0_typed, [ir.Constant(I64, 1)])
                cstr = state.builder.load(argv1ptr)
                s = state.builder.call(self.string_runtime["from_cstr"], [cstr])
                state.builder.branch(join)
                state.builder.position_at_end(no)
                state.builder.branch(join)
                state.builder.position_at_end(join)
                phi = state.builder.phi(self.string_type.as_pointer())
                phi.add_incoming(s, yes)
                phi.add_incoming(empty, no)
                ptr = self.alloca_entry(fn.params[0].name, self.string_type.as_pointer())
                state.allocas[fn.params[0].name] = ptr
                state.local_types[fn.params[0].name] = "string"
                state.builder.store(phi, ptr)
        else:
            for arg, p in zip(llvm_fn.args, fn.params):
                ptr = self.alloca_entry(p.name, self.llvm_type(p.type))
                state.allocas[p.name] = ptr
                state.local_types[p.name] = p.type
                state.builder.store(arg, ptr)

        state.current_return_type = fn.ret_type
        state.readonly = {p.name for p in fn.params if p.is_const}
        self._emit_block(fn.body, state.local_types)
        self._ensure_block_terminated(fn.ret_type if not self._is_special_main_state() else "int")
        self._restore_semantic()

    def _build_class(self, cls):
        # Methods.
        for m in cls.methods:
            if m.is_constructor or m.is_destructor:
                continue
            self._build_class_method(cls, m)
        # Constructor/destructor bodies.
        ctors = [m for m in cls.methods if m.is_constructor]
        if ctors:
            for m in ctors:
                self._build_class_ctor(cls, m)
        else:
            self._build_class_ctor(cls, None)
        destr = next((m for m in cls.methods if m.is_destructor), None)
        self._build_class_destr(cls, destr)

    def _build_class_method(self, cls, m):
        fn = self.functions[id(m)]
        entry = fn.append_basic_block("entry")
        state = _FunctionState(fn, ir.IRBuilder(entry))
        state.current_class = cls
        state.current_class_method = m
        state.current_return_type = m.ret_type
        self._set_function_state(state)
        self.semantic._current_class = cls
        this_ptr = self.alloca_entry("this", self.type_cache[cls.name].as_pointer())
        state.allocas["this"] = this_ptr
        state.local_types["this"] = cls.name
        state.builder.store(fn.args[0], this_ptr)
        for arg, p in zip(fn.args[1:], m.params):
            ptr = self.alloca_entry(p.name, self.llvm_type(p.type))
            state.allocas[p.name] = ptr
            state.local_types[p.name] = p.type
            state.builder.store(arg, ptr)
        self._emit_block(m.body, state.local_types)
        self._ensure_block_terminated(m.ret_type)
        self._restore_semantic()

    def _build_class_ctor(self, cls, ctor):
        key = ("ctor", cls.name) if ctor is None else id(ctor)
        fn = self.functions[key]
        entry = fn.append_basic_block("entry")
        state = _FunctionState(fn, ir.IRBuilder(entry))
        state.current_class = cls
        state.current_class_method = ctor
        state.current_return_type = cls.name
        self._set_function_state(state)

        raw = state.builder.call(self.runtime["calloc"], [
            ir.Constant(I64, 1),
            self.sizeof_type(self.type_cache[cls.name]),
        ])
        obj = self.typed_ptr_from_opaque(raw, self.type_cache[cls.name])
        state.builder.store(self.class_vtables[cls.name], state.builder.gep(obj, [ir.Constant(I32,0), ir.Constant(I32,0)]))

        if ctor is not None:
            for arg, p in zip(fn.args, ctor.params):
                ptr = self.alloca_entry(p.name, self.llvm_type(p.type))
                state.allocas[p.name] = ptr
                state.local_types[p.name] = p.type
                state.builder.store(arg, ptr)

        # Store object in `this` and run field initializers/body.
        this_ptr = self.alloca_entry("this", self.type_cache[cls.name].as_pointer())
        state.allocas["this"] = this_ptr
        state.local_types["this"] = cls.name
        state.builder.store(obj, this_ptr)
        for i, f in enumerate(cls.fields):
            if f.init is not None:
                ptr = state.builder.gep(obj, [ir.Constant(I32,0), ir.Constant(I32,1 + (1 if cls.base else 0) + i)])
                v = self.emit_expr(f.init, state.local_types, f.type)
                state.builder.store(self.cast_value_if_needed(v, f.type), ptr)
        if ctor is not None:
            self._emit_block(ctor.body, state.local_types)
        if state.builder.block.terminator is None:
            state.builder.ret(obj)
        self._restore_semantic()

    def _build_class_destr(self, cls, destr):
        fn = self.functions[("destr", cls.name)]
        entry = fn.append_basic_block("entry")
        state = _FunctionState(fn, ir.IRBuilder(entry))
        state.current_class = cls
        state.current_class_method = None
        state.current_return_type = "void"
        self._set_function_state(state)
        this_ptr = self.alloca_entry("this", self.type_cache[cls.name].as_pointer())
        state.allocas["this"] = this_ptr
        state.local_types["this"] = cls.name
        state.builder.store(fn.args[0], this_ptr)
        if destr is not None:
            self._emit_block(destr.body, state.local_types)
        # Clean owned fields.
        for f in reversed(cls.fields):
            if f.type == "string":
                p = state.builder.gep(fn.args[0], [ir.Constant(I32, 0), ir.Constant(I32, 1 + (1 if cls.base else 0) + cls.fields.index(f))])
                s = state.builder.load(p)
                state.builder.call(self.string_runtime["destr"], [s])
            elif isinstance(f.type, str) and f.type in self.class_decls:
                p = state.builder.gep(fn.args[0], [ir.Constant(I32, 0), ir.Constant(I32, 1 + (1 if cls.base else 0) + cls.fields.index(f))])
                obj = state.builder.load(p)
                null = state.builder.icmp_unsigned("!=", obj, ir.Constant(obj.type, None))
                bb = fn.append_basic_block("field.destroy")
                done = fn.append_basic_block("field.done")
                state.builder.cbranch(null, bb, done)
                state.builder.position_at_end(bb)
                state.builder.call(self.functions[("destr", f.type)], [obj])
                state.builder.call(self.runtime["free"], [obj])
                state.builder.branch(done)
                state.builder.position_at_end(done)
        if cls.base:
            baseptr = state.builder.gep(fn.args[0], [ir.Constant(I32,0), ir.Constant(I32,1)])
            state.builder.call(self.functions[("destr", cls.base)], [baseptr])
        state.builder.ret_void()
        self._restore_semantic()

    # ------------------------------------------------------------------
    # Fields / vtables
    # ------------------------------------------------------------------

    def _field_index(self, owner, name):
        for i, f in enumerate(owner.fields):
            if f.name == name:
                return i + 1 + (1 if owner.base else 0)
        raise LLVMCodeGenError(f"unknown field '{owner.name}.{name}'")

    def _class_field_index(self, clsname, name):
        cls = self.class_decls[clsname]
        return self._field_index(cls, name)

    def _class_vtable_index(self, clsname, method):
        methods = self.class_vtable_methods[clsname]
        for i, m in enumerate(methods):
            if m.name == method.name and [p.type for p in m.params] == [p.type for p in method.params]:
                return i
        raise LLVMCodeGenError(f"virtual method '{method.name}' has no vtable slot")

    def _union_field_ptr(self, obj, union_name, field_name):
        b = self.current_state.builder
        # All union fields start at byte zero.
        base = b.bitcast(obj, PTR)
        return base

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def _const_ptr(self, p):
        return ir.Constant(p.type, None)

    def _is_special_main_function(self, fn):
        return fn.name == "main" and not fn.is_extern and len(fn.params) in (0,1)

    def validate(self):
        try:
            text = str(self.module)
            mod = llvm.parse_assembly(text)
            mod.verify()
        except Exception as exc:
            raise LLVMCodeGenError(f"generated LLVM IR is invalid: {exc}") from exc


def generate_llvm_from_ir_text(text, verify=False, target_triple=None):
    ir_data = jcc.deserialize_ir(text)
    program = jcc.program_from_ir(ir_data)
    groups = jcc.groups_from_program(program)
    gen = LLVMCodeGen(program, groups, target_triple=target_triple)
    out = gen.build()
    if verify:
        gen.validate()
    return out


def generate_llvm(source, verify=False, target_triple=None):
    ir_text = jcc.transpile(source)
    return generate_llvm_from_ir_text(ir_text, verify=verify, target_triple=target_triple)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Jaguar IR -> LLVM IR backend")
    ap.add_argument("input", help="Jaguar IR (.jir), or '-' for stdin")
    ap.add_argument("-o", "--output", help="output LLVM IR file; stdout when omitted")
    ap.add_argument("--verify", action="store_true", help="parse and verify the emitted LLVM IR")
    ap.add_argument("--target-triple", help="override LLVM target triple")
    args = ap.parse_args(argv)

    try:
        if args.input == "-":
            ir_text = sys.stdin.read()
        else:
            ir_text = Path(args.input).read_text(encoding="utf-8")
        output = generate_llvm_from_ir_text(
            ir_text,
            verify=args.verify,
            target_triple=args.target_triple,
        )
    except (OSError, ValueError, LLVMCodeGenError) as exc:
        print(f"jcc-llvm: error: {exc}", file=sys.stderr)
        return 1

    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
    else:
        sys.stdout.write(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
