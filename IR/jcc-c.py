#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
jcc-c.py — Backend Jaguar IR -> C

Ce fichier ne parse pas le langage Jaguar. Il consomme exclusivement l'IR
produit par jcc.py, puis reprend la génération C existante sans modification
de sa logique de traduction.

Usage :
    python3 jcc.py mon_fichier.ja -o mon_fichier.jir
    python3 jcc-c.py mon_fichier.jir              # C sur stdout
    python3 jcc-c.py mon_fichier.jir -o out       # C + runtime + GCC
    python3 jcc-c.py mon_fichier.jir --emit-c     # C/runtimes sans GCC
"""

import sys
import os
import re
import subprocess
from pathlib import Path

import jcc
from jcc import *
from jcc import (
    _OPERATOR_FUNCTION_TOKENS,
    _iter_stmts,
)


# =========================================================================
# 5. OUTILS SPÉCIFIQUES AU BACKEND C
# =========================================================================

BUILTIN_TYPEDEFS: Dict[str, str] = {
    "bool": "typedef unsigned char _jBool;",
    "i8":   "typedef signed char i8;",
    "u8":   "typedef unsigned char u8;",
    "i16":  "typedef short i16;",
    "u16":  "typedef unsigned short u16;",
    "i32":  "typedef int i32;",
    "u32":  "typedef unsigned int u32;",
    "i64":  "typedef long long i64;",
    "u64":  "typedef unsigned long long u64;",
    "f32":  "typedef float f32;",
    "f64":  "typedef double f64;",
    "string": "typedef struct _jString { size_t length; unsigned char literal; char data[]; } string;",
}
ORDERED_BUILTIN_TYPES = list(BUILTIN_TYPEDEFS.keys())

C_TYPE_NAMES: Dict[str, str] = {
    "i8": "int8_t",
    "u8": "uint8_t",
    "i16": "int16_t",
    "u16": "uint16_t",
    "i32": "int32_t",
    "u32": "uint32_t",
    "i64": "int64_t",
    "u64": "uint64_t",
    "f32": "float",
    "f64": "double",
    "bool": "_jBool",
    "string": "string *",
}


def c_type(jaguar_type: str) -> str:
    if not isinstance(jaguar_type, str):
        return jaguar_type
    depth = len(jaguar_type) - len(jaguar_type.rstrip("*"))
    base = jaguar_type.rstrip("*")
    mapped = C_TYPE_NAMES.get(base, base)
    return mapped + (" *" * depth) if depth else mapped


def _function_type_parts(jaguar_type: str):
    if not isinstance(jaguar_type, str) or not jaguar_type.startswith("fn("):
        return None
    close = jaguar_type.rfind(") -> ")
    if close < 0:
        return None
    inner = jaguar_type[3:close]
    ret = jaguar_type[close + 5:].strip()
    return jcc._split_type_list(inner), ret


def _c_function_pointer_decl(jaguar_type: str, name: str) -> str | None:
    parts = _function_type_parts(jaguar_type)
    if parts is None:
        return None
    params, ret = parts
    p = ", ".join(c_type(x) for x in params) if params else "void"
    return f"{c_type(ret)} (*{name})({p})"

# =========================================================================
# 5. GÉNÉRATEUR DE CODE C
# =========================================================================

class CodeGenError(Exception):
    pass


# =========================================================================
# 5a. BIBLIOTHÈQUE SYSTÈME INTÉGRÉE
# =========================================================================
#
# Les fonctions sys:* sont des primitives du langage, dans le même esprit
# que les fonctions de la libc. Elles ne doivent donc pas être déclarées par
# l'utilisateur : le compilateur les traduit directement vers un petit
# runtime C embarqué, et n'émet que les morceaux réellement utilisés.
#
# API Jaguar :
#   sys:print(string)                         -> void
#   sys:console:set_color(string)             -> void
#   sys:console:reset_color()                 -> void
#   sys:execute(string program, string path)  -> int
#   sys:fs:read(string path)                  -> string
#   sys:fs:write(string path, string data)    -> void
#
# `sys:console:set_color` attend une séquence ANSI (par ex. "\\033[31m").
# Le deuxième argument de sys:execute est le répertoire de travail.

SYSTEM_BUILTINS = {
    ("thread", "start"): ("_j_thread_start", 1, "void*"),
    ("thread", "join"): ("_j_thread_join", 1, "void"),
    ("thread", "detach"): ("_j_thread_detach", 1, "void"),
    ("thread", "sleep"): ("_j_thread_sleep", 1, "void"),
    ("thread", "yield"): ("_j_thread_yield", 0, "void"),
    ("sys", "print"): ("_j_sys_print", 1, "void"),
    ("sys:console", "set_color"): ("_j_sys_console_set_color", 1, "void"),
    ("sys:console", "reset_color"): ("_j_sys_console_reset_color", 0, "void"),
    ("sys", "execute"): ("_j_sys_execute", 2, "int"),
    ("sys:fs", "read"): ("_j_sys_fs_read", 1, "string"),
    ("sys:fs", "write"): ("_j_sys_fs_write", 2, "void"),

    # jcc = bibliothèque standard JaguarCC.
    # Les fonctions volontairement exposées ici sont les fonctions libc
    # courantes qui restent simples et sûres sans demander de pointeurs.
    ("jcc", "exit"): ("_j_lib_exit", 1, "void"),
    ("jcc", "abort"): ("_j_lib_abort", 0, "void"),
    ("jcc", "abs_i32"): ("_j_lib_abs_i32", 1, "i32"),
    ("jcc", "min_i32"): ("_j_lib_min_i32", 2, "i32"),
    ("jcc", "max_i32"): ("_j_lib_max_i32", 2, "i32"),
    ("jcc", "clamp_i32"): ("_j_lib_clamp_i32", 3, "i32"),
    ("jcc", "random_i32"): ("_j_lib_random_i32", 2, "i32"),
    ("jcc", "time_ms"): ("_j_lib_time_ms", 0, "i64"),
    ("jcc", "assert"): ("_j_lib_assert", 2, "void"),

    # Math / stdlib.h + math.h
    ("jcc", "sqrt"): ("_j_lib_sqrt", 1, "f64"),
    ("jcc", "pow"): ("_j_lib_pow", 2, "f64"),
    ("jcc", "sin"): ("_j_lib_sin", 1, "f64"),
    ("jcc", "cos"): ("_j_lib_cos", 1, "f64"),
    ("jcc", "tan"): ("_j_lib_tan", 1, "f64"),
    ("jcc", "asin"): ("_j_lib_asin", 1, "f64"),
    ("jcc", "acos"): ("_j_lib_acos", 1, "f64"),
    ("jcc", "atan"): ("_j_lib_atan", 1, "f64"),
    ("jcc", "atan2"): ("_j_lib_atan2", 2, "f64"),
    ("jcc", "floor"): ("_j_lib_floor", 1, "f64"),
    ("jcc", "ceil"): ("_j_lib_ceil", 1, "f64"),
    ("jcc", "round"): ("_j_lib_round", 1, "f64"),
    ("jcc", "log"): ("_j_lib_log", 1, "f64"),
    ("jcc", "log10"): ("_j_lib_log10", 1, "f64"),
    ("jcc", "exp"): ("_j_lib_exp", 1, "f64"),
    ("jcc", "fmod"): ("_j_lib_fmod", 2, "f64"),

    # Les opérations sur string sont exclusivement des fonctions membres de la classe native string.

    # ctype.h
    ("jcc", "is_digit"): ("_j_lib_is_digit", 1, "bool"),
    ("jcc", "is_alpha"): ("_j_lib_is_alpha", 1, "bool"),
    ("jcc", "is_alnum"): ("_j_lib_is_alnum", 1, "bool"),
    ("jcc", "is_space"): ("_j_lib_is_space", 1, "bool"),
    ("jcc", "is_upper"): ("_j_lib_is_upper", 1, "bool"),
    ("jcc", "is_lower"): ("_j_lib_is_lower", 1, "bool"),
    ("jcc", "to_upper_char"): ("_j_lib_to_upper_char", 1, "i32"),
    ("jcc", "to_lower_char"): ("_j_lib_to_lower_char", 1, "i32"),

    # Fichiers / environnement : API valeur-only, donc pas de FILE*/char*.
    ("jcc", "file_exists"): ("_j_lib_file_exists", 1, "bool"),
    ("jcc", "remove_file"): ("_j_lib_remove_file", 1, "bool"),
    ("jcc", "rename_file"): ("_j_lib_rename_file", 2, "bool"),
    ("jcc", "env_get"): ("_j_lib_env_get", 1, "string"),
}


def _system_runtime(used, used_string=False):
    """Retourne le runtime C nécessaire aux primitives sys:* utilisées."""
    if not used and not used_string:
        return ""

    lines = [
        "/* Jaguar system library runtime (generated automatically). */",
        "#include <stdio.h>",
        "#include <stdlib.h>",
        "#include <string.h>",
        "#include <stddef.h>",
    ]

    if used_string:
        lines += [
            "",
            "static string *string_alloc(size_t length) {",
            "    string *s = (string *)malloc(sizeof(string) + length + 1);",
            "    if (!s) return 0;",
            "    s->length = length;",
            "    s->data[length] = '\\0';",
            "    return s;",
            "}",
            "static string *string_from_cstr(const char *src) {",
            "    string *s; size_t length;",
            "    if (!src) src = \"\";",
            "    length = strlen(src);",
            "    s = string_alloc(length);",
            "    if (!s) return 0;",
            "    memcpy(s->data, src, length);",
            "    s->literal = 0;",
            "    return s;",
            "}",
            "typedef struct _jLiteralNode { string *s; struct _jLiteralNode *next; } _jLiteralNode;",
            "static _jLiteralNode *_j_literal_head = 0;",
            "static int _j_literal_atexit = 0;",
            "static int _j_untrack_literal(string *self) { _jLiteralNode **pp; _jLiteralNode *n; if(!self)return 0; pp=&_j_literal_head; while(*pp){if((*pp)->s==self){n=*pp;*pp=n->next;free(n);return 1;}pp=&(*pp)->next;}return 0; }",
            "static void _j_free_literals(void) { _jLiteralNode *n; _jLiteralNode *next; n=_j_literal_head; while(n){next=n->next;free(n->s);free(n);n=next;} _j_literal_head=0; }",
            "static string *string_from_literal(const char *src) { string *s; _jLiteralNode *n; s=string_from_cstr(src); if(!s)return 0; s->literal=1; n=(_jLiteralNode*)malloc(sizeof(_jLiteralNode)); if(!n){free(s);return 0;} n->s=s;n->next=_j_literal_head;_j_literal_head=n; if(!_j_literal_atexit){atexit(_j_free_literals);_j_literal_atexit=1;} return s; }",
            "static string *string_ctor(void) { return string_from_cstr(\"\"); }",
            "static void string_destr(string *self) {",
            "    _jLiteralNode **pp; _jLiteralNode *n;",
            "    if (!self) return;",
            "    if (self->literal) {",
            "        pp = &_j_literal_head;",
            "        while (*pp) {",
            "            if ((*pp)->s == self) {",
            "                n = *pp; *pp = n->next; free(n); self->literal = 0; free(self); return;",
            "            }",
            "            pp = &(*pp)->next;",
            "        }",
            "        return;",
            "    }",
            "    free(self);",
            "}",
            "static i32 string_length(string *self) { return self ? (i32)self->length : 0; }",
            "static _jBool string_empty(string *self) { return (!self || self->length == 0) ? 1 : 0; }",
            "static _jBool string_equals(string *self, string *other) {",
            "    if (!self || !other) return self == other;",
            "    return strcmp(self->data ? self->data : \"\", other->data ? other->data : \"\") == 0;",
            "}",
            "",
            "static _jBool string_contains(string *self, string *needle) {",
            "    if (!self || !needle) return 0;",
            "    return strstr(self->data ? self->data : \"\", needle->data ? needle->data : \"\") != 0;",
            "}",
            "static _jBool string_starts_with(string *self, string *prefix) {",
            "    if (!self || !prefix || prefix->length > self->length) return 0;",
            "    return memcmp(self->data, prefix->data, prefix->length) == 0;",
            "}",
            "static _jBool string_ends_with(string *self, string *suffix) {",
            "    if (!self || !suffix || suffix->length > self->length) return 0;",
            "    return memcmp(self->data + self->length - suffix->length, suffix->data, suffix->length) == 0;",
            "}",
            "static string *string_concat(string *self, string *other) {",
            "    size_t a = self ? self->length : 0, b = other ? other->length : 0;",
            "    string *out = string_alloc(a + b);",
            "    if (!out) return 0;",
            "    if (a) memcpy(out->data, self->data, a);",
            "    if (b) memcpy(out->data + a, other->data, b);",
            "    out->data[out->length] = '\\0';",
            "    return out;",
            "}",
            "static string *string_substring(string *self, i32 start, i32 length) {",
            "    size_t a, n; string *out;",
            "    if (!self || start < 0 || length < 0 || (size_t)start > self->length) return string_from_cstr(\"\");",
            "    a = (size_t)start; n = (size_t)length; if (n > self->length - a) n = self->length - a;",
            "    out = string_alloc(n); if (!out) return 0;",
            "    memcpy(out->data, self->data + a, n); out->data[n] = '\\0'; return out;",
            "}",
            "static i32 string_char_at(string *self, i32 index) {",
            "    if (!self || index < 0 || (size_t)index >= self->length) return -1;",
            "    return (unsigned char)self->data[index];",
            "}",
            "static string *string_transform_case(string *self, int upper) {",
            "    size_t i; string *out;",
            "    out = string_from_cstr(self ? self->data : \"\"); if (!out) return 0;",
            "    for (i = 0; i < out->length; ++i) {",
            "        unsigned char c = (unsigned char)out->data[i];",
            "        if (upper && c >= 'a' && c <= 'z') out->data[i] = (char)(c - 'a' + 'A');",
            "        if (!upper && c >= 'A' && c <= 'Z') out->data[i] = (char)(c - 'A' + 'a');",
            "    } return out;",
            "}",
            "static string *string_to_upper(string *self) { return string_transform_case(self, 1); }",
            "static string *string_to_lower(string *self) { return string_transform_case(self, 0); }",
        ]

    if ("sys:console", "set_color") in used or ("sys:console", "reset_color") in used:
        lines += [
            "/* ANSI escape sequences are native on Unix-like terminals (Linux/macOS).",
            " * Windows needs Virtual Terminal Processing enabled explicitly. */",
            "#ifdef _WIN32",
            "#include <windows.h>",
            "static void _j_sys_enable_ansi(void) {",
            "    static int done = 0;",
            "    if (done) return;",
            "    done = 1;",
            "    HANDLE h = GetStdHandle(STD_OUTPUT_HANDLE);",
            "    if (h != INVALID_HANDLE_VALUE) {",
            "        DWORD mode = 0;",
            "        if (GetConsoleMode(h, &mode))",
            "            SetConsoleMode(h, mode | ENABLE_VIRTUAL_TERMINAL_PROCESSING);",
            "    }",
            "}",
            "#else",
            "/* POSIX / Unix-like systems already interpret ANSI sequences. */",
            "static void _j_sys_enable_ansi(void) { }",
            "#endif",
            "",
        ]

    if ("thread", "start") in used or any(k[0] == "thread" for k in used):
        lines += [
            "",
            "#ifdef _WIN32",
            "#include <windows.h>",
            "typedef struct _jThreadStartCtx { void (*fn)(void); } _jThreadStartCtx;",
            "typedef struct _jThreadHandle { HANDLE handle; } _jThreadHandle;",
            "static DWORD WINAPI _j_thread_entry(LPVOID raw) { _jThreadStartCtx *ctx=(_jThreadStartCtx*)raw; void (*fn)(void)=ctx?ctx->fn:0; if(ctx)free(ctx); if(fn)fn(); return 0; }",
            "static void *_j_thread_start(void (*fn)(void)) { _jThreadHandle *h; _jThreadStartCtx *ctx; DWORD id; if(!fn)return 0; h=(_jThreadHandle*)malloc(sizeof(*h)); ctx=(_jThreadStartCtx*)malloc(sizeof(*ctx)); if(!h||!ctx){free(h);free(ctx);return 0;} ctx->fn=fn; h->handle=CreateThread(0,0,_j_thread_entry,ctx,0,&id); if(!h->handle){free(ctx);free(h);return 0;} return h; }",
            "static void _j_thread_join(void *raw) { _jThreadHandle *h=(_jThreadHandle*)raw; if(!h)return; WaitForSingleObject(h->handle,INFINITE); CloseHandle(h->handle); free(h); }",
            "static void _j_thread_detach(void *raw) { _jThreadHandle *h=(_jThreadHandle*)raw; if(!h)return; CloseHandle(h->handle); free(h); }",
            "static void _j_thread_sleep(i32 ms) { if(ms<0)ms=0; Sleep((DWORD)ms); }",
            "static void _j_thread_yield(void) { SwitchToThread(); }",
            "#else",
            "#include <pthread.h>",
            "#include <sched.h>",
            "#include <time.h>",
            "typedef struct _jThreadStartCtx { void (*fn)(void); } _jThreadStartCtx;",
            "typedef struct _jThreadHandle { pthread_t thread; } _jThreadHandle;",
            "static void *_j_thread_entry(void *raw) { _jThreadStartCtx *ctx=(_jThreadStartCtx*)raw; void (*fn)(void)=ctx?ctx->fn:0; if(ctx)free(ctx); if(fn)fn(); return 0; }",
            "static void *_j_thread_start(void (*fn)(void)) { _jThreadHandle *h; _jThreadStartCtx *ctx; if(!fn)return 0; h=(_jThreadHandle*)malloc(sizeof(*h)); ctx=(_jThreadStartCtx*)malloc(sizeof(*ctx)); if(!h||!ctx){free(h);free(ctx);return 0;} ctx->fn=fn; if(pthread_create(&h->thread,0,_j_thread_entry,ctx)!=0){free(ctx);free(h);return 0;} return h; }",
            "static void _j_thread_join(void *raw) { _jThreadHandle *h=(_jThreadHandle*)raw; if(!h)return; pthread_join(h->thread,0); free(h); }",
            "static void _j_thread_detach(void *raw) { _jThreadHandle *h=(_jThreadHandle*)raw; if(!h)return; pthread_detach(h->thread); free(h); }",
            "static void _j_thread_sleep(i32 ms) { struct timespec ts; if(ms<0)ms=0; ts.tv_sec=(time_t)(ms/1000); ts.tv_nsec=(long)((ms%1000)*1000000L); nanosleep(&ts,0); }",
            "static void _j_thread_yield(void) { sched_yield(); }",
            "#endif",
        ]

    if ("sys", "print") in used:
        lines += [
            "",
            "static void _j_sys_print_string(string *s) {",
            "    printf(\"%s\\n\", (s && s->data) ? s->data : \"\");",
            "}",
            "",
            "static void _j_sys_print_int(int v) {",
            "    printf(\"%d\\n\", v);",
            "}",
            "",
            "static void _j_sys_print_i8(signed char v) {",
            "    printf(\"%d\\n\", (int)v);",
            "}",
            "",
            "static void _j_sys_print_u8(unsigned char v) {",
            "    printf(\"%u\\n\", (unsigned int)v);",
            "}",
            "",
            "static void _j_sys_print_i16(short v) {",
            "    printf(\"%d\\n\", (int)v);",
            "}",
            "",
            "static void _j_sys_print_u16(unsigned short v) {",
            "    printf(\"%u\\n\", (unsigned int)v);",
            "}",
            "",
            "static void _j_sys_print_i32(int v) {",
            "    printf(\"%d\\n\", v);",
            "}",
            "",
            "static void _j_sys_print_u32(unsigned int v) {",
            "    printf(\"%u\\n\", v);",
            "}",
            "",
            "static void _j_sys_print_i64(long long v) {",
            "    printf(\"%lld\\n\", v);",
            "}",
            "",
            "static void _j_sys_print_u64(unsigned long long v) {",
            "    printf(\"%llu\\n\", v);",
            "}",
            "",
            "static void _j_sys_print_float(float v) {",
            "    printf(\"%g\\n\", (double)v);",
            "}",
            "",
            "static void _j_sys_print_f32(float v) {",
            "    printf(\"%g\\n\", (double)v);",
            "}",
            "",
            "static void _j_sys_print_f64(double v) {",
            "    printf(\"%g\\n\", v);",
            "}",
            "",
            "static void _j_sys_print_bool(_jBool v) {",
            "    printf(\"%s\\n\", v ? \"true\" : \"false\");",
            "}",
            "",
            "static void _j_sys_print_dynamic(void *data, const char *type) {",
            "    if (!data || !type) { printf(\"<null>\\n\"); return; }",
            "    if (!strcmp(type, \"string\")) { string *v=(string*)data; printf(\"%s\\n\", (v && v->data) ? v->data : \"\"); return; }",
            "    if (!strcmp(type, \"bool\")) { printf(\"%s\\n\", *((_jBool*)data) ? \"true\" : \"false\"); return; }",
            "    if (!strcmp(type, \"f32\") || !strcmp(type, \"float\")) { printf(\"%g\\n\", (double)*((float*)data)); return; }",
            "    if (!strcmp(type, \"f64\")) { printf(\"%g\\n\", *((double*)data)); return; }",
            "    if (!strcmp(type, \"i8\")) { printf(\"%d\\n\", (int)*((signed char*)data)); return; }",
            "    if (!strcmp(type, \"u8\")) { printf(\"%u\\n\", (unsigned int)*((unsigned char*)data)); return; }",
            "    if (!strcmp(type, \"i16\")) { printf(\"%d\\n\", (int)*((short*)data)); return; }",
            "    if (!strcmp(type, \"u16\")) { printf(\"%u\\n\", (unsigned int)*((unsigned short*)data)); return; }",
            "    if (!strcmp(type, \"i32\") || !strcmp(type, \"int\")) { printf(\"%d\\n\", *((int*)data)); return; }",
            "    if (!strcmp(type, \"u32\")) { printf(\"%u\\n\", *((unsigned int*)data)); return; }",
            "    if (!strcmp(type, \"i64\")) { printf(\"%lld\\n\", *((long long*)data)); return; }",
            "    if (!strcmp(type, \"u64\")) { printf(\"%llu\\n\", *((unsigned long long*)data)); return; }",
            "    fprintf(stderr, \"Jaguar runtime error: cannot print a dynamic_list value of type \'%s\'\\n\", type);",
            "    abort();",
            "}",
        ]

    if ("sys:console", "set_color") in used:
        lines += [
            "",
            "static void _j_sys_console_set_color(string *color) {",
            "    _j_sys_enable_ansi();",
            "    if (color && color->data) fputs(color->data, stdout);",
            "    fflush(stdout);",
            "}",
        ]

    if ("sys:console", "reset_color") in used:
        lines += [
            "",
            "static void _j_sys_console_reset_color(void) {",
            "    _j_sys_enable_ansi();",
            "    fputs(\"\\033[0m\", stdout);",
            "    fflush(stdout);",
            "}",
        ]

    if ("sys", "execute") in used:
        lines += [
            "",
            "static int _j_sys_execute(string *program, string *path) {",
            "    char command[4096];",
            "    if (!program || !program->data) return -1;",
            "    if (!path || !path->data || !*path->data) return system(program->data);",
            "#ifdef _WIN32",
            "    sprintf(command, \"cd /d \\\"%s\\\" && \\\"%s\\\"\", path, program);",
            "#else",
            "    sprintf(command, \"cd \\\"%s\\\" && \\\"%s\\\"\", path, program);",
            "#endif",
            "    return system(command);",
            "}",
        ]

    if ("sys:fs", "read") in used:
        lines += [
            "",
            "static string * _j_sys_fs_read(string *path) {",
            "    FILE *file;",
            "    long size;",
            "    char *data;",
            "    if (!path || !path->data) return 0;",
            "    file = fopen(path, \"rb\");",
            "    if (!file) return 0;",
            "    if (fseek(file, 0, SEEK_END) != 0) {",
            "        fclose(file);",
            "        return 0;",
            "    }",
            "    size = ftell(file);",
            "    if (size < 0) {",
            "        fclose(file);",
            "        return 0;",
            "    }",
            "    rewind(file);",
            "    data = (char *)malloc((size_t)size + 1);",
            "    if (!data) {",
            "        fclose(file);",
            "        return 0;",
            "    }",
            "    if (size > 0 && fread(data, 1, (size_t)size, file) != (size_t)size) {",
            "        free(data);",
            "        fclose(file);",
            "        return 0;",
            "    }",
            "    data[size] = '\\0';",
            "    fclose(file);",
            "    return data;",
            "}",
        ]

    if ("sys:fs", "write") in used:
        lines += [
            "",
            "static void _j_sys_fs_write(string *path, string *data) {",
            "    FILE *file;",
            "    if (!path || !path->data) return;",
            "    file = fopen(path, \"wb\");",
            "    if (!file) return;",
            "    if (data && data->data) fputs(data->data, file);",
            "    fclose(file);",
            "}",
        ]

    if any(k[0] == "jcc" for k in used):
        lines += [
            "",
            "#include <time.h>",
            "#include <math.h>",
            "#include <ctype.h>",
            "static void _j_lib_exit(i32 code) { exit((int)code); }",
            "static void _j_lib_abort(void) { abort(); }",
            "static i32 _j_lib_abs_i32(i32 v) { return v < 0 ? -v : v; }",
            "static i32 _j_lib_min_i32(i32 a, i32 b) { return a < b ? a : b; }",
            "static i32 _j_lib_max_i32(i32 a, i32 b) { return a > b ? a : b; }",
            "static i32 _j_lib_clamp_i32(i32 v, i32 lo, i32 hi) { if (v < lo) return lo; if (v > hi) return hi; return v; }",
            "static i32 _j_lib_random_i32(i32 min, i32 max) { static int seeded=0; unsigned long range; if (!seeded) { srand((unsigned int)time(0)); seeded=1; } if (max <= min) return min; range=(unsigned long)((long)max-(long)min)+1UL; return min+(i32)(rand()%range); }",
            "static i64 _j_lib_time_ms(void) { return (i64)time(0) * 1000LL; }",
            "static void _j_lib_assert(_jBool condition, string *message) { if (!condition) { fprintf(stderr, \"Jaguar assertion failed: %s\\n\", (message && message->data) ? message->data : \"\"); abort(); } }",
            "static f64 _j_lib_sqrt(f64 v) { return sqrt(v); }",
            "static f64 _j_lib_pow(f64 a, f64 b) { return pow(a,b); }",
            "static f64 _j_lib_sin(f64 v) { return sin(v); }",
            "static f64 _j_lib_cos(f64 v) { return cos(v); }",
            "static f64 _j_lib_tan(f64 v) { return tan(v); }",
            "static f64 _j_lib_asin(f64 v) { return asin(v); }",
            "static f64 _j_lib_acos(f64 v) { return acos(v); }",
            "static f64 _j_lib_atan(f64 v) { return atan(v); }",
            "static f64 _j_lib_atan2(f64 y, f64 x) { return atan2(y,x); }",
            "static f64 _j_lib_floor(f64 v) { return floor(v); }",
            "static f64 _j_lib_ceil(f64 v) { return ceil(v); }",
            "static f64 _j_lib_round(f64 v) { return floor(v + 0.5); }",
            "static f64 _j_lib_log(f64 v) { return log(v); }",
            "static f64 _j_lib_log10(f64 v) { return log10(v); }",
            "static f64 _j_lib_exp(f64 v) { return exp(v); }",
            "static f64 _j_lib_fmod(f64 a, f64 b) { return fmod(a,b); }",
            "static _jBool _j_lib_is_digit(i32 c) { return isdigit((unsigned char)c)!=0; }",
            "static _jBool _j_lib_is_alpha(i32 c) { return isalpha((unsigned char)c)!=0; }",
            "static _jBool _j_lib_is_alnum(i32 c) { return isalnum((unsigned char)c)!=0; }",
            "static _jBool _j_lib_is_space(i32 c) { return isspace((unsigned char)c)!=0; }",
            "static _jBool _j_lib_is_upper(i32 c) { return isupper((unsigned char)c)!=0; }",
            "static _jBool _j_lib_is_lower(i32 c) { return islower((unsigned char)c)!=0; }",
            "static i32 _j_lib_to_upper_char(i32 c) { return (i32)toupper((unsigned char)c); }",
            "static i32 _j_lib_to_lower_char(i32 c) { return (i32)tolower((unsigned char)c); }",
            "static _jBool _j_lib_file_exists(string *p) { FILE *f; if(!p||!p->data)return 0; f=fopen(p->data,\"rb\"); if(!f)return 0; fclose(f); return 1; }",
            "static _jBool _j_lib_remove_file(string *p) { return p&&p->data ? remove(p->data)==0 : 0; }",
            "static _jBool _j_lib_rename_file(string *a, string *b) { return a&&b&&a->data&&b->data ? rename(a->data,b->data)==0 : 0; }",
            "static string *_j_lib_env_get(string *name) { const char *v; if(!name||!name->data)return 0; v=getenv(name->data); return v ? string_from_cstr(v) : 0; }",
        ]


    return "\n".join(lines)




# Précédence des opérateurs binaires (identique à celle du C, donc à celle
# du parser) : sert à ne mettre des parenthèses que là où elles sont
# nécessaires dans le C généré.
_BINOP_PREC = {
    "||": 1,
    "&&": 2,
    "==": 3, "!=": 3,
    "<": 4, ">": 4, "<=": 4, ">=": 4,
    "+": 5, "-": 5,
    "*": 6, "/": 6, "%": 6,
}
# opérateurs dont le résultat est un bool côté Jaguar
_BOOL_RESULT_OPS = {"||", "&&", "==", "!=", "<", ">", "<=", ">="}
def _literal(category: str):
    """Marqueur de type pour un littéral (pas encore de largeur figée) :
    un littéral entier correspond à n'importe quel type entier candidat,
    un littéral flottant à n'importe quel type flottant candidat."""
    return ("literal", category)


def _type_matches(param_type: str, arg_type) -> bool:
    if isinstance(arg_type, tuple) and arg_type[0] == "literal":
        category = arg_type[1]
        return param_type in (INTEGER_TYPES if category == "int" else FLOAT_TYPES)
    return param_type == arg_type


def _builtin_string_class():
    """Description Jaguar de la classe string native de jcc."""
    names = [
        ("length", "i32", []),
        ("empty", "bool", []),
        ("equals", "bool", [Param("string", "other")]),
        ("contains", "bool", [Param("string", "needle")]),
        ("starts_with", "bool", [Param("string", "prefix")]),
        ("ends_with", "bool", [Param("string", "suffix")]),
        ("concat", "string", [Param("string", "other")]),
        ("substring", "string", [Param("i32", "start"), Param("i32", "length")]),
        ("char_at", "i32", [Param("i32", "index")]),
        ("to_upper", "string", []),
        ("to_lower", "string", []),
    ]
    methods = [ClassMethod("void", "constr", [], Block([]), "public", False, False, True, False)]
    methods += [ClassMethod(ret, name, params, Block([]), "public") for name, ret, params in names]
    methods += [ClassMethod("void", "destr", [], Block([]), "public", False, False, False, True)]
    return ClassDecl("string", None, [], methods)


