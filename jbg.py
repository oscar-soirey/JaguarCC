#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Jaguar BindGen — bindings C robustes, notamment pour GLAD/OpenGL.

jbg.py transforme un header C en :
  <name>.ja       : API Jaguar
  <name>_jbg.h   : petit bridge C utilisé par JCC/GCC

Le bridge est important pour les API modernes comme GLAD : GLAD expose souvent
les fonctions via des pointeurs globaux et des #define (glClear -> glad_glClear),
ce qui ne peut pas être représenté par une simple déclaration de fonction C.

Le binding Jaguar utilise quelques types ABI natifs :
  cptr      -> void*
  cstr      -> char*
  cfuncptr  -> void (*)(void)

Les pointeurs C sont donc utilisables comme handles/adresses sans transformer
le header C en faux code Jaguar. Les appels restent exécutés par l'API C réelle.
"""
from __future__ import annotations
import argparse, os, re, sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

IDENT = r"[A-Za-z_][A-Za-z0-9_]*"
QUALIFIERS = {"const", "volatile", "restrict", "register", "static", "extern", "inline", "__inline", "__forceinline"}
CALLING = {"__cdecl", "__stdcall", "__fastcall", "__vectorcall", "WINAPI", "CALLBACK", "APIENTRY", "APIENTRYP", "GLAPI", "WINGDIAPI", "EGLAPI", "EGLAPIENTRY"}

SCALARS = {
    "void":"void", "char":"i8", "signed char":"i8", "unsigned char":"u8",
    "short":"i16", "short int":"i16", "signed short":"i16", "signed short int":"i16",
    "unsigned short":"u16", "unsigned short int":"u16", "int":"i32", "signed":"i32", "signed int":"i32",
    "unsigned":"u32", "unsigned int":"u32", "long":"i64", "long int":"i64", "signed long":"i64",
    "signed long int":"i64", "unsigned long":"u64", "unsigned long int":"u64", "long long":"i64",
    "long long int":"i64", "signed long long":"i64", "signed long long int":"i64",
    "unsigned long long":"u64", "unsigned long long int":"u64", "float":"f32", "double":"f64",
    "_Bool":"bool", "bool":"bool", "size_t":"u64", "ssize_t":"i64", "intptr_t":"i64", "uintptr_t":"u64",
}

@dataclass
class Param:
    c_type: str
    ja_type: str
    name: str

@dataclass
class Function:
    name: str
    ret_c: str
    ret_ja: str
    params: List[Param]
    macro_alias: bool = False

@dataclass
class Binding:
    functions: List[Function] = field(default_factory=list)
    constants: List[Tuple[str,str]] = field(default_factory=list)
    aliases: Dict[str,str] = field(default_factory=dict)
    function_aliases: Dict[str,Tuple[str,str,List[Tuple[str,str]]]] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)


def strip_comments(s):
    s = re.sub(r"/\*.*?\*/", " ", s, flags=re.S)
    return re.sub(r"//[^\n]*", "", s)

def join_lines(s):
    return re.sub(r"\\\r?\n", " ", s)

def norm(s): return re.sub(r"\s+", " ", s).strip()

def split_top(s, sep=","):
    out=[]; start=0; par=br=cur=0
    for i,ch in enumerate(s):
        if ch=='(': par+=1
        elif ch==')': par-=1
        elif ch=='[': br+=1
        elif ch==']': br-=1
        elif ch=='{': cur+=1
        elif ch=='}': cur-=1
        elif ch==sep and par==br==cur==0:
            out.append(s[start:i].strip()); start=i+1
    out.append(s[start:].strip())
    return [x for x in out if x]

def remove_attrs(s):
    s=re.sub(r"__attribute__\s*\(\(.*?\)\)"," ",s,flags=re.S)
    s=re.sub(r"__declspec\s*\([^)]*\)"," ",s,flags=re.S)
    s=re.sub(r"\[\[.*?\]\]"," ",s,flags=re.S)
    return norm(s)

def clean_type(s):
    s=remove_attrs(s)
    words=[w for w in s.split() if w not in QUALIFIERS and w not in CALLING]
    return norm(" ".join(words))

def map_type(c_type, aliases):
    t=clean_type(c_type)
    # function pointer
    if re.search(r"\(\s*\*", t) or re.search(r"\(\s*\w+\s*\*", t):
        return "cfuncptr"
    # arrays decay to pointers in function parameters
    if "[" in t or "]" in t:
        return "cptr"
    if "*" in t:
        base=clean_type(t.replace("*"," "))
        if base in ("char", "signed char", "unsigned char"):
            return "cstr" if base=="char" else "cptr"
        return "cptr"
    if t in SCALARS: return SCALARS[t]
    if t in aliases: return aliases[t]
    # opaque struct/union/enum aliases are represented by their ABI value only
    return None

def parse_param(p, i, aliases):
    p=remove_attrs(p)
    if not p or p=="void": return None
    # Function pointer parameter: void (*cb)(...)
    if re.search(r"\(\s*(?:\*\s*)?"+IDENT+r"\s*\)\s*\(",p):
        m=re.search(r"(?:\*\s*)?("+IDENT+r")\s*\)\s*\(",p)
        name=m.group(1) if m else f"arg{i}"
        cdecl=re.sub(r"\b"+re.escape(name)+r"\b", "", p, count=1).replace("(* )", "(*)")
        cdecl=norm(cdecl)
        return Param(cdecl,"cfuncptr",name)
    # Prefer an explicit trailing C parameter name, including pointer forms
    # such as `GLuint *buffers` and `const char *name`.
    m=re.match(r"^(.*?)\b("+IDENT+r")\s*$",p)
    if m:
        typ,name=m.group(1).strip(),m.group(2)
        jt=map_type(typ,aliases)
        if jt is not None:
            return Param(typ,jt,name)
    direct=map_type(p,aliases)
    if direct is not None:
        return Param(p,direct,f"arg{i}")
    return None

def parse_function_decl(stmt, aliases):
    stmt=remove_attrs(stmt).strip()
    stmt=re.sub(r"\b(?:__cdecl|__stdcall|__fastcall|__vectorcall|WINAPI|CALLBACK|APIENTRY|GLAPI)\b"," ",stmt)
    stmt=norm(stmt)
    m=re.match(r"^(?P<ret>.+?)\s*(?P<name>"+IDENT+r")\s*\((?P<args>.*)\)$",stmt,re.S)
    if not m: return None
    ret,name,args=m.group("ret"),m.group("name"),m.group("args")
    if "..." in args: return None
    jr=map_type(ret,aliases)
    if jr is None: return None
    ps=[]
    if args and args.strip()!="void":
        for i,p in enumerate(split_top(args),1):
            pp=parse_param(p,i,aliases)
            if pp is None: return None
            ps.append(pp)
    return Function(name,ret,jr,ps)

def parse_function_typedef(stmt, aliases):
    # typedef RET (CALLCONV NAME)(ARGS);
    m=re.match(r"typedef\s+(.+?)\s+\(\s*(?:\*\s*)?("+IDENT+r")\s*\)\s*\((.*)\)\s*$",norm(stmt),re.S)
    if not m: return None
    ret, name, args=m.groups()
    jr=map_type(ret,aliases)
    if jr is None: return None
    ps=[]
    if args.strip() and args.strip()!="void":
        for i,p in enumerate(split_top(args),1):
            pp=parse_param(p,i,aliases)
            if pp is None: return None
            ps.append((pp.c_type,pp.ja_type))
    return name,(ret, jr, ps)

def parse_header(text):
    original=text
    text=join_lines(strip_comments(text))
    b=Binding()
    # Object-like macros. Keep all sane C expressions: GLAD/OpenGL constants
    # are often hexadecimal, bitwise expressions, casts, aliases, etc.
    for raw in text.splitlines():
        line=raw.strip()
        m=re.match(r"#\s*define\s+("+IDENT+r")(.*)$",line)
        if not m: continue
        name,rest=m.group(1),m.group(2).strip()
        if rest.startswith("(") and re.match(r"^\([^)]*\)",rest):
            # This may still be an object macro whose value starts with a cast;
            # function-like macros have the '(' immediately after the name in
            # the raw source, which our regex cannot distinguish after spacing.
            if re.match(r"#\s*define\s+"+IDENT+r"\s*\(",line): continue
        if re.match(r"#\s*define\s+"+IDENT+r"\s*\(",line): continue
        if rest:
            b.constants.append((name,rest))
    # aliases from typedefs, including GL typedefs and function-pointer typedefs
    for m in re.finditer(r"\btypedef\s+([^;{}]+);",text,re.S):
        stmt=norm(m.group(0)[len("typedef "):-1])
        ft=parse_function_typedef("typedef "+stmt,b.aliases)
        if ft:
            b.function_aliases[ft[0]]=ft[1]
            continue
        mm=re.match(r"(.+?)\s+("+IDENT+r")$",stmt,re.S)
        if not mm: continue
        src,name=mm.groups(); jt=map_type(src,b.aliases)
        if jt is not None: b.aliases[name]=jt
        elif re.search(r"\b(?:struct|union|enum)\b",src): b.aliases[name]="cptr"
    # common opaque struct declarations / typedef struct X X;
    for m in re.finditer(r"\btypedef\s+(?:struct|union)\s+"+IDENT+r"\s+("+IDENT+r")\s*;",text):
        b.aliases.setdefault(m.group(1),"cptr")

    # GLAD and similar loaders expose #define foo glad_foo and a global whose
    # type is PFN...PROC. Recover the function signature from the typedef.
    macro_aliases={}
    for raw in text.splitlines():
        m=re.match(r"#\s*define\s+("+IDENT+r")\s+("+IDENT+r")\s*$",raw.strip())
        if m and m.group(2).startswith("glad_"):
            macro_aliases[m.group(1)]=m.group(2)
    globals_by_name={}
    for stmt in [x.strip() for x in text.split(";") if x.strip()]:
        m=re.search(r"\b(?:extern\s+)?(?:GLAPI\s+|APIENTRY\s+)?([A-Za-z_][A-Za-z0-9_]*(?:\s*\*)?)\s+(glad_"+IDENT+r")$",norm(stmt))
        if m: globals_by_name[m.group(2)]=m.group(1).strip()
    # Function aliases such as `#define glClear glad_glClear` are API symbols,
    # not constants. Do not re-emit them as Jaguar #define lines.
    b.constants = [(n,v) for (n,v) in b.constants if n not in macro_aliases]
    for fname,gname in macro_aliases.items():
        typ=globals_by_name.get(gname)
        sig=b.function_aliases.get(typ or "")
        if sig:
            retc,retja,ps=sig
            params=[Param(ct,jt,f"arg{i}") for i,(ct,jt) in enumerate(ps,1)]
            b.functions.append(Function(fname,retc,retja,params,True))

    # Normal prototypes. Remove preprocessor lines and bodies; statements ending
    # with ; are sufficient for C API headers. We deliberately do not parse C
    # function bodies.
    body="\n".join(x for x in text.splitlines() if not x.lstrip().startswith("#"))
    body=re.sub(r'extern\s+"C"\s*\{',' ',body)
    body=re.sub(r"\b(?:typedef)\s+(?:struct|union|enum)\s+"+IDENT+r"\s*\{.*?\}\s*;"," ",body,flags=re.S)
    body=re.sub(r"\b(?:struct|union|enum)\s+"+IDENT+r"\s*\{.*?\}\s*;"," ",body,flags=re.S)
    # Remove typedef statements; aliases were already collected.
    body=re.sub(r"\btypedef\s+[^;]+;"," ",body)
    seen={(f.name,tuple(p.ja_type for p in f.params)):f for f in b.functions}
    for stmt in [x.strip() for x in body.split(";") if x.strip()]:
        fn=parse_function_decl(stmt,b.aliases)
        if fn:
            key=(fn.name,tuple(p.ja_type for p in fn.params))
            seen.setdefault(key,fn)
    b.functions=list(seen.values())
    # Filter obvious non-API declarations.
    return b

def c_decl_type(t):
    return clean_type(t)

def _bridge_type(ja, c_original):
    if ja == "cptr": return "void *"
    if ja == "cstr": return "char *"
    if ja == "cfuncptr": return "void (*)(void)"
    return c_decl_type(c_original)

def _bridge_arg(ja, c_original, name):
    if ja == "cfuncptr":
        return f"({c_decl_type(c_original)}){name}"
    if ja == "cptr":
        return name
    if ja == "cstr":
        return name
    return name

def bridge_for(binding, header_name):
    lines=["/* Generated by jbg.py. Do not edit. */", f'#include "{header_name}"', ""]
    for fn in binding.functions:
        wrapper="__jbg_"+fn.name
        params=[]; args=[]
        for i,p in enumerate(fn.params,1):
            n=p.name or f"arg{i}"
            if p.ja_type == "cfuncptr":
                params.append(f"void (*{n})(void)")
            else:
                params.append(f"{_bridge_type(p.ja_type,p.c_type)} {n}")
            args.append(_bridge_arg(p.ja_type,p.c_type,n))
        ret=_bridge_type(fn.ret_ja,fn.ret_c)
        lines.append(f"static {ret} {wrapper}({', '.join(params) if params else 'void'}) {{")
        call=f"{fn.name}({', '.join(args)})"
        if ret=="void": lines.append(f"    {call};")
        elif fn.ret_ja=="cstr": lines.append(f"    return (char *)({call});")
        elif fn.ret_ja=="cptr": lines.append(f"    return (void *)({call});")
        elif fn.ret_ja=="cfuncptr": lines.append(f"    return (void (*)(void))({call});")
        else: lines.append(f"    return {call};")
        lines.append("}")
        lines.append(f"#undef {fn.name}")
        lines.append(f"#define {fn.name} {wrapper}")
        lines.append("")
    return "\n".join(lines)

def _macro_literal_type(value):
    v=value.strip()
    if re.match(r"^(?:0[xX][0-9A-Fa-f]+|\d+)[uUlL]*$",v): return "u32" if v.lower().endswith("u") or v.startswith(("0x","0X")) else "i32"
    if re.match(r"^[+-]?(?:\d+\.\d*|\.\d+)(?:[eE][+-]?\d+)?[fFlL]?$",v): return "f64"
    if v in ("true","false"): return "bool"
    if len(v)>=2 and v[0]=='"' and v[-1]=='"': return "cstr"
    return "u32"

def render_ja(binding, namespace, bridge_name, source_name):
    L=["// Jaguar binding généré par jbg.py", f"// Source: {os.path.basename(source_name)}", "", f'#include "{bridge_name}"', ""]
    if namespace: L += [f"namespace {namespace} {{", ""]
    for fn in binding.functions:
        indent="    " if namespace else ""
        L.append(indent+"@extern")
        params=", ".join(f"{p.ja_type} {p.name}" for p in fn.params)
        L.append(indent+f"{fn.ret_ja} {fn.name}({params});")
        L.append("")
    if namespace: L.append("}")
    return "\n".join(L).rstrip()+"\n"

def parser():
    p=argparse.ArgumentParser(prog="jbg.py",description="Jaguar BindGen — API C/GLAD -> Jaguar")
    p.add_argument("header")
    p.add_argument("-o","--output")
    p.add_argument("--namespace")
    p.add_argument("--include-header",nargs="?",const="__AUTO__",default=None)
    p.add_argument("--no-include",action="store_true",help="compatibilité; le bridge doit toujours inclure le header")
    p.add_argument("--bridge",help="nom du bridge .h (par défaut <output>_jbg.h)")
    p.add_argument("--quiet",action="store_true")
    return p

def main(argv=None):
    a=parser().parse_args(argv)
    if not os.path.isfile(a.header):
        print(f"JBG: fichier introuvable: {a.header}",file=sys.stderr); return 1
    with open(a.header,encoding="utf-8",errors="replace") as f: src=f.read()
    b=parse_header(src)
    out=a.output or os.path.splitext(a.header)[0]+".ja"
    bridge=a.bridge or os.path.splitext(os.path.basename(out))[0]+"_jbg.h"
    # Include by basename: JBS `include`/GCC -I points to the library directory.
    ja=render_ja(b,a.namespace,bridge, a.header)
    bridge_path=os.path.join(os.path.dirname(os.path.abspath(out)),bridge)
    os.makedirs(os.path.dirname(os.path.abspath(out)),exist_ok=True)
    with open(bridge_path,"w",encoding="utf-8",newline="\n") as f: f.write(bridge_for(b,os.path.basename(a.header)))
    with open(out,"w",encoding="utf-8",newline="\n") as f: f.write(ja)
    print(f"JBG: {len(b.functions)} fonction(s), {len(b.constants)} macro(s) -> {out}")
    print(f"JBG: bridge C -> {bridge_path}")
    if b.warnings and not a.quiet:
        for w in b.warnings: print("JBG: avertissement: "+w,file=sys.stderr)
    return 0

if __name__=="__main__": raise SystemExit(main())
