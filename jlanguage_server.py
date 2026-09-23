#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Jaguar Language Server.

Standalone language server for Jaguar. Place this file next to jcc.py; the VS Code
extension launches it as an external process.

Dependency-free LSP server.  The semantic index uses Jaguar's own lexer/parser
from jcc.py when the document is parseable, and falls back to a tolerant source
scan while the user is typing an incomplete file.  This is intentional: an
editor must keep completion working even when the current buffer is not yet a
valid Jaguar program.
"""
import importlib.util, json, os, re, sys, threading, traceback
from dataclasses import is_dataclass, fields
from urllib.parse import unquote, urlparse
from typing import Any, Dict, List, Optional

HERE = os.path.dirname(os.path.abspath(__file__))


def _jcc_candidates():
    """Yield JaguarCC candidates in deployment/test priority order."""
    explicit = os.environ.get("JAGUAR_JCC")
    candidates = []
    if explicit:
        candidates.append(os.path.abspath(explicit))
    candidates.extend([
        os.path.join(HERE, "jcc.py"),
        os.path.join(HERE, "jcc_fixed_round2.py"),
        os.path.join(HERE, "jcc_fixed.py"),
        os.path.join(HERE, "jcc(9).py"),
    ])
    seen = set()
    for path in candidates:
        path = os.path.abspath(path)
        if path not in seen:
            seen.add(path)
            yield path


def load_jcc():
    for path in _jcc_candidates():
        if not os.path.isfile(path):
            continue
        spec = importlib.util.spec_from_file_location("jaguar_jcc", path)
        if not spec or not spec.loader:
            continue
        try:
            mod = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = mod
            spec.loader.exec_module(mod)
            mod.__jaguar_source_path__ = path
            return mod
        except Exception:
            # An optional/broken development copy must not stop the server when
            # another valid JaguarCC is available.
            continue
    return None


JCC = load_jcc()

BUILTIN_TYPES = [
    "void", "bool", "int", "uint", "short", "ushort", "long", "ulong", "char", "uchar", "sbyte", "byte",
    "float", "double", "string",
    "i8", "u8", "i16", "u16", "i32", "u32", "i64", "u64", "f32", "f64",
    "auto", "cptr", "cstr", "cfuncptr",
    "list", "map", "container", "dynamic_list", "pair",
]
KEYWORDS = [
    "class", "struct", "union", "enum", "namespace", "using", "const", "virtual", "override",
    "constr", "destr", "if", "else", "while", "for_loop", "return", "break",
    "continue", "true", "false", "nullptr", "this", "new", "signal", "as", "loop", "public", "protected", "private",
]
DIRECTIVES = ["#define", "#undef", "#if", "#ifdef", "#ifndef", "#elif", "#elseif", "#else", "#endif", "#pragma", "#error", "#warning", "#line"]
JBS_DIRECTIVES = ["jbs", "version", "out", "include", "libpath", "c89", "keep_c", "mode", "define", "define_jbs", "compile", "compile_static", "compile_shared", "link", "shell", "python", "crimson", "if", "else"]
JBS_MODES = ["debug", "release", "relwithdebinfo", "minsizerel"]
JBS_CONDITION_COMMANDS = ["crimson", "shell", "python"]

STRING_METHODS = [
    ("length", "int length()", "Returns the number of characters."),
    ("empty", "bool empty()", "Returns whether the string is empty."),
    ("equals", "bool equals(string other)", "Compares string contents."),
    ("contains", "bool contains(string other)", "Checks whether the string contains another string."),
    ("starts_with", "bool starts_with(string prefix)", "Checks whether the string starts with a prefix."),
    ("ends_with", "bool ends_with(string suffix)", "Checks whether the string ends with a suffix."),
    ("concat", "string concat(string other)", "Returns the concatenation of two strings."),
    ("substring", "string substring(int start, int length)", "Returns a substring."),
    ("char_at", "i32 char_at(int index)", "Returns a character code."),
    ("to_upper", "string to_upper()", "Returns an uppercase copy."),
    ("to_lower", "string to_lower()", "Returns a lowercase copy."),
]
COLLECTION_METHODS = {
    "list": [("push", "void push(T value)", "Adds an element to the list."), ("get", "T get(int index)", "Gets an element."), ("size", "int size()", "Returns the number of elements.")],
    "map": [("emplace", "void emplace(K key, V value)", "Adds or replaces an entry."), ("size", "int size()", "Returns the number of entries.")],
    "container": [("get", "T get()", "Returns the contained value.")],
    "dynamic_list": [("push", "void push(auto value)", "Adds a value."), ("size", "int size()", "Returns the number of elements.")],
    "pair": [("first", "T", "First value."), ("second", "U", "Second value.")],
}

# Public JaguarCC signatures.  Return types and parameter types mirror the
# SYSTEM_BUILTINS declarations in jcc.py.  Keeping these here makes hover
# useful even when the function is not declared in the current workspace.
JCC_SIGNATURES = {
    "exit": ("void", "int status"), "abort": ("void", ""),
    "abs_i32": ("i32", "i32 value"), "min_i32": ("i32", "i32 a, i32 b"),
    "max_i32": ("i32", "i32 a, i32 b"), "clamp_i32": ("i32", "i32 value, i32 min, i32 max"),
    "random_i32": ("i32", "i32 min, i32 max"), "time_ms": ("i64", ""),
    "assert": ("void", "bool condition, string message"),
    "sqrt": ("f64", "f64 value"), "pow": ("f64", "f64 base, f64 exponent"),
    "sin": ("f64", "f64 value"), "cos": ("f64", "f64 value"), "tan": ("f64", "f64 value"),
    "asin": ("f64", "f64 value"), "acos": ("f64", "f64 value"), "atan": ("f64", "f64 value"),
    "atan2": ("f64", "f64 y, f64 x"), "floor": ("f64", "f64 value"),
    "ceil": ("f64", "f64 value"), "round": ("f64", "f64 value"),
    "log": ("f64", "f64 value"), "log10": ("f64", "f64 value"), "exp": ("f64", "f64 value"),
    "fmod": ("f64", "f64 x, f64 y"),
    "string_length": ("i32", "string value"), "string_equals": ("bool", "string a, string b"),
    "string_compare": ("i32", "string a, string b"), "string_contains": ("bool", "string value, string needle"),
    "string_starts_with": ("bool", "string value, string prefix"), "string_ends_with": ("bool", "string value, string suffix"),
    "string_concat": ("string", "string a, string b"), "string_substring": ("string", "string value, i32 start, i32 length"),
    "string_char_at": ("i32", "string value, i32 index"), "string_find": ("i32", "string value, string needle"),
    "string_to_upper": ("string", "string value"), "string_to_lower": ("string", "string value"),
    "string_to_i32": ("i32", "string value"), "string_to_i64": ("i64", "string value"),
    "string_to_f64": ("f64", "string value"), "i32_to_string": ("string", "i32 value"),
    "i64_to_string": ("string", "i64 value"), "f64_to_string": ("string", "f64 value"),
    "is_digit": ("bool", "i32 c"), "is_alpha": ("bool", "i32 c"), "is_alnum": ("bool", "i32 c"),
    "is_space": ("bool", "i32 c"), "is_upper": ("bool", "i32 c"), "is_lower": ("bool", "i32 c"),
    "to_upper_char": ("i32", "i32 c"), "to_lower_char": ("i32", "i32 c"),
    "file_exists": ("bool", "string path"), "remove_file": ("bool", "string path"),
    "rename_file": ("bool", "string old_path, string new_path"), "env_get": ("string", "string name"),
}

TYPE_INFO = {
    "void": (0, "no storage; only valid as a return type"),
    "bool": (1, "1 byte"), "int": (4, "4 bytes on the current JaguarCC C ABI"),
    "float": (4, "4 bytes on the current JaguarCC C ABI"),
    "i8": (1, "1 byte"), "u8": (1, "1 byte"), "i16": (2, "2 bytes"), "u16": (2, "2 bytes"),
    "i32": (4, "4 bytes"), "u32": (4, "4 bytes"), "i64": (8, "8 bytes"), "u64": (8, "8 bytes"),
    "f32": (4, "4 bytes"), "f64": (8, "8 bytes"),
    "string": (None, "pointer-sized string handle; the underlying string struct also stores a pointer and a size"),
    "cptr": (None, "pointer-sized"), "cstr": (None, "pointer-sized"), "cfuncptr": (None, "function-pointer-sized"),
    "auto": (None, "deduced from the initializer"),
    "uint": (4, "alias of u32"), "short": (2, "alias of i16"), "ushort": (2, "alias of u16"),
    "long": (8, "alias of i64"), "ulong": (8, "alias of u64"), "char": (1, "alias of i8"),
    "uchar": (1, "alias of u8"), "sbyte": (1, "alias of i8"), "byte": (1, "alias of u8"),
    "double": (8, "alias of f64"),
}


def pos_to_offset(text, line, character):
    lines = text.splitlines(True)
    return min(len(text), sum(len(x) for x in lines[:line]) + character)


def offset_to_pos(text, offset):
    before = text[:offset]
    return {"line": before.count("\n"), "character": len(before.rsplit("\n", 1)[-1])}


def word_at(text, offset):
    left = re.search(r"[A-Za-z_][A-Za-z0-9_]*$", text[:offset])
    right = re.match(r"[A-Za-z0-9_]*", text[offset:])
    return (left.group(0) if left else "") + (right.group(0) if right else "")


def clean_for_scan(text):
    out = list(text); i = 0; state = None
    while i < len(text):
        if state == "//":
            if text[i] != "\n": out[i] = " "
            else: state = None
        elif state == "/*":
            if text[i:i+2] == "*/": out[i] = out[i+1] = " "; i += 1; state = None
            elif text[i] != "\n": out[i] = " "
        elif state == '"':
            if text[i] == "\\":
                out[i] = " ";
                if i+1 < len(text) and text[i+1] != "\n": out[i+1] = " "; i += 1
            elif text[i] == '"': out[i] = " "; state = None
            elif text[i] != "\n": out[i] = " "
        else:
            if text[i:i+2] == "//": out[i] = out[i+1] = " "; i += 1; state = "//"
            elif text[i:i+2] == "/*": out[i] = out[i+1] = " "; i += 1; state = "/*"
            elif text[i] == '"': out[i] = " "; state = '"'
        i += 1
    return ''.join(out)


class SymbolIndex:
    def __init__(self, text):
        self.text = text
        self.scan = clean_for_scan(text)
        self.variables = {}
        self.classes = {}
        self.structs = {}
        self.unions = {}
        self.enums = {}
        self.functions = []
        self.namespaces = []
        self.errors = []
        self.used_jcc_parser = False
        self.parse_with_jcc()
        self.fallback_scan()

    def parse_with_jcc(self):
        if JCC is None:
            return
        try:
            program = JCC.Parser(JCC.tokenize(self.text)).parse_program()
            self.used_jcc_parser = True
            self._consume_program(program)
        except Exception as e:
            # The fallback scanner is deliberately tolerant during editing.
            self.errors.append(str(e))

    def _consume_program(self, program, namespace=None):
        for item in getattr(program, "items", []):
            cls = type(item).__name__
            if cls == "VarDecl":
                self.variables.setdefault(item.name, item.type)
            elif cls == "FunctionDecl":
                ns = getattr(item, "namespace", None) or namespace
                self.functions.append({"name": item.name, "type": item.ret_type, "args": ", ".join(f"{p.type} {p.name}" for p in item.params), "namespace": ns, "obj": item})
            elif cls == "StructDecl":
                self.structs[item.name] = {"name": item.name, "members": [{"name": f.name, "type": f.type, "kind": "field"} for f in item.fields]}
            elif cls == "UnionDecl":
                self.unions[item.name] = {"name": item.name, "members": [{"name": f.name, "type": f.type, "kind": "field"} for f in item.fields]}
            elif cls == "EnumDecl":
                self.enums[item.name] = {"name": item.name, "values": list(getattr(item, "values", []))}
            elif cls == "ClassDecl":
                members = []
                for f in item.fields:
                    members.append({"name": f.name, "type": f.type, "kind": "field", "access": getattr(f, "access", "private")})
                for m in item.methods:
                    members.append({"name": m.name, "type": m.ret_type, "args": ", ".join(f"{p.type} {p.name}" for p in m.params), "kind": "method", "access": getattr(m, "access", "private")})
                self.classes[item.name] = {"name": item.name, "base": item.base, "members": members}
            if getattr(item, "namespace", None) and getattr(item, "namespace", None) not in self.namespaces:
                self.namespaces.append(item.namespace)
            # Namespace parsing in jcc flattens functions into FunctionDecl.namespace.

    def fallback_scan(self):
        s = self.scan
        # This supplements the AST index for incomplete source.
        for m in re.finditer(r"\b(namespace|class|struct|union|enum)\s+([A-Za-z_]\w*)(?:\s*,\s*([A-Za-z_]\w*))?\s*\{", s):
            kind, name, base = m.groups()
            if kind == "class" and name not in self.classes: self.classes[name] = {"name": name, "base": base, "members": []}
            elif kind == "struct" and name not in self.structs: self.structs[name] = {"name": name, "members": []}
            elif kind == "union" and name not in self.unions: self.unions[name] = {"name": name, "members": []}
            elif kind == "enum" and name not in self.enums: self.enums[name] = {"name": name, "values": []}
            elif kind == "namespace" and name not in self.namespaces: self.namespaces.append(name)
        for name, u in self.unions.items():
            if u["members"]: continue
            m = re.search(r"\bunion\s+" + re.escape(name) + r"\s*\{([^}]*)\}", s, re.S)
            if m:
                for fm in re.finditer(r"(?:const\s+)?([A-Za-z_]\w*(?:\s*<[^;{}]+>)?(?:\s*\*)?)\s+([A-Za-z_]\w*)\s*;", m.group(1)):
                    u["members"].append({"name": fm.group(2), "type": fm.group(1).strip(), "kind": "field"})
        for name, e in self.enums.items():
            if e["values"]: continue
            m = re.search(r"\benum\s+" + re.escape(name) + r"\s*\{([^}]*)\}", s, re.S)
            if m: e["values"] = re.findall(r"[A-Za-z_]\w*", m.group(1))

        fn_re = re.compile(r"(?:^|[;{}])\s*(?:\$|%)?\s*(?:const\s+)?([A-Za-z_]\w*(?:\s*<[^;{}()]+>)?)\s+([A-Za-z_]\w*)\s*\(([^)]*)\)")
        for m in fn_re.finditer(s):
            typ, name, args = m.groups()
            if name in KEYWORDS or any(f["name"] == name and f["args"] == args for f in self.functions): continue
            self.functions.append({"name": name, "type": typ.strip(), "args": args.strip(), "namespace": None})
        var_re = re.compile(r"(?:^|[;{}])\s*(?:\$|%)?\s*(?:const\s+)?([A-Za-z_]\w*(?:\s*<[^;{}=]+>)?(?:\s*\*)?)\s+([A-Za-z_]\w*)\s*(?:=|;)")
        for m in var_re.finditer(s):
            typ, name = m.group(1).strip(), m.group(2)
            if typ not in KEYWORDS and name not in KEYWORDS: self.variables.setdefault(name, typ)
        for m in re.finditer(r"\bauto\s+([A-Za-z_]\w*)\s*=\s*([^;\n]+)", s):
            self.variables[m.group(1)] = self.infer_expr(m.group(2).strip())
        # Parse class members tolerantly if AST parsing failed.
        for c in self.classes.values():
            if c["members"]: continue
            body = s[s.find("{", s.find("class " + c["name"])) + 1:]
            for m in re.finditer(r"(?:\$|%)?\s*(?:const\s+)?([A-Za-z_]\w*(?:\s*<[^;{}]+>)?)\s+([A-Za-z_]\w*)\s*(?:=|;)", body):
                c["members"].append({"name": m.group(2), "type": m.group(1).strip(), "kind": "field", "access": "private"})
            for m in re.finditer(r"\b([A-Za-z_]\w*(?:\s*<[^;{}]+>)?)\s+([A-Za-z_]\w*)\s*\(([^)]*)\)", body):
                if m.group(2) not in KEYWORDS: c["members"].append({"name":m.group(2),"type":m.group(1).strip(),"args":m.group(3),"kind":"method","access":"private"})

    @staticmethod
    def infer_expr(expr):
        if re.match(r'^"', expr): return "string"
        if expr in ("true", "false"): return "bool"
        if re.match(r"^-?\d+\.\d*([eE][+-]?\d+)?$", expr): return "f64"
        if re.match(r"^-?\d+$", expr): return "i32"
        m = re.match(r"new\s+([A-Za-z_]\w*)", expr)
        return m.group(1) if m else "auto"

    def members_for_type(self, typ):
        typ = re.sub(r"^const\s+", "", typ or "").strip()
        typ = re.sub(r"\s*\*+$", "", typ).strip()
        b = re.match(r"([A-Za-z_]\w*)", typ)
        if not b: return []
        base = b.group(1)
        if base == "string":
            return [{"name":n,"detail":d,"documentation":doc,"kind":"method"} for n,d,doc in STRING_METHODS]
        if base in self.classes:
            return self.classes[base]["members"]
        if base in self.structs:
            return self.structs[base]["members"]
        if base in self.unions:
            return self.unions[base]["members"]
        m = re.match(r"(list|map|container|dynamic_list|pair)\s*<", typ)
        if m:
            return [{"name":n,"detail":d,"documentation":doc,"kind":"method"} for n,d,doc in COLLECTION_METHODS[m.group(1)]]
        return []


class JaguarServer:
    def __init__(self):
        self.docs = {}
        self.root = None
        self.send_lock = threading.Lock()
        self.jbs = None
        for candidate in (os.path.join(HERE, "jbs.py"), os.path.join(HERE, "jbs_fixed.py"), os.path.join(HERE, "jbs(5).py")):
            if os.path.isfile(candidate):
                try:
                    spec = importlib.util.spec_from_file_location("jaguar_jbs", candidate)
                    mod = importlib.util.module_from_spec(spec)
                    sys.modules[spec.name] = mod
                    spec.loader.exec_module(mod)
                    self.jbs = mod
                    break
                except Exception:
                    pass

    def send(self, obj):
        data = json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode()
        with self.send_lock:
            sys.stdout.buffer.write(f"Content-Length: {len(data)}\r\n\r\n".encode() + data)
            sys.stdout.buffer.flush()

    def result(self, ident, result): self.send({"jsonrpc":"2.0","id":ident,"result":result})
    def error(self, ident, code, msg): self.send({"jsonrpc":"2.0","id":ident,"error":{"code":code,"message":msg}})
    def notify(self, method, params): self.send({"jsonrpc":"2.0","method":method,"params":params})

    def handle(self, msg):
        method = msg.get("method"); p = msg.get("params") or {}; ident = msg.get("id")
        try:
            if method == "initialize":
                self.root = p.get("rootUri") or p.get("rootPath")
                self.result(ident, {"capabilities": {
                    "textDocumentSync": {"openClose": True, "change": 1},
                    "completionProvider": {"triggerCharacters": [".", ":"]},
                    "hoverProvider": True,
                    "definitionProvider": True,
                    "renameProvider": True,
                    "workspaceSymbolProvider": True,
                }, "serverInfo": {"name":"Jaguar Language Server", "version":"0.4.0"}})
            elif method == "initialized": pass
            elif method == "shutdown": self.result(ident, None)
            elif method == "exit": return False
            elif method == "textDocument/didOpen":
                d=p["textDocument"]; self.docs[d["uri"]]=d["text"]; self.publish_diagnostics(d["uri"])
            elif method == "textDocument/didChange":
                uri=p["textDocument"]["uri"]
                changes=p.get("contentChanges", [])
                if changes: self.docs[uri]=changes[-1].get("text", self.docs.get(uri, "")); self.publish_diagnostics(uri)
            elif method == "textDocument/didClose": self.docs.pop(p["textDocument"]["uri"], None)
            elif method == "textDocument/completion": self.result(ident, self.completion(p["textDocument"]["uri"], p["position"]))
            elif method == "textDocument/hover": self.result(ident, self.hover(p["textDocument"]["uri"], p["position"]))
            elif method == "textDocument/definition": self.result(ident, self.definition(p["textDocument"]["uri"], p["position"]))
            elif method == "textDocument/rename": self.result(ident, self.rename(p["textDocument"]["uri"], p["position"], p.get("newName", "")))
            elif method == "workspace/symbol": self.result(ident, self.workspace_symbols(p.get("query", "")))
            elif ident is not None: self.result(ident, None)
        except Exception as e:
            if ident is not None: self.error(ident, -32603, str(e))
            traceback.print_exc(file=sys.stderr)
        return True

    def context(self, uri, pos):
        text=self.docs.get(uri, ""); return text, pos_to_offset(text, pos.get("line",0), pos.get("character",0))

    @staticmethod
    def _is_jbs_uri(uri):
        path = unquote(urlparse(uri).path)
        return path.lower().endswith(".jbs") or os.path.basename(path).lower() == ".jbs"

    def completion(self, uri, pos):
        text, off = self.context(uri, pos); before=text[:off]
        if self._is_jbs_uri(uri):
            line_start = before.rfind("\n") + 1
            fragment = before[line_start:]

            # Conditions execute an existing JBS command and use its exit code
            # as a boolean. Offer command completions inside `if(...)`.
            if re.search(r"\bif\s*\(\s*!?\s*[A-Za-z_]*$", fragment):
                word = re.search(r"[A-Za-z_][A-Za-z0-9_]*$", fragment)
                prefix = word.group(0) if word else ""
                return {"isIncomplete":False,"items":[{"label":c,"kind":14,"detail":"JBS condition command"} for c in JBS_CONDITION_COMMANDS if c.startswith(prefix)]}

            if re.match(r"^\s*else\s+if\s*\(\s*!?\s*[A-Za-z_]*$", fragment):
                word = re.search(r"[A-Za-z_][A-Za-z0-9_]*$", fragment)
                prefix = word.group(0) if word else ""
                return {"isIncomplete":False,"items":[{"label":c,"kind":14,"detail":"JBS condition command"} for c in JBS_CONDITION_COMMANDS if c.startswith(prefix)]}

            if re.match(r"^\s*mode\s+\w*$", fragment):
                return {"isIncomplete":False,"items":[{"label":m,"kind":14,"detail":"JBS build mode"} for m in JBS_MODES]}

            word = re.search(r"[A-Za-z_][A-Za-z0-9_]*$", fragment)
            prefix = word.group(0) if word else ""
            items=[{"label":d,"kind":14,"detail":"JBS directive"} for d in JBS_DIRECTIVES if d.startswith(prefix)]
            return {"isIncomplete":False,"items":items}
        idx=SymbolIndex(text)
        # Critical: completion is requested after the dot, before or after a partial member name.
        m=re.search(r"([A-Za-z_]\w*)\.(?:[A-Za-z_]\w*)?$", before)
        if m:
            typ=idx.variables.get(m.group(1))
            if typ:
                return {"isIncomplete":False,"items":[self.item(x) for x in idx.members_for_type(typ)]}
        # Namespace completion: foo: or foo:bar:
        m=re.search(r"([A-Za-z_]\w*(?::[A-Za-z_]\w*)*):[A-Za-z_]\w*$", before)
        if m:
            ns=m.group(1); fs=[f for f in idx.functions if f.get("namespace") == ns]
            return {"isIncomplete":False,"items":[{"label":f["name"],"kind":3,"detail":f'{f["type"]} {f["name"]}({f["args"]})'} for f in fs]}
        items=[]
        for t in BUILTIN_TYPES: items.append({"label":t,"kind":25,"detail":"Jaguar type"})
        for k in KEYWORDS: items.append({"label":k,"kind":14,"detail":"keyword"})
        for f in idx.functions: items.append({"label":f["name"],"kind":3,"detail":f'{f["type"]} {f["name"]}({f["args"]})'})
        for n,t in idx.variables.items(): items.append({"label":n,"kind":6,"detail":t})
        for n in list(idx.classes)+list(idx.structs)+list(idx.unions)+list(idx.enums): items.append({"label":n,"kind":7,"detail":"Jaguar type"})
        for enum_name, enum in idx.enums.items():
            for value in enum.get("values", []):
                items.append({"label":value,"kind":21,"detail":f"{enum_name} enum value"})
        return {"isIncomplete":False,"items":items}

    @staticmethod
    def item(x):
        return {"label":x["name"],"kind":2 if x.get("kind") == "method" else 5,"detail":x.get("detail",x.get("type","")),"documentation":x.get("documentation",x.get("args", ""))}

    def _semantic_documents(self, uri):
        docs = self._workspace_documents()
        selected = {uri: docs.get(uri, self.docs.get(uri, ""))}
        queue = [uri]
        while queue:
            current = queue.pop()
            source = docs.get(current, "")
            for mod in re.findall(r"^\s*using\s+([A-Za-z_]\w*)\s*;", clean_for_scan(source), re.MULTILINE):
                candidates = []
                for du, ds in docs.items():
                    if os.path.splitext(os.path.basename(self._uri_path(du)))[0] == mod:
                        candidates.append(du)
                for du in candidates:
                    if du not in selected:
                        selected[du] = docs[du]; queue.append(du)
        return selected

    def _all_workspace_functions(self, name, namespace=None, uri=None):
        out = []
        for _, source in (self._semantic_documents(uri) if uri else self._workspace_documents()).items():
            for f in SymbolIndex(source).functions:
                if f["name"] == name and (namespace is None or f.get("namespace") == namespace):
                    if not any(x.get("args") == f.get("args") and x.get("type") == f.get("type") and x.get("namespace") == f.get("namespace") for x in out):
                        out.append(f)
        return out

    def _qualified_at(self, text, off):
        w = word_at(text, off)
        left = text[:off] + w
        m = re.search(r"([A-Za-z_]\w*(?::[A-Za-z_]\w*)*):[A-Za-z_]\w*$", left)
        return (m.group(1), w) if m else (None, w)

    def _auto_type_at(self, text, off):
        line_start = text.rfind("\n", 0, off) + 1
        line_end = text.find("\n", off)
        if line_end < 0: line_end = len(text)
        line = text[line_start:line_end]
        m = re.search(r"\bauto\s+([A-Za-z_]\w*)\s*=\s*(.+?)(?:;|$)", line)
        if not m or not (line_start + m.start() <= off <= line_start + m.end()): return None
        expr = m.group(2).strip()
        inferred = SymbolIndex.infer_expr(expr)
        if inferred != "auto": return inferred
        # Resolve a simple identifier initializer from local/function parameters.
        if re.fullmatch(r"[A-Za-z_]\w*", expr):
            name = expr
            prefix = text[:off]
            pm = re.findall(r"\b([A-Za-z_]\w*(?:\s*<[^>]+>)?)\s+" + re.escape(name) + r"\b", prefix)
            if pm: return pm[-1].strip()
        # Resolve a call to a known user function.
        cm = re.match(r"([A-Za-z_]\w*(?::[A-Za-z_]\w*)*)\s*\(", expr)
        if cm:
            q = cm.group(1); parts=q.split(":"); ns=":".join(parts[:-1]) or None; fn=parts[-1]
            for f in self._all_workspace_functions(fn, ns):
                return f.get("type")
        return "auto"

    def _symbol_info(self, idx, word, namespace=None, uri=None, off=None):
        if word == "auto":
            inferred = self._auto_type_at(idx.text, off if off is not None else idx.text.find(word))
            return {"kind": "type", "name": word, "type": inferred or "auto", "auto": True}
        if word in BUILTIN_TYPES:
            size, note = TYPE_INFO.get(word, (None, "Jaguar built-in type"))
            return {"kind": "type", "name": word, "type": word, "size": size, "note": note}
        if namespace == "jcc":
            sig = JCC_SIGNATURES.get(word)
            if sig:
                return {"kind": "function", "name": word, "type": sig[0], "args": sig[1], "namespace": "jcc", "jcc": True}
        if word in idx.classes:
            c = idx.classes[word]
            return {"kind": "class", "name": word, "type": f"class {word}" + (f" : {c['base']}" if c.get('base') else ""), "detail": c}
        if word in idx.structs:
            return {"kind": "struct", "name": word, "type": f"struct {word}", "detail": idx.structs[word]}
        funcs = self._all_workspace_functions(word, namespace, uri)
        if funcs:
            return {"kind": "function", "name": word, "overloads": funcs, "namespace": namespace}
        if word in idx.variables:
            return {"kind": "variable", "name": word, "type": idx.variables[word]}
        if word in idx.namespaces:
            funcs = self._all_workspace_functions("", word)
            return {"kind": "namespace", "name": word, "functions": funcs}
        for c in idx.classes.values():
            for m in c.get("members", []):
                if m.get("name") == word:
                    return {"kind": m.get("kind", "member"), "name": word, "type": m.get("type", ""), "args": m.get("args", ""), "access": m.get("access")}
        for st in idx.structs.values():
            for m in st.get("members", []):
                if m.get("name") == word:
                    return {"kind": "field", "name": word, "type": m.get("type", "")}
        return None

    def hover(self, uri, pos):
        text, off = self.context(uri, pos); w = word_at(text, off); idx = SymbolIndex(text)
        namespace, _ = self._qualified_at(text, off)
        if w == "auto":
            inferred = self._auto_type_at(text, off)
            if inferred:
                size, note = TYPE_INFO.get(inferred, (None, "deduced Jaguar type"))
                value = f"### `auto`\n\n**Deduced type:** `{inferred}`\n\n{note}"
                if size is not None: value += f"\n\n**Size:** `{size} byte{'s' if size != 1 else ''}`"
                return {"contents":{"kind":"markdown","value":value}}
        info = self._symbol_info(idx, w, namespace, uri, off)
        if not info: return None
        kind = info["kind"]
        if kind == "type":
            value = f"### Type `{w}`\n\nJaguar built-in type.\n\n**Storage:** {info['note']}"
            if info.get("size") is not None: value += f"\n\n**Size:** `{info['size']} byte{'s' if info['size'] != 1 else ''}`"
        elif kind == "class":
            c=info["detail"]; members=c.get("members",[])
            value=f"### Class `{w}`\n\n" + (f"**Base:** `{c['base']}`\n\n" if c.get('base') else "")
            value += f"**Members:** {len(members)}"
            if members: value += "\n\n" + "\n".join(f"- `{m.get('type','')} {m['name']}` ({m.get('kind','member')}, {m.get('access','private')})" for m in members[:30])
        elif kind == "struct":
            st=info["detail"]; members=st.get("members",[])
            value=f"### Struct `{w}`\n\n**Fields:** {len(members)}"
            if members: value += "\n\n" + "\n".join(f"- `{m.get('type','')} {m['name']}`" for m in members[:30])
        elif kind == "union":
            u=info["detail"]; members=u.get("members",[])
            value=f"### Union `{w}`\n\n**Fields:** {len(members)}"
            if members: value += "\n\n" + "\n".join(f"- `{m.get('type','')} {m['name']}`" for m in members[:30])
        elif kind == "enum":
            e=info["detail"]; values=e.get("values",[])
            value=f"### Enum `{w}`\n\n**Values:** {len(values)}"
            if values: value += "\n\n" + "\n".join(f"- `{v}`" for v in values[:50])
        elif kind == "function":
            overloads=info.get("overloads",[])
            if info.get("jcc"):
                overloads=[{"type":info["type"],"args":info.get("args","")} ]
            ns=f"{info.get('namespace')} :" if info.get('namespace') else ""
            value=f"### Function `{w}`\n\n**Signatures:** {len(overloads)}\n\n"
            value += "\n".join(f"```jaguar\n{info.get('namespace','') + ':' if info.get('namespace') else ''}{info.get('name',w)}({f.get('args','')}) -> {f.get('type','')}\n```" for f in overloads[:20])
            if len(overloads)>20: value += f"\n\n… and {len(overloads)-20} more overloads"
            if info.get("jcc"): value += "\n\n**Source:** JaguarCC standard library (`jcc`)"
        elif kind == "namespace":
            funcs=info.get("functions",[]); value=f"### Namespace `{w}`\n\n**Functions:** {len(funcs)}"
            if funcs: value += "\n\n" + "\n".join(f"- `{f['type']} {f['name']}({f.get('args','')})`" for f in funcs[:30])
        elif kind in ("method","field"):
            sig=f"{info.get('type','')} {w}" + (f"({info.get('args','')})" if kind=="method" else "")
            value=f"### {kind.capitalize()}\n```jaguar\n{sig}\n```" + (f"\n\n**Access:** `{info['access']}`" if info.get('access') else "")
        else:
            vtype = info.get('type','auto')
            size, note = TYPE_INFO.get(vtype, (None, 'size depends on the Jaguar/runtime representation'))
            value=f"### Variable `{w}`\n```jaguar\n{vtype} {w}\n```"
            value += f"\n\n**Storage:** {note}"
            if size is not None: value += f"\n\n**Size:** `{size} byte{'s' if size != 1 else ''}`"
        return {"contents":{"kind":"markdown","value":value}}

    @staticmethod
    def _uri_path(uri):
        parsed = urlparse(uri)
        path = unquote(parsed.path or "")
        if os.name == "nt" and re.match(r"^/[A-Za-z]:", path):
            path = path[1:]
        return path

    def _workspace_documents(self):
        docs = dict(self.docs)
        root_path = self._uri_path(self.root) if self.root and self.root.startswith("file:") else self.root
        if not root_path or not os.path.isdir(root_path):
            return docs
        for base, dirs, files in os.walk(root_path):
            dirs[:] = [d for d in dirs if d not in {".git", ".vscode", "node_modules", "__pycache__", "build", "bin", "obj"}]
            for name in files:
                if not name.lower().endswith((".ja", ".jah")): continue
                path = os.path.join(base, name)
                uri = "file://" + path.replace(os.sep, "/")
                if os.name == "nt" and re.match(r"^file://[A-Za-z]:", uri): uri = "file:///" + uri[7:]
                if uri not in docs:
                    try:
                        with open(path, "r", encoding="utf-8") as f: docs[uri] = f.read()
                    except (OSError, UnicodeDecodeError): pass
        return docs

    def rename(self, uri, pos, new_name):
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", new_name or ""):
            raise ValueError("Invalid Jaguar identifier")
        text, off = self.context(uri, pos); old = word_at(text, off)
        if not old or old == new_name: return None
        idx = SymbolIndex(text); namespace, _ = self._qualified_at(text, off)
        info = self._symbol_info(idx, old, namespace)
        if not info: return None
        kind = info["kind"]
        workspace_kind = kind in {"class", "struct", "function", "namespace", "type"}
        documents = self._workspace_documents() if workspace_kind else {uri: text}
        # For functions, only rename the matching namespace-qualified references.
        # For classes/structs/namespaces/types, the short identifier is unique enough
        # for Jaguar's current symbol model. Comments and strings are always ignored.
        changes = {}
        pattern = re.compile(r"\b" + re.escape(old) + r"\b")
        for doc_uri, source in documents.items():
            scan = clean_for_scan(source); edits=[]
            for m in pattern.finditer(scan):
                if kind == "function":
                    before = scan[max(0,m.start()-128):m.start()]
                    q = re.search(r"([A-Za-z_]\w*(?::[A-Za-z_]\w*)*):$", before)
                    found_ns = q.group(1) if q else None
                    if namespace and found_ns != namespace: continue
                    if not namespace and found_ns: continue
                st=offset_to_pos(source,m.start()); en=offset_to_pos(source,m.end())
                edits.append({"range":{"start":st,"end":en},"newText":new_name})
            if edits: changes[doc_uri]=edits
        if not changes: raise ValueError(f"No references found for '{old}'")
        return {"changes":changes}

    def definition(self, uri, pos):
        text,off=self.context(uri,pos); w=word_at(text,off)
        idx=SymbolIndex(text); scan=idx.scan
        patterns=[rf"\b(?:class|struct|union|enum)\s+{re.escape(w)}\b", rf"\b[A-Za-z_]\w*(?:\s*<[^;]+>)?\s+{re.escape(w)}\s*(?:=|;)", rf"\b[A-Za-z_]\w*\s+{re.escape(w)}\s*\("]
        for pat in patterns:
            m=re.search(pat,scan)
            if m:
                p=offset_to_pos(text,m.start()+m.group(0).find(w))
                return [{"uri":uri,"range":{"start":p,"end":offset_to_pos(text,m.start()+m.group(0).find(w)+len(w))}}]
        return []

    def workspace_symbols(self, query):
        out=[]
        for uri,text in self.docs.items():
            idx=SymbolIndex(text)
            for f in idx.functions:
                if query.lower() in f["name"].lower(): out.append({"name":f["name"],"kind":12,"location":{"uri":uri,"range":{"start":{"line":0,"character":0},"end":{"line":0,"character":0}}}})
        return out

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------
    @staticmethod
    def _diag(source, line, message, severity=1, start=0, end=None):
        """Create an LSP diagnostic. `line` is zero-based."""
        lines = source.splitlines()
        if not lines:
            text = ""
        else:
            line = max(0, min(line, len(lines) - 1))
            text = lines[line]
        if end is None:
            end = max(start + 1, start)
        start = max(0, min(start, len(text)))
        end = max(start + 1, min(end, len(text))) if text else start
        return {
            "range": {"start": {"line": line, "character": start},
                      "end": {"line": line, "character": end}},
            "severity": severity,
            "source": "Jaguar",
            "message": message,
        }

    @staticmethod
    def _error_line(message, default=0):
        m = re.search(r"(?:ligne|line)\s+(\d+)", str(message), re.I)
        return max(0, int(m.group(1)) - 1) if m else default

    @staticmethod
    def _numeric(t):
        if isinstance(t, tuple):
            return t and t[0] == "literal"
        return t in getattr(JCC, "INTEGER_TYPES", set()) | getattr(JCC, "FLOAT_TYPES", set())

    @staticmethod
    def _compatible(expected, actual):
        """Jaguar's diagnostics reject category errors while preserving the
        compiler's existing numeric implicit conversions."""
        if expected in (None, "auto") or actual is None:
            return True
        if isinstance(actual, tuple) and actual and actual[0] == "literal":
            if actual[1] == "int":
                return expected in (getattr(JCC, "INTEGER_TYPES", set()) | getattr(JCC, "FLOAT_TYPES", set()))
            if actual[1] == "float":
                return expected in getattr(JCC, "FLOAT_TYPES", set()) | getattr(JCC, "INTEGER_TYPES", set())
        if expected == actual:
            return True
        numeric = getattr(JCC, "INTEGER_TYPES", set()) | getattr(JCC, "FLOAT_TYPES", set())
        return expected in numeric and actual in numeric

    def _locate_name(self, source, name, preferred_line=0):
        lines = source.splitlines()
        if not lines:
            return preferred_line, 0, 1
        candidates = list(re.finditer(r"\b" + re.escape(name) + r"\b", lines[preferred_line] if 0 <= preferred_line < len(lines) else ""))
        if candidates:
            m=candidates[0]; return preferred_line,m.start(),m.end()
        for ln, line in enumerate(lines):
            m=re.search(r"\b" + re.escape(name) + r"\b", line)
            if m: return ln,m.start(),m.end()
        return max(0,min(preferred_line,len(lines)-1)),0,max(1,min(1,len(lines[max(0,min(preferred_line,len(lines)-1))])))

    def _locate_declaration(self, source, name, preferred_line=0, type_name=None):
        """Locate the declaration matching the current AST statement.

        Unlike _locate_name(), this deliberately searches for a declaration
        pattern, so a duplicate declaration is underlined on the new
        declaration rather than on the first occurrence of the variable.
        """
        lines = source.splitlines()
        if not lines:
            return preferred_line, 0, 1
        preferred_line = max(0, min(preferred_line, len(lines) - 1))
        type_part = re.escape(type_name) if type_name else r"[A-Za-z_]\w*"
        pat = re.compile(
            rf"\b{type_part}\s+\b{re.escape(name)}\b(?=\s*(?:=|;|,))"
        )
        order = [preferred_line] + [i for i in range(len(lines)) if i != preferred_line]
        for ln in order:
            m = pat.search(lines[ln])
            if m:
                start = m.start() + m.group(0).rfind(name)
                return ln, start, start + len(name)
        return self._locate_name(source, name, preferred_line)

    def _locate_second_declaration(self, source, name):
        """Find the second declaration of a variable name.

        jcc currently reports redeclaration errors without a source line.
        For that specific error, the second declaration is the one that must
        receive the underline.
        """
        lines = source.splitlines()
        pat = re.compile(r"\b[A-Za-z_]\w*\s+\b" + re.escape(name) + r"\b(?=\s*(?:=|;|,))")
        matches = []
        for ln, line in enumerate(lines):
            for m in pat.finditer(line):
                start = m.start() + m.group(0).rfind(name)
                matches.append((ln, start, start + len(name)))
        if len(matches) >= 2:
            return matches[1]
        if matches:
            return matches[0]
        return self._locate_name(source, name, 0)

    def _locate_initializer(self, source, name, preferred_line=0):
        lines=source.splitlines()
        if not lines: return preferred_line,0,1
        preferred_line=max(0,min(preferred_line,len(lines)-1))
        for ln in [preferred_line] + [i for i in range(len(lines)) if i != preferred_line]:
            line=lines[ln]
            m=re.search(r"\b"+re.escape(name)+r"\b\s*=\s*(.+?)(?:;|$)",line)
            if m: return ln,m.start(1),m.end(1)
        return self._locate_name(source,name,preferred_line)

    def _diagnose_type_expr(self, cg, expected, expr, local_types, source, fallback_line, label):
        if expr is None or expected == "auto":
            return None
        try:
            actual = cg.infer_type(expr, local_types)
        except Exception as e:
            return str(e), fallback_line, label
        if not self._compatible(expected, actual):
            if isinstance(actual, tuple):
                actual_name = "integer literal" if actual[1] == "int" else "floating-point literal"
            else:
                actual_name = actual or "unknown"
            return (f"Type mismatch: '{label}' expects '{expected}', "
                    f"but the expression has type '{actual_name}'"), fallback_line, label
        return None

    def _walk_diagnostics(self, cg, block, local_types, source, diagnostics, current_return=None, current_line=0):
        """Run the same type inference used by jcc.py over a function body.
        This catches errors before the user has to build the project."""
        local = dict(local_types)
        for st in getattr(block, "statements", []):
            line = current_line
            if hasattr(st, "name"):
                ln,_,_=self._locate_name(source, st.name, current_line)
                line=ln
            try:
                if isinstance(st, getattr(JCC, "VarDecl", ())):
                    # A redeclaration must be reported on the *second*
                    # declaration, not on the earlier symbol that happened to
                    # be found by a generic name search.
                    if st.name in local:
                        ln, a, b = self._locate_declaration(source, st.name, current_line, st.type)
                        diagnostics.append(self._diag(
                            source, ln,
                            f"Variable '{st.name}' is already declared in this scope",
                            start=a, end=b
                        ))
                    if st.init is not None:
                        if st.type == "auto":
                            try:
                                st.type = cg._resolve_auto_type(st.init, local)
                            except Exception as e:
                                # Keep the declaration in the local scope even
                                # when its initializer is currently invalid.
                                # This lets a following `int h = ...` correctly
                                # report the redeclaration on the second `h`.
                                diagnostics.append(self._diag(source, line, str(e), start=0, end=max(1, len(source.splitlines()[line]) if source.splitlines() else 1)))
                        else:
                            err=self._diagnose_type_expr(cg, st.type, st.init, local, source, line, st.name)
                            if err:
                                msg,ln,name=err; a,b,c=self._locate_initializer(source,name,ln)
                                diagnostics.append(self._diag(source,a,msg,start=b,end=c))
                    local[st.name]=st.type
                elif isinstance(st, getattr(JCC, "AssignStmt", ())):
                    if st.name not in local and st.name not in cg.global_types:
                        ln, a, b=self._locate_name(source,st.name,line)
                        diagnostics.append(self._diag(source,ln,f"Variable '{st.name}' is not declared",start=a,end=b))
                    else:
                        expected=local.get(st.name,cg.global_types.get(st.name))
                        err=self._diagnose_type_expr(cg,expected,st.expr,local,source,line,st.name)
                        if err:
                            msg,ln,name=err; a,b,c=self._locate_name(source,name,ln)
                            diagnostics.append(self._diag(source,a,msg,start=b,end=c))
                elif isinstance(st, getattr(JCC, "ReturnStmt", ())):
                    if current_return and st.expr is not None:
                        err=self._diagnose_type_expr(cg,current_return,st.expr,local,source,line,"return")
                        if err:
                            msg,ln,_=err; diagnostics.append(self._diag(source,ln,msg,start=0,end=max(1,len(source.splitlines()[ln]) if source.splitlines() else 1)))
                elif isinstance(st, getattr(JCC, "MemberAssignStmt", ())):
                    try:
                        target_type=cg.infer_type(st.target.obj,local)
                        owner,member=cg._find_class_member(target_type,st.target.name,"field") if target_type in cg.classes else (None,None)
                        if member is not None:
                            err=self._diagnose_type_expr(cg,member.type,st.expr,local,source,line,st.target.name)
                            if err:
                                msg,ln,name=err; a,b,c=self._locate_initializer(source,name,ln)
                                diagnostics.append(self._diag(source,a,msg,start=b,end=c))
                    except Exception as e:
                        diagnostics.append(self._diag(source,line,str(e),start=0,end=max(1,len(source.splitlines()[line]) if source.splitlines() else 1)))
                elif isinstance(st, getattr(JCC, "IfStmt", ())):
                    try: cg.infer_type(st.cond,local)
                    except Exception as e: diagnostics.append(self._diag(source,line,str(e),start=0,end=max(1,len(source.splitlines()[line]) if source.splitlines() else 1)))
                    self._walk_diagnostics(cg,st.then_block,local,source,diagnostics,current_return,line)
                    if isinstance(st.else_branch,getattr(JCC,"IfStmt",())):
                        self._walk_diagnostics(cg,st.else_branch,local,source,diagnostics,current_return,line)
                    elif isinstance(st.else_branch,getattr(JCC,"Block",())):
                        self._walk_diagnostics(cg,st.else_branch,local,source,diagnostics,current_return,line)
                elif isinstance(st, getattr(JCC, "WhileStmt", ())):
                    self._walk_diagnostics(cg,st.body,local,source,diagnostics,current_return,line)
                elif isinstance(st, getattr(JCC, "ForLoopStmt", ())):
                    try:
                        cg.infer_type(st.start,local); cg.infer_type(st.end,local)
                    except Exception as e: diagnostics.append(self._diag(source,line,str(e),start=0,end=max(1,len(source.splitlines()[line]) if source.splitlines() else 1)))
                    inner=dict(local); inner[st.var_name]=st.var_type
                    self._walk_diagnostics(cg,st.body,inner,source,diagnostics,current_return,line)
                elif isinstance(st, getattr(JCC, "CollectionLoopStmt", ())):
                    try: cg.infer_type(st.collection,local)
                    except Exception as e: diagnostics.append(self._diag(source,line,str(e),start=0,end=max(1,len(source.splitlines()[line]) if source.splitlines() else 1)))
                    self._walk_diagnostics(cg,st.body,local,source,diagnostics,current_return,line)
                elif isinstance(st, getattr(JCC, "ExprStmt", ())):
                    cg.infer_type(st.expr,local)
            except Exception as e:
                msg=str(e)
                a,b,c=self._locate_name(source, getattr(st,"name",""), line) if getattr(st,"name",None) else (line,0,1)
                diagnostics.append(self._diag(source,a,msg,start=b,end=c))

    def _workspace_functions_for(self, uri):
        """Return functions visible from the current file: current file, `using`
        files, plus JaguarCC's built-in jcc namespace."""
        visible = []
        seen = set()
        for du, ds in self._semantic_documents(uri).items():
            for f in SymbolIndex(ds).functions:
                key = (f.get("namespace"), f.get("name"), f.get("args"), f.get("type"))
                if key not in seen:
                    seen.add(key); visible.append(f)
        return visible

    @staticmethod
    def _function_decl_locations(source, name):
        """Return source locations of function declarations named `name`."""
        scan = clean_for_scan(source)
        # The parser accepts attributes and const between the type and name.
        pat = re.compile(r"(?:^|[;{}])\s*(?:@[A-Za-z_]\w*\s*)*(?:const\s+)?[A-Za-z_]\w*(?:\s*<[^;{}()]+>)?\s+" + re.escape(name) + r"\s*\(")
        out=[]
        for m in pat.finditer(scan):
            name_pos = m.end() - 1
            # Move from the opening parenthesis backwards to the identifier.
            q = name_pos - 1
            while q >= 0 and scan[q].isspace(): q -= 1
            end=q+1
            while q >= 0 and (scan[q].isalnum() or scan[q]=='_'): q -= 1
            start=q+1
            if scan[start:end] == name:
                out.append((start,end))
        return out

    def _diagnose_duplicate_functions(self, source, program, diagnostics):
        groups={}
        for item in getattr(program, "items", []):
            if isinstance(item, getattr(JCC, "FunctionDecl", ())):
                key=(getattr(item,"namespace",None), item.name, tuple(p.type for p in item.params))
                groups.setdefault(key, []).append(item)
        for (ns,name,params), funcs in groups.items():
            if len(funcs) <= 1: continue
            locs=self._function_decl_locations(source,name)
            # Declarations are in source order for normal top-level functions.
            for duplicate_index in range(1,len(funcs)):
                if duplicate_index < len(locs):
                    a,b=locs[duplicate_index]
                    ln=source[:a].count("\n")
                    diagnostics.append(self._diag(source,ln,
                        f"Function '{name}' is already declared with the same signature",
                        start=a-(source.rfind("\n",0,a)+1), end=b-(source.rfind("\n",0,a)+1)))
                else:
                    ln, a, b=self._locate_name(source,name,0)
                    diagnostics.append(self._diag(source,ln,
                        f"Function '{name}' is already declared with the same signature",start=a,end=b))

    def _diagnose_invalid_exposed(self, source, diagnostics):
        """`@exposed` is a reflection attribute for public class fields, not
        private methods. jcc currently drops the attribute on methods, so the
        language server must diagnose this editor-side."""
        scan=clean_for_scan(source)
        # Inside a class, @exposed immediately followed by a method declaration
        # is invalid unless the member is explicitly public with `$`.
        class_spans=[]
        for cm in re.finditer(r"\bclass\s+[A-Za-z_]\w*(?:\s*,\s*[A-Za-z_]\w*)?\s*\{",scan):
            depth=1; i=cm.end()
            while i < len(scan) and depth:
                if scan[i]=='{': depth+=1
                elif scan[i]=='}': depth-=1
                i+=1
            if depth==0: class_spans.append((cm.end(),i-1))
        pat=re.compile(r"@exposed\s*(?:const\s+)?[A-Za-z_]\w*(?:\s*<[^;{}()]+>)?\s+(?!\$)(?:%\s*)?[A-Za-z_]\w*\s*\(")
        for lo,hi in class_spans:
            for m in pat.finditer(scan,lo,hi):
                # A `%` access marker is protected and therefore also invalid.
                snippet=scan[m.start():m.end()]
                line=scan[:m.start()].count("\n")
                ls=scan.rfind("\n",0,m.start())+1
                at=max(ls,m.start())
                diagnostics.append(self._diag(source,line,
                    "'@exposed' can only be used on public class members",
                    start=at-ls,end=max(at-ls+1,min(len(source.splitlines()[line]),m.end()-ls))))

    def _iter_ast_calls(self, obj):
        if isinstance(obj, getattr(JCC, "Call", ())):
            yield obj
        if is_dataclass(obj):
            for f in fields(obj):
                value=getattr(obj,f.name)
                if is_dataclass(value): yield from self._iter_ast_calls(value)
                elif isinstance(value,list):
                    for x in value:
                        if is_dataclass(x): yield from self._iter_ast_calls(x)
                elif isinstance(value,dict):
                    for x in value.values():
                        if is_dataclass(x): yield from self._iter_ast_calls(x)

    def _call_text_location(self, source, call):
        callee=getattr(call,"callee",None)
        name=getattr(callee,"name",None)
        ns=getattr(callee,"namespace",None)
        if not name: return (0,0,1)
        target=(str(ns)+":" if ns else "")+name
        line_hint=0
        # Search calls in source; prefer the first still-unused occurrence.
        pat=re.compile(r"\b"+re.escape(target)+r"\s*\(")
        m=pat.search(clean_for_scan(source))
        if not m: return self._locate_name(source,name,line_hint)
        ls=source.rfind("\n",0,m.start())+1
        return m.start() and (source[:m.start()].count("\n"),m.start()-ls,m.start()-ls+len(target)) or (0,0,len(target))

    def _diagnose_unknown_calls(self, uri, source, program, diagnostics):
        visible=self._workspace_functions_for(uri)
        user={(f.get("namespace"),f.get("name")) for f in visible}
        std=set(getattr(JCC,"SYSTEM_BUILTINS",{}).keys()) if JCC is not None else set()
        # Also expose jcc functions as the standard library even if the parser
        # represents them only through SYSTEM_BUILTINS.
        for call in self._iter_ast_calls(program):
            callee=getattr(call,"callee",None)
            ns=getattr(callee,"namespace",None); name=getattr(callee,"name",None)
            if not name: continue
            if ns is None:
                exists=any(f.get("namespace") is None and f.get("name")==name for f in visible)
                if not exists:
                    # Unqualified built-ins are not part of jcc; Jaguar requires
                    # the `jcc:` namespace for the standard library.
                    ln,a,b=self._locate_name(source,name,0)
                    diagnostics.append(self._diag(source,ln,f"Unknown function '{name}'",start=a,end=b))
            else:
                if (ns,name) in std or (ns,name) in user: continue
                ln,a,b=self._locate_name(source,name,0)
                diagnostics.append(self._diag(source,ln,f"Unknown function '{ns}:{name}'",start=max(0,a-len(ns)-1),end=b))

    def _semantic_diagnostics(self, uri, source, program):
        """Legacy supplemental diagnostics.

        Published diagnostics use JaguarCC itself as the authoritative source.
        This helper remains available for older internal callers/tests, but it
        must never override the compiler result.
        """
        diagnostics=[]
        self._diagnose_duplicate_functions(source, program, diagnostics)
        self._diagnose_invalid_exposed(source, diagnostics)
        self._diagnose_unknown_calls(uri, source, program, diagnostics)
        try:
            groups=JCC.Resolver(program).resolve()
            cg=JCC.CodeGen(program,groups)
            # Let the real compiler catch semantic/codegen errors too.  Keep
            # this diagnostic pending until the source walk below has run, so
            # we do not display the exact same error twice.
            compiler_error = None
            try:
                cg.gen()
            except Exception as e:
                compiler_error = str(e)
            for item in program.items:
                if isinstance(item,getattr(JCC,"VarDecl",())):
                    local={}
                    if item.init is not None:
                        err=self._diagnose_type_expr(cg,item.type,item.init,local,source,0,item.name)
                        if err:
                            msg,ln,name=err; a,b,c=self._locate_initializer(source,name,ln); diagnostics.append(self._diag(source,a,msg,start=b,end=c))
                elif isinstance(item,getattr(JCC,"FunctionDecl",())):
                    local={p.name:p.type for p in item.params}
                    cg._current_class=None
                    self._walk_diagnostics(cg,item.body,local,source,diagnostics,item.ret_type,0)
                elif isinstance(item,getattr(JCC,"ClassDecl",())):
                    cg._current_class=item
                    for method in item.methods:
                        if method is None: continue
                        local={p.name:p.type for p in method.params}
                        self._walk_diagnostics(cg,method.body,local,source,diagnostics,method.ret_type,0)
                    cg._current_class=None
            if compiler_error and not any(d.get("message") == compiler_error for d in diagnostics):
                msg=compiler_error; line=self._error_line(msg,0)
                if "déjà déclarée" in msg or "définie plusieurs fois" in msg or "already declared" in msg:
                    # Variable/function duplicate declarations are diagnosed above
                    # with an exact source location. Do not fall back to a generic
                    # name search (which can land on `using`, comments, etc.).
                    if "fonction '" in msg or "Function '" in msg or "définie plusieurs fois" in msg:
                        return diagnostics
                    diagnostics = [d for d in diagnostics if not d.get("message", "").startswith("Variable '") or "already declared in this scope" not in d.get("message", "")]
                name_match=re.search(r"['‘]([A-Za-z_][A-Za-z0-9_:]*)['’]",msg)
                name=name_match.group(1).split(":")[-1] if name_match else ""
                if name and ("déjà déclarée" in msg or "already declared" in msg):
                    ln,a,b = self._locate_second_declaration(source, name)
                else:
                    ln,a,b=self._locate_name(source,name,line) if name else (line,0,max(1,len(source.splitlines()[line]) if source.splitlines() and line<len(source.splitlines()) else 1))
                diagnostics.append(self._diag(source,ln,msg,start=a,end=b))
        except Exception as e:
            msg=str(e)
            # Resolver errors for duplicate functions are already reported above
            # at the second declaration. Never use the resolver exception's
            # fallback line (which can point at an unrelated `using` line).
            if "fonction '" in msg and "définie plusieurs fois" in msg:
                return diagnostics
            line=self._error_line(msg,0)
            diagnostics.append(self._diag(source,line,msg,start=0,end=max(1,len(source.splitlines()[line]) if source.splitlines() and line<len(source.splitlines()) else 1)))
        return diagnostics

    def _compiler_diagnostics(self, source):
        """Return diagnostics produced by the same JaguarCC used to compile.

        Semantic rules are deliberately not duplicated in the language server:
        class constness, override compatibility, overload resolution, namespaces,
        collection APIs, unions, etc. belong to jcc.py.
        """
        if JCC is None:
            return [{
                "message": "JaguarCC compiler not found",
                "line": 1, "column": 0, "end_column": 1, "severity": 1,
            }]

        diagnose = getattr(JCC, "diagnose_source", None)
        if callable(diagnose):
            result = diagnose(source)
            return [] if result is None else list(result)

        transpile = getattr(JCC, "transpile", None)
        if not callable(transpile):
            return [{
                "message": "Loaded JaguarCC does not expose diagnose_source() or transpile()",
                "line": 1, "column": 0, "end_column": 1, "severity": 1,
            }]

        try:
            transpile(source)
            return []
        except Exception as exc:
            message = getattr(exc, "_jaguar_message", str(exc))
            line = int(getattr(exc, "_jaguar_line", self._error_line(message, 0) + 1))
            column = int(getattr(exc, "_jaguar_column", 0))
            end_column = int(getattr(exc, "_jaguar_end_column", column + 1))
            return [{
                "message": message,
                "line": max(1, line),
                "column": max(0, column),
                "end_column": max(max(0, column) + 1, end_column),
                "severity": 1,
            }]

    def publish_diagnostics(self, uri):
        """Publish exactly the diagnostics reported by JaguarCC.

        The tolerant scanner remains useful for completion/hover while a file
        is incomplete, but it must not invent semantic errors or resurrect stale
        rules (for example an old const-context or collection-method rule).
        """
        source = self.docs.get(uri, "")
        if self._is_jbs_uri(uri):
            diagnostics = []
            if self.jbs is not None and source.strip():
                try:
                    self.jbs.parse_jbs(source)
                except Exception as exc:
                    line = max(0, int(getattr(exc, "line", 1) or 1) - 1)
                    col = max(0, int(getattr(exc, "column", 0) or 0))
                    diagnostics.append({"range":{"start":{"line":line,"character":col},"end":{"line":line,"character":col+1}},"severity":1,"source":"JBS","message":str(exc)})
            self.notify("textDocument/publishDiagnostics", {"uri":uri,"diagnostics":diagnostics})
            return
        if not source.strip():
            self.notify("textDocument/publishDiagnostics", {"uri": uri, "diagnostics": []})
            return

        compiler_diagnostics = self._compiler_diagnostics(source)
        diagnostics = []
        seen = set()
        lines = source.splitlines()

        for d in compiler_diagnostics:
            line = max(1, int(d.get("line", 1))) - 1
            start = max(0, int(d.get("column", 0)))
            end = max(start + 1, int(d.get("end_column", start + 1)))
            if lines:
                line = min(line, len(lines) - 1)
                width = len(lines[line])
                if width:
                    start = min(start, width)
                    end = min(max(start + 1, end), width)
                else:
                    start = end = 0
            message = d.get("message", "Jaguar compilation error")
            key = (line, start, end, message)
            if key in seen:
                continue
            seen.add(key)
            diagnostics.append({
                "range": {
                    "start": {"line": line, "character": start},
                    "end": {"line": line, "character": end},
                },
                "severity": int(d.get("severity", 1)),
                "source": "Jaguar",
                "message": message,
            })

        self.notify("textDocument/publishDiagnostics", {"uri": uri, "diagnostics": diagnostics})



def main():
    server=JaguarServer(); data=sys.stdin.buffer
    while True:
        header=b""
        while b"\r\n\r\n" not in header:
            chunk=data.read(1)
            if not chunk: return
            header += chunk
        head,rest=header.split(b"\r\n\r\n",1)
        m=re.search(br"Content-Length:\s*(\d+)",head,re.I)
        if not m: continue
        n=int(m.group(1)); body=rest
        while len(body)<n:
            chunk=data.read(n-len(body))
            if not chunk:return
            body+=chunk
        msg=json.loads(body[:n].decode("utf-8"))
        if server.handle(msg) is False:return

if __name__ == "__main__": main()