class CodeGen:
    def __init__(self, program: Program, groups: Dict[FuncKey, List[FunctionDecl]],
                 c89: bool = False):
        self.program = program
        self.groups = groups
        self.classes: Dict[str, ClassDecl] = {x.name:x for x in program.items if isinstance(x, ClassDecl)}
        self.enums: Dict[str, EnumDecl] = {x.name:x for x in program.items if isinstance(x, EnumDecl) and not x.namespace}
        self.unions: Dict[str, UnionDecl] = {x.name:x for x in program.items if isinstance(x, UnionDecl)}
        self.structs: Dict[str, StructDecl] = {x.name:x for x in program.items if isinstance(x, StructDecl)}
        self.using_namespaces = list(getattr(program, "_using_namespaces", []))
        self.using_symbols = dict(getattr(program, "_using_symbols", {}))
        self.type_aliases = dict(getattr(program, "_type_aliases", {}))
        self.forward_decls = [(x.kind, x.name) for x in program.items if isinstance(x, ForwardDecl)]
        self.macros: Dict[str, str] = {}
        for x in program.items:
            if isinstance(x, PreprocLine):
                m = re.match(r"\s*#\s*define\s+([A-Za-z_]\w*)(?:\s+(.*?))?\s*$", x.text)
                if m and m.group(2):
                    value = m.group(2).strip()
                    if re.fullmatch(r"[+-]?\d+", value): self.macros[m.group(1)] = "int"
                    elif re.fullmatch(r"[+-]?(?:\d+\.\d*|\.\d+)(?:[eE][+-]?\d+)?", value): self.macros[m.group(1)] = "float"
                    elif value in ("true", "false"): self.macros[m.group(1)] = "bool"
                    elif len(value) >= 2 and value[0] == value[-1] == '"': self.macros[m.group(1)] = "string"
        if "string" not in self.classes:
            self.classes["string"] = _builtin_string_class()
        self._current_class: Optional[ClassDecl] = None
        self._current_namespace: Optional[str] = None
        # c89=False : déclarations laissées à leur place (C99+)
        # c89=True  : déclarations remontées en tête de bloc (C89 strict)
        self.c89 = c89

        # état pendant la génération d'une fonction
        self._in_main = False            # `return;` -> `return 0;` dans main
        self._loop_depth = 0             # pour valider break / continue
        self._readonly_vars = set()      # variables const et de for_loop (non modifiables)
        self._const_object_vars = set()  # `const Class value` => const receiver
        self._current_class_method_const = False
        self._scope_owned = []
        self._loop_scope_bases = []
        self._tmp_id = 0                 # noms uniques des temporaires de for_loop
        self._change_handlers: Dict[str, object] = {}
        self._in_change_handler = False
        self._current_source_line = 1
        self.decorators: Dict[tuple, DecoratorDecl] = dict(getattr(program, "_decorators", {}))
        self._decorator_call_target_name: Optional[str] = None
        self._decorator_target_params: List[Param] = []
        self._current_function_local_types: Dict[str, str] = {}

        # variables globales : nom -> type Jaguar (pour l'inférence de
        # types dans la résolution de surcharge, et la validation)
        self.global_types: Dict[str, str] = {}
        self.global_decl_lines: Dict[str, int] = {}
        self.union_globals: Dict[str, str] = {}
        self.global_const: set[str] = set()
        fn_c_names = {
            fn.mangled_name for fns in groups.values() for fn in fns
        }
        for item in program.items:
            if isinstance(item, UnionDecl):
                # A named union declaration also provides its default global
                # storage in Jaguar, so `union val { ... }` can be used as
                # `val.member` directly.
                if item.name in self.global_types:
                    raise CodeGenError(f"global variable '{item.name}' is declared multiple times")
                self.global_types[item.name] = item.name
                self.global_decl_lines[item.name] = getattr(item, "_jaguar_line", 1)
                self.union_globals[item.name] = f"_j_union_{item.name}"
            if isinstance(item, VarDecl):
                if item.type == "auto":
                    raise CodeGenError("'auto' is not allowed for a global variable")
                if item.name in self.global_types:
                    raise CodeGenError(
                        f"global variable '{item.name}' is declared multiple times"
                    )
                if item.name in fn_c_names:
                    raise CodeGenError(
                        f"global variable '{item.name}' has the same name "
                        f"(in C) as a function"
                    )
                self.global_types[item.name] = item.type
                self.global_decl_lines[item.name] = getattr(item, "_jaguar_line", 1)
                if item.is_const: self.global_const.add(item.name)

    def _walk_expressions(self):
        def exprs(e):
            if e is None: return
            yield e
            if isinstance(e, (UnaryOp, CastExpr)): yield from exprs(e.operand)
            elif isinstance(e, BinOp): yield from exprs(e.left); yield from exprs(e.right)
            elif isinstance(e, NewExpr):
                for a in e.args: yield from exprs(a.expr if isinstance(a, NamedArg) else a)
            elif isinstance(e, MemberAccess): yield from exprs(e.obj)
            elif isinstance(e, IndexAccess): yield from exprs(e.obj); yield from exprs(e.index)
            elif isinstance(e, Call):
                yield from exprs(e.callee)
                for a in e.args: yield from exprs(a.expr if isinstance(a, NamedArg) else a)
        for item in self.program.items:
            if isinstance(item, FunctionDecl):
                for st in _iter_stmts(item.body.statements):
                    for attr in ("expr","cond","init","target","start","end","collection"):
                        if hasattr(st, attr): yield from exprs(getattr(st, attr))
            elif isinstance(item, VarDecl): yield from exprs(item.init)

    def _validate_parameter_defaults(self):
        # Defaults are part of Jaguar declarations, so type-check them before
        # any C is emitted. This makes declaration errors independent of GCC.
        owners = []
        for item in self.program.items:
            if isinstance(item, FunctionDecl):
                owners.append((item.name, item.params))
            elif isinstance(item, ClassDecl):
                for m in item.methods:
                    owners.append((f"{item.name}::{m.name}", m.params))
        for owner_name, params in owners:
            for p in params:
                if p.default is None:
                    continue
                at = self.infer_type(p.default, {})
                self._check_assignable(p.type, at, f"default value of parameter '{p.name}'", p.default)

    def gen(self, split_runtime: bool = False):
        self._validate_parameter_defaults()
        used_types = self._used_builtin_types()
        # `string` is a core language type and its runtime is always available.
        # This also guarantees sys:print/string helpers are defined even when
        # the source never declares a string variable explicitly.
        used_types.update({"string", "i32", "bool"})
        used_system = self._used_system_builtins()
        if self._uses_collections():
            # Le runtime polymorphe des collections partage les helpers string/bool.
            used_types.update({"string", "i32", "bool"})
        used_string = True
        if used_string:
            used_types.update({"string", "i32", "bool"})
        for k in ("jcc",):
            if any(key[0] == k for key in used_system):
                used_types.update({"i32", "i64", "f32", "f64", "bool", "string"})
        typedef_lines = [
            BUILTIN_TYPEDEFS[t] for t in ORDERED_BUILTIN_TYPES if t in used_types
        ]
        pair_lines = self._pair_typedefs()
        alias_lines = []
        for item in self.program.items:
            if isinstance(item, TypeAliasDecl):
                fp = _function_type_parts(item.target)
                if fp is not None:
                    params, ret = fp
                    p = ", ".join(c_type(x) for x in params) if params else "void"
                    alias_lines.append(f"typedef {c_type(ret)} (*{item.name})({p});")
                else:
                    alias_lines.append(f"typedef {self._decl_c_type(item.target)} {item.name};")

        parts = []
        # c_type() maps Jaguar fixed-width types (u32, i64, ...) back to
        # the generated C ABI. The runtime header owns the builtin typedefs
        # when direct compilation is requested.
        if not split_runtime and any(t in used_types for t in ("i8", "u8", "i16", "u16", "i32", "u32", "i64", "u64")):
            parts.append("#include <stdint.h>")
        needs_new = any(isinstance(x, NewExpr) for x in self._walk_expressions())
        if not split_runtime and (self.classes or needs_new or self.structs):
            parts.append("#include <stdlib.h>")
        if not split_runtime and (needs_new or self.structs):
            parts.append("#include <string.h>")
            parts.append("#include <stdio.h>")
            parts.append("static void *_j_alloc_value(size_t size, const void *src) { void *p = malloc(size); if (!p) { fprintf(stderr, \"Jaguar runtime error: allocation failed\\n\"); abort(); } memcpy(p, src, size); return p; }")
        runtime_chunks = []
        runtime_typedefs = []
        if split_runtime:
            runtime_chunks.append("static void *_j_alloc_value(size_t size, const void *src) { void *p = malloc(size); if (!p) { fprintf(stderr, \"Jaguar runtime error: allocation failed\\n\"); abort(); } memcpy(p, src, size); return p; }") if needs_new else ""
        # All named class/struct types get an early C forward declaration so
        # pointers and prototypes may refer to them before their definition.
        known_class_names = set(self.classes) - {"string"}
        known_struct_names = {x.name for x in self.program.items if isinstance(x, StructDecl)}
        known_union_names = {x.name for x in self.program.items if isinstance(x, UnionDecl)}
        forward_lines = []
        for kind, name in self.forward_decls:
            if kind == "class":
                forward_lines.append(f"typedef struct {name} {name};")
            elif kind == "struct":
                forward_lines.append(f"typedef struct {name} {name};")
            elif kind == "union":
                forward_lines.append(f"typedef union {name} {name};")
        for name in sorted(known_class_names | known_struct_names):
            line = f"typedef struct {name} {name};"
            if line not in forward_lines:
                forward_lines.append(line)
        for name in sorted(known_union_names):
            line = f"typedef union {name} {name};"
            if line not in forward_lines:
                forward_lines.append(line)
        if forward_lines:
            parts.append("\n".join(forward_lines))
        enum_lines = []
        for en in [x for x in self.program.items if isinstance(x, EnumDecl)]:
            cname = f"{en.namespace}_{en.name}" if en.namespace else en.name
            enum_lines.append("typedef enum " + cname + " {")
            initializers = getattr(en, "initializers", None) or {}
            for i, v in enumerate(en.values):
                suffix = "," if i < len(en.values)-1 else ""
                if v in initializers:
                    expr = self.gen_expr(initializers[v], {})
                    enum_lines.append(f"    {cname}_{v} = {expr}{suffix}")
                else:
                    enum_lines.append(f"    {cname}_{v}{suffix}")
            enum_lines.append(f"}} {cname};")
        if enum_lines:
            parts.append("\n".join(enum_lines))
        # Le runtime est normalement inline pour conserver la compatibilité de
        # transpile(). Avec split_runtime, il est externalisé dans
        # jaguar_runtime.c / jaguar_runtime.h.
        if typedef_lines and not split_runtime:
            parts.append("\n".join(typedef_lines))
        if alias_lines:
            parts.append("\n".join(alias_lines))
        if pair_lines:
            parts.append("\n".join(pair_lines))

        runtime = _system_runtime(used_system, used_string)
        if runtime:
            if split_runtime:
                runtime_chunks.append(runtime)
            else:
                parts.append(runtime)
        collection_runtime = self._collection_runtime()
        if collection_runtime:
            if split_runtime:
                c_lines = collection_runtime.splitlines()
                runtime_typedefs.extend(line for line in c_lines if line.startswith("typedef "))
                runtime_chunks.append("\n".join(line for line in c_lines if not line.startswith("typedef ")))
            else:
                parts.append(collection_runtime)
        reflection = self._native_reflection_runtime()
        if reflection:
            reflection_prelude = self._native_reflection_prelude()
            if split_runtime:
                r_lines = reflection_prelude.splitlines()
                runtime_typedefs.extend(line for line in r_lines if line.startswith("typedef "))
                runtime_chunks.append("\n".join(line for line in r_lines if not line.startswith("typedef ")))
            else:
                parts.append(reflection_prelude)
            # La factory est une API runtime dynamique : son symbole doit
            # toujours être déclaré avant le code utilisateur dès que le
            # runtime réflexion/factory est présent.
            # factory/print are emitted in the program unit itself, while
            # member_exists/set_member live in the split runtime.
            parts.append("static void *_j_factory_construct(string *name);")
            split_decl = "" if split_runtime else "static "
            parts.append(split_decl + "_jBool _j_reflect_member_exists(void *obj, const char *name);")
            parts.append(split_decl + "void _j_reflect_set_member(void *obj, const char *name, const char *type_name, long long si, unsigned long long ui, double f, string *str, void *ptr);")
            parts.append("static void _j_reflect_print(void *obj, const char *name);")
        for item in self.program.items:
            parts.append(self.gen_item(item))
        if reflection:
            parts.append(reflection)
        if split_runtime:
            import re
            runtime_c_parts = []
            for chunk in runtime_chunks:
                if not chunk:
                    continue
                runtime_c_parts.append(re.sub(r"(?m)^static ", "", chunk))
            runtime_c = '#include "jaguar_runtime.h"\n\n' + "\n\n".join(runtime_c_parts) + "\n"
            proto_re = re.compile(r"(?m)^(?:const )?(?:unsigned |signed )?[A-Za-z_][A-Za-z0-9_]*(?:\s*\*)*\s*[A-Za-z_][A-Za-z0-9_]*\([^;{}]*\)\s*\{")
            prototypes = []
            for m in proto_re.finditer(runtime_c):
                sig = m.group(0).rsplit("{", 1)[0].strip() + ";"
                if sig not in prototypes:
                    prototypes.append(sig)
            header_lines = [
                "#ifndef JAGUAR_RUNTIME_H",
                "#define JAGUAR_RUNTIME_H",
                "#include <stddef.h>",
                "#include <stdio.h>",
                "#include <stdlib.h>",
                "#include <string.h>",
            ]
            if any(k[0] == "thread" for k in used_system):
                header_lines += ["#ifdef _WIN32", "#include <windows.h>", "#else", "#include <pthread.h>", "#endif"]
            if any(t in used_types for t in ("i8", "u8", "i16", "u16", "i32", "u32", "i64", "u64")):
                header_lines.append("#include <stdint.h>")
            header_lines.extend(typedef_lines)
            header_lines.extend(runtime_typedefs)
            header_lines.extend(prototypes)
            header_lines.append("#endif")
            parts.insert(0, '#include "jaguar_runtime.h"')
            return {"program": "\n\n".join(parts) + "\n", "runtime_h": "\n\n".join(header_lines) + "\n", "runtime_c": runtime_c}

        return "\n\n".join(parts) + "\n"

    def _used_system_builtins(self):
        used = set()

        def scan_expr(e):
            if isinstance(e, Call):
                if isinstance(e.callee, NamespacedIdent):
                    key = (e.callee.namespace, e.callee.name)
                    if key in SYSTEM_BUILTINS:
                        used.add(key)
                for a in e.args:
                    scan_expr(a)
            elif isinstance(e, CastExpr):
                scan_expr(e.operand)
            elif isinstance(e, UnaryOp):
                scan_expr(e.operand)
            elif isinstance(e, BinOp):
                scan_expr(e.left)
                scan_expr(e.right)

        def scan_stmt(stmt):
            if isinstance(stmt, ExprStmt):
                scan_expr(stmt.expr)
            elif isinstance(stmt, ReturnStmt) and stmt.expr is not None:
                scan_expr(stmt.expr)
            elif isinstance(stmt, VarDecl) and stmt.init is not None:
                scan_expr(stmt.init)
            elif isinstance(stmt, AssignStmt):
                scan_expr(stmt.expr)
            elif isinstance(stmt, PointerAssignStmt):
                scan_expr(stmt.target); scan_expr(stmt.expr)
            elif isinstance(stmt, IfStmt):
                scan_expr(stmt.cond)
                for x in stmt.then_block.statements:
                    scan_stmt(x)
                if isinstance(stmt.else_branch, IfStmt):
                    scan_stmt(stmt.else_branch)
                elif isinstance(stmt.else_branch, Block):
                    for x in stmt.else_branch.statements:
                        scan_stmt(x)
            elif isinstance(stmt, (WhileStmt, ForLoopStmt, CollectionLoopStmt)):
                if isinstance(stmt, ForLoopStmt):
                    scan_expr(stmt.start)
                    scan_expr(stmt.end)
                elif isinstance(stmt, CollectionLoopStmt):
                    scan_expr(stmt.collection)
                for x in stmt.body.statements:
                    scan_stmt(x)
            elif isinstance(stmt, VariableChangeHandler):
                for x in stmt.body.statements:
                    scan_stmt(x)

        for item in self.program.items:
            if isinstance(item, FunctionDecl):
                for stmt in item.body.statements:
                    scan_stmt(stmt)
            elif isinstance(item, TopExprStmt):
                scan_expr(item.expr)
            elif isinstance(item, ClassDecl):
                for f in item.fields:
                    if f.init is not None:
                        scan_expr(f.init)
                for signal in getattr(item, "signals", []):
                    for stmt in signal.body.statements:
                        scan_stmt(stmt)
                for m in item.methods:
                    for stmt in m.body.statements:
                        scan_stmt(stmt)
            elif isinstance(item, VarDecl) and item.init is not None:
                scan_expr(item.init)

        return used

    def _program_uses_string(self) -> bool:
        def expr(e):
            if isinstance(e, StringLit): return True
            if isinstance(e, Call): return expr(e.callee) or any(expr(a) for a in e.args)
            if isinstance(e, MemberAccess): return expr(e.obj)
            if isinstance(e, CastExpr): return expr(e.operand)
            if isinstance(e, UnaryOp): return expr(e.operand)
            if isinstance(e, BinOp): return expr(e.left) or expr(e.right)
            return False
        def stmt(s):
            if isinstance(s, VarDecl): return expr(s.init) if s.init else False
            if isinstance(s, ExprStmt): return expr(s.expr)
            if isinstance(s, ReturnStmt): return expr(s.expr) if s.expr else False
            if isinstance(s, AssignStmt): return expr(s.expr)
            if isinstance(s, MemberAssignStmt): return expr(s.target) or expr(s.expr)
            if isinstance(s, PointerAssignStmt): return expr(s.target) or expr(s.expr)
            if isinstance(s, IfStmt): return expr(s.cond) or any(stmt(x) for x in s.then_block.statements) or (stmt(s.else_branch) if isinstance(s.else_branch, IfStmt) else any(stmt(x) for x in s.else_branch.statements) if isinstance(s.else_branch, Block) else False)
            if isinstance(s, (WhileStmt, LoopStmt, ForLoopStmt)): return (expr(s.cond) if isinstance(s, WhileStmt) else False) or any(stmt(x) for x in s.body.statements)
            if isinstance(s, VariableChangeHandler): return any(stmt(x) for x in s.body.statements)
            return False
        for item in self.program.items:
            if isinstance(item, FunctionDecl) and (item.ret_type == "string" or any(p.type == "string" for p in item.params)): return True
            if isinstance(item, ClassDecl) and any(f.type == "string" for f in item.fields): return True
            if isinstance(item, ClassDecl) and any(m.ret_type == "string" or any(p.type == "string" for p in m.params) for m in item.methods): return True
            if isinstance(item, VarDecl) and item.type == "string": return True
            if isinstance(item, FunctionDecl) and any(stmt(x) for x in item.body.statements): return True
            if isinstance(item, ClassDecl) and any(stmt(x) for m in item.methods for x in m.body.statements): return True
        return False

    def _used_builtin_types(self) -> set:
        used = set()

        def note(t):
            if t in BUILTIN_TYPEDEFS:
                used.add(t)
            gp=self._generic_parts(t)
            if gp:
                for part in self._split_generic_args(gp[1]): note(part)

        for item in self.program.items:
            if isinstance(item, FunctionDecl):
                note(item.ret_type)
                for p in item.params:
                    note(p.type)
                for s in _iter_stmts(item.body.statements):
                    if isinstance(s, VarDecl):
                        note(s.type)
                        if s.type == "auto":
                            used.update(("i32", "f32"))
                    elif isinstance(s, ForLoopStmt):
                        note(s.var_type)
            elif isinstance(item, StructDecl):
                for f in item.fields:
                    note(f.type)
            elif isinstance(item, ClassDecl):
                for f in item.fields:
                    note(f.type)
                for m in item.methods:
                    note(m.ret_type)
                    for p in m.params: note(p.type)
                    for st in _iter_stmts(m.body.statements):
                        if isinstance(st, VarDecl):
                            note(st.type)
                            if st.type == "auto": used.update(("i32", "f32"))
            elif isinstance(item, VarDecl):     # variable globale
                note(item.type)
            elif isinstance(item, TypeAliasDecl):
                # Function-pointer aliases can contain several builtin types.
                # Scan both parameters and return type so their C typedefs are
                # emitted before the alias itself.
                fp = _function_type_parts(item.target)
                if fp is not None:
                    params, ret = fp
                    note(ret)
                    for p in params: note(p)
                else:
                    note(item.target)
        return used


    @staticmethod
    def _generic_parts(t):
        if not isinstance(t, str): return None
        if t == "dynamic_list": return ("dynamic_list", "")
        for k in ("list", "map", "container", "pair"):
            p=k+"<"
            if t.startswith(p) and t.endswith(">"):
                return k,t[len(p):-1]
        return None

    def _split_generic_args(self, inner):
        depth=0; start=0; out=[]
        for i,ch in enumerate(inner):
            if ch=='<': depth+=1
            elif ch=='>': depth-=1
            elif ch==',' and depth==0:
                out.append(inner[start:i].strip()); start=i+1
        out.append(inner[start:].strip())
        return out

    def _pair_c_type(self,t):
        p=self._generic_parts(t)
        if not p or p[0] != "pair": return c_type(t)
        a,b=self._split_generic_args(p[1])
        def clean(x): return canonical_type(x).replace("<","_").replace(">","_").replace(",","_").replace(":","_")
        return f"_jPair_{clean(a)}_{clean(b)}"

    def _pair_typedefs(self):
        pairs=set()
        def note(t):
            p=self._generic_parts(t)
            if p:
                if p[0]=="pair": pairs.add(t)
                for x in self._split_generic_args(p[1]): note(x)
        def scan(stmts, env):
            env=dict(env)
            for st in stmts:
                if isinstance(st, VarDecl):
                    note(st.type); env[st.name]=st.type
                elif isinstance(st, CollectionLoopStmt):
                    ct=env.get(st.collection.name) if isinstance(st.collection, Ident) else None
                    if ct:
                        gp=self._generic_parts(ct)
                        if gp and gp[0]=="map":
                            a,b=self._split_generic_args(gp[1]); note(f"pair<{a},{b}>")
                    scan(st.body.statements, env)
                elif isinstance(st, IfStmt):
                    scan(st.then_block.statements, env)
                    if isinstance(st.else_branch, Block): scan(st.else_branch.statements, env)
                    elif isinstance(st.else_branch, IfStmt): scan([st.else_branch], env)
                elif isinstance(st, (WhileStmt, LoopStmt, ForLoopStmt)):
                    scan(st.body.statements, env)
        for item in self.program.items:
            if isinstance(item, FunctionDecl):
                env={p.name:p.type for p in item.params}
                scan(item.body.statements, env)
            elif isinstance(item, ClassDecl):
                for f in item.fields: note(f.type)
                for m in item.methods:
                    env={p.name:p.type for p in m.params}
                    scan(m.body.statements, env)
            elif isinstance(item, VarDecl): note(item.type)
        out=[]
        # Nested pair types must be emitted from the innermost pair outward,
        # and generic members (e.g. list<pair<...>>) must use their generated
        # C container type instead of a raw Jaguar generic spelling.
        for t in sorted(pairs, key=lambda x: (x.count("<"), x)):
            a,b=self._split_generic_args(self._generic_parts(t)[1]); cn=self._pair_c_type(t)
            ac=self._collection_c_type(a) if self._generic_parts(a) else c_type(a)
            bc=self._collection_c_type(b) if self._generic_parts(b) else c_type(b)
            out.append(f"typedef struct {cn} {{ {ac} first; {bc} second; }} {cn};")
        return out

    def _collection_c_type(self,t):
        p=self._generic_parts(t)
        return {"list":"_jList","map":"_jMap","container":"_jContainer","pair":self._pair_c_type(t),"dynamic_list":"_jDynamicList"}[p[0]] if p else c_type(t)

    def _storage_c_type(self, t):
        return self._collection_c_type(t) if self._generic_parts(t) else c_type(t)

    def _collection_elem_size(self,t):
        if t=="string": return "sizeof(string*)"
        if t in self.classes: return "sizeof(void*)"
        if self._generic_parts(t): return f"sizeof({self._collection_c_type(t)})"
        return f"sizeof({c_type(t)})"

    def _gen_collection_init(self,name,t,init,local_types):
        kind,inner=self._generic_parts(t); out=[]
        if kind=="dynamic_list":
            if init is not None and not isinstance(init, ListLiteral):
                init_type = self.infer_type(init, local_types)
                self._check_assignable("dynamic_list", init_type, f"dynamic_list initializer for '{name}'", init)
                out.append(f"{name} = {self.gen_expr(init,local_types)};")
                return out
            out.append(f'_j_dynamic_list_init(&{name});')
            if init is not None:
                for x in init.items:
                    out.extend(self._gen_dynamic_list_push(name, x, local_types))
        elif kind=="list":
            if init is not None and not isinstance(init, ListLiteral):
                init_type = self.infer_type(init, local_types)
                self._check_assignable(f"list<{inner}>", init_type, f"list initializer for '{name}'", init)
                out.append(f"{name} = {self.gen_expr(init,local_types)};")
                return out
            out.append(f'_j_list_init(&{name},{self._collection_elem_size(inner)},"{inner}");')
            if init is not None:
                for x in init.items:
                    xt=self.infer_type(x,local_types)
                    self._check_assignable(inner, xt, f"item of list '{name}'", x)
                    ex=self.gen_expr(x,local_types); n=self._tmp_id; self._tmp_id+=1
                    if self.c89:
                        out.append("{")
                        out.append(f'    {self._collection_c_type(inner)} _jct{n};')
                        out.append(f'    _jct{n} = {ex};')
                        out.append(f'    _j_list_push(&{name}, &_jct{n});')
                        out.append("}")
                    else:
                        out.append(f'{self._collection_c_type(inner)} _jct{n} = {ex};')
                        out.append(f'_j_list_push(&{name}, &_jct{n});')
        elif kind=="pair":
            parts=self._split_generic_args(inner)
            if len(parts)!=2: raise CodeGenError("pair must have two types")
            if init is not None:
                if isinstance(init, ListLiteral):
                    if len(init.items)!=2: raise CodeGenError("invalid pair initializer: use {first, second}")
                    a,b=parts
                    self._check_assignable(a, self.infer_type(init.items[0],local_types), f"first item of pair '{name}'", init.items[0])
                    self._check_assignable(b, self.infer_type(init.items[1],local_types), f"second item of pair '{name}'", init.items[1])
                    out.append(f"{name}.first = {self.gen_expr(init.items[0],local_types)};")
                    out.append(f"{name}.second = {self.gen_expr(init.items[1],local_types)};")
                else:
                    # A pair is a plain value type: an existing pair of the
                    # same type can initialize it directly, just like a
                    # normal struct value.
                    init_type = self.infer_type(init, local_types)
                    self._check_assignable(f"pair<{parts[0]},{parts[1]}>", init_type, f"pair initializer for '{name}'", init)
                    out.append(f"{name} = {self.gen_expr(init,local_types)};")
        elif kind=="map":
            parts=self._split_generic_args(inner)
            if len(parts)!=2: raise CodeGenError("map must have two types: map<key,value>")
            if init is not None and not isinstance(init, ListLiteral):
                init_type = self.infer_type(init, local_types)
                self._check_assignable(f"map<{parts[0]},{parts[1]}>", init_type, f"map initializer for '{name}'", init)
                out.append(f"{name} = {self.gen_expr(init,local_types)};")
                return out
            kt,vt=parts; out.append(f'_j_map_init(&{name},{self._collection_elem_size(kt)},{self._collection_elem_size(vt)},"{kt}","{vt}");')
            if init is not None:
                if len(init.items)%2: raise CodeGenError("invalid map initializer: use {key, value, ...}")
                for i in range(0,len(init.items),2):
                    self._check_assignable(kt, self.infer_type(init.items[i],local_types), f"key of map '{name}'", init.items[i])
                    self._check_assignable(vt, self.infer_type(init.items[i+1],local_types), f"value of map '{name}'", init.items[i+1])
                    k=self.gen_expr(init.items[i],local_types); v=self.gen_expr(init.items[i+1],local_types)
                    nk=self._tmp_id; self._tmp_id+=1; nv=self._tmp_id; self._tmp_id+=1
                    if self.c89:
                        out.append("{")
                        out.append(f'    {self._storage_c_type(kt)} _jck{nk};')
                        out.append(f'    {self._storage_c_type(vt)} _jcv{nv};')
                        out.append(f'    _jck{nk} = {k};')
                        out.append(f'    _jcv{nv} = {v};')
                        out.append(f'    _j_map_emplace(&{name}, &_jck{nk}, &_jcv{nv});')
                        out.append("}")
                    else:
                        out.append(f'{self._storage_c_type(kt)} _jck{nk} = {k};')
                        out.append(f'{self._storage_c_type(vt)} _jcv{nv} = {v};')
                        out.append(f'_j_map_emplace(&{name}, &_jck{nk}, &_jcv{nv});')
        else:
            if init is None: out.append(f'_j_container_init(&{name},0,"{inner}",0);')
            elif isinstance(init,NewExpr):
                if init.type!=inner: raise CodeGenError(f"new {init.type} is incompatible with container<{inner}>")
                if inner in self.classes:
                    ctor=self.resolve_class_constructor_call(inner, init.args, local_types)
                    ordered=self._ordered_call_args(init.args,ctor.params,f"constructeur '{inner}'") if ctor else []
                    args=", ".join(self.gen_expr(a,local_types) for a in ordered)
                    symbol = ctor.mangled_name if ctor else f"{inner}_ctor"
                    out.append(f'_j_container_init(&{name},(void*){symbol}({args}),"{inner}",(void(*)(void*)){inner}_destr);')
                else:
                    if len(init.args)!=1: raise CodeGenError(f"new {inner}(...) expects a value")
                    value = init.args[0].expr if isinstance(init.args[0],NamedArg) else init.args[0]
                    self._check_assignable(inner, self.infer_type(value,local_types), f"container initializer for '{name}'", value)
                    ex=self.gen_expr(value,local_types)
                    out.append(f'{{ {self._storage_c_type(inner)} *_jtmp=( {self._storage_c_type(inner)}*)malloc(sizeof({self._storage_c_type(inner)})); if(!_jtmp)abort(); *_jtmp={ex}; _j_container_init(&{name},_jtmp,"{inner}",0); }}')
            else:
                self._check_assignable(inner, self.infer_type(init,local_types), f"container initializer for '{name}'", init)
                ex=self.gen_expr(init,local_types); out.append(f'{{ {self._storage_c_type(inner)} *_jtmp=({self._storage_c_type(inner)}*)malloc(sizeof({self._storage_c_type(inner)})); if(!_jtmp)abort(); *_jtmp={ex}; _j_container_init(&{name},_jtmp,"{inner}",0); }}')
        return out

    def _gen_dynamic_list_push(self, name, expr_node, local_types):
        t=self.infer_type(expr_node, local_types)
        temp_type = t
        if isinstance(t, tuple):
            temp_type = "int" if t[1] == "int" else "float"
            t = "i32" if t[1] == "int" else "f32"
        if t is None or t == "void":
            raise CodeGenError("dynamic_list.push() cannot determine the value type")
        runtime_type = t
        seen_aliases = set()
        while isinstance(runtime_type, str) and runtime_type in self.type_aliases and runtime_type not in seen_aliases:
            seen_aliases.add(runtime_type)
            runtime_type = self.type_aliases[runtime_type]
        gp = self._generic_parts(runtime_type) if isinstance(runtime_type, str) else None
        runtime_head = gp[0] if gp else runtime_type
        if runtime_head in {"list", "map", "container"}:
            raise CodeGenError(
                f"dynamic_list.push() cannot store owning collection type '{t}' because the runtime would copy ownership unsafely"
            )
        if runtime_head == "dynamic_list":
            raise CodeGenError(
                "dynamic_list.push() cannot store another dynamic_list because the runtime does not provide nested ownership semantics"
            )
        ex=self.gen_expr(expr_node, local_types)
        n=self._tmp_id; self._tmp_id += 1
        if t == "string":
            return [f'_j_dynamic_list_push_owned(&{name}, (void*){ex}, "string", _j_destroy_string_value);']
        if t in self.classes:
            if isinstance(expr_node, NewExpr):
                return [f'_j_dynamic_list_push_owned(&{name}, (void*){ex}, "{t}", (void(*)(void*)){t}_destr);']
            return [f'_j_dynamic_list_push_borrowed(&{name}, (void*){ex}, "{t}");']
        return [f'{{ {self._storage_c_type(temp_type)} _jdlv{n} = {ex}; _j_dynamic_list_push_copy(&{name}, &_jdlv{n}, sizeof(_jdlv{n}), "{t}"); }}']

    def _uses_collections(self):
        def typ(t):
            return isinstance(t, str) and (t == "dynamic_list" or t.startswith("list<") or t.startswith("map<") or t.startswith("container<"))
        def expr(e):
            if isinstance(e, (ListLiteral, NewExpr)): return True
            if isinstance(e, Call): return expr(e.callee) or any(expr(a) for a in e.args)
            if isinstance(e, MemberAccess): return expr(e.obj)
            if isinstance(e, IndexAccess): return expr(e.obj) or expr(e.index)
            if isinstance(e, CastExpr): return expr(e.operand)
            if isinstance(e, UnaryOp): return expr(e.operand)
            if isinstance(e, BinOp): return expr(e.left) or expr(e.right)
            return False
        def stmt(st):
            if isinstance(st, VarDecl): return typ(st.type) or (expr(st.init) if st.init else False)
            if isinstance(st, (AssignStmt, MemberAssignStmt)): return expr(st.expr) or (expr(st.target) if isinstance(st, MemberAssignStmt) else False)
            if isinstance(st, ExprStmt): return expr(st.expr)
            if isinstance(st, ReturnStmt): return expr(st.expr) if st.expr else False
            if isinstance(st, IfStmt): return expr(st.cond) or any(stmt(x) for x in st.then_block.statements) or (any(stmt(x) for x in st.else_branch.statements) if isinstance(st.else_branch, Block) else stmt(st.else_branch) if isinstance(st.else_branch, IfStmt) else False)
            if isinstance(st, (WhileStmt, LoopStmt, ForLoopStmt)): return (expr(st.cond) if isinstance(st, WhileStmt) else False) or any(stmt(x) for x in st.body.statements)
            return False
        for item in self.program.items:
            if isinstance(item, VarDecl) and typ(item.type): return True
            if isinstance(item, FunctionDecl) and (typ(item.ret_type) or any(typ(p.type) for p in item.params) or any(stmt(x) for x in item.body.statements)): return True
            if isinstance(item, ClassDecl) and (any(typ(f.type) for f in item.fields) or any(stmt(x) for m in item.methods for x in m.body.statements)): return True
        return False

    def _collection_runtime(self):
        if not self._uses_collections(): return ""
        return "\n".join([
            "/* Jaguar containers: runtime polymorphic storage, no C templates. */",
            "#include <string.h>",
            "typedef struct _jDynamicItem { void *data; size_t size; const char *type; void (*destroy)(void*); } _jDynamicItem;",
            "typedef struct _jDynamicList { _jDynamicItem *items; size_t size; size_t cap; } _jDynamicList;",
            "typedef struct _jList { void **items; size_t size; size_t cap; size_t elem_size; const char *elem_type; } _jList;",
            "typedef struct _jMapEntry { void *key; void *value; } _jMapEntry;",
            "typedef struct _jMap { _jMapEntry *items; size_t size; size_t cap; size_t key_size; size_t value_size; const char *key_type; const char *value_type; } _jMap;",
            "typedef struct _jContainer { void *data; const char *type; void (*destroy)(void*); } _jContainer;",
            "static void *_j_memdup(const void *src,size_t n){void*p=malloc(n);if(p&&src)memcpy(p,src,n);return p;}",
            "static void _j_destroy_string_value(void*p){if(p)_j_untrack_literal((string*)p);}",
            "static void _j_dynamic_list_init(_jDynamicList*l){l->items=0;l->size=0;l->cap=0;}",
            "static void _j_dynamic_list_grow(_jDynamicList*l){if(l->size==l->cap){size_t nc=l->cap?l->cap*2:4;_jDynamicItem*ni=(_jDynamicItem*)realloc(l->items,nc*sizeof(_jDynamicItem));if(!ni)abort();l->items=ni;l->cap=nc;}}",
            "static void _j_dynamic_list_push_copy(_jDynamicList*l,const void*v,size_t n,const char*t){_j_dynamic_list_grow(l);l->items[l->size].data=_j_memdup(v,n);if(!l->items[l->size].data)abort();l->items[l->size].size=n;l->items[l->size].type=t;l->items[l->size].destroy=0;l->size++;}",
            "static void _j_dynamic_list_borrowed(void*p){(void)p;}",
            "static void _j_dynamic_list_push_owned(_jDynamicList*l,void*v,const char*t,void(*destroy)(void*)){_j_dynamic_list_grow(l);l->items[l->size].data=v;l->items[l->size].size=sizeof(void*);l->items[l->size].type=t;l->items[l->size].destroy=destroy;l->size++;}",
            "static void _j_dynamic_list_push_borrowed(_jDynamicList*l,void*v,const char*t){_j_dynamic_list_push_owned(l,v,t,_j_dynamic_list_borrowed);}",
            "static void *_j_dynamic_list_get(_jDynamicList*l,size_t i){if(!l||i>=l->size){fprintf(stderr,\"Jaguar runtime error: dynamic_list index %lu out of range\\n\",(unsigned long)i);abort();}return l->items[i].data;}",
            "static const char *_j_dynamic_list_type(_jDynamicList*l,size_t i){if(!l||i>=l->size){fprintf(stderr,\"Jaguar runtime error: dynamic_list index %lu out of range\\n\",(unsigned long)i);abort();}return l->items[i].type;}",
            "static void _j_dynamic_list_destroy(_jDynamicList*l){size_t i;if(!l)return;for(i=0;i<l->size;i++){if(l->items[i].destroy!=_j_dynamic_list_borrowed){if(l->items[i].destroy)l->items[i].destroy(l->items[i].data);free(l->items[i].data);}}free(l->items);l->items=0;l->size=0;l->cap=0;}",
            "static void _j_list_init(_jList*l,size_t es,const char*t){l->items=0;l->size=0;l->cap=0;l->elem_size=es;l->elem_type=t;}",
            "static void _j_destroy_string_slot(void*p){string*s=p?*(string**)p:0;if(s){string_destr(s);}}",
            "static void _j_list_push(_jList*l,const void*v){void*p;if(l->size==l->cap){size_t nc=l->cap?l->cap*2:4;void**ni=(void**)realloc(l->items,nc*sizeof(void*));if(!ni)abort();l->items=ni;l->cap=nc;}p=_j_memdup(v,l->elem_size);if(!p)abort();l->items[l->size++]=p;}",
            "static void *_j_list_get(_jList*l,size_t i){if(!l||i>=l->size){fprintf(stderr,\"Jaguar runtime error: list index %lu out of range\\n\",(unsigned long)i);abort();}return l->items[i];}",
            "static void _j_list_destroy(_jList*l,void(*destroy)(void*)){size_t i;if(!l)return;for(i=0;i<l->size;i++){if(destroy)destroy(l->items[i]);free(l->items[i]);}free(l->items);l->items=0;l->size=0;l->cap=0;}",
            "static void _j_map_init(_jMap*m,size_t ks,size_t vs,const char*kt,const char*vt){m->items=0;m->size=0;m->cap=0;m->key_size=ks;m->value_size=vs;m->key_type=kt;m->value_type=vt;}",
            "static int _j_map_keyeq(const void*a,const void*b,size_t n,const char*t){if(!strcmp(t,\"string\")){string*sa=*(string**)a;string*sb=*(string**)b;return sa&&sb&&sa->data&&sb->data&&!strcmp(sa->data,sb->data);}return memcmp(a,b,n)==0;}",
            "static void *_j_map_get(_jMap*m,const void*k){size_t i;for(i=0;i<m->size;i++)if(_j_map_keyeq(m->items[i].key,k,m->key_size,m->key_type))return m->items[i].value;return 0;}",
            "static void *_j_map_get_i8(_jMap*m,int8_t k){return _j_map_get(m,&k);}",
            "static void *_j_map_get_i16(_jMap*m,int16_t k){return _j_map_get(m,&k);}",
            "static void *_j_map_get_i32(_jMap*m,int32_t k){return _j_map_get(m,&k);}",
            "static void *_j_map_get_i64(_jMap*m,int64_t k){return _j_map_get(m,&k);}",
            "static void *_j_map_get_u8(_jMap*m,uint8_t k){return _j_map_get(m,&k);}",
            "static void *_j_map_get_u16(_jMap*m,uint16_t k){return _j_map_get(m,&k);}",
            "static void *_j_map_get_u32(_jMap*m,uint32_t k){return _j_map_get(m,&k);}",
            "static void *_j_map_get_u64(_jMap*m,uint64_t k){return _j_map_get(m,&k);}",
            "static void *_j_map_get_f32(_jMap*m,float k){return _j_map_get(m,&k);}",
            "static void *_j_map_get_f64(_jMap*m,double k){return _j_map_get(m,&k);}",
            "static void *_j_map_get_bool(_jMap*m,_jBool k){return _j_map_get(m,&k);}",
            "static void *_j_map_get_string(_jMap*m,string*k){size_t i;for(i=0;i<m->size;i++){string*sk=*(string**)m->items[i].key;if(sk&&k&&sk->data&&k->data&&!strcmp(sk->data,k->data))return m->items[i].value;}fprintf(stderr,\"Jaguar runtime error: map key not found\\n\");abort();return 0;}",
            "static void *_j_map_get_string_cstr(_jMap*m,const char*k){size_t i;for(i=0;i<m->size;i++){string*sk=*(string**)m->items[i].key;if(sk&&sk->data&&k&&!strcmp(sk->data,k))return m->items[i].value;}fprintf(stderr,\"Jaguar runtime error: map key not found\\n\");abort();return 0;}",
            "static void _j_map_emplace(_jMap*m,const void*k,const void*v){size_t i;void*kp;void*vp;for(i=0;i<m->size;i++)if(_j_map_keyeq(m->items[i].key,k,m->key_size,m->key_type)){memcpy(m->items[i].value,v,m->value_size);return;}if(m->size==m->cap){size_t nc=m->cap?m->cap*2:4;_jMapEntry*ni=(_jMapEntry*)realloc(m->items,nc*sizeof(_jMapEntry));if(!ni)abort();m->items=ni;m->cap=nc;}kp=_j_memdup(k,m->key_size);vp=_j_memdup(v,m->value_size);if(!kp||!vp)abort();m->items[m->size].key=kp;m->items[m->size].value=vp;m->size++;}",
            "static void _j_map_destroy(_jMap*m,void(*kd)(void*),void(*vd)(void*)){size_t i;if(!m)return;for(i=0;i<m->size;i++){if(kd)kd(m->items[i].key);if(vd)vd(m->items[i].value);free(m->items[i].key);free(m->items[i].value);}free(m->items);m->items=0;m->size=0;m->cap=0;}",
            "static void _j_container_init(_jContainer*c,void*d,const char*t,void(*destroy)(void*)){c->data=d;c->type=t;c->destroy=destroy;}",
            "static void *_j_container_get(_jContainer*c){if(!c||!c->data){fprintf(stderr,\"Jaguar runtime error: empty container access\\n\");abort();}return c->data;}",
            "static void _j_container_destroy(_jContainer*c){if(!c)return;if(c->data){if(c->destroy)c->destroy(c->data);else free(c->data);}c->data=0;c->destroy=0;}",
        ])

    def _native_reflection_prelude(self):
        return "\n".join([
            "typedef struct _jReflectEntry { const char *name; void *ptr; const char *type_name; } _jReflectEntry;",
            "typedef struct _jReflectMap { _jReflectEntry *entries; size_t count; } _jReflectMap;",
            "typedef struct _jReflectVTable { const char *type_name; _jReflectEntry *(*get_member)(void*, const char*); } _jReflectVTable;",
            "static _jReflectEntry *_j_reflect_find(void *obj, const char *name) { _jReflectVTable *vt; if (!obj || !name) return 0; vt=*(_jReflectVTable**)obj; return (vt&&vt->get_member)?vt->get_member(obj,name):0; }",
            "static void *_j_reflect_get_member(void *obj, const char *name) { _jReflectEntry *e=_j_reflect_find(obj,name); if(!e){fprintf(stderr,\"Jaguar runtime error: member '%s' does not exist or is not exposed\\n\",name?name:\"<null>\"); return 0;} return e->ptr; }",
            "static const char *_j_reflect_get_type(void *obj, const char *name) { _jReflectEntry *e=_j_reflect_find(obj,name); return e?e->type_name:0; }",
            "static _jBool _j_reflect_member_exists(void *obj,const char *name) { return _j_reflect_find(obj,name)!=0; }",
            "",
            "static void _j_reflect_set_member(void *obj,const char *name,const char *src_type,long long si,unsigned long long ui,double f,string *str,void *ptr) {",
            "    _jReflectEntry *e=_j_reflect_find(obj,name); if(!e||!e->ptr||!e->type_name||!src_type){fprintf(stderr,\"Jaguar runtime error: member '%s' does not exist or is not exposed\\n\",name?name:\"<null>\");return;}",
            '    if(!strcmp(e->type_name,"string")&&!strcmp(src_type,"string")){*(string**)e->ptr=str;return;}',
            '    if(!strcmp(e->type_name,"i32")||!strcmp(e->type_name,"int")){*(int*)e->ptr=(int)(f && (!strcmp(src_type,"f32")||!strcmp(src_type,"f64")||!strcmp(src_type,"float")) ? f : si);return;}',
            '    if(!strcmp(e->type_name,"u32")){*(unsigned int*)e->ptr=(unsigned int)ui;return;}',
            '    if(!strcmp(e->type_name,"i64")){*(long long*)e->ptr=(long long)si;return;}',
            '    if(!strcmp(e->type_name,"u64")){*(unsigned long long*)e->ptr=(unsigned long long)ui;return;}',
            '    if(!strcmp(e->type_name,"f32")||!strcmp(e->type_name,"float")){*(float*)e->ptr=(float)f;return;}',
            '    if(!strcmp(e->type_name,"f64")){*(double*)e->ptr=f;return;}',
            '    if(!strcmp(e->type_name,"bool")){*(unsigned char*)e->ptr=(unsigned char)si;return;}',
            "    fprintf(stderr,\"Jaguar runtime error: cannot assign value of type '%s' to reflected member '%s' of type '%s'\\n\",src_type,name?name:\"<null>\",e->type_name);",
            "}",
        ])

    def _native_reflection_runtime(self):
        # Le runtime réflexion/factory n'est émis que si le programme
        # possède réellement des classes. Cela évite d'injecter des types
        # (_jBool, string, etc.) et des helpers inutiles dans un programme
        # Jaguar qui n'utilise pas la réflexion.
        if not any(name != "string" for name in self.classes):
            return ""
        registered=[]
        for c in self.classes.values():
            if c.name == "string" or not c.is_registered:
                continue
            # Registration requires a constructor that is actually callable
            # with no arguments. Looking only at the first constructor is
            # incorrect once constructors are overloaded.
            try:
                self.resolve_class_constructor_call(c.name, [], {})
            except CodeGenError:
                continue
            registered.append(c)
        exposed_any=any(getattr(f,"is_exposed",False) for c in self.classes.values() for f in c.fields)
        # Le runtime factory doit exister même lorsqu'aucune classe n'est
        # actuellement enregistrée : `factory:construct()` est résolu au
        # runtime et son argument peut être une string dynamique.
        lines=[
            "/* Jaguar native dynamic reflection / factory runtime. */", "#include <string.h>",
            "static void _j_reflect_print(void *obj,const char *name) {",
            "    _jReflectEntry *e=_j_reflect_find(obj,name); if(!e){printf(\"<null>\\n\");return;}",
            "    if(!strcmp(e->type_name,\"string\")){string *s=*(string**)e->ptr;printf(\"%s\\n\",(s&&s->data)?s->data:\"\");}",
            "    else if(!strcmp(e->type_name,\"bool\")){printf(\"%s\\n\",*(unsigned char*)e->ptr?\"true\":\"false\");}",
            "    else if(!strcmp(e->type_name,\"i32\")||!strcmp(e->type_name,\"int\")){printf(\"%d\\n\",*(int*)e->ptr);}",
            "    else if(!strcmp(e->type_name,\"u32\")){printf(\"%u\\n\",*(unsigned int*)e->ptr);}",
            "    else if(!strcmp(e->type_name,\"i64\")){printf(\"%lld\\n\",*(long long*)e->ptr);}",
            "    else if(!strcmp(e->type_name,\"u64\")){printf(\"%llu\\n\",*(unsigned long long*)e->ptr);}",
            "    else if(!strcmp(e->type_name,\"f32\")||!strcmp(e->type_name,\"float\")){printf(\"%g\\n\",(double)*(float*)e->ptr);}",
            "    else if(!strcmp(e->type_name,\"f64\")){printf(\"%g\\n\",*(double*)e->ptr);}",
            "    else printf(\"<object:%s>\\n\",e->type_name);",
            "}",
        ]
        lines += [
            "static void *_j_factory_construct(string *name) {",
            "    if(!name||!name->data) {",
            '        fprintf(stderr, "Jaguar runtime error: factory:construct() received a null class name\\n");',
            "        abort();",
            "    }",
        ]
        for c in registered:
            ctor = self.resolve_class_constructor_call(c.name, [], {})
            if ctor is None:
                ctor_args = ""
                ctor_symbol = f"{c.name}_ctor"
            else:
                ordered = self._ordered_call_args([], ctor.params, f"constructor '{c.name}'")
                ctor_args = ", ".join(self.gen_expr(arg, {}) for arg in ordered)
                ctor_symbol = ctor.mangled_name
            lines.append(f'    if(strcmp(name->data,"{c.name}")==0)return(void*){ctor_symbol}({ctor_args});')
        lines += [
            '    fprintf(stderr, "Jaguar runtime error: cannot construct class \'%s\': class is not registered\\n", name->data);',
            "    abort();",
            "    return 0;",
            "}",
        ]
        return "\n".join(lines)

    # -- déclarations --
    def gen_item(self, item) -> str:
        if hasattr(item, "namespace"):
            self._current_namespace = getattr(item, "namespace", None)
        self._current_source_line = getattr(item, "_jaguar_line", 1)
        if isinstance(item, PreprocLine):
            return item.text
        if isinstance(item, (ForwardDecl, TypeAliasDecl, UsingNamespaceDecl, UsingSymbolDecl, UsingImportDecl, EnumDecl, DecoratorDecl)):
            return ""
        if isinstance(item, StructDecl):
            return self.gen_struct(item)
        if isinstance(item, UnionDecl):
            return self.gen_union(item)
        if isinstance(item, ClassDecl):
            return self.gen_class(item)
        if isinstance(item, FunctionDecl):
            if item.is_prototype:
                params = [self._param_c_decl(p) for p in item.params]
                if item.is_variadic:
                    params.append("...")
                return self._function_return_c_decl(item.ret_type, item.mangled_name, params) + ";"
            return self.gen_function(item)
        if isinstance(item, VarDecl):
            return self.gen_global_var(item)
        if isinstance(item, TopExprStmt):
            return self.gen_expr(item.expr, {}) + ";"
        raise NotImplementedError(f"item non géré: {item!r}")

    # -- variables globales ---------------------------------------------
    #
    # En C (C89 comme C99), l'initialiseur d'une variable de portée fichier
    # doit être une expression constante. On le vérifie ici pour donner une
    # erreur Jaguar claire plutôt qu'une erreur obscure du compilateur C.
    def _is_const_expr(self, e) -> bool:
        if isinstance(e, (IntLit, FloatLit, StringLit, BoolLit)):
            return True
        if isinstance(e, Ident):
            # un identifiant qui n'est pas une variable globale est supposé
            # être une macro #define (ex: M_PI), donc constant
            return e.name not in self.global_types
        if isinstance(e, CastExpr):
            return self._is_const_expr(e.operand)
        if isinstance(e, UnaryOp):
            return self._is_const_expr(e.operand)
        if isinstance(e, BinOp):
            return self._is_const_expr(e.left) and self._is_const_expr(e.right)
        return False   # Call, NamespacedIdent, ...

    def gen_global_var(self, v: VarDecl) -> str:
        if v.is_extern:
            if v.init is not None:
                raise CodeGenError(f"extern global variable '{v.name}' cannot have an initializer")
            return "extern " + self._var_c_decl(v) + ";"
        if self._generic_parts(v.type):
            raise CodeGenError("list/map/container must currently be local variables")
        ctype = c_type(v.type)
        if v.init is None:
            return f"{ctype} {v.name};"
        if v.type.endswith("*"):
            init_type = self.infer_type(v.init, {})
            if isinstance(v.init, Ident) and v.init.name == "NULL":
                raise CodeGenError(
                    f"pointer variable '{v.name}' must be initialized with 'nullptr'; C-style 'NULL' is not allowed"
                )
            if isinstance(init_type, tuple):
                init_desc = init_type[1]
            elif init_type is None:
                init_desc = "an unknown expression"
            else:
                init_desc = init_type
            if init_type != "nullptr" and not (isinstance(init_type, str) and init_type.endswith("*")):
                raise CodeGenError(
                    f"pointer variable '{v.name}' must be initialized with a pointer expression or 'nullptr', not {init_desc}"
                )
        if v.type == "string":
            raise CodeGenError("global variables of type 'string' must be initialized at runtime")
        if not self._is_const_expr(v.init):
            raise CodeGenError(
                f"initializer of global variable '{v.name}' must be a "
                f"constant expression (literals, #define macros, operations between "
                f"constants): function calls and references to another variable are not allowed"
                f""
            )
        return f"{self._var_c_decl(v)} = {self.gen_expr(v.init, {})};"

    def _field_c_decl(self, f) -> str:
        # Fields may contain C function-pointer aliases/types. A raw c_type()
        # would leave `fn(...) -> T` in the generated C, which is invalid.
        fp = self._function_ptr_c_decl(f.type, f.name)
        if fp is not None:
            return fp
        arr = self._fixed_array_parts(f.type)
        if arr is not None:
            base, dims = arr
            suffix = "".join(f"[{d}]" for d in dims)
            return f"{self._decl_c_type(base)} {f.name}{suffix}"
        base_type = self._collection_c_type(f.type) if self._generic_parts(f.type) else c_type(f.type)
        if getattr(f, "type", "").endswith("*") and getattr(f, "pointee_const", False):
            return "const " + c_type(f.type[:-1]) + " * " + f.name
        if getattr(f, "type", "").endswith("*") and getattr(f, "is_const", False):
            return c_type(f.type) + " const " + f.name
        if getattr(f, "is_const", False):
            return "const " + base_type + " " + f.name
        return base_type + " " + f.name

    def gen_struct(self, s: StructDecl) -> str:
        lines = [f"struct {s.name} {{"]
        for f in s.fields:
            lines.append(f"    {self._field_c_decl(f)};")
        lines.append("};")
        lines.append(
            f"static {s.name} _j_struct_{s.name}_default(void) {{ "
            f"{s.name} value; memset(&value, 0, sizeof(value)); return value; }}"
        )

        # Value construction with arguments is deliberately implemented by a
        # normal C function instead of a C99 compound literal. This keeps the
        # same Jaguar semantics in `--c89` mode and gives us a single place to
        # materialize the fields in declaration order. Array fields are not
        # assignable in C and therefore cannot participate in positional
        # struct construction.
        if s.fields:
            params = []
            for i, f in enumerate(s.fields):
                if self._fixed_array_parts(f.type) is not None:
                    raise CodeGenError(
                        f"struct '{s.name}' positional construction is not supported when field '{f.name}' is an array"
                    )
                fp = self._function_ptr_c_decl(f.type, f"_j_arg{i}")
                if fp is not None:
                    params.append(fp)
                else:
                    params.append(f"{self._decl_c_type(f.type)} _j_arg{i}")
            lines.append(f"static {s.name} _j_struct_{s.name}_make(" + ", ".join(params) + ") {")
            lines.append(f"    {s.name} value;")
            for i, f in enumerate(s.fields):
                lines.append(f"    value.{f.name} = _j_arg{i};")
            lines.append("    return value;")
            lines.append("}")

        lines.append(
            f"static {s.name} *_j_struct_{s.name}_new(void) {{ "
            f"{s.name} *value = ({s.name}*)calloc(1, sizeof({s.name})); "
            "if (!value) abort(); return value; }"
        )
        return "\n".join(lines)

    def gen_union(self, u: UnionDecl) -> str:
        lines = [f"union {u.name} {{"]
        for f in u.fields:
            lines.append(f"    {self._field_c_decl(f)};")
        lines.append("};")
        # Jaguar's named union declaration exposes one global union value with
        # the same name. This is what makes `val.a = 5` valid after
        # `union val { int a; float b; }`.
        lines.append(f"union {u.name} _j_union_{u.name};")
        return "\n".join(lines)

    def _class_all_fields(self, cls):
        out=[]
        if cls.base: out += self._class_all_fields(self.classes[cls.base])
        out += [(cls.name, f) for f in cls.fields]
        return out

    def _find_class_member(self, clsname, name, kind="field"):
        cls=self.classes.get(clsname)
        while cls:
            seq=cls.fields if kind=="field" else cls.methods
            for x in seq:
                if x.name==name: return cls,x
            cls=self.classes.get(cls.base) if cls.base else None
        return None,None

    def _find_class_method_candidates(self, clsname, name):
        """Collect visible methods by signature, with derived declarations
        replacing inherited methods that have the same logical signature."""
        chain = []
        cls = self.classes.get(clsname)
        while cls:
            chain.append(cls)
            cls = self.classes.get(cls.base) if cls.base else None
        by_sig = {}
        for owner in reversed(chain):
            for m in owner.methods:
                if m.name == name and not m.is_constructor and not m.is_destructor:
                    sig = tuple(p.type for p in m.params)
                    by_sig[sig] = (owner, m)
        return list(by_sig.values())

    def resolve_class_method_call(self, clsname, name, args, local_types, receiver_const=False):
        candidates = self._find_class_method_candidates(clsname, name)
        if receiver_const:
            candidates = [(owner, method) for owner, method in candidates if method.is_const]
            if not candidates:
                raise CodeGenError(f"cannot call non-const method '{name}' on a const object")
        if not candidates:
            return None, None
        prepared = []
        if len(candidates) == 1:
            owner, method = candidates[0]
            ordered = self._ordered_call_args(args, method.params, f"'{name}'")
            for arg, param in zip(ordered, method.params):
                at = self.infer_type(arg.expr if isinstance(arg, NamedArg) else arg, local_types)
                self._check_assignable(param.type, at, f"argument '{param.name}' of method '{name}'", arg.expr if isinstance(arg, NamedArg) else arg)
            return owner, method
        for owner, method in candidates:
            try:
                ordered = self._ordered_call_args(args, method.params, f"'{name}'")
                for arg, param in zip(ordered, method.params):
                    at = self.infer_type(arg.expr if isinstance(arg, NamedArg) else arg, local_types)
                    self._check_assignable(param.type, at, f"argument '{param.name}' of method '{name}'", arg.expr if isinstance(arg, NamedArg) else arg)
            except CodeGenError:
                continue
            prepared.append((owner, method, ordered))
        if len(prepared) == 1:
            return prepared[0][0], prepared[0][1]
        scored = []
        for owner, method, ordered in prepared:
            arg_types = [self.infer_type(a, local_types) for a in ordered]
            if len(method.params) == len(ordered):
                scores = [self._implicit_type_match(p.type, at) for p, at in zip(method.params, arg_types)]
                if all(scores):
                    scored.append((sum(scores), owner, method))
        if scored:
            best = max(x[0] for x in scored)
            matches = [(owner, method) for score, owner, method in scored if score == best]
        else:
            matches = []
        if len(matches) == 1:
            return matches[0]
        if not matches:
            raise CodeGenError(f"no overload of '{name}' matches the provided argument types")
        raise CodeGenError(f"ambiguous call to overloaded method '{name}'")

    def resolve_class_constructor_call(self, clsname, args, local_types):
        """Resolve a class constructor using the normal overload rules."""
        cls = self.classes[clsname]
        candidates = [m for m in cls.methods if m.is_constructor]
        if not candidates:
            if args:
                raise CodeGenError(f"'{cls.name}' has no constructor taking arguments")
            return None

        prepared = []
        for ctor in candidates:
            try:
                ordered = self._ordered_call_args(args, ctor.params, f"constructor '{cls.name}'")
                for arg, param in zip(ordered, ctor.params):
                    at = self.infer_type(arg, local_types)
                    self._check_assignable(
                        param.type, at,
                        f"argument '{param.name}' of constructor '{cls.name}'",
                        arg
                    )
            except CodeGenError:
                continue
            prepared.append((ctor, ordered))

        if not prepared:
            raise CodeGenError(f"no constructor of '{cls.name}' matches the provided argument types")
        if len(prepared) == 1:
            return prepared[0][0]

        scored = []
        for ctor, ordered in prepared:
            arg_types = [self.infer_type(a, local_types) for a in ordered]
            scores = [self._implicit_type_match(p.type, at) for p, at in zip(ctor.params, arg_types)]
            if len(scores) == len(ordered) and all(scores):
                scored.append((sum(scores), ctor))
        if scored:
            best = max(x[0] for x in scored)
            matches = [ctor for score, ctor in scored if score == best]
        else:
            matches = []
        if len(matches) == 1:
            return matches[0]
        raise CodeGenError(f"ambiguous constructor call for '{cls.name}'")

    def _expr_is_const_receiver(self, expr, local_types):
        """Return whether an expression denotes a const class instance."""
        if isinstance(expr, Ident):
            if expr.name == "this":
                return bool(self._current_class_method_const)
            t = local_types.get(expr.name)
            g = None
            if t is None:
                g = self._resolve_global_name(expr.name)
                t = self.global_types.get(g) if g else None
            if t in self.classes:
                return (expr.name in getattr(self, "_const_object_vars", set())
                        or (g is not None and g in getattr(self, "global_const", set())))
            if isinstance(t, str) and t.endswith("*"):
                return expr.name in getattr(self, "_pointee_const_vars", set())
            return False
        if isinstance(expr, MemberAccess):
            if self._expr_is_const_receiver(expr.obj, local_types):
                return True
            ot = self.infer_type(expr.obj, local_types)
            base = ot.rstrip("*") if isinstance(ot, str) else ot
            if base in self.classes:
                owner, field = self._find_class_member(base, expr.name, "field")
                if field is not None and getattr(field, "is_const", False):
                    return field.type in self.classes
            return False
        if isinstance(expr, UnaryOp) and expr.op == "*":
            return self._expr_is_const_receiver(expr.operand, local_types)
        return False

    @staticmethod
    def _check_const_receiver_method(method, receiver_const, name):
        if receiver_const and not method.is_const:
            raise CodeGenError(f"cannot call non-const method '{name}' on a const object")

    @staticmethod
    def _vtable_method_name(method):
        """Stable vtable field name shared by overrides with the same signature."""
        if not method.params:
            return method.name
        suffix = "_".join(
            p.type.replace("*", "_ptr")
                 .replace("<", "_")
                 .replace(">", "_")
                 .replace(",", "_")
                 .replace(":", "_")
            for p in method.params
        )
        return f"{method.name}_{suffix}"

    def gen_class(self, cls: ClassDecl) -> str:
        self._current_namespace = cls.namespace
        # Validate class-level signals once, while the complete field list is
        # available. A class signal may only refer to a field of this class or
        # one of its bases.
        signal_handlers = {}
        for signal in getattr(cls, "signals", []):
            if signal.name in signal_handlers:
                raise CodeGenError(f"signal: multiple handlers for member '{signal.name}' in class '{cls.name}'")
            owner, member = self._find_class_member(cls.name, signal.name, "field")
            if member is None:
                raise CodeGenError(f"signal: member '{signal.name}' is not declared in class '{cls.name}'")
            signal_handlers[signal.name] = signal.body
        # Emit a C struct with an explicit vtable. Inheritance is represented
        # by embedding the base object as `_base`, preserving public layout.
        lines=[f"typedef struct {cls.name}_vtable {cls.name}_vtable;"]
        lines.append(f"struct {cls.name} {{")
        lines.append(f"    {cls.name}_vtable *_vptr;")
        if cls.base: lines.append(f"    {cls.base} _base;")
        if any(getattr(f, "is_exposed", False) for _, f in self._class_all_fields(cls)):
            lines.append("    _jReflectMap _reflect_map;")
        for f in cls.fields:
            lines.append(f"    {self._field_c_decl(f)};")
        lines.append("};")
        lines.append(f"struct {cls.name}_vtable {{")
        # Keep reflection metadata first so every class vtable has the same
        # native prefix and can be inspected through _jReflectVTable.
        lines.append("    const char *type_name;")
        lines.append("    _jReflectEntry *(*get_member)(void *self, const char *name);")
        virt=[]
        for m in self._all_virtual_methods(cls):
            virt.append(m)
            ps=", ".join(["const void *self" if m.is_const else "void *self"] + [("const " if p.is_const else "") + f"{self._decl_c_type(p.type)} {p.name}" for p in m.params])
            lines.append(f"    {self._decl_c_type(m.ret_type)} (*{self._vtable_method_name(m)})({ps});")
        lines.append("};")
        # Native reflection: each registered/exposed class gets a typed member lookup.
        exposed = [f for f in self._class_all_fields(cls) if getattr(f[1], "is_exposed", False)]
        lines.append(f"static _jReflectEntry *{cls.name}_get_member(void *obj, const char *name) {{")
        lines.append(f"    {cls.name} *self = ({cls.name}*)obj;")
        if exposed:
            lines.append("    size_t i;")
            lines.append("    if (!self->_reflect_map.entries) return 0;")
            lines.append("    for (i = 0; i < self->_reflect_map.count; ++i)")
            lines.append("        if (strcmp(self->_reflect_map.entries[i].name, name) == 0) return &self->_reflect_map.entries[i];")
        lines.append("    return 0;")
        lines.append("}")
        # constructors/prototypes are needed before method bodies
        for m in cls.methods:
            if m.is_constructor or m.is_destructor: continue
            self_decl = f"const {cls.name} *self" if m.is_const else f"{cls.name} *self"
            ps=", ".join([self_decl]+[("const " if p.is_const else "") + f"{self._decl_c_type(p.type)} {p.name}" for p in m.params])
            lines.append(f"{self._decl_c_type(m.ret_type)} {m.mangled_name or (cls.name + "_" + m.name)}({ps});")
        # Every Jaguar class gets a destructor entry point, even when the
        # user did not explicitly write `destr()`. This lets automatic scope
        # cleanup always call `<Class>_destr()` and lets an implicit derived
        # destructor destroy its base subobject.
        lines.append(f"void {cls.name}_destr({cls.name} *self);")
        lines.append(f"{cls.name} *{cls.name}_new(void);")
        for m in cls.methods:
            if m.is_constructor:
                ps=", ".join(f"{self._decl_c_type(p.type)} {p.name}" for p in m.params)
                lines.append(f"{cls.name} *{m.mangled_name}({ps});")
        if not any(m.is_constructor for m in cls.methods):
            lines.append(f"{cls.name} *{cls.name}_ctor(void);")
        # vtable definition
        lines.append(f"static {cls.name}_vtable {cls.name}_vtable_instance = {{")
        lines.append(f"    \"{cls.name}\",")
        lines.append(f"    {cls.name}_get_member,")
        for m in virt:
            self_qual = "const void *" if m.is_const else "void *"
            lines.append(f"    ({c_type(m.ret_type)} (*)({self_qual}{', ' if m.params else ''}{', '.join(self._decl_c_type(p.type)+' '+p.name for p in m.params)})){m.mangled_name or (cls.name + '_' + m.name)},")
        lines.append("};")
        # methods
        old=self._current_class; old_const=self._current_class_method_const; self._current_class=cls
        old_readonly=set(self._readonly_vars)
        old_return=getattr(self, "_current_return_type", None)
        old_change_handlers=dict(self._change_handlers)
        for m in cls.methods:
            if m.is_constructor or m.is_destructor: continue
            self_decl = f"const {cls.name} *self" if m.is_const else f"{cls.name} *self"
            ps=", ".join([self_decl]+[("const " if p.is_const else "")+f"{self._decl_c_type(p.type)} {p.name}" for p in m.params])
            method_readonly=set(self._readonly_vars)
            self._current_class_method_const=m.is_const
            self._current_return_type=m.ret_type
            self._current_source_line=getattr(m, "_jaguar_line", self._current_source_line)
            self._readonly_vars = set(old_readonly) | {p.name for p in m.params if p.is_const}
            self._change_handlers = dict(signal_handlers)
            body = self.gen_block(m.body, {p.name:p.type for p in m.params})
            self._readonly_vars = method_readonly
            if m.ret_type != "void" and not self._block_guarantees_return(m.body):
                err = CodeGenError(
                    f"non-void function '{m.name}' may exit without returning a value of type '{m.ret_type}'"
                )
                err._jaguar_line = getattr(m, "_jaguar_line", self._current_source_line)
                err._jaguar_column = getattr(m, "_jaguar_column", 0)
                err._jaguar_end_column = getattr(m, "_jaguar_end_column", err._jaguar_column + len(m.name))
                raise err
            lines.append(f"{self._decl_c_type(m.ret_type)} {m.mangled_name or (cls.name + "_" + m.name)}({ps}) {body}")
        # Each explicit constructor is a real overload with its own C symbol.
        # A class without an explicit constructor still gets an implicit
        # no-argument constructor named `<Class>_ctor`.
        ctors = [m for m in cls.methods if m.is_constructor]
        for ctor in (ctors if ctors else [None]):
            ctor_params = ctor.params if ctor else []
            ctor_body = ctor.body if ctor else Block([])
            ctor_symbol = ctor.mangled_name if ctor else f"{cls.name}_ctor"
            ps=", ".join(f"{self._decl_c_type(p.type)} {p.name}" for p in ctor_params)
            lines.append(f"{cls.name} *{ctor_symbol}({ps}) {{")
            lines.append(f"    {cls.name} *self = ({cls.name}*)calloc(1, sizeof({cls.name}));")
            lines.append("    if (!self) return 0;")
            lines.append(f"    self->_vptr = &{cls.name}_vtable_instance;")
            if cls.base:
                base_local_types = {p.name: p.type for p in ctor_params}
                base_args = [Ident(p.name) for p in ctor_params]
                base_ctor = self.resolve_class_constructor_call(cls.base, base_args, base_local_types)
                if base_ctor is not None:
                    base_ordered = self._ordered_call_args(base_args, base_ctor.params, f"constructor '{cls.base}'")
                    args = ", ".join(self.gen_expr(a, base_local_types) for a in base_ordered)
                    base_has_reflection = any(getattr(f, "is_exposed", False) for _, f in self._class_all_fields(self.classes[cls.base]))
                    base_symbol = base_ctor.mangled_name
                    if base_has_reflection:
                        lines.append(f"    {{ {cls.base} *_base_tmp = {base_symbol}({args}); if (_base_tmp) {{ self->_base = *_base_tmp; _base_tmp->_reflect_map.entries = 0; _base_tmp->_reflect_map.count = 0; free(_base_tmp); }} }}")
                    else:
                        lines.append(f"    {{ {cls.base} *_base_tmp = {base_symbol}({args}); if (_base_tmp) {{ self->_base = *_base_tmp; free(_base_tmp); }} }}")
                elif ctor_params:
                    raise CodeGenError(
                        f"constructor '{cls.name}' has no compatible constructor in base class '{cls.base}'"
                    )
            if exposed:
                lines.append(f"    self->_reflect_map.count = {len(exposed)};")
                lines.append(f"    self->_reflect_map.entries = (_jReflectEntry*)calloc({len(exposed)}, sizeof(_jReflectEntry));")
                lines.append("    if (!self->_reflect_map.entries) { free(self); return 0; }")
                for idx, (owner, f) in enumerate(exposed):
                    access_expr = self._base_member_expr("self", cls, f.name)
                    lines.append(f'    self->_reflect_map.entries[{idx}].name = "{f.name}";')
                    lines.append(f"    self->_reflect_map.entries[{idx}].ptr = (void*)&{access_expr};")
                    lines.append(f'    self->_reflect_map.entries[{idx}].type_name = "{f.type}";')
            for f in cls.fields:
                field_local_types = {p.name:p.type for p in ctor_params}
                if self._generic_parts(f.type):
                    for field_line in self._gen_collection_init(f"self->{f.name}", f.type, f.init, field_local_types):
                        lines.append("    " + field_line)
                elif f.init is not None:
                    lines.append(f"    self->{f.name} = {self.gen_expr(f.init, field_local_types)};")
            # user ctor body
            old2=self._current_class; self._current_class=cls
            old2_const=self._current_class_method_const
            old2_readonly=set(self._readonly_vars)
            old2_const_objects=set(getattr(self, "_const_object_vars", set()))
            old2_return=getattr(self, "_current_return_type", None); self._current_return_type="void"
            self._current_class_method_const=False
            self._readonly_vars=set(old_readonly)
            self._const_object_vars=set()
            for line in self._gen_body_lines(ctor_body.statements, {p.name:p.type for p in ctor_params}): lines.append("    "+line)
            self._current_class=old2; self._current_class_method_const=old2_const; self._readonly_vars=old2_readonly; self._const_object_vars=old2_const_objects; self._current_return_type=old2_return
            lines.append("    return self;"); lines.append("}")
        # Class-level signals are active while an explicit/implicit destructor
        # body executes as well; field cleanup itself happens after the body.
        destr=next((m for m in cls.methods if m.is_destructor),None)
        # A destructor is always generated. If the user supplied one, its
        # body runs first. The base destructor is then invoked automatically.
        # This means `destr()` is optional and inheritance remains safe.
        lines.append(f"void {cls.name}_destr({cls.name} *self) {{")
        old3=self._current_class; self._current_class=cls
        old3_const=self._current_class_method_const
        old3_readonly=set(self._readonly_vars)
        old3_const_objects=set(getattr(self, "_const_object_vars", set()))
        old3_return=getattr(self, "_current_return_type", None); self._current_return_type="void"
        self._current_class_method_const=False
        self._readonly_vars=set(old_readonly)
        self._const_object_vars=set()
        self._change_handlers = dict(signal_handlers)
        if destr:
            for line in self._gen_body_lines(destr.body.statements, {}):
                lines.append("    "+line)
        for field_cleanup in self._class_field_cleanup_lines(cls):
            lines.append("    " + field_cleanup)
        if cls.base:
            lines.append(f"    {cls.base}_destr(&self->_base);")
        self._current_class=old3; self._current_class_method_const=old3_const; self._readonly_vars=old3_readonly; self._const_object_vars=old3_const_objects; self._current_return_type=old3_return; self._change_handlers=old_change_handlers
        lines.append("}")
        self._current_class=old; self._current_class_method_const=old_const; self._readonly_vars=old_readonly; self._current_return_type=old_return; self._change_handlers=old_change_handlers
        return "\n".join(lines)

    def _class_field_cleanup_lines(self, cls):
        """Nettoyage automatique des champs dont la classe possède la mémoire."""
        lines = []
        for f in reversed(cls.fields):
            name = f"self->{f.name}"
            gp = self._generic_parts(f.type)
            if gp:
                kind, inner = gp
                if kind == "dynamic_list":
                    lines.append(f"_j_dynamic_list_destroy(&{name});")
                elif kind == "list":
                    d = "_j_destroy_string_slot" if inner == "string" else "0"
                    lines.append(f"_j_list_destroy(&{name},{d});")
                elif kind == "map":
                    parts = self._split_generic_args(inner)
                    kd = "_j_destroy_string_slot" if parts and parts[0] == "string" else "0"
                    vd = "_j_destroy_string_slot" if len(parts) > 1 and parts[1] == "string" else "0"
                    lines.append(f"_j_map_destroy(&{name},{kd},{vd});")
                elif kind == "container":
                    lines.append(f"_j_container_destroy(&{name});")
                elif kind == "pair":
                    parts = self._split_generic_args(inner)
                    if len(parts) == 2:
                        if parts[0] == "string":
                            lines.append(f"if ({name}.first) string_destr({name}.first);")
                        if parts[1] == "string":
                            lines.append(f"if ({name}.second) string_destr({name}.second);")
                continue
            if f.type == "string":
                lines.append(f"if ({name}) string_destr({name});")
            elif isinstance(f.type, str) and f.type.endswith("*") and f.type[:-1] in self.classes:
                base = f.type[:-1]
                lines.append(f"if ({name}) {base}_destr({name});")
                lines.append(f"if ({name}) free({name});")
        return lines

    def _all_virtual_methods(self, cls):
        ordered=[]
        if cls.base: ordered += self._all_virtual_methods(self.classes[cls.base])
        for m in cls.methods:
            if m.is_virtual or m.is_override:
                for i,x in enumerate(ordered):
                    if x.name==m.name and [p.type for p in x.params]==[p.type for p in m.params]: ordered[i]=m; break
                else: ordered.append(m)
        return ordered

    @staticmethod
    def default_mangle(name: str, namespace: Optional[str]) -> str:
        """Nom C de repli : un chemin Jaguar a:b:c devient a_b_c."""
        if namespace:
            return f"{namespace.replace(':', '_')}_{name}"
        return name

    def _resolve_class_name(self, name: str, namespace: Optional[str] = None) -> Optional[str]:
        if name in self.classes:
            return name
        ns = namespace if namespace is not None else self._current_namespace
        if ns:
            q = f"{ns.replace(':', '_')}_{name}"
            if q in self.classes: return q
        for imported in self.using_namespaces:
            q = f"{imported.replace(':', '_')}_{name}"
            if q in self.classes: return q
        return None

    def _resolve_global_name(self, name: str, namespace: Optional[str] = None) -> Optional[str]:
        if name in self.global_types: return name
        ns = namespace if namespace is not None else self._current_namespace
        if ns:
            q = f"{ns.replace(':', '_')}_{name}"
            if q in self.global_types: return q
        for imported in self.using_namespaces:
            q = f"{imported.replace(':', '_')}_{name}"
            if q in self.global_types: return q
        return None

    def _resolve_struct_name(self, name: str, namespace: Optional[str] = None) -> Optional[str]:
        if name in self.structs: return name
        ns = namespace if namespace is not None else self._current_namespace
        if ns:
            q = f"{ns.replace(':', '_')}_{name}"
            if q in self.structs: return q
        for imported in self.using_namespaces:
            q = f"{imported.replace(':', '_')}_{name}"
            if q in self.structs: return q
        return None

    # -- cas spécial : la fonction main() ------------------------------
    #
    # Côté Jaguar, main a une signature fixe : `void main(string param)`
    # (ou `void main()`). Mais en C, main() ne peut être écrit que
    # "int main(void)" ou "int main(int argc, char *argv[])" -- générer
    # `main(string param)` produirait du C invalide / non portable.
    #
    # On garde donc "string" côté langage Jaguar (c'est ce que l'utilisateur
    # écrit et voit), et on traduit uniquement au moment de la génération :
    #   - le paramètre string de Jaguar est lié à argv[1] (chaîne vide si
    #     l'utilisateur ne fournit pas d'argument) ;
    #   - "return;" (void, tel qu'écrit en Jaguar) devient "return 0;" ;
    #   - un "return 0;" final est ajouté si le bloc ne se termine pas
    #     déjà par un return (on ne compte pas sur la règle C99 du
    #     "fall off the end of main returns 0").
    @staticmethod
    def _is_special_main(fn: FunctionDecl) -> bool:
        return fn.namespace is None and fn.name == "main"

    @staticmethod
    def _function_type_parts(t: str):
        m = re.fullmatch(r"fn\((.*)\) -> (.+)", t)
        if not m:
            return None
        raw_params, ret = m.group(1), m.group(2).strip()
        params = [] if not raw_params.strip() else [x.strip() for x in raw_params.split(",")]
        return params, ret

    @staticmethod
    def _fixed_array_parts(t):
        if not isinstance(t, str):
            return None
        m = re.match(r"^(.*?)(?:\[(\d+)\])+$", t)
        if not m:
            return None
        base = m.group(1)
        dims = [int(x) for x in re.findall(r"\[(\d+)\]", t)]
        return base, dims

    def _decl_c_type(self, t: str) -> str:
        """Lower a Jaguar type at a C ABI boundary.

        Bare class values are represented by pointers in generated code: local
        class variables already use `Class *`, so function parameters and return
        values must use the same representation. Pointer types (`Class*`) keep
        their explicit pointer depth and generic types keep their runtime C
        container representation.
        """
        if isinstance(t, str) and t in self.classes and t != "string":
            return f"{t} *"
        return self._collection_c_type(t) if self._generic_parts(t) else c_type(t)

    def _function_ptr_c_decl(self, t: str, name: str) -> Optional[str]:
        parts = self._function_type_parts(t)
        if not parts:
            return None
        params, ret = parts
        variadic = bool(params and params[-1] == "...")
        fixed = params[:-1] if variadic else params
        cparams = ", ".join(self._decl_c_type(x) for x in fixed) if fixed else "void"
        if variadic:
            cparams = (cparams + ", " if cparams != "void" else "") + "..."
        return f"{self._decl_c_type(ret)} (*{name})({cparams})"

    def _function_return_c_decl(self, ret_type: str, name: str, params: list[str]) -> str:
        """Build a C declaration for a Jaguar function returning a function pointer.

        Jaguar represents a C function pointer type as `fn(...) -> R`. When that
        type is itself the return type of another function, it cannot be emitted
        with the ordinary `R name(args)` form because `fn(...) -> R` is not C
        syntax. The C declarator must put the function name inside the pointer
        declarator:

            R (*name(args))(callback_args)

        The resolver may expand a callback alias before CodeGen reaches this
        point, so this helper intentionally works from the expanded Jaguar type.
        """
        parts = self._function_type_parts(ret_type)
        if not parts:
            cparams = ", ".join(params) if params else "void"
            return f"{self._decl_c_type(ret_type)} {name}({cparams})"

        returned_params, returned_ret = parts
        returned_cparams = (
            ", ".join(self._decl_c_type(x) for x in returned_params)
            if returned_params else "void"
        )
        outer_cparams = ", ".join(params) if params else "void"
        return (
            f"{self._decl_c_type(returned_ret)} "
            f"(*{name}({outer_cparams}))({returned_cparams})"
        )

    def _pointee_c_type(self, t: str) -> str:
        """Lower one pointer pointee type without introducing an implicit
        class pointer twice. `A` is `A *` at ABI boundaries, but the pointee
        of `A*` is still the class object `A`, not another pointer."""
        if isinstance(t, str) and t in self.classes and t != "string":
            return t
        if self._generic_parts(t):
            return self._collection_c_type(t)
        return c_type(t)

    def _param_c_decl(self, p: Param) -> str:
        fp = self._function_ptr_c_decl(p.type, p.name)
        if fp is not None:
            return fp
        arr = self._fixed_array_parts(p.type)
        if arr is not None:
            base, _dims = arr
            return f"{self._decl_c_type(base)} * {p.name}"
        if p.type.endswith("*") and p.pointee_const:
            base = "const " + self._pointee_c_type(p.type[:-1]) + " *"
        elif p.type.endswith("*") and p.is_const:
            base = self._decl_c_type(p.type) + " const"
        elif p.is_const:
            base = "const " + self._decl_c_type(p.type)
        else:
            base = self._decl_c_type(p.type)
        return f"{base} {p.name}"

    def _var_c_decl(self, v: VarDecl) -> str:
        fp = self._function_ptr_c_decl(v.type, v.name)
        if fp is not None:
            return fp
        arr = self._fixed_array_parts(v.type)
        if arr is not None:
            base, dims = arr
            suffix = "".join(f"[{d}]" for d in dims)
            return f"{self._decl_c_type(base)} {v.name}{suffix}"
        if v.type.endswith("*") and v.pointee_const:
            base = "const " + self._pointee_c_type(v.type[:-1]) + " *"
        elif v.type.endswith("*") and v.is_const:
            base = c_type(v.type) + " const"
        elif v.is_const:
            base = "const " + self._decl_c_type(v.type)
        else:
            base = self._decl_c_type(v.type)
        return f"{base} {v.name}"

    @staticmethod
    def _block_has_break_for_current_loop(block, nested_loop_depth=0) -> bool:
        """Return whether this loop body can execute a `break` that exits it.

        Breaks belonging to nested loops do not make the outer loop fall
        through. This distinction matters for return-path analysis of
        unconditional `loop {}` / `while (true) {}` constructs.
        """
        for stmt in getattr(block, "statements", []):
            if isinstance(stmt, BreakStmt):
                if nested_loop_depth == 0:
                    return True
                continue
            if isinstance(stmt, IfStmt):
                if CodeGen._block_has_break_for_current_loop(stmt.then_block, nested_loop_depth):
                    return True
                if isinstance(stmt.else_branch, Block) and CodeGen._block_has_break_for_current_loop(stmt.else_branch, nested_loop_depth):
                    return True
                if isinstance(stmt.else_branch, IfStmt) and CodeGen._statement_has_break_for_current_loop(stmt.else_branch, nested_loop_depth):
                    return True
                continue
            if isinstance(stmt, (LoopStmt, WhileStmt, ForLoopStmt, CollectionLoopStmt)):
                if CodeGen._block_has_break_for_current_loop(stmt.body, nested_loop_depth + 1):
                    return True
        return False

    @staticmethod
    def _statement_has_break_for_current_loop(stmt, nested_loop_depth=0) -> bool:
        if isinstance(stmt, BreakStmt):
            return nested_loop_depth == 0
        if isinstance(stmt, IfStmt):
            if CodeGen._block_has_break_for_current_loop(stmt.then_block, nested_loop_depth):
                return True
            if isinstance(stmt.else_branch, Block):
                return CodeGen._block_has_break_for_current_loop(stmt.else_branch, nested_loop_depth)
            if isinstance(stmt.else_branch, IfStmt):
                return CodeGen._statement_has_break_for_current_loop(stmt.else_branch, nested_loop_depth)
        return False

    @staticmethod
    def _statement_guarantees_return(stmt) -> bool:
        # This predicate really means "control cannot fall through this
        # statement". A return does so by returning; an unconditional loop
        # does so by never reaching the following statement unless it has a
        # break targeting that loop.
        if isinstance(stmt, ReturnStmt):
            return stmt.expr is not None
        if isinstance(stmt, IfStmt):
            if not CodeGen._block_guarantees_return(stmt.then_block):
                return False
            if isinstance(stmt.else_branch, Block):
                return CodeGen._block_guarantees_return(stmt.else_branch)
            if isinstance(stmt.else_branch, IfStmt):
                return CodeGen._statement_guarantees_return(stmt.else_branch)
            return False
        if isinstance(stmt, LoopStmt):
            return not CodeGen._block_has_break_for_current_loop(stmt.body)
        if isinstance(stmt, WhileStmt):
            if isinstance(stmt.cond, BoolLit) and stmt.cond.value:
                return not CodeGen._block_has_break_for_current_loop(stmt.body)
        return False

    @staticmethod
    def _block_guarantees_return(block) -> bool:
        for stmt in getattr(block, "statements", []):
            if CodeGen._statement_guarantees_return(stmt):
                return True
        return False

    def _find_decorator(self, name, namespace):
        return self.decorators.get((namespace, name)) or self.decorators.get((None, name))

    def _gen_decorator_wrapper(self, fn: FunctionDecl, public_name: str, target_name: str, use: DecoratorUse, index: int) -> str:
        dec = self._find_decorator(use.name, fn.namespace)
        if dec is None:
            raise CodeGenError(f"unknown decorator '@{use.name}'")
        fn_param_names = {p.name for p in fn.params}
        if any(p.name in fn_param_names for p in dec.params):
            raise CodeGenError(f"decorator '@{use.name}' parameter names must not collide with decorated function parameters")
        target_types = {p.name: p.type for p in fn.params}
        ordered = self._ordered_call_args(use.args, dec.params, f"decorator '@{use.name}'")
        for arg, p in zip(ordered, dec.params):
            self._check_assignable(p.type, self.infer_type(arg, target_types), f"argument '{p.name}' of decorator '@{use.name}'", arg)
        wrapper_name = public_name if index == 0 else f"{public_name}__decor_{index}"
        params_c = [self._param_c_decl(p) for p in fn.params]
        header = self._function_return_c_decl("void", wrapper_name, params_c)
        local_types = dict(target_types)
        local_types.update({p.name: p.type for p in dec.params})
        self._current_namespace = dec.namespace
        self._current_source_line = getattr(use, "_jaguar_line", getattr(fn, "_jaguar_line", 1))
        self._change_handlers = {}
        self._readonly_vars = {p.name for p in fn.params if p.is_const} | {p.name for p in dec.params if p.is_const}
        self._const_object_vars = {p.name for p in fn.params if p.is_const and p.type in self.classes}
        self._pointee_const_vars = {p.name for p in fn.params if p.pointee_const}
        self._current_return_type = "void"
        self._current_function_local_types = local_types
        self._decorator_call_target_name = target_name
        self._decorator_target_params = list(fn.params)
        try:
            decls = [f"{self._decl_c_type(p.type)} {p.name} = {self.gen_expr(arg, target_types)};" for p, arg in zip(dec.params, ordered)]
            body_lines = self._gen_body_lines(dec.body.statements, local_types)
        finally:
            self._decorator_call_target_name = None
            self._decorator_target_params = []
        lines = [f"{header} {{"]
        lines.extend("    " + x for x in decls)
        lines.extend("    " + x for x in body_lines)
        lines.append("}")
        return "\n".join(lines)

    def gen_function(self, fn: FunctionDecl) -> str:
        self._current_namespace = fn.namespace
        self._current_source_line = getattr(fn, "_jaguar_line", 1)
        if self._is_special_main(fn):
            return self._gen_main(fn)

        self._change_handlers = {}
        if fn.is_variadic and not fn.is_prototype:
            raise CodeGenError("variadic Jaguar functions must currently be prototypes/@extern; Jaguar does not expose va_list yet")
        if fn.decorators and (fn.is_prototype or fn.is_extern or fn.ret_type != "void"):
            raise CodeGenError("decorators currently require a non-extern, non-prototype void function")
        params = [self._param_c_decl(p) for p in fn.params]
        if fn.is_variadic:
            params.append("...")
        public_name = fn.mangled_name
        implementation_name = fn.implementation_name or public_name
        header = self._function_return_c_decl(fn.ret_type, implementation_name, params)
        local_types = {p.name: p.type for p in fn.params}
        self._current_function_local_types = local_types
        self._readonly_vars = {p.name for p in fn.params if p.is_const}
        self._const_object_vars = {p.name for p in fn.params if p.is_const and p.type in self.classes}
        self._pointee_const_vars = {p.name for p in fn.params if p.pointee_const}
        self._current_return_type = fn.ret_type
        body = self.gen_block(fn.body, local_types)
        if fn.ret_type != "void" and not self._block_guarantees_return(fn.body):
            err = CodeGenError(f"non-void function '{fn.name}' may exit without returning a value of type '{fn.ret_type}'")
            err._jaguar_line = getattr(fn, "_jaguar_line", 1)
            err._jaguar_column = getattr(fn, "_jaguar_column", 0)
            err._jaguar_end_column = getattr(fn, "_jaguar_end_column", err._jaguar_column + len(fn.name))
            raise err
        impl = f"{header} {body}"
        if not fn.decorators:
            return impl
        target = implementation_name
        wrappers=[]
        for index in range(len(fn.decorators)-1, -1, -1):
            wrapper_name = public_name if index == 0 else f"{public_name}__decor_{index}"
            wrappers.append(self._gen_decorator_wrapper(fn, public_name, target, fn.decorators[index], index))
            target = wrapper_name
        return impl + "\n\n" + "\n\n".join(reversed(wrappers))

    def _gen_main(self, fn: FunctionDecl) -> str:
        if fn.ret_type != "void":
            err = CodeGenError("main() must use return type 'void' in Jaguar")
            err._jaguar_line = getattr(fn, "_jaguar_line", 1)
            err._jaguar_column = getattr(fn, "_jaguar_column", 0)
            err._jaguar_end_column = getattr(fn, "_jaguar_end_column", err._jaguar_column + len(fn.name))
            raise err
        if len(fn.params) == 0:
            header = "int main(void)"
            prelude_lines: List[str] = []
            local_types: dict = {}
        elif len(fn.params) == 1 and fn.params[0].type == "string":
            param_name = fn.params[0].name
            used_names = {param_name}

            def collect_declared_names(node):
                if node is None:
                    return
                if isinstance(node, VarDecl):
                    used_names.add(node.name)
                    collect_declared_names(node.init)
                    return
                if isinstance(node, ForLoopStmt):
                    used_names.add(node.var_name)
                    collect_declared_names(node.start); collect_declared_names(node.end)
                    collect_declared_names(node.body)
                    return
                if isinstance(node, CollectionLoopStmt):
                    used_names.add(node.var_name)
                    collect_declared_names(node.collection); collect_declared_names(node.body)
                    return
                if isinstance(node, list):
                    for item in node:
                        collect_declared_names(item)
                    return
                if hasattr(node, "__dict__"):
                    for value in node.__dict__.values():
                        if isinstance(value, (str, int, float, bool, type(None))):
                            continue
                        collect_declared_names(value)

            collect_declared_names(fn.body)
            argc_name = "_j_main_argc"
            argv_name = "_j_main_argv"
            while argc_name in used_names:
                argc_name += "_"
            while argv_name in used_names or argv_name == argc_name:
                argv_name += "_"
            header = f"int main(int {argc_name}, char *{argv_name}[])"
            prelude_lines = [f'string *{param_name} = string_from_cstr(({argc_name} > 1) ? {argv_name}[1] : "");']
            local_types = {param_name: "string"}
        else:
            raise CodeGenError(
                "main() must be declared either without parameters or with a "
                "single parameter of type 'string' (invalid main declaration)"
            )

        # Le prélude (liaison de argv[1]) est lui-même une déclaration : il
        # doit rester en tête, avant les variables locales de l'utilisateur.
        # _in_main : tout `return;` (même dans un if / une boucle imbriquée)
        # devient `return 0;`
        self._change_handlers = {}
        self._readonly_vars = set()
        self._const_object_vars = set()
        self._pointee_const_vars = set()
        self._current_return_type = fn.ret_type
        self._in_main = True
        body_lines = self._gen_body_lines(fn.body.statements, local_types)
        self._in_main = False
        ends_with_return = (
            len(fn.body.statements) > 0
            and isinstance(fn.body.statements[-1], ReturnStmt)
        )
        if not ends_with_return:
            body_lines.append("return 0;")

        lines = [f"{header} {{"]
        lines.extend(f"    {line}" for line in prelude_lines)
        lines.extend(f"    {line}" for line in body_lines)
        lines.append("}")
        return "\n".join(lines)

    # -- corps de bloc : déclarations de variables + instructions -------
    #
    # Mode par défaut : chaque déclaration reste EXACTEMENT à sa place, avec
    # son initialiseur (`bool b = true;` -> `_jBool b = 1;`).
    #
    # Mode c89 : C89 exige que les déclarations précèdent toutes les
    # instructions d'un bloc. Règle appliquée ici :
    #   - déclaration située AVANT la première instruction : émise telle
    #     quelle, initialiseur compris (`i32 x = 1;`) ;
    #   - déclaration située APRÈS une instruction : remontée en tête de
    #     bloc sans initialiseur (`i32 y;`), et l'initialisation reste à
    #     sa place d'origine (`y = expr;`), ce qui préserve l'ordre
    #     d'évaluation.
    #
    # La même règle s'applique à chaque bloc imbriqué (if / else / while /
    # for_loop) : C89 autorise les déclarations en tête de N'IMPORTE quel
    # bloc, donc chaque bloc a ses propres déclarations.
    def _resolve_auto_type(self, expr, local_types: dict) -> str:
        t = self.infer_type(expr, local_types)
        if isinstance(t, tuple) and t[0] == "literal":
            return "i32" if t[1] == "int" else "f32"
        if t is None:
            raise CodeGenError("cannot deduce the type of 'auto' variable")
        # `void_ptr` is an internal Jaguar type used by runtime APIs that
        # intentionally expose an untyped pointer (for example
        # `dynamic_list.get()`). It must become an actual C `void *` when
        # `auto` materializes the inferred type.
        if t == "void*":
            return "void*"
        return canonical_type(t)

    def _is_owned_class_type(self, type_name: str) -> bool:
        return type_name in self.classes

    def _scope_cleanup_lines(self, owned, exclude_names=None) -> List[str]:
        out = []
        exclude_names = exclude_names or set()
        for name, type_name in reversed(owned):
            if name in exclude_names:
                continue
            gp=self._generic_parts(type_name)
            if gp:
                kind,inner=gp
                if kind=="dynamic_list":
                    out.append(f"_j_dynamic_list_destroy(&{name});")
                elif kind=="list":
                    d="_j_destroy_string_slot" if inner=="string" else "0"
                    out.append(f"_j_list_destroy(&{name},{d});")
                elif kind=="map":
                    parts=self._split_generic_args(inner)
                    kd="_j_destroy_string_slot" if parts and parts[0]=="string" else "0"
                    vd="_j_destroy_string_slot" if len(parts)>1 and parts[1]=="string" else "0"
                    out.append(f"_j_map_destroy(&{name},{kd},{vd});")
                elif kind=="pair":
                    parts=self._split_generic_args(inner)
                    if len(parts)==2:
                        if parts[0]=="string": out.extend([f"if ({name}.first) {{ string_destr({name}.first); }}"])
                        if parts[1]=="string": out.extend([f"if ({name}.second) {{ string_destr({name}.second); }}"])
                else: out.append(f"_j_container_destroy(&{name});")
            else:
                if type_name == "string":
                    out.append(f"if ({name}) string_destr({name});")
                elif type_name in self.classes:
                    if name in getattr(self, "_const_object_vars", set()):
                        out.append(f"if ({name}) {type_name}_destr(({type_name}*){name});")
                    else:
                        out.append(f"if ({name}) {type_name}_destr({name});")
                elif isinstance(type_name, str) and type_name.endswith("*"):
                    base = type_name[:-1]
                    if base in self.classes:
                        out.append(f"if ({name}) {base}_destr({name});")
                    out.append(f"if ({name}) free({name});")
                else:
                    out.append(f"if ({name}) {type_name}_destr({name});")
                    out.append(f"free({name});")
        return out

    def _all_active_cleanup_lines(self, exclude_names=None) -> List[str]:
        out = []
        exclude_names = exclude_names or set()
        for owned in reversed(self._scope_owned):
            out.extend(self._scope_cleanup_lines(owned, exclude_names))
        return out

    def _loop_cleanup_lines(self) -> List[str]:
        base = self._loop_scope_bases[-1] if self._loop_scope_bases else 0
        out = []
        for owned in reversed(self._scope_owned[base:]):
            out.extend(self._scope_cleanup_lines(owned))
        return out

    def _gen_body_lines(self, statements: list, local_types: dict) -> List[str]:
        decl_lines: List[str] = []
        old_dynamic_reflection = set(getattr(self, "_dynamic_reflection_vars", set()))
        self._dynamic_reflection_vars = set(old_dynamic_reflection)
        stmt_lines: List[str] = []
        in_prefix = True
        owned = []
        self._scope_owned.append(owned)

        for s in statements:
            if isinstance(s, (UsingNamespaceStmt, UsingSymbolStmt, TypeAliasStmt)):
                continue
            self._current_source_line = getattr(s, "_jaguar_line", self._current_source_line)
            if isinstance(s, VarDecl):
                if s.name in local_types:
                    raise CodeGenError(
                        f"variable '{s.name}' is already declared "
                        f"(parameter or variable with the same name)"
                    )
                if s.name in self.global_types:
                    raise CodeGenError(
                        f"local variable '{s.name}' shadows a global variable "
                        f"with the same name"
                    )
                if s.type.endswith("*") and s.init is not None:
                    init_type = self.infer_type(s.init, local_types)
                    if isinstance(s.init, Ident) and s.init.name == "NULL":
                        raise CodeGenError(
                            f"pointer variable '{s.name}' must be initialized with 'nullptr'; C-style 'NULL' is not allowed"
                        )
                    if isinstance(init_type, tuple):
                        init_desc = init_type[1]
                    elif init_type is None:
                        init_desc = "an unknown expression"
                    else:
                        init_desc = init_type
                    if (
                        init_type != "nullptr"
                        and not (isinstance(init_type, str) and init_type.endswith("*"))
                        and not (s.type == "i8*" and isinstance(s.init, StringLit))
                    ):
                        raise CodeGenError(
                            f"pointer variable '{s.name}' must be initialized with a pointer expression or 'nullptr', not {init_desc}"
                        )
                # `auto` is resolved from its initializer.
                if s.type == "auto":
                    s.type = self._resolve_auto_type(s.init, local_types)
                # A brace literal (`{...}`) initializing a generic container
                # (list<T>, map<K,V>, pair<A,B>, dynamic_list) has no type of
                # its own to infer here: it is validated and consumed by the
                # dedicated _gen_collection_init() logic below instead.
                if s.init is not None and s.type != "auto" and not (isinstance(s.init, ListLiteral) and self._generic_parts(s.type)):
                    init_type = self._check_expression_types(s.init, local_types)
                    self._target_pointee_const = s.pointee_const
                    self._check_assignable(s.type, init_type, f"initializer of variable '{s.name}'", s.init)
                    self._target_pointee_const = False
                if self._generic_parts(s.type):
                    init = None
                elif s.init is not None and s.type != "auto" and s.type in self.classes and isinstance(s.init, Call) and isinstance(s.init.callee, NamespacedIdent) and s.init.callee.namespace == "factory" and s.init.callee.name == "construct":
                    if len(s.init.args) != 1:
                        raise CodeGenError("factory:construct() expects exactly one class name")
                    init = f"({s.type}*)_j_factory_construct({self.gen_expr(s.init.args[0].expr if isinstance(s.init.args[0], NamedArg) else s.init.args[0], local_types)})"
                elif s.init is not None and isinstance(s.init, Call) and self._is_reflection_call(s.init):
                    # GetMember() est dynamique et retourne un void*. Dans un
                    # contexte typé, le type déclaré de la destination fournit
                    # implicitement le type à lire. Pas besoin d'écrire
                    # `(int)h.GetMember(name)`.
                    init = self._gen_reflection_value(s.init, s.type, local_types)
                else:
                    init = (
                        self._gen_expr_for_expected_type(s.init, s.type, local_types)
                        if s.init is not None else None
                    )
                if self._generic_parts(s.type):
                    local_types[s.name] = s.type
                    decl = f"{self._collection_c_type(s.type)} {s.name};"
                    if self.c89:
                        decl_lines.append(decl)
                    else:
                        stmt_lines.append(decl)
                    stmt_lines.extend(self._gen_collection_init(s.name,s.type,s.init,local_types))
                    owned.append((s.name,s.type))
                    if self.c89 and s.init is not None:
                        in_prefix = False
                    continue
                local_types[s.name] = s.type
                if isinstance(s.init, Call) and isinstance(s.init.callee, NamespacedIdent) and s.init.callee.namespace == "factory" and s.init.callee.name == "construct":
                    self._dynamic_reflection_vars.add(s.name)
                if not hasattr(self, "_pointee_const_vars"): self._pointee_const_vars = set()
                if s.pointee_const: self._pointee_const_vars.add(s.name)
                if self._is_owned_class_type(s.type):
                    owned.append((s.name, s.type))
                elif s.init is not None and isinstance(s.init, NewExpr) and s.type.endswith("*"):
                    owned.append((s.name, s.type))
                ctype = c_type(s.type)
                is_class = s.type in self.classes
                if is_class:
                    # Une variable de classe Jaguar est une propriété possédée
                    # par pointeur, comme les objets alloués par le runtime.
                    # Sans initialiseur explicite, construire l'objet par le
                    # constructeur sans arguments (ou avec ses valeurs par
                    # défaut) évite tout pointeur indéfini au nettoyage de portée.
                    if s.init is None:
                        ctor = self.resolve_class_constructor_call(s.type, [], local_types)
                        ordered = self._ordered_call_args(
                            [], ctor.params if ctor else [],
                            f"constructor '{s.type}'"
                        )
                        s.init = Call(Ident(s.type), ordered)
                        init = self.gen_expr(s.init, local_types)
                    ctype = s.type + " *"

                if is_class:
                    cdecl = f"{ctype} {s.name}"
                else:
                    cdecl = self._var_c_decl(s)
                if s.is_const:
                    self._readonly_vars.add(s.name)
                    if is_class:
                        self._const_object_vars.add(s.name)
                        cdecl = f"const {s.type} *{s.name}"
                if not self.c89:
                    if init is not None:
                        stmt_lines.append(f"{cdecl} = {init};")
                    else:
                        stmt_lines.append(f"{cdecl};")
                elif in_prefix:
                    if init is not None:
                        decl_lines.append(f"{cdecl} = {init};")
                    else:
                        decl_lines.append(f"{cdecl};")
                else:
                    # C89 cannot assign to a `const` object after its
                    # declaration. Jaguar has already enforced constness at
                    # the language level, so for a late declaration we keep
                    # the Jaguar semantic restriction but emit a mutable C
                    # declaration that can receive its initialization at the
                    # original source position. This preserves evaluation
                    # order instead of hoisting a side-effecting initializer.
                    late_cdecl = cdecl
                    if s.is_const and not s.pointee_const and not self._function_ptr_c_decl(s.type, s.name):
                        late_cdecl = f"{c_type(s.type)} {s.name}"
                    decl_lines.append(f"{late_cdecl};")
                    if init is not None:
                        stmt_lines.append(f"{s.name} = {init};")
                continue

            in_prefix = False
            stmt_lines.extend(self.gen_stmt(s, local_types))

        cleanup = self._scope_cleanup_lines(owned)
        self._scope_owned.pop()
        # Un return/break/continue final est déjà précédé du nettoyage
        # nécessaire : ne pas émettre une seconde destruction après lui.
        if statements and isinstance(statements[-1], (ReturnStmt, BreakStmt, ContinueStmt)):
            cleanup = []
        return decl_lines + stmt_lines + cleanup

    def gen_block(self, block: Block, local_types: dict, indent: int = 1) -> str:
        pad = "    " * indent
        lines = ["{"]
        for line in self._gen_body_lines(block.statements, local_types):
            lines.append(pad + line)
        lines.append("    " * (indent - 1) + "}")
    
        return "\n".join(lines)

    def _collect_change_handlers(self, statements, local_types):
        handlers = {}
        for st in statements:
            if isinstance(st, VariableChangeHandler):
                if st.name not in local_types and st.name not in self.global_types:
                    if not (self._current_class and self._find_class_member(self._current_class.name, st.name, "field")[1] is not None):
                        raise CodeGenError(f"signal: variable '{st.name}' is not a local variable or member of class '{self._current_class.name}'" if self._current_class else f"signal: variable '{st.name}' is not declared")
                if st.name in handlers:
                    raise CodeGenError(f"signal: multiple handlers for variable '{st.name}' in the same function")
                handlers[st.name] = st.body
        return handlers

    def _gen_change_trigger(self, name, local_types, old_tmp):
        if self._in_change_handler or name not in self._change_handlers:
            return []
        body = self._change_handlers[name]
        old_type = local_types.get(name, self.global_types.get(name))
        if old_type == "string":
            cond = f"(({old_tmp} == 0 && {name} != 0) || ({old_tmp} != 0 && {name} == 0) || ({old_tmp} != 0 && {name} != 0 && strcmp({old_tmp}->data, {name}->data) != 0))"
        else:
            cond = f"({old_tmp} != {name})"
        self._in_change_handler = True
        try:
            body_lines = self._gen_body_lines(body.statements, local_types)
        finally:
            self._in_change_handler = False
        lines = [f"if ({cond}) {{"]
        lines.extend("    " + x for x in body_lines)
        lines.append("}")
        return lines

    def _gen_member_change_trigger(self, name, local_types, old_tmp, current_expr):
        if self._in_change_handler or name not in self._change_handlers:
            return []
        body = self._change_handlers[name]
        old_type = self.infer_type(MemberAccess(Ident("this"), name), local_types)
        if old_type == "string":
            cond = f"(({old_tmp} == 0 && {current_expr} != 0) || ({old_tmp} != 0 && {current_expr} == 0) || ({old_tmp} != 0 && {current_expr} != 0 && strcmp({old_tmp}->data, {current_expr}->data) != 0))"
        else:
            cond = f"({old_tmp} != {current_expr})"
        self._in_change_handler = True
        try:
            body_lines = self._gen_body_lines(body.statements, local_types)
        finally:
            self._in_change_handler = False
        return [f"if ({cond}) {{"] + ["    " + x for x in body_lines] + ["}"]

    def _expr_pointee_const(self, e):
        if isinstance(e, Ident):
            return e.name in getattr(self, "_pointee_const_vars", set())
        if isinstance(e, UnaryOp) and e.op == "&" and isinstance(e.operand, Ident):
            return e.operand.name in getattr(self, "_readonly_vars", set())
        return False

    def _gen_expr_for_expected_type(self, expr, expected_type, local_types):
        """Generate an expression with a narrow ABI-aware contextual conversion.

        Jaguar `string` remains the native runtime string type.  The only
        special case here is a string *literal* passed to a C character
        pointer (`i8*`): the literal already has the C representation needed
        by the ABI, so emit it directly instead of constructing a Jaguar
        `string` object.

        This deliberately does not make arbitrary `string` values convertible
        to `i8*`, which would require exposing the runtime string storage and
        would blur the distinction between Jaguar strings and C strings.
        """
        if isinstance(expr, StringLit) and canonical_type(expected_type) == "i8*":
            return f"((int8_t*)({expr.value}))"
        return self.gen_expr(expr, local_types)

    def _gen_ordered_call_args(self, ordered_args, params, local_types, variadic=False):
        """Emit fixed args contextually and variadic tail args as normal expressions."""
        fixed_params = params
        fixed_args = ordered_args[:len(fixed_params)]
        out = [self._gen_expr_for_expected_type(arg, param.type, local_types) for arg, param in zip(fixed_args, fixed_params)]
        if variadic:
            out.extend(self.gen_expr(arg, local_types) for arg in ordered_args[len(fixed_params):])
        return ", ".join(out)

    def _check_assignable(self, target_type, source_type, context="assignment", source_expr=None):
        target_type = canonical_type(target_type) if isinstance(target_type, str) else target_type
        if isinstance(source_type, tuple):
            source_type = source_type[1] if source_type[0] != "literal" else source_type
        if source_type is None:
            raise CodeGenError(f"cannot assign an expression of unknown type to '{target_type}' ({context})")
        if isinstance(source_type, tuple) and source_type[0] == "literal":
            category = source_type[1]
            if category == "int" and target_type in INTEGER_TYPES | FLOAT_TYPES: return
            if category == "float" and target_type in FLOAT_TYPES: return
            if category == "bool" and target_type == "bool": return
            raise CodeGenError(f"type mismatch: literal of type '{category}' cannot initialize '{target_type}' ({context})")
        if source_type == "nullptr":
            if isinstance(target_type, str) and target_type.endswith("*"): return
            raise CodeGenError(f"cannot assign 'nullptr' to non-pointer type '{target_type}' ({context})")
        # A string literal is still a Jaguar `string` in normal expressions,
        # but it can be passed directly to a C `char*`/`i8*` parameter.  This
        # is a contextual ABI conversion, not a conversion of Jaguar string
        # objects themselves.
        if target_type == "i8*" and isinstance(source_expr, StringLit):
            return
        if target_type == source_type: return
        if target_type == "bool":
            raise CodeGenError(f"cannot assign '{source_type}' to 'bool' ({context}); an explicit cast is required")
        if isinstance(target_type, str) and target_type.endswith("*"):
            if isinstance(source_type, str) and source_type.endswith("*") and source_type == target_type:
                if source_expr is not None and self._expr_pointee_const(source_expr) and not getattr(self, "_target_pointee_const", False):
                    raise CodeGenError(f"cannot discard constness when assigning to '{target_type}' ({context}); use a pointer-to-const destination")
                return
            raise CodeGenError(f"cannot assign '{source_type}' to pointer type '{target_type}' ({context}); use an explicit cast if this is intentional")
        if target_type in INTEGER_TYPES and source_type in INTEGER_TYPES: return
        if target_type in INTEGER_TYPES and isinstance(source_type, str) and source_type in getattr(self, "enums", {}): return
        if target_type in FLOAT_TYPES and source_type in INTEGER_TYPES | FLOAT_TYPES: return
        if target_type == "string" and source_type == "string": return
        gp = self._generic_parts(target_type)
        if gp and gp[0] == "container" and isinstance(source_type, str) and source_type == gp[1] + "*": return
        if target_type in self.classes and source_type == target_type: return
        if target_type in getattr(self, "enums", {}) and source_type == target_type: return
        raise CodeGenError(f"type mismatch: cannot assign '{source_type}' to '{target_type}' ({context})")

    def _check_expression_types(self, e, local_types):
        if e is None: return None
        def numeric(t):
            if isinstance(t, tuple) and t[0] == "literal":
                return t[1] in ("int", "float")
            return t in INTEGER_TYPES | FLOAT_TYPES
        if isinstance(e, BinOp):
            lt=self.infer_type(e.left,local_types); rt=self.infer_type(e.right,local_types)
            custom=self._resolve_operator(e.op, lt, rt)
            if custom is None:
                if e.op in ("+","-","*","/","%"):
                    if e.op == "+" and lt == "string" and rt == "string":
                        pass
                    elif lt == "string" or rt == "string":
                        raise CodeGenError(f"operator '{e.op}' is not defined for 'string' operands")
                    elif not (numeric(lt) and numeric(rt)):
                        raise CodeGenError(f"no operator exists for '{lt}' {e.op} '{rt}'")
                elif e.op in ("<",">","<=",">="):
                    if lt is None or rt is None:
                        raise CodeGenError(f"no operator exists for '{lt}' {e.op} '{rt}'")
                    if not (numeric(lt) and numeric(rt)):
                        raise CodeGenError(f"no operator exists for '{lt}' {e.op} '{rt}'")
                elif e.op in ("==", "!="):
                    # C accepts equality for scalar values and matching
                    # pointers, but not for Jaguar structs/unions/classes as
                    # value objects. A custom Jaguar operator has already been
                    # handled above. Keep string/string and numeric equality
                    # available as in the existing compiler.
                    def scalar_or_pointer(t):
                        if isinstance(t, tuple) and t[0] == "literal":
                            return t[1] in ("int", "float", "bool")
                        if not isinstance(t, str):
                            return False
                        if t in INTEGER_TYPES | FLOAT_TYPES | {"bool", "string"}:
                            return True
                        if t in self.enums:
                            return True
                        if t == "nullptr" or t.endswith("*"):
                            return True
                        return False
                    if not (scalar_or_pointer(lt) and scalar_or_pointer(rt)):
                        raise CodeGenError(f"no operator exists for '{lt}' {e.op} '{rt}'")
                    if ((lt in self.classes or lt in self.structs or lt in self.unions)
                            or (rt in self.classes or rt in self.structs or rt in self.unions)):
                        # Class values are represented by pointers internally,
                        # so equality between class variables was already valid
                        # C. Struct/union value equality is the important case
                        # that C rejects and Jaguar does not define implicitly.
                        if lt in self.structs or rt in self.structs or lt in self.unions or rt in self.unions:
                            raise CodeGenError(f"no operator exists for '{lt}' {e.op} '{rt}'")
            self._check_expression_types(e.left,local_types); self._check_expression_types(e.right,local_types)
        elif isinstance(e, UnaryOp):
            t=self.infer_type(e.operand,local_types)
            if e.op == "!" and t != "bool": raise CodeGenError(f"operator '!' requires 'bool', got '{t}'")
            if e.op in ("-","+") and not numeric(t): raise CodeGenError(f"unary '{e.op}' requires a numeric operand, got '{t}'")
            if e.op == "*" and not (isinstance(t,str) and t.endswith("*")): raise CodeGenError(f"cannot dereference '{t}'; a pointer is required")
            self._check_expression_types(e.operand,local_types)
        elif isinstance(e, Call):
            self.infer_type(e,local_types)
            for a in e.args: self._check_expression_types(a.expr if isinstance(a,NamedArg) else a,local_types)
        elif isinstance(e, Ident):
            inferred = self.infer_type(e, local_types)
            if inferred is None and not self.groups.get((None, e.name)):
                raise CodeGenError(f"unknown identifier '{e.name}'")
        elif isinstance(e, NamespacedIdent):
            inferred = self.infer_type(e, local_types)
            if inferred is None:
                raise CodeGenError(f"unknown identifier '{e.namespace}:{e.name}'")
        elif isinstance(e, MemberAccess): self.infer_type(e,local_types); self._check_expression_types(e.obj,local_types)
        elif isinstance(e, IndexAccess): self.infer_type(e,local_types); self._check_expression_types(e.obj,local_types); self._check_expression_types(e.index,local_types)
        elif isinstance(e, CastExpr): self._check_expression_types(e.operand,local_types)
        elif isinstance(e, NewExpr):
            for a in e.args: self._check_expression_types(a.expr if isinstance(a,NamedArg) else a,local_types)
        return self.infer_type(e,local_types)

    def gen_stmt(self, s, local_types: dict) -> List[str]:
        """Lignes C d'une instruction. Une instruction simple donne une
        seule ligne ; if / while / for_loop en donnent plusieurs, dont les
        lignes de corps portent déjà 4 espaces d'indentation."""
        if isinstance(s, ReturnStmt):
            transfer_name = None
            if isinstance(s.expr, Ident):
                for owned_scope in reversed(self._scope_owned):
                    if any(name == s.expr.name for name, _ in owned_scope):
                        transfer_name = s.expr.name
                        break
            cleanup = self._all_active_cleanup_lines({transfer_name} if transfer_name else set())
            if s.expr is None:
                if self._current_return_type not in ("void", "int") and not self._in_main:
                    raise CodeGenError(f"non-void function must return a value of type '{self._current_return_type}'")
                return cleanup + ["return 0;" if self._in_main else "return;"]
            expr_type=self._check_expression_types(s.expr, local_types)
            self._check_assignable(self._current_return_type, expr_type, "return statement", s.expr)
            expr = self.gen_expr(s.expr, local_types)
            return cleanup + [f"return {expr};"]
        if isinstance(s, VariableChangeHandler):
            if s.name not in local_types and s.name not in self.global_types:
                if not (self._current_class and self._find_class_member(self._current_class.name, s.name, "field")[1] is not None):
                    raise CodeGenError(f"signal: variable '{s.name}' is not a local variable or member of class '{self._current_class.name}'" if self._current_class else f"signal: variable '{s.name}' is not declared")
            if s.name in self._change_handlers:
                raise CodeGenError(f"signal: multiple handlers for variable '{s.name}' in the same scope")
            self._change_handlers[s.name] = s.body
            return []
        if isinstance(s, MemberAssignStmt):
            if isinstance(s.target, IndexAccess):
                indexed_type = self.infer_type(s.target.obj, local_types)
                if self._fixed_array_parts(indexed_type) is None:
                    raise CodeGenError("operator [] is read-only for list/map: it cannot create or modify an entry")
                target_type = self.infer_type(s.target, local_types)
                expr_type = self._check_expression_types(s.expr, local_types)
                self._check_assignable(target_type, expr_type, "array element assignment", s.expr)
                return [f"{self.gen_expr(s.target, local_types)} = {self.gen_expr(s.expr, local_types)};"]
            if self._is_reflection_call(s.target):
                self._validate_reflection_call(s.target, local_types)
                obj=self.gen_expr(s.target.callee.obj,local_types); name=self.gen_expr(s.target.args[0],local_types)
                t=self.infer_type(s.expr,local_types); expr=self.gen_expr(s.expr,local_types)
                if isinstance(t,tuple): t="i32" if t[1]=="int" else "f64"
                if t == "string": call = f'_j_reflect_set_member((void*){obj},{name}->data,"string",0,0,0.0,{expr},0)'
                elif t in ("f32","float","f64"): call = f'_j_reflect_set_member((void*){obj},{name}->data,"{t}",0,0,(double)({expr}),0,0)'
                elif t == "bool": call = f'_j_reflect_set_member((void*){obj},{name}->data,"bool",(long long)({expr}),0,0.0,0,0)'
                elif t in INTEGER_TYPES: call = f'_j_reflect_set_member((void*){obj},{name}->data,"{t}",(long long)({expr}),(unsigned long long)({expr}),0.0,0,0)'
                else: call = f'_j_reflect_set_member((void*){obj},{name}->data,"{t}",0,0,0.0,0,(void*)({expr}))'
                return [call + ";"]
            if self._expr_is_const_receiver(s.target.obj, local_types):
                receiver_name = s.target.obj.name if isinstance(s.target.obj, Ident) else "object"
                raise CodeGenError(f"cannot modify member '{s.target.name}' through const object '{receiver_name}'")
            ot = self.infer_type(s.target.obj, local_types)
            if isinstance(ot, str) and ot.endswith("*"): ot = ot[:-1]
            owner, member = self._find_class_member(ot, s.target.name, "field") if ot in self.classes else (None, None)
            if member is None and ot in self.structs and not any(f.name == s.target.name for f in self.structs[ot].fields):
                raise CodeGenError(f"member '{s.target.name}' is absent from '{ot}'")
            if member is not None and getattr(member, "is_const", False):
                raise CodeGenError(f"const member '{s.target.name}' cannot be modified")
            if member is not None and getattr(member, "pointee_const", False):
                # The field itself may be reassigned, but its pointee cannot be modified.
                pass
            if self._current_class_method_const and isinstance(s.target.obj, Ident) and s.target.obj.name == "this":
                raise CodeGenError(f"a const method cannot modify member '{s.target.name}'")
            target_type = self.infer_type(s.target, local_types)
            value_type = self._check_expression_types(s.expr, local_types)
            self._check_assignable(target_type, value_type, f"assignment to member '{s.target.name}'", s.target)
            target = self.gen_member_access(s.target, local_types)
            if (not self._in_change_handler and isinstance(s.target.obj, Ident) and s.target.obj.name == "this" and s.target.name in self._change_handlers):
                old_type = self.infer_type(s.target, local_types)
                old_tmp = f"__j_old_{self._tmp_id}"
                self._tmp_id += 1
                old_c = c_type(old_type)
                return [f"{old_c} {old_tmp} = {target};", f"{target} = {self.gen_expr(s.expr, local_types)};"] + self._gen_member_change_trigger(s.target.name, local_types, old_tmp, target)
            return [f"{target} = {self.gen_expr(s.expr, local_types)};"]
        if isinstance(s, PointerAssignStmt):
            if isinstance(s.target, UnaryOp) and s.target.op == "*":
                operand=s.target.operand
                if isinstance(operand, Ident) and operand.name in getattr(self, "_pointee_const_vars", set()):
                    raise CodeGenError(f"cannot modify through const pointer '{operand.name}'")
                if isinstance(operand, MemberAccess):
                    ot=self.infer_type(operand.obj, local_types)
                    if isinstance(ot,str) and ot.endswith("*"): ot=ot[:-1]
                    _, mf=self._find_class_member(ot, operand.name, "field") if ot in self.classes else (None,None)
                    if mf is not None and getattr(mf,"pointee_const",False):
                        raise CodeGenError(f"cannot modify through const pointer member '{operand.name}'")
            target_type = self.infer_type(s.target, local_types)
            if target_type is None:
                raise CodeGenError("cannot determine the type of the pointer target")
            value_type=self._check_expression_types(s.expr,local_types)
            self._check_assignable(target_type, value_type, "pointer dereference assignment", s.target)
            return [f"{self.gen_expr(s.target, local_types)} = {self.gen_expr(s.expr, local_types)};"]
        if isinstance(s, AssignStmt):
            if s.name not in local_types and s.name not in self.global_types:
                # Dans une méthode/constructeur, `field = value;` est le
                # raccourci Jaguar pour `this.field = value;`. Réutiliser le
                # chemin MemberAssignStmt conserve les contrôles d'accès, de
                # constance, de type et de méthode const.
                if self._current_class:
                    owner, member = self._find_class_member(self._current_class.name, s.name, "field")
                    if member is not None:
                        return self.gen_stmt(
                            MemberAssignStmt(MemberAccess(Ident("this"), s.name), s.expr),
                            local_types
                        )
                raise CodeGenError(
                    f"assignment to '{s.name}': variable is not declared"
                )
            if s.name in self._readonly_vars or s.name in self.global_const:
                raise CodeGenError(f"const/read-only variable '{s.name}' cannot be modified")
            target_type = local_types.get(s.name, self.global_types.get(s.name))
            value_type = self._check_expression_types(s.expr, local_types)
            self._target_pointee_const = s.name in getattr(self, "_pointee_const_vars", set())
            self._check_assignable(target_type, value_type, f"assignment to '{s.name}'", s.expr)
            self._target_pointee_const = False
            if isinstance(s.expr, Call) and isinstance(s.expr.callee, NamespacedIdent) and s.expr.callee.namespace == "factory" and s.expr.callee.name == "construct":
                self._dynamic_reflection_vars.add(s.name)
            elif s.name in self._dynamic_reflection_vars:
                self._dynamic_reflection_vars.discard(s.name)
            if isinstance(target_type, str) and target_type.endswith("*"):
                value_type = self.infer_type(s.expr, local_types)
                if value_type != "nullptr" and not (isinstance(value_type, str) and value_type.endswith("*")):
                    raise CodeGenError(
                        f"pointer variable '{s.name}' can only be assigned a pointer expression or 'nullptr', not '{value_type}'"
                    )
            lines = []
            if not self._in_change_handler and s.name in self._change_handlers:
                old_type = local_types.get(s.name, self.global_types.get(s.name))
                ctype = c_type(old_type)
                old_tmp = f"__j_old_{self._tmp_id}"
                self._tmp_id += 1
                lines.append(f"{ctype} {old_tmp} = {s.name};")
                lines.append(f"{s.name} = {self.gen_expr(s.expr, local_types)};")
                lines.extend(self._gen_change_trigger(s.name, local_types, old_tmp))
            else:
                lines.append(f"{s.name} = {self.gen_expr(s.expr, local_types)};")
            return lines
        if isinstance(s, ExprStmt):
            self._check_expression_types(s.expr, local_types)
            return [f"{self.gen_expr(s.expr, local_types)};"]
        if isinstance(s, IfStmt):
            ct=self._check_expression_types(s.cond, local_types)
            # Jaguar permits pointers in boolean contexts: a non-null pointer
            # is true and nullptr is false.  This is intentional and mirrors
            # C pointer truthiness without allowing arbitrary integers.
            if ct != "bool" and not (isinstance(ct, str) and ct.endswith("*")):
                raise CodeGenError(f"if condition must have type 'bool' or a pointer, got '{ct}'")
            return self._gen_if(s, local_types)
        if isinstance(s, WhileStmt):
            ct=self._check_expression_types(s.cond, local_types)
            if ct != "bool" and not (isinstance(ct, str) and ct.endswith("*")):
                raise CodeGenError(f"while condition must have type 'bool' or a pointer, got '{ct}'")
            return self._gen_while(s, local_types)
        if isinstance(s, LoopStmt):
            return self._gen_loop(s, local_types)
        if isinstance(s, ForLoopStmt):
            return self._gen_for_loop(s, local_types)
        if isinstance(s, CollectionLoopStmt):
            return self._gen_collection_loop(s, local_types)
        if isinstance(s, BreakStmt):
            self._check_in_loop("break")
            return self._loop_cleanup_lines() + ["break;"]
        if isinstance(s, ContinueStmt):
            self._check_in_loop("continue")
            return self._loop_cleanup_lines() + ["continue;"]
        raise NotImplementedError(f"instruction non gérée: {s!r}")

    # -- contrôle de flux -------------------------------------------------
    def _check_in_loop(self, keyword: str):
        if self._loop_depth == 0:
            raise CodeGenError(f"'{keyword}' outside of a loop")

    def _gen_scoped(self, block: Block, local_types: dict) -> List[str]:
        """Generate a nested lexical scope without leaking per-scope semantic state.

        `local_types` is already copied, but the CodeGen also keeps mutable sets
        for const/read-only variables, pointer-to-const variables, const class
        receivers, dynamic reflection objects, and signal handlers. These names
        are scope-local too, so they must be restored after the nested block.
        """
        inner = dict(local_types)
        saved_readonly = set(self._readonly_vars)
        saved_pointee_const = set(getattr(self, "_pointee_const_vars", set()))
        saved_const_objects = set(getattr(self, "_const_object_vars", set()))
        saved_dynamic_reflection = set(getattr(self, "_dynamic_reflection_vars", set()))
        saved_change_handlers = dict(self._change_handlers)
        try:
            return ["    " + line for line in self._gen_body_lines(block.statements, inner)]
        finally:
            self._readonly_vars = saved_readonly
            self._pointee_const_vars = saved_pointee_const
            self._const_object_vars = saved_const_objects
            self._dynamic_reflection_vars = saved_dynamic_reflection
            self._change_handlers = saved_change_handlers

    def _gen_if(self, s: IfStmt, local_types: dict) -> List[str]:
        lines = [f"if ({self.gen_expr(s.cond, local_types)}) {{"]
        lines += self._gen_scoped(s.then_block, local_types)
        branch = s.else_branch
        while isinstance(branch, IfStmt):                      # else if
            lines.append(f"}} else if ({self.gen_expr(branch.cond, local_types)}) {{")
            lines += self._gen_scoped(branch.then_block, local_types)
            branch = branch.else_branch
        if branch is not None:                                 # else
            lines.append("} else {")
            lines += self._gen_scoped(branch, local_types)
        lines.append("}")
        return lines

    def _gen_while(self, s: WhileStmt, local_types: dict) -> List[str]:
        self._loop_depth += 1
        self._loop_scope_bases.append(len(self._scope_owned))
        body = self._gen_scoped(s.body, local_types)
        self._loop_scope_bases.pop()
        self._loop_depth -= 1
        return [f"while ({self.gen_expr(s.cond, local_types)}) {{"] + body + ["}"]

    def _gen_loop(self, s: LoopStmt, local_types: dict) -> List[str]:
        self._loop_depth += 1
        self._loop_scope_bases.append(len(self._scope_owned))
        body = self._gen_scoped(s.body, local_types)
        self._loop_scope_bases.pop()
        self._loop_depth -= 1
        return ["while (1) {"] + body + ["}"]

    # for_loop(début, fin) : `i` parcourt début..fin, fin COMPRISE.
    #
    # Traduction C89 :
    #     {
    #         T i;  T _jendN;  int _jmoreN;
    #         i = début;  _jendN = fin;
    #         for (_jmoreN = (i <= _jendN); _jmoreN;
    #              _jmoreN = (i != _jendN), i += _jmoreN) { ... }
    #     }
    # - le bloc englobant donne à `i` sa portée locale (et respecte C89) ;
    # - `fin` n'est évaluée qu'UNE fois (_jendN) ;
    # - le drapeau _jmoreN évite le dépassement : `i` n'est jamais
    #   incrémenté au-delà de `fin`, donc for_loop(250, 255) avec un u8
    #   se termine bien (un simple `i <= fin; i++` bouclerait à l'infini) ;
    # - si début > fin, le corps ne s'exécute pas ;
    # - `continue` fonctionne : il passe par l'expression d'incrément.
    def _gen_for_loop(self, s: ForLoopStmt, local_types: dict) -> List[str]:
        name = s.var_name
        if name in local_types:
            raise CodeGenError(
                f"variable '{name}' is already declared "
                f"(parameter or variable with the same name)"
            )
        if name in self.global_types:
            raise CodeGenError(
                f"loop variable '{name}' shadows a global variable with the same name"
            )

        # bornes évaluées dans la portée EXTÉRIEURE (i n'y est pas visible)
        start = self.gen_expr(s.start, local_types)
        end = self.gen_expr(s.end, local_types)

        n = self._tmp_id
        self._tmp_id += 1
        end_v, more_v = f"_jend{n}", f"_jmore{n}"
        ctype = c_type(s.var_type)

        inner = dict(local_types)
        inner[name] = s.var_type
        self._loop_depth += 1
        self._readonly_vars.add(name)
        self._loop_scope_bases.append(len(self._scope_owned))
        body = self._gen_scoped(s.body, inner)
        self._loop_scope_bases.pop()
        self._loop_depth -= 1
        self._readonly_vars.discard(name)

        lines = [
            "{",
            f"    {ctype} {name};",
            f"    {ctype} {end_v};",
            f"    int {more_v};",
            f"    {name} = {start};",
            f"    {end_v} = {end};",
            f"    for ({more_v} = ({name} <= {end_v}); {more_v}; "
            f"{more_v} = ({name} != {end_v}), {name} += {more_v}) {{",
        ]
        lines += ["    " + line for line in body]
        lines += ["    }", "}"]
        return lines

    def _gen_collection_loop(self, s: CollectionLoopStmt, local_types: dict) -> List[str]:
        ct = self.infer_type(s.collection, local_types)
        gp = self._generic_parts(ct)
        if not gp or gp[0] != ("list" if s.kind == "loop_list" else "map"):
            raise CodeGenError(f"{s.kind} expects a list<T> or a map<K,V>, respectively")
        obj = self.gen_expr(s.collection, local_types)
        source_name = s.collection.name if isinstance(s.collection, Ident) else None
        if source_name: self._readonly_vars.add(source_name)
        inner = dict(local_types)
        if s.kind == "loop_list":
            elem = gp[1]
            inner[s.var_name] = elem
            n=self._tmp_id; self._tmp_id+=1
            body=self._gen_scoped(s.body, inner)
            if source_name: self._readonly_vars.discard(source_name)
            return ["{", f"    size_t _jli{n};", f"    for (_jli{n}=0; _jli{n}<{obj}.size; ++_jli{n}) {{", f"        {self._collection_c_type(elem)} {s.var_name} = *(({self._collection_c_type(elem)}*)_j_list_get(&{obj}, _jli{n}));"] + ["    "+x for x in body] + ["    }", "}"]
        kt,vt=self._split_generic_args(gp[1]); pair=f"pair<{kt},{vt}>"
        inner[s.var_name]=pair
        n=self._tmp_id; self._tmp_id+=1
        body=self._gen_scoped(s.body, inner)
        if source_name: self._readonly_vars.discard(source_name)
        pcn=self._pair_c_type(pair)
        return ["{", f"    size_t _jmi{n};", f"    {pcn} {s.var_name};", f"    for (_jmi{n}=0; _jmi{n}<{obj}.size; ++_jmi{n}) {{", f"        {s.var_name}.first = *({c_type(kt)}*){obj}.items[_jmi{n}].key;", f"        {s.var_name}.second = *({c_type(vt)}*){obj}.items[_jmi{n}].value;"] + ["    "+x for x in body] + ["    }", "}"]

    # -- primitives sys:* ------------------------------------------------
    def _system_builtin(self, callee, call=None):
        """Resolve a sys:* primitive, including through `using namespace sys;`.

        Builtins are not normal Jaguar FunctionDecls, so they must be resolved
        here rather than by Resolver.resolve_call_target().  An unqualified
        `print(...)` therefore means `sys:print(...)` when `sys` is imported.
        """
        if isinstance(callee, NamespacedIdent):
            return SYSTEM_BUILTINS.get((callee.namespace, callee.name))
        if isinstance(callee, Ident):
            namespaces = getattr(call, "_using_namespaces", self.using_namespaces) if call is not None else self.using_namespaces
            matches = []
            for ns in namespaces:
                info = SYSTEM_BUILTINS.get((ns, callee.name))
                if info is not None:
                    matches.append(info)
            if len(matches) == 1:
                return matches[0]
            if len(matches) > 1:
                raise CodeGenError(f"ambiguous system function '{callee.name}' imported from multiple namespaces")
        return None

    def _validate_system_call(self, call, local_types=None):
        info = self._system_builtin(call.callee, call)
        if info is None:
            return None
        c_name, argc, ret_type = info
        if isinstance(call.callee, NamespacedIdent) and call.callee.namespace == "thread" and local_types is not None:
            vals = [a.expr if isinstance(a, NamedArg) else a for a in call.args]
            if call.callee.name == "start" and (len(vals) != 1 or self.infer_type(vals[0], local_types) != "fn() -> void"):
                raise CodeGenError("'thread:start' expects a function pointer of type 'fn() -> void'")
            if call.callee.name in ("join", "detach") and len(vals) == 1:
                if self.infer_type(vals[0], local_types) not in ("void*", "nullptr"):
                    raise CodeGenError(f"'thread:{call.callee.name}' expects a thread handle")
            if call.callee.name == "sleep" and len(vals) == 1:
                t=self.infer_type(vals[0], local_types)
                if isinstance(t,tuple): t="int" if t[1]=="int" else t
                if t not in INTEGER_TYPES:
                    raise CodeGenError("'thread:sleep' expects an integer millisecond count")
        if len(call.args) != argc:
            if argc == 0:
                expected = "no arguments"
            elif argc == 1:
                expected = "1 argument"
            else:
                expected = f"{argc} arguments"
            raise CodeGenError(
                f"'{call.callee.namespace}:{call.callee.name}' expects {expected}, "
                f"{len(call.args)} provided"
            )
        return info

    def _system_print_function(self, arg_type):
        """Retourne le helper C adapté au type de sys:print."""
        if isinstance(arg_type, tuple) and arg_type[0] == "literal":
            if arg_type[1] == "int":
                return "_j_sys_print_int"
            if arg_type[1] == "float":
                return "_j_sys_print_f64"

        return {
            "string": "_j_sys_print_string",
            "int": "_j_sys_print_int",
            "float": "_j_sys_print_float",
            "i8": "_j_sys_print_i8",
            "u8": "_j_sys_print_u8",
            "i16": "_j_sys_print_i16",
            "u16": "_j_sys_print_u16",
            "i32": "_j_sys_print_i32",
            "u32": "_j_sys_print_u32",
            "i64": "_j_sys_print_i64",
            "u64": "_j_sys_print_u64",
            "f32": "_j_sys_print_f32",
            "f64": "_j_sys_print_f64",
            "bool": "_j_sys_print_bool",
        }.get(arg_type)

    # -- résolution d'appel (choix de la bonne surcharge) --
    def _ordered_call_args(self, args, params, callee_name="function", variadic=False):
        """Réordonne les paramètres fixes et conserve les arguments variadiques en fin."""
        fixed_params = params
        ordered = [None] * len(fixed_params)
        by_name = {p.name:i for i,p in enumerate(fixed_params)}
        variadic_args = []
        next_pos = 0; named_seen = False

        def arg_error(message, arg):
            err = CodeGenError(message)
            node = arg.expr if isinstance(arg, NamedArg) else arg
            line = getattr(arg, "_jaguar_line", None) or getattr(node, "_jaguar_line", None)
            col = getattr(arg, "_jaguar_name_column", None) if isinstance(arg, NamedArg) else None
            end = getattr(arg, "_jaguar_name_end_column", None) if isinstance(arg, NamedArg) else None
            if col is None:
                col = getattr(node, "_jaguar_column", None)
                end = getattr(node, "_jaguar_end_column", None)
            if line is not None and col is not None:
                err._jaguar_line = line
                err._jaguar_column = col
                err._jaguar_end_column = end if end is not None else col + 1
            raise err

        for arg in args:
            if isinstance(arg, NamedArg):
                named_seen = True
                if arg.name not in by_name:
                    arg_error(f"unknown named parameter '{arg.name}' for {callee_name}", arg)
                i = by_name[arg.name]
            else:
                if named_seen:
                    arg_error("a positional argument cannot follow a named argument", arg)
                while next_pos < len(ordered) and ordered[next_pos] is not None:
                    next_pos += 1
                if next_pos >= len(ordered):
                    if variadic:
                        variadic_args.append(arg)
                        continue
                    arg_error(f"too many arguments for {callee_name}", arg)
                i = next_pos; next_pos += 1
            if ordered[i] is not None:
                arg_error(f"parameter '{fixed_params[i].name}' provided more than once", arg)
            ordered[i] = arg.expr if isinstance(arg, NamedArg) else arg
        missing = [fixed_params[i].name for i,x in enumerate(ordered) if x is None and fixed_params[i].default is None]
        if missing:
            raise CodeGenError(f"missing parameters for {callee_name}: {', '.join(missing)}")
        for i, x in enumerate(ordered):
            if x is None:
                ordered[i] = fixed_params[i].default
        return ordered + variadic_args

    @staticmethod
    def _implicit_type_match(param_type, arg_type):
        if _type_matches(param_type, arg_type):
            return 3
        if isinstance(arg_type, tuple):
            return 0
        integer = set(INTEGER_TYPES)
        floating = set(FLOAT_TYPES)
        if arg_type in integer and param_type in integer:
            return 2
        if arg_type in integer and param_type in floating:
            return 1
        if arg_type in floating and param_type in floating:
            return 2
        return 0

    def resolve_call_target(self, call: Call, local_types: dict) -> Optional[FunctionDecl]:
        if isinstance(call.callee, Ident):
            key = (None, call.callee.name)
            name = call.callee.name
        elif isinstance(call.callee, NamespacedIdent):
            key = (call.callee.namespace, call.callee.name)
            name = call.callee.name
        else:
            return None

        candidates = self.groups.get(key)
        if not candidates and isinstance(call.callee, Ident):
            symbol_imports = getattr(call, "_using_symbols", {})
            imported = symbol_imports.get(call.callee.name)
            if imported:
                candidates = self.groups.get(imported, [])
                name = imported[1]
            namespace_matches = []
            for ns in getattr(call, "_using_namespaces", self.using_namespaces):
                fns = self.groups.get((ns, call.callee.name), [])
                if fns:
                    namespace_matches.append(fns)
            if len(namespace_matches) == 1:
                candidates = namespace_matches[0]
            elif len(namespace_matches) > 1:
                raise CodeGenError(f"ambiguous function '{call.callee.name}' imported from multiple namespaces")
        if not candidates:
            return None
        prepared = []
        # For a single visible candidate, keep the exact argument diagnostic
        # instead of collapsing it into the generic "no overload" error.
        # With real overloads, incompatible candidates are still skipped so
        # that another signature can be selected.
        if len(candidates) == 1:
            fn = candidates[0]
            ordered = self._ordered_call_args(call.args, fn.params, f"'{name}'", fn.is_variadic)
            fixed_params = fn.params
            for arg, param in zip(ordered, fixed_params):
                at = self.infer_type(arg.expr if isinstance(arg, NamedArg) else arg, local_types)
                self._check_assignable(
                    param.type, at,
                    f"argument '{param.name}' of function '{name}'",
                    arg.expr if isinstance(arg, NamedArg) else arg
                )
            return fn

        for fn in candidates:
            try:
                ordered = self._ordered_call_args(call.args, fn.params, f"'{name}'", fn.is_variadic)
                fixed_params = fn.params
                for arg, param in zip(ordered, fixed_params):
                    at = self.infer_type(arg.expr if isinstance(arg, NamedArg) else arg, local_types)
                    self._check_assignable(
                        param.type, at,
                        f"argument '{param.name}' of function '{name}'",
                        arg.expr if isinstance(arg, NamedArg) else arg
                    )
            except CodeGenError:
                # Une surcharge incompatible ne doit pas bloquer la recherche
                # des autres signatures possibles.
                continue
            prepared.append((fn, ordered))
        if len(prepared) == 1:
            return prepared[0][0]

        scored = []
        for fn, ordered in prepared:
            arg_types = [self.infer_type(a, local_types) for a in ordered]
            fixed_params = fn.params
            if (len(ordered) >= len(fixed_params)) and (fn.is_variadic or len(fn.params) == len(ordered)):
                scores = [self._implicit_type_match(p.type, at) for p, at in zip(fixed_params, arg_types)]
                if all(scores):
                    scored.append((sum(scores), fn))
        if scored:
            best=max(x[0] for x in scored); matches=[fn for score,fn in scored if score==best]
        else:
            matches=[]
        if len(matches) == 1:
            return matches[0]
        if not matches:
            raise CodeGenError(
                f"no overload of '{name}' matches the provided argument types"
            )
        raise CodeGenError(f"ambiguous call to overloaded function '{name}'")

    def _operator_candidates(self, op):
        name = "operator" + op
        candidates = list(self.groups.get((self._current_namespace, name), []))
        for fn in self.groups.get((None, name), []):
            if fn not in candidates: candidates.append(fn)
        return candidates

    def _resolve_operator(self, op, left_type, right_type):
        if op not in _OPERATOR_FUNCTION_TOKENS or left_type is None or right_type is None:
            return None
        matches=[]
        for fn in self._operator_candidates(op):
            if len(fn.params) == 2 and _type_matches(fn.params[0].type, left_type) and _type_matches(fn.params[1].type, right_type):
                matches.append(fn)
        if len(matches) > 1:
            raise CodeGenError(f"ambiguous overload for operator '{op}'")
        return matches[0] if matches else None

    def infer_type(self, e, local_types: dict) -> Optional[str]:
        if isinstance(e, IntLit):
            return _literal("int")
        if isinstance(e, FloatLit):
            return _literal("float")
        if isinstance(e, StringLit):
            return "string"
        if isinstance(e, BoolLit):
            return "bool"
        if isinstance(e, NullPtrLit):
            return "nullptr"
        if isinstance(e, Ident):
            if e.name == "this" and self._current_class:
                return self._current_class.name
            # implicit class members inside a method
            if self._current_class:
                fowner, f = self._find_class_member(self._current_class.name, e.name, "field")
                if f is not None:
                    self._check_member_access(fowner, f, e.name)
                    return f.type
                mowner, m = self._find_class_member(self._current_class.name, e.name, "method")
                if m is not None:
                    self._check_member_access(mowner, m, e.name)
                    return m.ret_type
            global_name = self._resolve_global_name(e.name)
            class_name = self._resolve_class_name(e.name)
            if global_name and global_name in self.global_types:
                decl_line = self.global_decl_lines.get(global_name, 1)
                use_line = getattr(e, "_jaguar_line", getattr(self, "_current_source_line", decl_line))
                if use_line < decl_line:
                    raise CodeGenError(f"global variable '{e.name}' must be declared before use")
            t = local_types.get(e.name) or (self.global_types.get(global_name) if global_name else None) or class_name or self.macros.get(e.name)
            if t is not None: return t
            # Function identifiers are first-class values for callback/function-pointer assignments.
            candidates = self.groups.get((None, e.name), [])
            if len(candidates) == 1:
                fn = candidates[0]
                return f"fn({', '.join([p.type for p in fn.params] + (["..."] if fn.is_variadic else []))}) -> {fn.ret_type}"
            # Global enum values are first-class typed constants.
            for en in getattr(self.program, "_enums", {}).values():
                if en.namespace is None and e.name in en.values:
                    return en.name
            symbols = getattr(self.program, "_using_symbols", {})
            imported = symbols.get(e.name)
            if imported:
                ns, name = imported
                imported_fns = self.groups.get((ns, name), [])
                if len(imported_fns) == 1:
                    fn = imported_fns[0]
                    return f"fn({', '.join([p.type for p in fn.params] + (["..."] if fn.is_variadic else []))}) -> {fn.ret_type}"
                for key, en in getattr(self.program, "_enums", {}).items():
                    if key == f"{ns}:{en.name}" and name in en.values:
                        return f"{ns}_{en.name}" if ns else en.name
            namespace_function_matches = []
            for ns in getattr(self.program, "_using_namespaces", []):
                ns_fns = self.groups.get((ns, e.name), [])
                if len(ns_fns) == 1:
                    namespace_function_matches.append(ns_fns[0])
                for key, en in getattr(self.program, "_enums", {}).items():
                    if key == f"{ns}:{en.name}" and e.name in en.values:
                        return f"{ns}_{en.name}"
            if len(namespace_function_matches) == 1:
                fn = namespace_function_matches[0]
                return f"fn({', '.join([p.type for p in fn.params] + (["..."] if fn.is_variadic else []))}) -> {fn.ret_type}"
            return None
        if isinstance(e, IndexAccess):
            ot=self.infer_type(e.obj, local_types); gp=self._generic_parts(ot)
            arr = self._fixed_array_parts(ot) if isinstance(ot, str) else None
            if arr is not None:
                base, dims = arr
                return base + ("".join(f"[{d}]" for d in dims[1:]) if len(dims) > 1 else "")
            if not gp: raise CodeGenError(f"'[]' cannot be used on '{ot}'")
            if gp[0]=="list": return gp[1]
            if gp[0]=="map": return self._split_generic_args(gp[1])[1]
            if gp[0]=="dynamic_list": return "dynamic_value"
            raise CodeGenError("a container cannot be indexed")
        if isinstance(e, MemberAccess):
            ot=self.infer_type(e.obj, local_types)
            if isinstance(ot, str) and ot.endswith("*"):
                ot = ot.rstrip("*")
            gp=self._generic_parts(ot)
            if gp:
                kind,inner=gp
                if kind=="list" and e.name in ("push", "get", "size"):
                    return "void" if e.name=="push" else ("i32" if e.name=="size" else inner)
                if kind=="map" and e.name in ("emplace", "size"):
                    return "void" if e.name=="emplace" else "i32"
                if kind=="dynamic_list" and e.name in ("push", "get", "type", "size"):
                    return {"push":"void","get":"void*","type":"string","size":"i32"}[e.name]
                if kind=="container" and e.name=="get": return inner
                if kind=="pair":
                    a,b=self._split_generic_args(inner)
                    if e.name=="first": return a
                    if e.name=="second": return b
                if kind=="container" and inner in self.classes:
                    _, f=self._find_class_member(inner,e.name,"field")
                    if f: return f.type
                    _, m=self._find_class_member(inner,e.name,"method")
                    if m: return m.ret_type
                raise CodeGenError(f"member '{e.name}' is not available on '{ot}'")
            if ot == "string":
                valid = {
                    "length": "i32", "empty": "bool",
                    "equals": "bool", "contains": "bool",
                    "starts_with": "bool", "ends_with": "bool",
                    "concat": "string", "substring": "string",
                    "char_at": "i32", "to_upper": "string", "to_lower": "string",
                }
                if e.name in valid: return valid[e.name]
                raise CodeGenError(f"unknown string member '{e.name}'")
            if ot in self.unions:
                for f in self.unions[ot].fields:
                    if f.name == e.name:
                        return f.type
                raise CodeGenError(f"member '{e.name}' is absent from union '{ot}'")
            if ot in self.structs:
                for f in self.structs[ot].fields:
                    if f.name == e.name:
                        return f.type
                raise CodeGenError(f"member '{e.name}' is absent from struct '{ot}'")
            if ot in self.classes:
                _, f=self._find_class_member(ot,e.name,"field")
                if f: return f.type
                _, m=self._find_class_member(ot,e.name,"method")
                if m: return m.ret_type
                raise CodeGenError(f"member '{e.name}' is absent from class '{ot}'")
            raise CodeGenError(f"member '{e.name}' is not available on expression of type '{ot}'")
        if isinstance(e, NamespacedIdent):
            enums = getattr(self.program, "_enums", {})
            for key, en in enums.items():
                if (en.namespace == e.namespace and e.name in en.values) or (en.name == e.namespace and e.name in en.values):
                    return en.name if not en.namespace else f"{en.namespace}_{en.name}"
            q = f"{e.namespace.replace(':', '_')}_{e.name}"
            if q in self.global_types:
                decl_line = self.global_decl_lines.get(q, 1)
                use_line = getattr(e, "_jaguar_line", getattr(self, "_current_source_line", decl_line))
                if use_line < decl_line:
                    raise CodeGenError(f"global variable '{e.namespace}:{e.name}' must be declared before use")
                return self.global_types[q]
            if q in self.classes:
                return q
            if q in self.unions:
                return q
            candidates = self.groups.get((e.namespace, e.name), [])
            if len(candidates) == 1:
                fn = candidates[0]
                return f"fn({', '.join([p.type for p in fn.params] + (["..."] if fn.is_variadic else []))}) -> {fn.ret_type}"
            return None
        if isinstance(e, CastExpr):
            return e.target_type
        if isinstance(e, NewExpr):
            return e.type + "*"
        if isinstance(e, UnaryOp):
            if e.op == "!":
                return "bool"
            operand_type = self.infer_type(e.operand, local_types)
            if e.op == "&":
                if operand_type is None: return None
                if not isinstance(e.operand, (Ident, MemberAccess, IndexAccess, UnaryOp)) or (isinstance(e.operand, UnaryOp) and e.operand.op != "*"):
                    raise CodeGenError("cannot take the address of this expression; '&' requires a variable, member, element, or dereferenced pointer")
                return operand_type + "*"
            if e.op == "*":
                if isinstance(operand_type, str) and operand_type.endswith("*"):
                    return operand_type[:-1]
                raise CodeGenError("cannot dereference a non-pointer expression")
            return operand_type
        if isinstance(e, BinOp):
            lt=self.infer_type(e.left, local_types); rt=self.infer_type(e.right, local_types)
            custom=self._resolve_operator(e.op, lt, rt)
            if custom is not None:
                return custom.ret_type
            # Built-in string concatenation. Keep custom operator overloads
            # higher priority so an explicit Jaguar operator+ can still win.
            if e.op == "+" and lt == "string" and rt == "string":
                return "string"
            if e.op in _BOOL_RESULT_OPS:
                return "bool"
            return lt or rt
        if isinstance(e, Call):
            if isinstance(e.callee, Ident) and e.callee.name == "func" and self._decorator_call_target_name is not None:
                if e.args:
                    raise CodeGenError("decorator 'func()' does not accept explicit arguments")
                return "void"
            if isinstance(e.callee, Ident) and e.callee.name in TYPE_KEYWORDS and e.callee.name not in self.classes and e.callee.name != "string":
                raise CodeGenError(f"functional cast is not allowed: use C-style syntax `({e.callee.name})expression`")
            if self._is_reflection_call(e):
                self._validate_reflection_call(e, local_types)
                return "void*"
            if self._is_reflection_member_exists_call(e):
                self._validate_member_exists_call(e, local_types)
                return "bool"
            if self._is_reflection_set_member_call(e):
                self._validate_set_member_call(e, local_types)
                return "void"
            callee_type = self.infer_type(e.callee, local_types)
            fp_parts = self._function_type_parts(callee_type) if isinstance(callee_type, str) else None
            direct_function_call = False
            if isinstance(e.callee, Ident):
                direct_function_call = bool(self.groups.get((None, e.callee.name)))
                if not direct_function_call:
                    imported = getattr(self.program, "_using_symbols", {}).get(e.callee.name)
                    if imported:
                        direct_function_call = bool(self.groups.get(imported))
            elif isinstance(e.callee, NamespacedIdent):
                direct_function_call = bool(self.groups.get((e.callee.namespace, e.callee.name)))
            if fp_parts is not None and not direct_function_call:
                if any(isinstance(a, NamedArg) for a in e.args):
                    raise CodeGenError("named parameters are not available for function-pointer calls")
                params, ret_type = fp_parts
                variadic = bool(params and params[-1] == "...")
                fixed_params = params[:-1] if variadic else params
                if (not variadic and len(e.args) != len(fixed_params)) or (variadic and len(e.args) < len(fixed_params)):
                    expected = f"at least {len(fixed_params)}" if variadic else str(len(fixed_params))
                    raise CodeGenError(f"function pointer expects {expected} argument(s), {len(e.args)} provided")
                for param_type, arg in zip(fixed_params, e.args):
                    at = self.infer_type(arg, local_types)
                    self._check_assignable(
                        param_type, at, f"argument of function pointer call", arg
                    )
                return ret_type
            if isinstance(e.callee, Ident):
                class_name = self._resolve_class_name(e.callee.name)
            elif isinstance(e.callee, NamespacedIdent):
                class_name = self._resolve_class_name(e.callee.name, e.callee.namespace)
            else:
                class_name = None
            if class_name is not None:
                self.resolve_class_constructor_call(class_name, e.args, local_types)
                return class_name
            if isinstance(e.callee, Ident):
                struct_name = self._resolve_struct_name(e.callee.name)
            elif isinstance(e.callee, NamespacedIdent):
                struct_name = self._resolve_struct_name(e.callee.name, e.callee.namespace)
            else:
                struct_name = None
            if struct_name is not None:
                struct_decl = self.structs[struct_name]
                if any(isinstance(a, NamedArg) for a in e.args):
                    raise CodeGenError(f"struct '{struct_name}' construction only accepts positional arguments")
                if not e.args:
                    return struct_name
                if len(e.args) != len(struct_decl.fields):
                    raise CodeGenError(
                        f"struct '{struct_name}' construction expects {len(struct_decl.fields)} argument(s), {len(e.args)} provided"
                    )
                for arg, field in zip(e.args, struct_decl.fields):
                    at = self.infer_type(arg, local_types)
                    self._check_assignable(field.type, at, f"initializer for struct field '{field.name}'", arg)
                    self._check_expression_types(arg, local_types)
                return struct_name
            if isinstance(e.callee, Ident) and self._current_class:
                owner, method = self.resolve_class_method_call(
                    self._current_class.name,
                    e.callee.name,
                    e.args,
                    local_types,
                    receiver_const=bool(self._current_class_method_const),
                )
                if method is not None:
                    self._check_member_access(owner, method, e.callee.name)
                    return method.ret_type
            if self._is_reflection_member_exists_call(e):
                self._validate_member_exists_call(e, local_types)
                obj=self.gen_expr(e.callee.obj,local_types); name=self.gen_expr(e.args[0],local_types)
                return f"_j_reflect_member_exists((void*){obj},{name}->data)"
            if self._is_reflection_set_member_call(e):
                self._validate_set_member_call(e, local_types)
                obj=self.gen_expr(e.callee.obj,local_types); name=self.gen_expr(e.args[0],local_types)
                value=e.args[1]; t=self.infer_type(value,local_types); expr=self.gen_expr(value,local_types)
                if isinstance(t,tuple): t="i32" if t[1]=="int" else "f64"
                if t == "string": call = f'_j_reflect_set_member((void*){obj},{name}->data,"string",0,0,0.0,{expr},0)'
                elif t in ("f32","float","f64"): call = f'_j_reflect_set_member((void*){obj},{name}->data,"{t}",0,0,(double)({expr}),0,0)'
                elif t == "bool": call = f'_j_reflect_set_member((void*){obj},{name}->data,"bool",(long long)({expr}),0,0.0,0,0)'
                elif t in INTEGER_TYPES: call = f'_j_reflect_set_member((void*){obj},{name}->data,"{t}",(long long)({expr}),(unsigned long long)({expr}),0.0,0,0)'
                else: call = f'_j_reflect_set_member((void*){obj},{name}->data,"{t}",0,0,0.0,0,(void*)({expr}))'
                return call
            if isinstance(e.callee, MemberAccess):
                receiver_const = self._expr_is_const_receiver(e.callee.obj, local_types)
                ot = self.infer_type(e.callee.obj, local_types)
                if isinstance(ot, str) and ot.endswith("*"):
                    ot = ot.rstrip("*")
                gp=self._generic_parts(ot)
                if gp:
                    kind,inner=gp
                    if kind=="dynamic_list" and e.callee.name=="push":
                        if len(e.args) != 1: raise CodeGenError("dynamic_list::push expects 1 argument")
                        return "void"
                    if kind=="dynamic_list" and e.callee.name=="get":
                        if len(e.args) != 1: raise CodeGenError("dynamic_list::get expects 1 argument")
                        return "void*"
                    if kind=="dynamic_list" and e.callee.name=="type":
                        if len(e.args) != 1: raise CodeGenError("dynamic_list::type expects 1 argument")
                        return "string"
                    if kind=="dynamic_list" and e.callee.name=="size":
                        if len(e.args) != 0: raise CodeGenError("dynamic_list::size expects 0 arguments")
                        return "i32"
                    if kind=="list" and e.callee.name=="push":
                        if len(e.args) != 1: raise CodeGenError("list::push expects 1 argument")
                        at = self.infer_type(e.args[0], local_types)
                        self._check_assignable(inner, at, "argument of list::push", e.args[0])
                        return "void"
                    if kind=="list" and e.callee.name=="get":
                        if len(e.args) != 1: raise CodeGenError("list::get expects 1 argument")
                        self._check_assignable("i32", self.infer_type(e.args[0], local_types), "index of list::get", e.args[0])
                        return inner
                    if kind=="list" and e.callee.name=="size":
                        if len(e.args) != 0: raise CodeGenError("list::size expects 0 arguments")
                        return "i32"
                    if kind=="map" and e.callee.name=="emplace":
                        if len(e.args) != 2: raise CodeGenError("map::emplace expects 2 arguments")
                        kt,vt=self._split_generic_args(inner)
                        self._check_assignable(kt, self.infer_type(e.args[0], local_types), "key argument of map::emplace", e.args[0])
                        self._check_assignable(vt, self.infer_type(e.args[1], local_types), "value argument of map::emplace", e.args[1])
                        return "void"
                    if kind=="map" and e.callee.name=="size":
                        if len(e.args) != 0: raise CodeGenError("map::size expects 0 arguments")
                        return "i32"
                    if kind=="container" and e.callee.name=="get":
                        if len(e.args) != 0: raise CodeGenError("container::get expects 0 arguments")
                        return inner
                if ot == "string":
                    specs = {
                        "length": ("i32", []), "empty": ("bool", []),
                        "equals": ("bool", [Param("string", "other")]),
                        "contains": ("bool", [Param("string", "needle")]),
                        "starts_with": ("bool", [Param("string", "prefix")]),
                        "ends_with": ("bool", [Param("string", "suffix")]),
                        "concat": ("string", [Param("string", "other")]),
                        "substring": ("string", [Param("i32", "start"), Param("i32", "length")]),
                        "char_at": ("i32", [Param("i32", "index")]),
                        "to_upper": ("string", []), "to_lower": ("string", []),
                    }
                    if e.callee.name not in specs:
                        raise CodeGenError(f"unknown string::{e.callee.name} method")
                    ret_type, params = specs[e.callee.name]
                    ordered = self._ordered_call_args(e.args, params, f"string::{e.callee.name}")
                    for arg, param in zip(ordered, params):
                        self._check_assignable(param.type, self.infer_type(arg, local_types), f"argument '{param.name}' of string::{e.callee.name}", arg)
                    return ret_type
                owner, m = self.resolve_class_method_call(
                    ot, e.callee.name, e.args, local_types, receiver_const
                ) if ot in self.classes else (None, None)
                if m is not None:
                    self._check_member_access(owner, m, e.callee.name)
                    return m.ret_type
            if isinstance(e.callee, NamespacedIdent) and e.callee.namespace == "factory" and e.callee.name == "construct":
                return "void*"
            if isinstance(e.callee, NamespacedIdent) and self._current_class and e.callee.namespace in self.classes and self._current_class.base == e.callee.namespace:
                owner, m = self.resolve_class_method_call(
                    e.callee.namespace,
                    e.callee.name,
                    e.args,
                    local_types,
                    receiver_const=bool(self._current_class_method_const),
                )
                if m is not None:
                    self._check_member_access(owner, m, e.callee.name)
                    return m.ret_type
            system = self._validate_system_call(e, local_types)
            if system is not None:
                return system[2]
            target = self.resolve_call_target(e, local_types)
            if target is not None:
                return target.ret_type
            if callee_type is not None:
                if isinstance(callee_type, str) and callee_type.endswith("*"):
                    # Pointer values are not callable unless they are Jaguar
                    # function-pointer types, which were handled above.
                    raise CodeGenError(f"expression of type '{callee_type}' is not callable")
                if isinstance(e.callee, Ident):
                    raise CodeGenError(f"expression of type '{callee_type}' is not callable")
                if isinstance(e.callee, MemberAccess):
                    raise CodeGenError(f"member '{e.callee.name}' is not callable")
            return None
        return None

    def _gen_operand(self, e, parent_prec: int, local_types: dict, is_right: bool) -> str:
        """Génère un opérande de BinOp en ajoutant des parenthèses
        seulement si nécessaire : opérande de précédence plus faible, ou
        de même précédence à droite (a - (b - c) != a - b - c).
        Sans cela, `(1 + 2) * 3` serait émis `1 + 2 * 3`."""
        s = self.gen_expr(e, local_types)
        if isinstance(e, BinOp):
            p = _BINOP_PREC[e.op]
            if p < parent_prec or (p == parent_prec and is_right):
                return f"({s})"
        return s

    def _base_member_expr(self, root, cls, name):
        cur = cls
        expr = root
        first = True
        while cur:
            for f in cur.fields:
                if f.name == name:
                    return (expr + "->" + f.name) if first else (expr + "." + f.name)
            if cur.base:
                expr = expr + "->_base" if first else expr + "._base"
                first = False
                cur = self.classes[cur.base]
            else:
                break
        raise CodeGenError(f"member '{name}' not found in class '{cls.name}'")


    def _base_object_ptr_expr(self, root, cls, owner):
        """Retourne un pointeur vers le sous-objet `owner` d'un objet `cls`."""
        if cls.name == owner.name:
            return root
        cur = cls
        expr = root
        while cur and cur.name != owner.name:
            if not cur.base:
                break
            expr = f"&(({expr})->_base)"
            cur = self.classes.get(cur.base)
        if cur is not None and cur.name == owner.name:
            return expr
        raise CodeGenError(
            f"cannot resolve base-class object '{owner.name}' from '{cls.name}'"
        )

    def _class_can_access(self, owner, member) -> bool:
        """Vérifie l'accès à un membre de classe depuis le contexte courant."""
        access = getattr(member, "access", "private")
        if access == "public":
            return True
        if self._current_class is None:
            return False
        if access == "private":
            # private = uniquement la classe qui a réellement déclaré le membre.
            return self._current_class.name == owner.name
        if access == "protected":
            # protected = classe propriétaire + toutes ses classes dérivées.
            cur = self._current_class
            while cur:
                if cur.name == owner.name:
                    return True
                cur = self.classes.get(cur.base) if cur.base else None
            return False
        return False

    def _check_member_access(self, owner, member, name: str):
        if not self._class_can_access(owner, member):
            access = getattr(member, "access", "private")
            raise CodeGenError(
                f"{access} member '{name}' is inaccessible from class "
                f"'{self._current_class.name if self._current_class else 'this context'}'"
            )

    def gen_member_access(self, e, local_types):
        raw_ot=self.infer_type(e.obj, local_types)
        pointer_object = isinstance(raw_ot, str) and raw_ot.endswith("*")
        ot=raw_ot.rstrip("*") if pointer_object else raw_ot
        gp=self._generic_parts(ot)
        if gp:
            kind,inner=gp; obj=self.gen_expr(e.obj,local_types)
            if kind=="pair":
                if e.name not in ("first", "second"): raise CodeGenError(f"member '{e.name}' is not available on {ot}")
                return f"{obj}.{e.name}"
            if kind=="container" and e.name=="get": return f"(*(({self._collection_c_type(inner) if self._generic_parts(inner) else c_type(inner)}*)_j_container_get(&{obj})))"
            if kind=="container" and inner in self.classes: return f"(({inner}*)_j_container_get(&{obj}))->%s" % e.name
            raise CodeGenError(f"member '{e.name}' is not available on {ot}")
        if ot in self.unions:
            if not any(f.name == e.name for f in self.unions[ot].fields):
                raise CodeGenError(f"member '{e.name}' is absent from '{ot}'")
            obj = self.gen_expr(e.obj, local_types)
            return f"{obj}.{e.name}"
        if ot in self.structs:
            if not any(f.name == e.name for f in self.structs[ot].fields):
                raise CodeGenError(f"member '{e.name}' is absent from '{ot}'")
            obj = self.gen_expr(e.obj, local_types)
            return (f"{obj}->{e.name}" if pointer_object else f"{obj}.{e.name}")
        if ot not in self.classes:
            raise CodeGenError(f"'{ot}' is not a class")
        owner, member=self._find_class_member(ot,e.name,"field")
        if member is None:
            owner, member=self._find_class_member(ot,e.name,"method")
        if member is None: raise CodeGenError(f"member '{e.name}' is absent from '{ot}'")
        if not getattr(member, "is_exposed", False):
            self._check_member_access(owner, member, e.name)
        if isinstance(member, ClassMethod):
            self._check_const_receiver_method(
                member,
                self._expr_is_const_receiver(e.obj, local_types),
                e.name,
            )
        if isinstance(member, ClassField):
            if isinstance(e.obj, Ident) and self._current_class and e.obj.name=="this":
                return self._base_member_expr("self", self._current_class, e.name)
            obj = self.gen_expr(e.obj, local_types)
            if owner.name == ot:
                return obj + "->" + e.name
            return self._base_member_expr(obj, self.classes[ot], e.name)
        obj = self.gen_expr(e.obj, local_types)
        if owner.name == ot:
            return obj + "->" + e.name
        return f"{owner.name}_{e.name}({self._base_object_ptr_expr(obj, self.classes[ot], owner)})"

    def _is_reflection_call(self, e):
        return (isinstance(e, Call) and isinstance(e.callee, MemberAccess)
                and e.callee.name == "GetMember" and len(e.args) == 1)

    def _is_reflection_member_exists_call(self, e):
        return (isinstance(e, Call) and isinstance(e.callee, MemberAccess)
                and e.callee.name == "MemberExists" and len(e.args) == 1)

    def _is_reflection_set_member_call(self, e):
        return (isinstance(e, Call) and isinstance(e.callee, MemberAccess)
                and e.callee.name == "SetMember" and len(e.args) == 2)

    def _is_dynamic_reflection_object(self, expr):
        # Only values originating from factory:construct() are treated as
        # dynamically-typed Jaguar class instances for reflection. An arbitrary
        # void* must not gain reflection capabilities.
        if isinstance(expr, Call) and isinstance(expr.callee, NamespacedIdent):
            return expr.callee.namespace == "factory" and expr.callee.name == "construct"
        if isinstance(expr, Ident):
            return expr.name in getattr(self, "_dynamic_reflection_vars", set())
        return False

    def _validate_reflection_call(self, e, local_types):
        ot=self.infer_type(e.callee.obj,local_types)
        if ot not in self.classes and not self._is_dynamic_reflection_object(e.callee.obj):
            raise CodeGenError("GetMember() can only be used on a class instance")
        if self.infer_type(e.args[0],local_types)!="string": raise CodeGenError("GetMember() expects a member name of type 'string'")
        return ot

    def _validate_member_exists_call(self, e, local_types):
        ot=self.infer_type(e.callee.obj,local_types)
        if ot not in self.classes and not self._is_dynamic_reflection_object(e.callee.obj):
            raise CodeGenError("MemberExists() can only be used on a class instance")
        if self.infer_type(e.args[0],local_types)!="string": raise CodeGenError("MemberExists() expects a member name of type 'string'")
        return ot

    def _validate_set_member_call(self, e, local_types):
        ot=self.infer_type(e.callee.obj,local_types)
        if ot not in self.classes and not self._is_dynamic_reflection_object(e.callee.obj):
            raise CodeGenError("SetMember() can only be used on a class instance")
        if self.infer_type(e.args[0],local_types)!="string": raise CodeGenError("SetMember() expects a member name of type 'string' as its first argument")
        if len(e.args) != 2: raise CodeGenError("SetMember() expects exactly 2 arguments")
        if self.infer_type(e.args[1],local_types) is None: raise CodeGenError("SetMember() cannot determine the value type")
        return ot

    def _gen_reflection_value(self, call, target_type, local_types: dict) -> str:
        """Convertit implicitement le pointeur retourné par GetMember() en
        une valeur du type attendu par le contexte (ex: `int v =
        h.GetMember(name)`). Le nom du membre reste entièrement dynamique :
        seul le type attendu par le code appelant est connu à la compilation.
        """
        self._validate_reflection_call(call, local_types)
        obj = self.gen_expr(call.callee.obj, local_types)
        name = self.gen_expr(call.args[0], local_types)
        ptr = f"_j_reflect_get_member((void*){obj},{name}->data)"
        target = canonical_type(target_type)
        if target in INTEGER_TYPES:
            return f"(({c_type(target)})({ptr} ? *({c_type(target)}*){ptr} : 0))"
        if target in ("f32", "float", "f64", "double"):
            return f"(({c_type(target)})({ptr} ? *({c_type(target)}*){ptr} : 0.0))"
        if target == "bool":
            return f"(({c_type(target)})({ptr} ? *({c_type(target)}*){ptr} : 0))"
        if target == "string":
            return f'(({ptr} && *(string**){ptr}) ? string_from_cstr((*(string**){ptr})->data) : string_from_cstr(""))'
        # Pour les types de classes/pointeurs, GetMember() fournit
        # directement la valeur stockée.
        return f"({c_type(target)}){ptr}"

    def gen_expr(self, e, local_types: dict) -> str:
        if isinstance(e, NullPtrLit):
            return "((void*)0)"
        if isinstance(e, IntLit):
            return e.value
        if isinstance(e, FloatLit):
            return e.value
        if isinstance(e, StringLit):
            return f"string_from_literal({e.value})"
        if isinstance(e, BoolLit):
            return "1" if e.value else "0"     # pas de <stdbool.h> en C89
        if isinstance(e, UnaryOp):
            inner = self.gen_expr(e.operand, local_types)
            # Keep unary operators bound to the complete operand. Without
            # these parentheses, `!(a == b)` could become `(!a == b)` in C.
            if isinstance(e.operand, (BinOp, UnaryOp)):
                inner = f"({inner})"
            return f"({e.op}{inner})"
        if isinstance(e, NewExpr):
            if e.type in self.classes:
                ctor_args = e.args
                # `T* p => T(args)` is parsed as `new T(T(args))`; unwrap the
                # constructor call so the arrow shorthand invokes T's
                # constructor exactly once.
                if (len(e.args) == 1 and isinstance(e.args[0], Call)
                        and ((isinstance(e.args[0].callee, Ident) and self._resolve_class_name(e.args[0].callee.name) == e.type)
                             or (isinstance(e.args[0].callee, NamespacedIdent) and self._resolve_class_name(e.args[0].callee.name, e.args[0].callee.namespace) == e.type))):
                    ctor_args = e.args[0].args
                ctor=self.resolve_class_constructor_call(e.type, ctor_args, local_types)
                ordered=self._ordered_call_args(ctor_args,ctor.params,f"constructor '{e.type}'") if ctor else []
                symbol = ctor.mangled_name if ctor else f"{e.type}_ctor"
                return f"{symbol}(" + ", ".join(self.gen_expr(a,local_types) for a in ordered) + ")"
            if e.type in self.structs:
                if not e.args:
                    return f"_j_struct_{e.type}_new()"
                if len(e.args) == 1:
                    value = e.args[0].expr if isinstance(e.args[0], NamedArg) else e.args[0]
                    if isinstance(value, Call) and not value.args:
                        if isinstance(value.callee, Ident) and self._resolve_struct_name(value.callee.name) == e.type:
                            return f"_j_struct_{e.type}_new()"
                        if isinstance(value.callee, NamespacedIdent) and self._resolve_struct_name(value.callee.name, value.callee.namespace) == e.type:
                            return f"_j_struct_{e.type}_new()"
                raise CodeGenError(f"new {e.type} expects an empty constructor")
            if e.type in BUILTIN_TYPEDEFS or e.type in INTEGER_TYPES or e.type in FLOAT_TYPES or e.type == "bool":
                if len(e.args) != 1:
                    raise CodeGenError(f"new {e.type}(value) expects exactly one initializer")
                value=e.args[0].expr if isinstance(e.args[0],NamedArg) else e.args[0]
                vt=self.infer_type(value,local_types)
                self._check_assignable(e.type, vt, f"initializer of new {e.type}", e.args[0] if e.args else e)
                n=self._tmp_id; self._tmp_id+=1
                return f"(({c_type(e.type)}*)({self.gen_expr(value,local_types)}))" if False else f"((({c_type(e.type)}*)_j_alloc_value(sizeof({c_type(e.type)}), &( {c_type(e.type)} ){{ {self.gen_expr(value,local_types)} }})))"
            raise CodeGenError(f"cannot allocate value of unknown type '{e.type}' with new")
        if isinstance(e, ListLiteral):
            raise CodeGenError("a {...} literal must be used as a list/map initializer")
        if isinstance(e, IndexAccess):
            ot=self.infer_type(e.obj,local_types); gp=self._generic_parts(ot)
            arr = self._fixed_array_parts(ot) if isinstance(ot, str) else None
            obj=self.gen_expr(e.obj,local_types); idx=self.gen_expr(e.index,local_types)
            if arr is not None:
                return f"{obj}[{idx}]"
            if not gp: raise CodeGenError(f"'[]' cannot be used on '{ot}'")
            if gp[0]=="dynamic_list": return f"_j_dynamic_list_get(&{obj},(size_t)({idx}))"
            if gp[0]=="list": return f"(*({self._collection_c_type(gp[1])}*)_j_list_get(&{obj},(size_t)({idx})))"
            if gp[0]=="dynamic_list": return f"_j_dynamic_list_get(&{obj},(size_t)({idx}))"
            if gp[0]=="map":
                kt,vt=self._split_generic_args(gp[1])
                self._check_assignable(kt, self.infer_type(e.index, local_types), "map index", e.index)
                value_c = self._storage_c_type(vt)
                if kt=="string":
                    if isinstance(e.index, StringLit):
                        return f"(*({value_c}*)_j_map_get_string_cstr(&{obj},{e.index.value}))"
                    return f"(*({value_c}*)_j_map_get_string(&{obj},{idx}))"
                scalar_key = canonical_type(kt)
                if scalar_key in INTEGER_TYPES or scalar_key in FLOAT_TYPES or scalar_key == "bool":
                    helper = f"_j_map_get_{scalar_key}" if scalar_key != "bool" else "_j_map_get_bool"
                    return f"(*({value_c}*){helper}(&{obj},({c_type(scalar_key)})({idx})))"
                if not (isinstance(e.index, (Ident, MemberAccess, IndexAccess))
                        or (isinstance(e.index, UnaryOp) and e.index.op == "*")):
                    raise CodeGenError(
                        "map indexing with a non-scalar key requires an addressable key expression (for example a variable)"
                    )
                return f"(*({value_c}*)_j_map_get(&{obj}, (const void*)&({idx})))"
            raise CodeGenError("a container cannot be indexed")
        if isinstance(e, Ident):
            if e.name == "this":
                if not self._current_class:
                    raise CodeGenError("'this' is only available inside a class")
                return "self"
            if self._current_class and e.name not in local_types and e.name not in self.global_types:
                fowner, f=self._find_class_member(self._current_class.name,e.name,"field")
                if f:
                    self._check_member_access(fowner, f, e.name)
                    return f"self->{e.name}" if fowner == self._current_class else self._base_member_expr("self", self._current_class, e.name)
                mowner, m=self._find_class_member(self._current_class.name,e.name,"method")
                if m:
                    self._check_member_access(mowner, m, e.name)
                    return f"{self._current_class.name}_{e.name}(self" + (", " if m.params else "") + ", ".join(p.name for p in m.params) + ")"
            symbols = getattr(self.program, "_using_symbols", {})
            imported = symbols.get(e.name)
            if imported:
                ns, name = imported
                imported_fns = self.groups.get((ns, name), [])
                if len(imported_fns) == 1:
                    return imported_fns[0].mangled_name or self.default_mangle(name, ns)
                for key, en in getattr(self.program, "_enums", {}).items():
                    if key == f"{ns}:{en.name}" and name in en.values:
                        return f"{ns}_{en.name}_{name}" if ns else f"{en.name}_{name}"
            namespace_function_matches = []
            for ns in getattr(self.program, "_using_namespaces", []):
                ns_fns = self.groups.get((ns, e.name), [])
                if len(ns_fns) == 1:
                    namespace_function_matches.append(ns_fns[0])
                for key, en in getattr(self.program, "_enums", {}).items():
                    if key == f"{ns}:{en.name}" and e.name in en.values:
                        return f"{ns}_{en.name}_{e.name}"
            if len(namespace_function_matches) == 1:
                return namespace_function_matches[0].mangled_name or self.default_mangle(e.name, namespace_function_matches[0].namespace)
            for en in getattr(self.program, "_enums", {}).values():
                if en.namespace is None and e.name in en.values:
                    return f"{en.name}_{e.name}"
            if e.name in self.union_globals:
                return self.union_globals[e.name]
            gname = self._resolve_global_name(e.name)
            if gname and gname in self.union_globals:
                return self.union_globals[gname]
            if gname: return gname
            cname = self._resolve_class_name(e.name)
            if cname: return cname
            return e.name
        if isinstance(e, MemberAccess):
            return self.gen_member_access(e, local_types)
        if isinstance(e, NamespacedIdent):
            enums = getattr(self.program, "_enums", {})
            for key, en in enums.items():
                if (en.namespace == e.namespace and e.name in en.values) or (en.name == e.namespace and e.name in en.values):
                    cname = f"{en.namespace}_{en.name}" if en.namespace else en.name
                    return f"{cname}_{e.name}"
            if e.namespace == "factory" and e.name == "construct":
                return "_j_factory_construct"
            q = f"{e.namespace.replace(':', '_')}_{e.name}"
            if q in self.global_types:
                if q in self.union_globals: return self.union_globals[q]
                return q
            if q in self.classes:
                return q
            if self._current_class and e.namespace in self.classes:
                owner, m = self._find_class_member(e.namespace, e.name, "method")
                if m is not None and self._current_class.base == e.namespace:
                    return f"{e.namespace}_{e.name}(self" + (", " if m.params else "") + ", ".join(p.name for p in m.params) + ")"
            candidates = self.groups.get((e.namespace, e.name), [])
            if len(candidates) == 1:
                return candidates[0].mangled_name or self.default_mangle(e.name, e.namespace)
            return self.default_mangle(e.name, e.namespace)
        if isinstance(e, CastExpr):
            # dynamic_list stocke les valeurs primitives par adresse et les objets
            # comme pointeurs. Un cast vers une valeur primitive déréférence donc
            # l'élément, tandis qu'un cast vers une classe conserve le pointeur.
            if isinstance(e.operand, IndexAccess):
                ot = self.infer_type(e.operand.obj, local_types)
                gp = self._generic_parts(ot)
                if gp and gp[0] == "dynamic_list":
                    obj = self.gen_expr(e.operand.obj, local_types)
                    idx = self.gen_expr(e.operand.index, local_types)
                    ptr = f"_j_dynamic_list_get(&{obj},(size_t)({idx}))"
                    target = canonical_type(e.target_type)
                    if target in INTEGER_TYPES:
                        return f"(({c_type(target)})*((({c_type(target)}*){ptr})))"
                    if target in ("f32", "float", "f64", "double"):
                        return f"(({c_type(target)})*((({c_type(target)}*){ptr})))"
                    if target == "bool":
                        return f"(({c_type(target)})*(((_jBool*){ptr})))"
                    if target == "string":
                        return f"(({ptr} && *(string**){ptr}) ? string_from_cstr((*(string**){ptr})->data) : string_from_cstr(""))"
                    if target in self.classes:
                        return f"({target}*){ptr}"
                    return f"({c_type(target)}){ptr}"
            # GetMember() retourne volontairement un pointeur vers la vraie
            # valeur stockée dans l'objet. Un cast Jaguar vers un type valeur
            # doit donc déréférencer ce pointeur, au lieu de convertir
            # directement l'adresse en entier (ce qui donnait l'adresse du
            # champ, tronquée en i32).
            if isinstance(e.operand, Call) and self._is_reflection_call(e.operand):
                self._validate_reflection_call(e.operand, local_types)
                obj = self.gen_expr(e.operand.callee.obj, local_types)
                name = self.gen_expr(e.operand.args[0], local_types)
                target = e.target_type
                ptr = f"_j_reflect_get_member((void*){obj},{name}->data)"
                if target in INTEGER_TYPES:
                    return f"(({c_type(target)})({ptr} ? *({c_type(target)}*){ptr} : 0))"
                if target in ("f32", "float", "f64", "double"):
                    return f"(({c_type(target)})({ptr} ? *({c_type(target)}*){ptr} : 0.0))"
                if target == "bool":
                    return f"(({c_type(target)})({ptr} ? *({c_type(target)}*){ptr} : 0))"
                if target == "string":
                    return f'(({ptr} && *(string**){ptr}) ? string_from_cstr((*(string**){ptr})->data) : string_from_cstr(""))'
                # Pour les types pointeurs/classes, GetMember() fournit déjà
                # directement l'adresse/valeur stockée.
                return f"({c_type(target)}){ptr}"
            # A union value is not directly castable in C. Jaguar allows a
            # union value to be viewed through the member whose type matches
            # the cast target, e.g. `(int)val` for `union val { int a; ... }`.
            if isinstance(e.operand, Ident):
                union_type = self.infer_type(e.operand, local_types)
                if union_type in self.unions:
                    target = canonical_type(e.target_type)
                    for field in self.unions[union_type].fields:
                        if canonical_type(field.type) == target:
                            obj = self.gen_expr(e.operand, local_types)
                            return f"({c_type(e.target_type)})({obj}.{field.name})"
                    raise CodeGenError(
                        f"cannot cast union '{union_type}' to '{e.target_type}': "
                        "the target type is not one of its members"
                    )
            # Casts ordinaires : forme C classique.
            return f"({c_type(e.target_type)}){self.gen_expr(e.operand, local_types)}"
        if isinstance(e, UnaryOp):
            inner = self.gen_expr(e.operand, local_types)
            # -(-x) et non --x (qui serait un décrément en C) ; !(a && b)
            if isinstance(e.operand, (BinOp, UnaryOp)):
                inner = f"({inner})"
            return f"{e.op}{inner}"
        if isinstance(e, BinOp):
            left_type = self.infer_type(e.left,local_types)
            right_type = self.infer_type(e.right,local_types)
            custom=self._resolve_operator(e.op, left_type, right_type)
            if custom is not None:
                return f"{custom.mangled_name}({self.gen_expr(e.left,local_types)}, {self.gen_expr(e.right,local_types)})"
            if e.op == "+" and left_type == "string" and right_type == "string":
                return f"string_concat({self.gen_expr(e.left,local_types)}, {self.gen_expr(e.right,local_types)})"
            prec = _BINOP_PREC[e.op]
            left = self._gen_operand(e.left, prec, local_types, is_right=False)
            right = self._gen_operand(e.right, prec, local_types, is_right=True)
            return f"{left} {e.op} {right}"
        if isinstance(e, Call):
            if isinstance(e.callee, Ident) and e.callee.name == "func" and self._decorator_call_target_name is not None:
                if e.args:
                    raise CodeGenError("decorator 'func()' does not accept explicit arguments")
                args = ", ".join(p.name for p in self._decorator_target_params)
                return f"{self._decorator_call_target_name}({args})"
            # Reflection calls have a special dynamic receiver (`factory:construct()`
            # may only be known as `void*`), so they must be recognized before
            # asking for the type of the `MemberAccess` callee.
            if self._is_reflection_call(e):
                self._validate_reflection_call(e, local_types)
                obj = self.gen_expr(e.callee.obj, local_types)
                name = self.gen_expr(e.args[0], local_types)
                return f"_j_reflect_get_member((void*){obj},{name}->data)"
            if self._is_reflection_member_exists_call(e):
                self._validate_member_exists_call(e, local_types)
                obj = self.gen_expr(e.callee.obj, local_types)
                name = self.gen_expr(e.args[0], local_types)
                return f"_j_reflect_member_exists((void*){obj},{name}->data)"
            if self._is_reflection_set_member_call(e):
                self._validate_set_member_call(e, local_types)
                obj = self.gen_expr(e.callee.obj, local_types)
                name = self.gen_expr(e.args[0], local_types)
                value = e.args[1]
                t = self.infer_type(value, local_types)
                expr = self.gen_expr(value, local_types)
                if isinstance(t, tuple):
                    t = "i32" if t[1] == "int" else "f64"
                if t == "string":
                    return f'_j_reflect_set_member((void*){obj},{name}->data,"string",0,0,0.0,{expr},0)'
                if t in ("f32", "float", "f64"):
                    return f'_j_reflect_set_member((void*){obj},{name}->data,"{t}",0,0,(double)({expr}),0,0)'
                if t == "bool":
                    return f'_j_reflect_set_member((void*){obj},{name}->data,"bool",(long long)({expr}),0,0.0,0,0)'
                if t in INTEGER_TYPES:
                    return f'_j_reflect_set_member((void*){obj},{name}->data,"{t}",(long long)({expr}),(unsigned long long)({expr}),0.0,0,0)'
                return f'_j_reflect_set_member((void*){obj},{name}->data,"{t}",0,0,0.0,0,(void*)({expr}))'
            callee_type = self.infer_type(e.callee, local_types)
            fp_parts = self._function_type_parts(callee_type) if isinstance(callee_type, str) else None
            # A uniquely-resolved named/namespace function also has a
            # function type when used as a value. In a call position it must
            # still go through normal overload/default/named-argument
            # resolution rather than being mistaken for a function pointer.
            direct_function_call = False
            if isinstance(e.callee, Ident):
                direct_function_call = bool(self.groups.get((None, e.callee.name)))
                if not direct_function_call:
                    imported = getattr(self.program, "_using_symbols", {}).get(e.callee.name)
                    if imported:
                        direct_function_call = bool(self.groups.get(imported))
            elif isinstance(e.callee, NamespacedIdent):
                direct_function_call = bool(self.groups.get((e.callee.namespace, e.callee.name)))
            if fp_parts is not None and not direct_function_call:
                if any(isinstance(a, NamedArg) for a in e.args):
                    raise CodeGenError("named parameters are not available for function-pointer calls")
                params, _ = fp_parts
                variadic = bool(params and params[-1] == "...")
                fixed_params = params[:-1] if variadic else params
                if (not variadic and len(e.args) != len(fixed_params)) or (variadic and len(e.args) < len(fixed_params)):
                    expected = f"at least {len(fixed_params)}" if variadic else str(len(fixed_params))
                    raise CodeGenError(f"function pointer expects {expected} argument(s), {len(e.args)} provided")
                for param_type, arg in zip(fixed_params, e.args):
                    at = self.infer_type(arg, local_types)
                    self._check_assignable(param_type, at, "argument of function pointer call", arg)
                callee = self.gen_expr(e.callee, local_types)
                args = ", ".join(
                    [self._gen_expr_for_expected_type(a, param_type, local_types) for a, param_type in zip(e.args, fixed_params)]
                    + ([self.gen_expr(a, local_types) for a in e.args[len(fixed_params):]] if variadic else [])
                )
                return f"{callee}({args})"
            if self._is_reflection_call(e):
                self._validate_reflection_call(e, local_types)
                obj=self.gen_expr(e.callee.obj,local_types); name=self.gen_expr(e.args[0],local_types)
                return f"_j_reflect_get_member((void*){obj},{name}->data)"
            # Appel direct à une méthode de la classe courante (ou héritée) :
            # `printff()` doit devenir `MyClass_printff(self, ...)` et, pour
            # une méthode définie dans une classe de base, recevoir l'adresse
            # du sous-objet `_base` correspondant. Cela doit aussi passer par
            # la résolution normale des paramètres (y compris les paramètres
            # nommés).
            if isinstance(e.callee, Ident) and self._current_class:
                owner, method = self.resolve_class_method_call(self._current_class.name, e.callee.name, e.args, local_types)
                if method is not None:
                    self._check_member_access(owner, method, e.callee.name)
                    ordered_args = self._ordered_call_args(e.args, method.params, f"'{e.callee.name}'")
                    args = ", ".join(self.gen_expr(a, local_types) for a in ordered_args)
                    if owner.name == self._current_class.name:
                        if method.is_virtual:
                            return f"self->_vptr->{self._vtable_method_name(method)}((void*)self" + (", " + args if args else "") + ")"
                        return f"{method.mangled_name or (owner.name + '_' + method.name)}(self" + (", " + args if args else "") + ")"
                    base_self = "self"
                    cur = self._current_class
                    first_base = True
                    while cur is not None and cur.name != owner.name:
                        if not cur.base:
                            break
                        base_self += ("->_base" if first_base else "._base")
                        first_base = False
                        cur = self.classes.get(cur.base)
                    if cur is not None and cur.name == owner.name:
                        return f"{method.mangled_name or (owner.name + '_' + method.name)}(&{base_self}" + (", " + args if args else "") + ")"
                    raise CodeGenError(
                        f"cannot resolve base-class method '{e.callee.name}' from class '{self._current_class.name}'"
                    )

            if isinstance(e.callee, NamespacedIdent) and e.callee.namespace == "factory" and e.callee.name == "construct":
                if len(e.args) != 1 or isinstance(e.args[0], NamedArg):
                    raise CodeGenError("factory:construct() expects exactly one positional argument (the class name)")
                return f"_j_factory_construct({self.gen_expr(e.args[0], local_types)})"
            if isinstance(e.callee, Ident) and e.callee.name == "string":
                if len(e.args) != 0:
                    raise CodeGenError("string() takes no arguments; use a string literal")
                return "string_ctor()"
            if self._is_reflection_member_exists_call(e):
                self._validate_member_exists_call(e, local_types)
                obj=self.gen_expr(e.callee.obj,local_types); name=self.gen_expr(e.args[0],local_types)
                return f"_j_reflect_member_exists((void*){obj},{name}->data)"
            if self._is_reflection_set_member_call(e):
                self._validate_set_member_call(e, local_types)
                obj=self.gen_expr(e.callee.obj,local_types); name=self.gen_expr(e.args[0],local_types)
                value=e.args[1]; t=self.infer_type(value,local_types); expr=self.gen_expr(value,local_types)
                if isinstance(t,tuple): t="i32" if t[1]=="int" else "f64"
                if t == "string": call = f'_j_reflect_set_member((void*){obj},{name}->data,"string",0,0,0.0,{expr},0)'
                elif t in ("f32","float","f64"): call = f'_j_reflect_set_member((void*){obj},{name}->data,"{t}",0,0,(double)({expr}),0,0)'
                elif t == "bool": call = f'_j_reflect_set_member((void*){obj},{name}->data,"bool",(long long)({expr}),0,0.0,0,0)'
                elif t in INTEGER_TYPES: call = f'_j_reflect_set_member((void*){obj},{name}->data,"{t}",(long long)({expr}),(unsigned long long)({expr}),0.0,0,0)'
                else: call = f'_j_reflect_set_member((void*){obj},{name}->data,"{t}",0,0,0.0,0,(void*)({expr}))'
                return call
            if isinstance(e.callee, MemberAccess):
                ot = self.infer_type(e.callee.obj, local_types)
                if isinstance(ot, str) and ot.endswith("*"):
                    ot = ot.rstrip("*")
                gp=self._generic_parts(ot)
                if gp:
                    kind,inner=gp; obj=self.gen_expr(e.callee.obj,local_types)
                    if kind=="dynamic_list" and e.callee.name=="push":
                        if len(e.args)!=1: raise CodeGenError("dynamic_list::push expects 1 argument")
                        return "".join(self._gen_dynamic_list_push(obj, e.args[0], local_types))
                    if kind=="dynamic_list" and e.callee.name=="get":
                        if len(e.args)!=1: raise CodeGenError("dynamic_list::get expects 1 argument")
                        idx=self.gen_expr(e.args[0],local_types)
                        return f"_j_dynamic_list_get(&{obj},(size_t)({idx}))"
                    if kind=="dynamic_list" and e.callee.name=="type":
                        if len(e.args)!=1: raise CodeGenError("dynamic_list::type expects 1 argument")
                        idx=self.gen_expr(e.args[0],local_types)
                        return f"string_from_cstr(_j_dynamic_list_type(&{obj},(size_t)({idx})))"
                    if kind=="dynamic_list" and e.callee.name=="size":
                        if len(e.args)!=0: raise CodeGenError("dynamic_list::size expects 0 arguments")
                        return f"(i32){obj}.size"
                    if kind=="list" and e.callee.name=="size":
                        if len(e.args)!=0: raise CodeGenError("list::size expects 0 arguments")
                        return f"(i32){obj}.size"
                    if kind=="list" and e.callee.name=="get":
                        if len(e.args)!=1: raise CodeGenError("list::get expects 1 argument")
                        idx=self.gen_expr(e.args[0],local_types)
                        elem_c=self._collection_c_type(inner)
                        return f"(*({elem_c}*)_j_list_get(&{obj},(size_t)({idx})))"
                    if kind=="list" and e.callee.name=="push":
                        if isinstance(e.callee.obj, Ident) and e.callee.obj.name in self._readonly_vars:
                            raise CodeGenError(f"list '{e.callee.obj.name}' is read-only during loop_list")
                        if len(e.args)!=1: raise CodeGenError("list::push expects 1 argument")
                        ex_type = self.infer_type(e.args[0], local_types)
                        self._check_assignable(inner, ex_type, "argument of list::push", e.args[0])
                        ex=self.gen_expr(e.args[0],local_types); n=self._tmp_id; self._tmp_id+=1
                        return f"{{ {self._storage_c_type(inner)} _jcp{n} = {ex}; _j_list_push(&{obj}, &_jcp{n}); }}"
                    if kind=="map" and e.callee.name=="emplace":
                        if isinstance(e.callee.obj, Ident) and e.callee.obj.name in self._readonly_vars:
                            raise CodeGenError(f"map '{e.callee.obj.name}' is read-only during loop_map")
                        if len(e.args)!=2: raise CodeGenError("map::emplace expects 2 arguments")
                        kt,vt=self._split_generic_args(inner)
                        self._check_assignable(kt, self.infer_type(e.args[0], local_types), "key argument of map::emplace", e.args[0])
                        self._check_assignable(vt, self.infer_type(e.args[1], local_types), "value argument of map::emplace", e.args[1])
                        k=self.gen_expr(e.args[0],local_types); v=self.gen_expr(e.args[1],local_types); n=self._tmp_id; self._tmp_id+=1
                        return f"{{ {self._storage_c_type(kt)} _jmk{n} = {k}; {self._storage_c_type(vt)} _jmv{n} = {v}; _j_map_emplace(&{obj}, &_jmk{n}, &_jmv{n}); }}"
                    if kind=="map" and e.callee.name=="size":
                        if len(e.args)!=0: raise CodeGenError("map::size expects 0 arguments")
                        return f"(i32){obj}.size"
                    if kind=="container" and e.callee.name=="get":
                        if len(e.args)!=0: raise CodeGenError("container::get expects 0 arguments")
                        return f"(*(({self._collection_c_type(inner) if self._generic_parts(inner) else c_type(inner)}*)_j_container_get(&{obj})))"
                if ot == "string":
                    obj = self.gen_expr(e.callee.obj, local_types)
                    args = ", ".join(self.gen_expr(a, local_types) for a in self._ordered_call_args(e.args, [Param("string", "other")] if e.callee.name in ("equals","contains","starts_with","ends_with","concat") else [Param("i32","start"),Param("i32","length")] if e.callee.name=="substring" else [Param("i32","index")] if e.callee.name=="char_at" else [], f"string::{e.callee.name}"))
                    mapping = {
                        "length": ("string_length", 0), "empty": ("string_empty", 0),
                        "equals": ("string_equals", 1), "contains": ("string_contains", 1),
                        "starts_with": ("string_starts_with", 1), "ends_with": ("string_ends_with", 1),
                        "concat": ("string_concat", 1), "substring": ("string_substring", 2),
                        "char_at": ("string_char_at", 1), "to_upper": ("string_to_upper", 0),
                        "to_lower": ("string_to_lower", 0),
                    }
                    if e.callee.name not in mapping:
                        raise CodeGenError(f"unknown string::{e.callee.name} method")
                    fn, argc = mapping[e.callee.name]
                    if len(e.args) != argc:
                        raise CodeGenError(f"string::{e.callee.name} expects {argc} argument(s)")
                    string_params = [Param("string", "other")] if e.callee.name in ("equals","contains","starts_with","ends_with","concat") else [Param("i32","start"), Param("i32","length")] if e.callee.name == "substring" else [Param("i32","index")] if e.callee.name == "char_at" else []
                    ordered_args = self._ordered_call_args(e.args, string_params, f"string::{e.callee.name}")
                    for arg, param in zip(ordered_args, string_params):
                        self._check_assignable(param.type, self.infer_type(arg, local_types), f"argument '{param.name}' of string::{e.callee.name}", arg)
                    args = ", ".join(self.gen_expr(a, local_types) for a in ordered_args)
                    return f"{fn}({obj}" + (", " + args if args else "") + ")"
            if isinstance(e.callee, Ident):
                class_name = self._resolve_class_name(e.callee.name)
            elif isinstance(e.callee, NamespacedIdent):
                class_name = self._resolve_class_name(e.callee.name, e.callee.namespace)
            else:
                class_name = None
            if class_name is not None:
                ctor=self.resolve_class_constructor_call(class_name, e.args, local_types)
                ordered_args=self._ordered_call_args(e.args, ctor.params, f"constructeur '{class_name}'") if ctor else []
                args=", ".join(self.gen_expr(a,local_types) for a in ordered_args)
                symbol = ctor.mangled_name if ctor else f"{class_name}_ctor"
                return f"{symbol}({args})"
            if isinstance(e.callee, Ident):
                struct_name = self._resolve_struct_name(e.callee.name)
            elif isinstance(e.callee, NamespacedIdent):
                struct_name = self._resolve_struct_name(e.callee.name, e.callee.namespace)
            else:
                struct_name = None
            if struct_name is not None:
                struct_decl = self.structs[struct_name]
                if any(isinstance(a, NamedArg) for a in e.args):
                    raise CodeGenError(f"struct '{struct_name}' construction only accepts positional arguments")
                if not e.args:
                    return f"_j_struct_{struct_name}_default()"
                if len(e.args) != len(struct_decl.fields):
                    raise CodeGenError(
                        f"struct '{struct_name}' construction expects {len(struct_decl.fields)} argument(s), {len(e.args)} provided"
                    )
                for arg, field in zip(e.args, struct_decl.fields):
                    at = self.infer_type(arg, local_types)
                    self._check_assignable(field.type, at, f"initializer for struct field '{field.name}'", arg)
                    self._check_expression_types(arg, local_types)
                return f"_j_struct_{struct_name}_make(" + ", ".join(self.gen_expr(a, local_types) for a in e.args) + ")"
            if isinstance(e.callee, NamespacedIdent) and self._current_class and e.callee.namespace in self.classes and self._current_class.base == e.callee.namespace:
                owner,m=self.resolve_class_method_call(
                    e.callee.namespace,
                    e.callee.name,
                    e.args,
                    local_types,
                    receiver_const=bool(self._current_class_method_const),
                )
                if m is not None:
                    ordered_args=self._ordered_call_args(e.args, m.params, f"'{e.callee.name}'")
                    args=", ".join(self.gen_expr(a,local_types) for a in ordered_args)
                    return f"{m.mangled_name or (owner.name + '_' + m.name)}(&self->_base" + (", "+args if args else "") + ")"
            if isinstance(e.callee, Ident) and self._current_class:
                owner, m = self.resolve_class_method_call(
                    self._current_class.name,
                    e.callee.name,
                    e.args,
                    local_types,
                    receiver_const=bool(self._current_class_method_const),
                )
                if m is not None:
                    self._check_member_access(owner, m, e.callee.name)
                    ordered_args = self._ordered_call_args(e.args, m.params, f"'{e.callee.name}'")
                    args = ", ".join(self.gen_expr(a, local_types) for a in ordered_args)
                    if owner.name == self._current_class.name:
                        if m.is_virtual:
                            self_arg = "(const void*)self" if m.is_const else "(void*)self"
                            return f"self->_vptr->{self._vtable_method_name(m)}({self_arg}" + (", " + args if args else "") + ")"
                        return f"{m.mangled_name or (owner.name + '_' + m.name)}(self" + (", " + args if args else "") + ")"
                    base_self = "self"
                    cur = self._current_class
                    while cur is not None and cur.name != owner.name:
                        if not cur.base:
                            break
                        base_self += "->_base"
                        cur = self.classes.get(cur.base)
                    if cur is not None and cur.name == owner.name:
                        return f"{m.mangled_name or (owner.name + '_' + m.name)}(&{base_self}" + (", " + args if args else "") + ")"
                    raise CodeGenError(
                        f"cannot resolve base-class method '{e.callee.name}' from class '{self._current_class.name}'"
                    )
            if isinstance(e.callee, MemberAccess):
                receiver_const = self._expr_is_const_receiver(e.callee.obj, local_types)
                ot=self.infer_type(e.callee.obj,local_types)
                if isinstance(ot, str) and ot.endswith("*"):
                    ot = ot.rstrip("*")
                owner, m = self.resolve_class_method_call(ot, e.callee.name, e.args, local_types, receiver_const) if ot in self.classes else (None, None)
                if m is not None:
                    self._check_member_access(owner, m, e.callee.name)
                    obj=self.gen_expr(e.callee.obj,local_types)
                    ordered_args=self._ordered_call_args(e.args, m.params, f"'{e.callee.name}'")
                    args=", ".join(self.gen_expr(a,local_types) for a in ordered_args)
                    if m.is_virtual:
                        self_arg = f"(const void*){obj}" if m.is_const else f"(void*){obj}"
                        return f"{obj}->_vptr->{self._vtable_method_name(m)}({self_arg}" + (", "+args if args else "") + ")"
                    receiver = obj if owner.name == ot else self._base_object_ptr_expr(obj, self.classes[ot], owner)
                    return f"{m.mangled_name or (owner.name + '_' + m.name)}({receiver}" + (", "+args if args else "") + ")"
            target = None
            system = self._validate_system_call(e, local_types)
            if system is not None:
                if isinstance(e.callee, NamespacedIdent) and e.callee.namespace == "thread":
                    args = [self.gen_expr(a.expr if isinstance(a, NamedArg) else a, local_types) for a in e.args]
                    if e.callee.name == "start": return f"_j_thread_start({args[0]})"
                    if e.callee.name == "join": return f"_j_thread_join({args[0]})"
                    if e.callee.name == "detach": return f"_j_thread_detach({args[0]})"
                    if e.callee.name == "sleep": return f"_j_thread_sleep((i32)({args[0]}))"
                    if e.callee.name == "yield": return "_j_thread_yield()"
                # sys:print accepte les types primitifs imprimables.
                is_sys_print = (
                    e.callee.name == "print"
                    and isinstance(e.callee, (Ident, NamespacedIdent))
                    and system == SYSTEM_BUILTINS.get(("sys", "print"))
                )
                if is_sys_print:
                    if self._is_reflection_call(e.args[0]):
                        self._validate_reflection_call(e.args[0], local_types)
                        robj=self.gen_expr(e.args[0].callee.obj,local_types); rname=self.gen_expr(e.args[0].args[0],local_types)
                        return f"_j_reflect_print((void*){robj},{rname}->data)"
                    if isinstance(e.args[0], IndexAccess):
                        indexed_type = self.infer_type(e.args[0].obj, local_types)
                        indexed_gp = self._generic_parts(indexed_type)
                        if indexed_gp and indexed_gp[0] == "dynamic_list":
                            obj = self.gen_expr(e.args[0].obj, local_types)
                            idx = self.gen_expr(e.args[0].index, local_types)
                            return f"_j_sys_print_dynamic(_j_dynamic_list_get(&{obj},(size_t)({idx})), _j_dynamic_list_type(&{obj},(size_t)({idx})))"
                    arg_type = self.infer_type(e.args[0], local_types)
                    callee_str = self._system_print_function(arg_type)
                    if callee_str is None:
                        raise CodeGenError(
                            "sys:print cannot automatically print "
                            f"an expression of type '{arg_type}'"
                        )
                else:
                    callee_str = system[0]
            else:
                target = self.resolve_call_target(e, local_types)
                if target is not None:
                    callee_str = target.mangled_name
                else:
                    raise CodeGenError(f"unknown function '{e.callee.namespace + ':' if isinstance(e.callee, NamespacedIdent) else ''}{e.callee.name}'")
            if system is not None and any(isinstance(a, NamedArg) for a in e.args):
                raise CodeGenError("named parameters are not available for built-in jcc/sys functions")
            if system is not None:
                ordered_args=e.args
            else:
                ordered_args=self._ordered_call_args(e.args, target.params, f"'{target.name}'", target.is_variadic) if target is not None else e.args
            if target is not None:
                args = self._gen_ordered_call_args(ordered_args, target.params, local_types, target.is_variadic)
            else:
                args = ", ".join(self.gen_expr(a, local_types) for a in ordered_args)
            return f"{callee_str}({args})"
        raise NotImplementedError(f"unsupported expression: {e!r}")


