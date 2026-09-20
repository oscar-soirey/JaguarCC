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
from typing import Any, Dict, List, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
JCC_PATH = os.path.join(HERE, "jcc.py")


def load_jcc():
    if not os.path.isfile(JCC_PATH):
        return None
    spec = importlib.util.spec_from_file_location("jaguar_jcc", JCC_PATH)
    if not spec or not spec.loader:
        return None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

JCC = load_jcc()

BUILTIN_TYPES = [
    "void", "bool", "int", "float", "string",
    "i8", "u8", "i16", "u16", "i32", "u32", "i64", "u64", "f32", "f64",
    "auto", "cptr", "cstr", "cfuncptr",
]
KEYWORDS = [
    "class", "struct", "namespace", "using", "const", "virtual", "override",
    "constr", "destr", "if", "else", "while", "for_loop", "return", "break",
    "continue", "true", "false", "new", "signal", "public", "protected", "private",
]
DIRECTIVES = ["#define", "#undef", "#if", "#ifdef", "#ifndef", "#elif", "#elseif", "#else", "#endif", "#pragma", "#error", "#warning", "#line"]

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
            elif cls == "ClassDecl":
                members = []
                for f in item.fields:
                    members.append({"name": f.name, "type": f.type, "kind": "field", "access": getattr(f, "access", "private")})
                for m in item.methods:
                    members.append({"name": m.name, "type": m.ret_type, "args": ", ".join(f"{p.type} {p.name}" for p in m.params), "kind": "method", "access": getattr(m, "access", "private")})
                self.classes[item.name] = {"name": item.name, "base": item.base, "members": members}
            # Namespace parsing in jcc flattens functions into FunctionDecl.namespace.

    def fallback_scan(self):
        s = self.scan
        # This supplements the AST index for incomplete source.
        for m in re.finditer(r"\b(namespace|class|struct)\s+([A-Za-z_]\w*)(?:\s*,\s*([A-Za-z_]\w*))?\s*\{", s):
            kind, name, base = m.groups()
            if kind == "class" and name not in self.classes: self.classes[name] = {"name": name, "base": base, "members": []}
            elif kind == "struct" and name not in self.structs: self.structs[name] = {"name": name, "members": []}
            elif kind == "namespace" and name not in self.namespaces: self.namespaces.append(name)
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
        m = re.match(r"(list|map|container|dynamic_list|pair)\s*<", typ)
        if m:
            return [{"name":n,"detail":d,"documentation":doc,"kind":"method"} for n,d,doc in COLLECTION_METHODS[m.group(1)]]
        return []


class JaguarServer:
    def __init__(self):
        self.docs = {}
        self.root = None
        self.send_lock = threading.Lock()

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
                    "workspaceSymbolProvider": True,
                }, "serverInfo": {"name":"Jaguar Language Server", "version":"0.2.0"}})
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
            elif method == "workspace/symbol": self.result(ident, self.workspace_symbols(p.get("query", "")))
            elif ident is not None: self.result(ident, None)
        except Exception as e:
            if ident is not None: self.error(ident, -32603, str(e))
            traceback.print_exc(file=sys.stderr)
        return True

    def context(self, uri, pos):
        text=self.docs.get(uri, ""); return text, pos_to_offset(text, pos.get("line",0), pos.get("character",0))

    def completion(self, uri, pos):
        text, off = self.context(uri, pos); before=text[:off]; idx=SymbolIndex(text)
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
        for n in list(idx.classes)+list(idx.structs): items.append({"label":n,"kind":7,"detail":"type"})
        return {"isIncomplete":False,"items":items}

    @staticmethod
    def item(x):
        return {"label":x["name"],"kind":2 if x.get("kind") == "method" else 5,"detail":x.get("detail",x.get("type","")),"documentation":x.get("documentation",x.get("args", ""))}

    def hover(self, uri, pos):
        text,off=self.context(uri,pos); w=word_at(text,off); idx=SymbolIndex(text)
        if w in BUILTIN_TYPES: return {"contents":{"kind":"markdown","value":f"**{w}**\n\nJaguar built-in type."}}
        for f in idx.functions:
            if f["name"]==w: return {"contents":{"kind":"markdown","value":f'```jaguar\n{f["type"]} {f["name"]}({f["args"]})\n```'}}
        if w in idx.variables: return {"contents":{"kind":"markdown","value":f'`{idx.variables[w]}` **{w}**'}}
        return None

    def definition(self, uri, pos):
        text,off=self.context(uri,pos); w=word_at(text,off)
        idx=SymbolIndex(text); scan=idx.scan
        patterns=[rf"\b(?:class|struct)\s+{re.escape(w)}\b", rf"\b[A-Za-z_]\w*(?:\s*<[^;]+>)?\s+{re.escape(w)}\s*(?:=|;)", rf"\b[A-Za-z_]\w*\s+{re.escape(w)}\s*\("]
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

    def publish_diagnostics(self, uri):
        # Only publish parser diagnostics when the buffer is sufficiently complete.
        # Otherwise completion should not be drowned in errors while typing.
        idx=SymbolIndex(self.docs.get(uri,""))
        diagnostics=[]
        if idx.used_jcc_parser:
            self.notify("textDocument/publishDiagnostics", {"uri":uri,"diagnostics":diagnostics})
        else:
            # No hard parser diagnostics for incomplete buffers in this version.
            self.notify("textDocument/publishDiagnostics", {"uri":uri,"diagnostics":[]})


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