# Attach precise source spans to semantic CodeGen errors at the AST node that
# triggered them. Parser nodes are annotated with expression/statement spans,
# so this remains source-language aware and never guesses from generated C.
def _attach_codegen_node_span(method, arg_index):
    def wrapped(self, *args, **kwargs):
        try:
            return method(self, *args, **kwargs)
        except CodeGenError as exc:
            if not hasattr(exc, "_jaguar_column"):
                node = args[arg_index] if len(args) > arg_index else None
                if node is not None:
                    # Statement-level errors should point at the actual offending
                    # expression rather than the indentation/start of the statement.
                    if isinstance(node, ReturnStmt) and node.expr is not None:
                        node = node.expr
                    elif isinstance(node, IfStmt) and "if condition" in str(exc):
                        node = node.cond
                    elif isinstance(node, WhileStmt) and "while condition" in str(exc):
                        node = node.cond
                    elif isinstance(node, MemberAssignStmt):
                        node = node.target if "member" in str(exc) else node.expr
                    elif isinstance(node, PointerAssignStmt):
                        node = node.expr
                    line = getattr(node, "_jaguar_line", None)
                    col = getattr(node, "_jaguar_column", None)
                    end = getattr(node, "_jaguar_end_column", None)
                    if isinstance(node, MemberAccess) and "member '" in str(exc):
                        col = getattr(node, "_jaguar_member_column", col)
                        end = getattr(node, "_jaguar_member_end_column", end)
                    if method.__name__ == "gen_member_access":
                        col = getattr(node, "_jaguar_member_column", col)
                        end = getattr(node, "_jaguar_member_end_column", end)
                    if method.__name__ == "resolve_call_target":
                        col = getattr(node, "_jaguar_callee_column", col)
                        end = getattr(node, "_jaguar_callee_end_column", end)
                    if line is not None and col is not None:
                        exc._jaguar_line = line
                        exc._jaguar_column = col
                        exc._jaguar_end_column = end if end is not None else col + 1
            raise
    wrapped.__name__ = getattr(method, "__name__", "wrapped")
    wrapped.__doc__ = getattr(method, "__doc__", None)
    return wrapped

CodeGen._check_assignable = _attach_codegen_node_span(CodeGen._check_assignable, 3)
CodeGen._check_expression_types = _attach_codegen_node_span(CodeGen._check_expression_types, 0)
CodeGen.resolve_call_target = _attach_codegen_node_span(CodeGen.resolve_call_target, 0)
CodeGen.infer_type = _attach_codegen_node_span(CodeGen.infer_type, 0)
CodeGen.gen_expr = _attach_codegen_node_span(CodeGen.gen_expr, 0)
CodeGen.gen_stmt = _attach_codegen_node_span(CodeGen.gen_stmt, 0)
CodeGen.gen_member_access = _attach_codegen_node_span(CodeGen.gen_member_access, 0)


def _clean_diagnostic_message(message: str) -> str:
    # Avoid exposing Python's internal literal-type tuple representation.
    message = re.sub(r"got '\('literal', 'int'\)'", "got 'int literal'", message)
    message = re.sub(r"got '\('literal', 'float'\)'", "got 'float literal'", message)
    return message


def _guess_error_line(source: str, message: str) -> int:
    explicit = re.search(r"\bline\s+(\d+)", message)
    if explicit:
        return max(1, int(explicit.group(1)))
    return 1


def _find_span_on_line(source: str, line: int, message: str):
    lines = source.splitlines()
    if not lines:
        return max(1, line), 0, 1
    line = max(1, min(line, len(lines)))
    text = lines[line - 1]

    patterns = [
        r"unknown type '([^']+)'",
        r"operator '([^']+)'",
        r"unary '([^']+)'",
        r"invalid override: [A-Za-z_][\w]*::([A-Za-z_]\w*)",
        r"unknown base class '([^']+)'",
        r"(?:unknown|ambiguous) function '([^']+)'",
        r"function '([^']+)' declared",
        r"prototype of '([^']+)' declared",
        r"class '([^']+)' declared",
        r"type alias '([^']+)' declared",
        r"enum value '([^']+)' declared",
        r"enum '([^']+)' declared",
        r"member '([^']+)'",
        r"string::([A-Za-z_]\w*)",
        r"variable '([^']+)'",
        r"parameter '([^']+)'",
        r"function-pointer[^']*'([^']+)'",
    ]
    for pat in patterns:
        m = re.search(pat, message)
        if not m:
            continue
        needle = m.group(1).split("::")[-1]
        if "operator '" in message or "unary '" in message:
            op = needle
            # Highlight the full unary expression when its operand is present.
            om = re.search(re.escape(op) + r"\s*[A-Za-z_(]", text)
            if om:
                a = om.start()
                if text[om.end()-1] == "(":
                    close = text.find(")", om.end()-1)
                    return line, a, max(a + len(op) + 1, close + 1 if close >= 0 else om.end())
                return line, a, min(len(text), om.end() + max(0, len(text) - om.end()))
            hit = text.find(op)
            if hit >= 0: return line, hit, hit + len(op)
        if "unknown base class" in message:
            nm = re.search(r",\s*" + re.escape(needle) + r"\b", text)
            if nm:
                a = nm.start() + nm.group(0).rfind(needle); return line, a, a + len(needle)
        for hit in re.finditer(r"\b" + re.escape(needle) + r"\b", text):
            return line, hit.start(), hit.end()

    if "expects " in message and ("provided" in message or "arguments" in message):
        name_m = re.search(r"'([^']+)' expects", message)
        if name_m:
            needle=name_m.group(1).split(":")[-1]
            hit=re.search(r"\b"+re.escape(needle)+r"\s*\(",text)
            if hit: return line, hit.start(), hit.end()-1

    if "initializer" in message and "cannot assign" in message:
        eq = text.find("=")
        if eq >= 0:
            a = eq + 1
            while a < len(text) and text[a].isspace(): a += 1
            return line, a, max(a + 1, len(text.rstrip()))
    if "if condition" in message:
        m=re.search(r"\bif\s*\(",text)
        if m:
            a=m.end(); b=text.find(")",a); return line,a,max(a+1,b if b>=0 else len(text))
    if "while condition" in message:
        m=re.search(r"\bwhile\s*\(",text)
        if m:
            a=m.end(); b=text.find(")",a); return line,a,max(a+1,b if b>=0 else len(text))
    for keyword in ("break", "continue", "return", "constr", "destr"):
        if keyword in message:
            hit=re.search(r"\b"+keyword+r"\b",text)
            if hit: return line, hit.start(), hit.end()

    return line, 0, max(1, len(text))


def _diagnostic_from_exception(source: str, exc: Exception):
    message = _clean_diagnostic_message(str(exc))
    line = getattr(exc, "_jaguar_line", None)
    if line is None:
        line = _guess_error_line(source, message)
    column = getattr(exc, "_jaguar_column", None)
    end_column = getattr(exc, "_jaguar_end_column", None)
    symbol = getattr(exc, "_jaguar_symbol", None)
    if symbol and line and 1 <= line <= len(source.splitlines()):
        text = source.splitlines()[line - 1]
        preferred_start = column if column is not None else 0
        hit = re.search(r"\b" + re.escape(symbol) + r"\b", text[preferred_start:])
        if hit:
            column = preferred_start + hit.start()
            end_column = column + len(symbol)
    if column is None:
        _, column, end_column = _find_span_on_line(source, line, message)
    elif end_column is None:
        end_column = column + 1
    return {
        "message": message,
        "line": max(1, int(line)),
        "column": max(0, int(column)),
        "end_column": max(max(0, int(column)) + 1, int(end_column)),
        "severity": 1,
        "kind": type(exc).__name__,
    }




# =========================================================================
# IR -> C API
# =========================================================================

def _load_program_from_ir_text(ir_text: str):
    ir = jcc.deserialize_ir(ir_text)
    program = jcc.program_from_ir(ir)
    groups = jcc.groups_from_program(program)
    return ir, program, groups


def generate_ir(ir_text: str, c89=None, split_runtime=False):
    """Generate C directly from a serialized Jaguar IR string."""
    ir, program, groups = _load_program_from_ir_text(ir_text)
    effective_c89 = bool(ir.get("options", {}).get("c89", False)) if c89 is None else bool(c89)
    cg = CodeGen(program, groups, c89=effective_c89)
    return cg.gen(split_runtime=split_runtime)


def transpile(source: str, c89: bool = False) -> str:
    """Convenience API: front-end to IR, then this backend to C."""
    ir_text = jcc.transpile(source, c89=c89)
    return generate_ir(ir_text, c89=c89, split_runtime=False)


def transpile_files(source: str, c89: bool = False):
    """Convenience API returning the program and generated shared runtime files."""
    ir_text = jcc.transpile(source, c89=c89)
    return generate_ir(ir_text, c89=c89, split_runtime=True)


def diagnose_source(source: str, c89: bool = False):
    """Run the complete front-end + C backend and return one structured diagnostic."""
    try:
        ir_text = jcc.transpile(source, c89=c89)
        generate_ir(ir_text, c89=c89, split_runtime=False)
    except (LexError, ParseError, ResolverError, CodeGenError) as exc:
        # The front-end exceptions can already carry exact source positions.
        if not hasattr(exc, "_jaguar_line"):
            exc._jaguar_line = 1
        return [_diagnostic_from_exception(source, exc)]
    return []


def format_diagnostic(diagnostic, filename=None, prefix="Jaguar Error"):
    location = f"{filename}:{diagnostic['line']}:{diagnostic['column'] + 1}" if filename else f"<stdin>:{diagnostic['line']}:{diagnostic['column'] + 1}"
    return f"{prefix}: {location}: {diagnostic['message']}"


def main(argv):
    out_path = None
    in_path = None
    c89 = None
    emit_c = False
    args = argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "-o" and i + 1 < len(args):
            out_path = args[i + 1]
            i += 2
        elif args[i] == "--c89":
            c89 = True
            i += 1
        elif args[i] == "--emit-c":
            emit_c = True
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
        ir, program, groups = _load_program_from_ir_text(ir_text)
        effective_c89 = bool(ir.get("options", {}).get("c89", False)) if c89 is None else c89
        cg = CodeGen(program, groups, c89=effective_c89)
        generated = cg.gen(split_runtime=bool(out_path)) if out_path else cg.gen()
    except (LexError, ParseError, ResolverError, CodeGenError, ValueError) as e:
        source = ""
        try:
            source = ir.get("source", {}).get("text", "")
        except Exception:
            pass
        if isinstance(e, (LexError, ParseError, ResolverError, CodeGenError)):
            d = _diagnostic_from_exception(source, e)
            mapped_file, mapped_line = _map_source_location(source, d["line"]) if source else (None, d["line"])
            if mapped_file:
                location = f"{mapped_file}:{mapped_line}:{d['column'] + 1}"
            else:
                location = f"{input_name}:{d['line']}:{d['column'] + 1}" if input_name else f"<stdin>:{d['line']}:{d['column'] + 1}"
            print(f"Jaguar Error: {location}: {d['message']}", file=sys.stderr)
        else:
            print(f"Jaguar Error: {e}", file=sys.stderr)
        return 1

    if out_path:
        if out_path.endswith(".c"):
            print("Jaguar Error: output name must be given without the .c extension (e.g. -o out)", file=sys.stderr)
            return 1

        out_base = Path(out_path)
        out_base.parent.mkdir(parents=True, exist_ok=True)
        c_path = out_base.with_suffix(out_base.suffix + ".c") if out_base.suffix else Path(str(out_base) + ".c")
        runtime_h_path = out_base.parent / "jaguar_runtime.h"
        runtime_c_path = out_base.parent / "jaguar_runtime.c"
        with open(c_path, "w", encoding="utf-8") as f:
            f.write(generated["program"])
        with open(runtime_h_path, "w", encoding="utf-8") as f:
            f.write(generated["runtime_h"])
        with open(runtime_c_path, "w", encoding="utf-8") as f:
            f.write(generated["runtime_c"])

        print(f"Jaguar: C generated at {c_path}")
        print(f"Jaguar: runtime C generated at {runtime_c_path}")
        print(f"Jaguar: runtime header generated at {runtime_h_path}")
        if emit_c:
            return 0
        print(f"Jaguar: GCC compilation -> {out_path}")
        try:
            gcc_path = Path(__file__).resolve().parent / "toolchain" / "bin" / ("gcc.exe" if os.name == "nt" else "gcc")
            if not gcc_path.is_file():
                print(f"Jaguar Error: GCC toolchain not found: {gcc_path}", file=sys.stderr)
                for generated_path in (c_path, runtime_c_path, runtime_h_path):
                    try:
                        generated_path.unlink()
                    except OSError:
                        pass
                return 1
            gcc_args = [str(gcc_path)]
            if effective_c89:
                gcc_args += ["-std=c89"]
            gcc_args += [str(c_path), str(runtime_c_path), "-o", out_path, "-lm"]
            if "_j_thread_" in generated.get("runtime_c", "") and os.name != "nt":
                gcc_args.append("-pthread")
            result = subprocess.run(gcc_args, check=False)
        except OSError as e:
            print(f"Jaguar Error: failed to launch gcc: {e}", file=sys.stderr)
            return 1

        if result.returncode != 0:
            print(f"Jaguar Error: gcc failed with exit code {result.returncode}", file=sys.stderr)
            for generated_path in (c_path, runtime_c_path, runtime_h_path):
                try:
                    generated_path.unlink()
                except OSError:
                    pass
            return result.returncode
    else:
        sys.stdout.write(generated)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
