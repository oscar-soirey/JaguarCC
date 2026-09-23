#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
jcc.py — Compilateur Jaguar -> C

Pipeline : Lexer -> Parser (récursif descendant) -> AST
           -> Resolver (surcharge de fonctions, name mangling)
           -> IR Jaguar (JSON sérialisé)

La génération C est volontairement séparée dans jcc-c.py. Le front-end
reste la source de vérité pour le langage Jaguar ; les backends consomment
uniquement l'IR résolu.

Usage :
    python3 jcc.py mon_fichier.ja            # écrit l'IR JSON sur stdout
    python3 jcc.py mon_fichier.ja -o out.jir
    python3 jcc.py mon_fichier.ja --c89      # mémorise l'option dans l'IR
    cat mon_fichier.ja | python3 jcc.py      # lecture depuis stdin

Backend C :
    python3 jcc-c.py out.jir -o out
    python3 jcc-c.py out.jir --emit-c

Portée du langage (rien de plus n'est implémenté) :
  - directives préprocesseur (#define ...), passées telles quelles
  - commentaires // et /* ... */ (dont /** ... */), supprimés à la lexe
  - le langage n'est pas sensible aux sauts de ligne
  - types : void, int/i32, uint/u32, short/i16, ushort/u16, long/i64,
    ulong/u64, char/i8, uchar/u8, float/f32, double/f64, string, bool -- les types "custom" (i8, u8, ..., f64, bool, string) sont
    définis par des typedef générés automatiquement (pas d'include), et
    ne sont émis que s'ils sont effectivement utilisés
  - le type Jaguar "bool" est émis sous le nom C "_jBool" (car "bool" est
    déjà un mot-clé / une macro en C99+ via <stdbool.h>)
  - fonctions typées, paramètres nommés
  - variables locales : `type nom;` ou `type nom = expression;`
  - variables globales : mêmes formes, directement au niveau du fichier
    (hors fonction). En C, l'initialiseur d'une globale doit être une
    expression constante : littéraux, macros #define, opérations entre
    constantes -- ni appel de fonction, ni autre variable. Une globale
    sans initialiseur vaut 0 (règle du C). Pas (encore) de globale dans
    un namespace.
  - affectation : `nom = expression;` (variable locale, paramètre ou
    globale ; la variable doit avoir été déclarée)
  - littéraux booléens : true / false (émis en C sous la forme 1 / 0)
  - surcharge de fonctions (même nom, signatures différentes) : mangling
    par types de paramètres UNIQUEMENT quand un nom est réellement
    surchargé ; sinon le nom reste tel quel (namespace mis à part)
  - attribut @extern devant une fonction : désactive tout name mangling
    (namespace ET surcharge), la fonction garde exactement son nom déclaré
  - fonction spéciale main(string param) : voir jcc-c.py pour
    la traduction vers le main() C standard
  - namespaces { ... } contenant fonctions/struct, avec namespaces
    imbriqués -> chemin "a:b:c", manglé en "a_b_c", via "a:b:c:fn()"
  - bibliothèque système intégrée : sys:print, sys:console:set_color,
    sys:console:reset_color, sys:execute, sys:fs:read et sys:fs:write ;
    ces appels génèrent automatiquement le runtime C minimal nécessaire
  - struct (typedef struct C, jamais de struct C++)
  - expressions : + - * / %, moins unaire, comparaisons (== != < > <= >=),
    logique (&& || !), parenthèses, appels. Les comparaisons et les
    opérateurs logiques sont de type bool.
  - instruction return
  - if (cond) { ... } else if (cond) { ... } else { ... }
    (accolades obligatoires, parenthèses autour de la condition)
  - while (condition) { ... } : boucle conditionnelle classique ;
  - loop { ... } : boucle sans condition, on en sort avec break (ou return).
  - int i = for_loop(début, fin) { ... } : i parcourt début..fin, fin
    COMPRISE (aucune itération si début > fin). i est en lecture seule
    dans le corps, et n'existe que dans la boucle. Le type de i doit
    être entier (int, i8..i64, u8..u64).
  - break; et continue; (uniquement à l'intérieur d'une boucle)
  - chaque bloc { } a sa propre portée : une variable déclarée dans un
    bloc n'existe plus après lui, et deux blocs frères peuvent réutiliser
    un même nom. Masquer une variable visible (paramètre, variable d'un
    bloc englobant, globale) est interdit.

Limite assumée : la résolution de surcharge se fait par égalité stricte
de types (pas de conversions implicites). Les valeurs typées disponibles
dans une fonction sont ses paramètres, ses variables locales et
globales (types déclarés), les littéraux (dont true/false, de type
bool), et les résultats d'appels.

Une variable locale n'a pas le droit de porter le nom d'une variable
globale (masquage interdit) : cela évite qu'une déclaration remontée en
tête de bloc (voir plus bas) ne change silencieusement la cible d'une
référence située avant elle.

Comme pour les fonctions, une globale doit être déclarée AVANT son
usage dans le fichier (l'ordre source est conservé dans le C généré).

Portabilité C : le C généré vise un C ANSI/C89 "propre" -- pas de _Bool
natif (C99), et main() est toujours émis sous l'une des deux formes
standard attendues par un compilateur C (int main(void) ou
int main(int argc, char *argv[])), jamais avec un type "string".

Déclarations de variables et ordre du code généré :
  - par défaut, chaque déclaration reste EXACTEMENT à sa place, avec son
    initialiseur (`bool b = true;` -> `_jBool b = 1;`). Cela mélange
    déclarations et instructions, ce qui est du C99 : accepté par tous
    les compilateurs actuels (gcc, clang, MSVC).
  - avec --c89, le C produit est du C89 strict : comme C89 exige que les
    déclarations d'un bloc précèdent la première instruction, une
    déclaration située après une instruction est "remontée" en tête de
    bloc (sans initialiseur), et son initialisation reste à sa place
    d'origine sous forme d'affectation.
  Les deux modes ont exactement la même sémantique (mêmes règles de
  portée et de masquage) ; seule la disposition du C change.
"""

import sys
import os
import re
import subprocess
import json
import dataclasses
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Dict, Tuple


# =========================================================================
# 1. LEXER
# =========================================================================

# Types "natifs" C (aucun typedef à générer)
NATIVE_TYPE_KEYWORDS = {"void", "int", "float"}
TYPE_ALIASES = {"int":"i32", "uint":"u32", "short":"i16", "ushort":"u16", "long":"i64", "ulong":"u64", "char":"i8", "uchar":"u8", "sbyte":"i8", "byte":"u8", "float":"f32", "double":"f64"}
def canonical_type(name: str) -> str:
    if not isinstance(name, str):
        return name
    if name.endswith("*"):
        base = name.rstrip("*")
        return canonical_type(base) + "*" * (len(name) - len(base))
    return TYPE_ALIASES.get(name, name)

# Types intégrés côté langage Jaguar. Leur représentation dans un backend
# particulier n'est pas définie par le front-end.
LANGUAGE_BUILTIN_TYPES = {
    "bool", "i8", "u8", "i16", "u16", "i32", "u32", "i64", "u64",
    "f32", "f64", "string",
}


def _split_type_list(text: str) -> list[str]:
    parts=[]; start=0; depth=0
    for i,ch in enumerate(text):
        if ch in "(<": depth += 1
        elif ch in ")>": depth -= 1
        elif ch == "," and depth == 0:
            parts.append(text[start:i].strip()); start=i+1
    tail=text[start:].strip()
    if tail: parts.append(tail)
    return parts


TYPE_KEYWORDS = NATIVE_TYPE_KEYWORDS | LANGUAGE_BUILTIN_TYPES | set(TYPE_ALIASES.keys()) | {"dynamic_list", "list", "map", "container", "pair"}
INTEGER_TYPES = {"int", "i8", "i16", "i32", "i64", "u8", "u16", "u32", "u64"}
FLOAT_TYPES = {"float", "f32", "f64"}

KEYWORDS = TYPE_KEYWORDS | {
    "struct", "union", "enum", "namespace", "class", "virtual", "override", "constr", "destr", "return", "true", "false", "nullptr", "const", "using", "as", "loop",
    "if", "else", "while", "break", "continue", "for_loop", "this", "auto", "signal", "new",
}

_OPERATOR_FUNCTION_TOKENS = {"+", "-", "*", "/", "%", "==", "!=", "<", ">", "<=", ">="}
_OPERATOR_C_SUFFIX = {
    "+": "add", "-": "sub", "*": "mul", "/": "div", "%": "mod",
    "==": "eq", "!=": "neq", "<": "lt", ">": "gt", "<=": "le", ">=": "ge",
}

def _operator_c_name(name: str) -> str:
    if isinstance(name, str) and name.startswith("operator") and name[8:] in _OPERATOR_C_SUFFIX:
        return "operator_" + _OPERATOR_C_SUFFIX[name[8:]]
    return name

# tokens à trois caractères (testés avant les tokens à deux caractères)
THREE_CHAR_TOKENS = {"..."}

# tokens à deux caractères (testés AVANT les tokens à un caractère)
TWO_CHAR_TOKENS = {"==", "!=", "<=", ">=", "&&", "||", "=>", "->"}

# tokens à un seul caractère
SINGLE_CHAR_TOKENS = set("{}[]();,:.$+-*/%@=<>!&")


class LexError(Exception):
    pass


@dataclass
class Token:
    kind: str   # nom du token ("IDENT", "INT", "{", "void", "i32", "@", ...)
    value: str
    line: int
    column: int = 0
    end_column: int = 0


def tokenize(src: str) -> List[Token]:
    tokens: List[Token] = []
    i = 0
    n = len(src)
    line = 1
    column = 0

    while i < n:
        c = src[i]

        if c == "\n":
            line += 1
            column = 0
            i += 1
            continue

        if c in " \t\r":
            i += 1
            column += 1
            continue

        start_line = line
        start_column = column

        # --- directive préprocesseur : toute la ligne, telle quelle ---
        if c == "#":
            j = src.find("\n", i)
            if j == -1:
                j = n
            directive = src[i:j].rstrip()
            m = re.match(r"#\s*([A-Za-z_][A-Za-z0-9_]*)", directive)
            if m:
                name = m.group(1)
                if name == "include":
                    err = LexError("#include is not supported by Jaguar; use `using` or BindGen")
                    err._jaguar_line = start_line; err._jaguar_column = start_column; err._jaguar_end_column = start_column + len(directive)
                    raise err
                if name == "elseif":
                    directive = "#elif" + directive[m.end():]
            tokens.append(Token("PREPROC", directive, start_line, start_column, start_column + len(directive)))
            column += j - i
            i = j
            continue

        # --- commentaire mono-ligne ---
        if c == "/" and i + 1 < n and src[i + 1] == "/":
            j = src.find("\n", i)
            if j == -1:
                j = n
            column += j - i
            i = j
            continue

        # --- commentaire multiligne /* ... */ (couvre aussi /** ... */) ---
        if c == "/" and i + 1 < n and src[i + 1] == "*":
            j = src.find("*/", i + 2)
            if j == -1:
                err = LexError(f"unterminated multiline comment (line {line})")
                err._jaguar_line = start_line; err._jaguar_column = start_column; err._jaguar_end_column = start_column + 2
                raise err
            chunk = src[i:j + 2]
            newlines = chunk.count("\n")
            if newlines:
                line += newlines
                column = len(chunk.rsplit("\n", 1)[-1])
            else:
                column += len(chunk)
            i = j + 2
            continue

        # --- chaîne de caractères ---
        if c == '"':
            j = i + 1
            while j < n and src[j] != '"':
                if src[j] == "\\" and j + 1 < n:
                    j += 2
                else:
                    j += 1
            if j >= n:
                err = LexError(f"unterminated string literal (line {line})")
                err._jaguar_line = start_line; err._jaguar_column = start_column; err._jaguar_end_column = start_column + 1
                raise err
            value = src[i:j + 1]
            tokens.append(Token("STRING", value, start_line, start_column, start_column + len(value)))
            column += len(value)
            i = j + 1
            continue

        # --- nombres (entiers et flottants) ---
        if c.isdigit():
            j = i
            while j < n and src[j].isdigit():
                j += 1
            is_float = False
            if j < n and src[j] == "." and j + 1 < n and src[j + 1].isdigit():
                is_float = True
                j += 1
                while j < n and src[j].isdigit():
                    j += 1
            value = src[i:j]
            tokens.append(Token("FLOAT" if is_float else "INT", value, start_line, start_column, start_column + len(value)))
            column += len(value)
            i = j
            continue

        # --- identifiants / mots-clés ---
        if c.isalpha() or c == "_":
            j = i
            while j < n and (src[j].isalnum() or src[j] == "_"):
                j += 1
            word = src[i:j]
            kind = word if word in KEYWORDS else "IDENT"
            tokens.append(Token(kind, word, start_line, start_column, start_column + len(word)))
            column += len(word)
            i = j
            continue

        # --- tokens à trois caractères : ... ---
        if src[i:i + 3] in THREE_CHAR_TOKENS:
            three = src[i:i + 3]
            tokens.append(Token(three, three, start_line, start_column, start_column + 3))
            i += 3
            column += 3
            continue

        # --- opérateurs à deux caractères : == != <= >= && || ---
        if src[i:i + 2] in TWO_CHAR_TOKENS:
            two = src[i:i + 2]
            tokens.append(Token(two, two, start_line, start_column, start_column + 2))
            i += 2
            column += 2
            continue

        # --- ponctuation simple (dont '@' pour les attributs, '=' pour
        #     l'initialisation des variables) ---
        if c in SINGLE_CHAR_TOKENS:
            tokens.append(Token(c, c, start_line, start_column, start_column + 1))
            i += 1
            column += 1
            continue

        err = LexError(f"unexpected character {c!r} (line {line})")
        err._jaguar_line = start_line; err._jaguar_column = start_column; err._jaguar_end_column = start_column + 1
        raise err

    tokens.append(Token("EOF", "", line, column, column))
    return tokens


# =========================================================================
# 2. AST
# =========================================================================

@dataclass
class Param:
    type: str
    name: str
    is_const: bool = False
    default: Optional[object] = None
    pointee_const: bool = False


@dataclass
class Field:
    type: str
    name: str


@dataclass
class ClassField:
    type: str
    name: str
    access: str = "private"
    init: Optional[object] = None
    is_const: bool = False
    is_exposed: bool = False
    pointee_const: bool = False


@dataclass
class ClassMethod:
    ret_type: str
    name: str
    params: List[Param]
    body: object
    access: str = "private"
    is_virtual: bool = False
    is_override: bool = False
    is_constructor: bool = False
    is_destructor: bool = False
    is_const: bool = False
    mangled_name: Optional[str] = None


@dataclass
class ClassDecl:
    name: str
    base: Optional[str]
    fields: List[ClassField]
    methods: List[ClassMethod]
    is_registered: bool = False
    namespace: Optional[str] = None
    # Class-level signal handlers. These are declarations in the class body,
    # not statements inside a member function.
    signals: List["VariableChangeHandler"] = field(default_factory=list)


# --- expressions ---
@dataclass
class Ident:
    name: str


@dataclass
class NamespacedIdent:
    namespace: str
    name: str


@dataclass
class IntLit:
    value: str


@dataclass
class FloatLit:
    value: str


@dataclass
class StringLit:
    value: str


@dataclass
class BoolLit:
    value: bool


@dataclass
class NullPtrLit:
    pass


@dataclass
class CastExpr:
    target_type: str
    operand: object


@dataclass
class UnaryOp:
    op: str
    operand: object


@dataclass
class BinOp:
    op: str
    left: object
    right: object


@dataclass
class IndexAccess:
    obj: object
    index: object


@dataclass
class NewExpr:
    type: str
    args: list


@dataclass
class ListLiteral:
    items: list


@dataclass
class MemberAccess:
    obj: object
    name: str


@dataclass
class NamedArg:
    name: str
    expr: object


@dataclass
class Call:
    callee: object   # Ident, NamespacedIdent ou MemberAccess
    args: list


# --- instructions ---
@dataclass
class ReturnStmt:
    expr: Optional[object]


@dataclass
class ExprStmt:
    expr: object


@dataclass
class VarDecl:
    """Variable declaration with separate constness for the variable and pointee."""
    type: str
    name: str
    init: Optional[object] = None
    is_const: bool = False
    pointee_const: bool = False
    is_extern: bool = False
    namespace: Optional[str] = None


@dataclass
class AssignStmt:
    """Affectation d'une variable : `nom = expr;`."""
    name: str
    expr: object


@dataclass
class PointerAssignStmt:
    """Affectation through a pointer/dereference expression."""
    target: object
    expr: object


@dataclass
class VariableChangeHandler:
    name: str
    body: object


@dataclass
class DecoratorUse:
    name: str
    args: list


@dataclass
class MemberAssignStmt:
    target: MemberAccess
    expr: object


@dataclass
class Block:
    statements: list


@dataclass
class DecoratorDecl:
    name: str
    params: List[Param]
    body: Block
    namespace: Optional[str] = None


@dataclass
class IfStmt:
    """if (cond) { ... } [else if (...) { ... }]* [else { ... }]
    else_branch est soit un Block (else), soit un IfStmt (else if)."""
    cond: object
    then_block: Block
    else_branch: Optional[object] = None


@dataclass
class WhileStmt:
    """Classic conditional while loop: `while (condition) { ... }`."""
    cond: object
    body: Block


@dataclass
class LoopStmt:
    """Unconditional loop: `loop { ... }`."""
    body: Block


@dataclass
class ForwardDecl:
    kind: str   # class / struct
    name: str


@dataclass
class TypeAliasDecl:
    name: str
    target: str


@dataclass
class UsingNamespaceDecl:
    namespace: str


@dataclass
class UsingSymbolDecl:
    namespace: str
    name: str
    alias: str


@dataclass
class UsingImportDecl:
    name: str


@dataclass
class EnumDecl:
    name: str
    values: List[str]
    namespace: Optional[str] = None
    initializers: Optional[Dict[str, object]] = None


@dataclass
class UsingNamespaceStmt:
    namespace: str


@dataclass
class UsingSymbolStmt:
    namespace: str
    name: str
    alias: str


@dataclass
class TypeAliasStmt:
    name: str
    target: str


@dataclass
class ForLoopStmt:
    """int i = for_loop(début, fin) { ... } -- i parcourt début..fin,
    fin COMPRISE."""
    var_type: str
    var_name: str
    start: object
    end: object
    body: Block


@dataclass
class CollectionLoopStmt:
    kind: str
    var_name: str
    collection: object
    body: Block


@dataclass
class BreakStmt:
    pass


@dataclass
class ContinueStmt:
    pass


# --- déclarations de haut niveau ---
@dataclass
class FunctionDecl:
    ret_type: str
    name: str
    params: List[Param]
    body: Block
    namespace: Optional[str] = None
    is_extern: bool = False
    is_const: bool = False
    is_prototype: bool = False
    # rempli par le Resolver (nom final choisi pour le C généré)
    mangled_name: Optional[str] = None
    is_variadic: bool = False
    decorators: List[DecoratorUse] = field(default_factory=list)
    implementation_name: Optional[str] = None


@dataclass
class StructDecl:
    name: str
    fields: List[Field]
    namespace: Optional[str] = None


@dataclass
class UnionDecl:
    name: str
    fields: List[Field]
    namespace: Optional[str] = None


@dataclass
class PreprocLine:
    text: str


@dataclass
class TopExprStmt:
    """Appel isolé au niveau global, comme dans l'exemple d'origine
    (`my_namespace:Foo();` hors de toute fonction)."""
    expr: object


@dataclass
class Program:
    items: list


def _iter_stmts(stmts):
    """Parcourt récursivement toutes les instructions, y compris celles
    des blocs imbriqués (if / else / while / for_loop)."""
    for s in stmts:
        yield s
        if isinstance(s, IfStmt):
            yield from _iter_stmts(s.then_block.statements)
            if isinstance(s.else_branch, IfStmt):
                yield from _iter_stmts([s.else_branch])
            elif isinstance(s.else_branch, Block):
                yield from _iter_stmts(s.else_branch.statements)
        elif isinstance(s, (WhileStmt, LoopStmt, ForLoopStmt, CollectionLoopStmt)):
            yield from _iter_stmts(s.body.statements)
        elif isinstance(s, VariableChangeHandler):
            yield from _iter_stmts(s.body.statements)


# =========================================================================
# 3. PARSER (analyse récursive descendante)
# =========================================================================

class ParseError(Exception):
    pass


KNOWN_ATTRIBUTES = {"extern", "register", "exposed"}


class Parser:
    def __init__(self, tokens: List[Token]):
        self.tokens = tokens
        self.pos = 0
        self._last_type_span = None

    @staticmethod
    def _mark_line(node, line, column=None, end_column=None):
        try:
            setattr(node, "_jaguar_line", line)
            if column is not None:
                setattr(node, "_jaguar_column", column)
            if end_column is not None:
                setattr(node, "_jaguar_end_column", end_column)
        except Exception:
            pass
        return node

    @staticmethod
    def _mark_token(node, token):
        return Parser._mark_line(node, token.line, token.column, token.end_column)

    # -- utilitaires --
    def peek(self, offset: int = 0) -> Token:
        idx = self.pos + offset
        if idx >= len(self.tokens):
            return self.tokens[-1]
        return self.tokens[idx]

    def advance(self) -> Token:
        tok = self.tokens[self.pos]
        if self.pos < len(self.tokens) - 1:
            self.pos += 1
        return tok

    def expect(self, kind: str) -> Token:
        tok = self.peek()
        if tok.kind != kind:
            err = ParseError(
                f"expected '{kind}' but found '{tok.kind}' ({tok.value!r}) on line {tok.line}"
            )
            err._jaguar_line = tok.line
            err._jaguar_column = tok.column
            err._jaguar_end_column = tok.end_column if tok.end_column > tok.column else tok.column + 1
            raise err
        return self.advance()

    def _parse_error(self, message: str, tok: Token | None = None):
        tok = tok or self.peek()
        err = ParseError(message)
        err._jaguar_line = tok.line
        err._jaguar_column = tok.column
        err._jaguar_end_column = tok.end_column if tok.end_column > tok.column else tok.column + 1
        raise err

    # -- programme --
    def parse_program(self) -> Program:
        items = []
        while self.peek().kind != "EOF":
            result = self.parse_toplevel()
            if isinstance(result, list):
                items.extend(result)
            else:
                items.append(result)
        return Program(items)

    def parse_toplevel(self):
        tok = self.peek()

        if tok.kind == "PREPROC":
            self.advance()
            return PreprocLine(tok.value)

        if tok.kind == "using":
            self.advance()
            if self.peek().kind == "namespace":
                self.advance()
                parts = [self.expect("IDENT").value]
                while self.peek().kind == ":":
                    self.advance(); parts.append(self.expect("IDENT").value)
                self.expect(";")
                return self._mark_token(UsingNamespaceDecl(":".join(parts)), tok)
            first = self.expect("IDENT").value
            if self.peek().kind == ":":
                parts = [first]
                while self.peek().kind == ":":
                    self.advance(); parts.append(self.expect("IDENT").value)
                namespace = ":".join(parts[:-1]); symbol = parts[-1]
                alias = symbol
                if self.peek().kind == "as":
                    self.advance(); alias = self.expect("IDENT").value
                self.expect(";")
                return self._mark_token(UsingSymbolDecl(namespace, symbol, alias), tok)
            if self.peek().kind == ";":
                self.advance()
                return UsingImportDecl(first)
            self.expect("=")
            target = self.parse_type()
            target_span = self._last_type_span
            self.expect(";")
            node = self._mark_token(TypeAliasDecl(first, target), tok)
            if target_span:
                setattr(node, "_jaguar_target_column", target_span[1]); setattr(node, "_jaguar_target_end_column", target_span[2])
            return node

        if tok.kind == "enum":
            return self.parse_enum()

        if tok.kind == "union":
            line = tok.line
            self.advance()
            name_tok = self.expect("IDENT")
            if self.peek().kind == ";":
                self.advance()
                return self._mark_line(ForwardDecl("union", name_tok.value), line)
            self.pos -= 2
            return self.parse_union()

        if tok.kind == "struct":
            line = tok.line
            self.advance()
            name_tok = self.expect("IDENT")
            if self.peek().kind == ";":
                self.advance()
                return self._mark_line(ForwardDecl("struct", name_tok.value), line)
            self.pos -= 2
            return self.parse_struct()

        if tok.kind == "class":
            line = tok.line
            self.advance()
            name_tok = self.expect("IDENT")
            if self.peek().kind == ";":
                self.advance()
                return self._mark_line(ForwardDecl("class", name_tok.value), line)
            self.pos -= 2
            return self.parse_class()

        if tok.kind == "namespace":
            return self.parse_namespace()

        if tok.kind == "@":
            if self._is_decorator_use_ahead():
                uses = self.parse_decorator_uses()
                return self.parse_function(decorator_uses=uses)
            save = self.pos
            attrs = self.parse_attributes()
            if self.peek().kind == "class":
                return self.parse_class(attrs)
            if self._is_function_ahead():
                self.pos = save
                return self.parse_function()
            # @extern is also valid on a file-scope variable. This is needed
            # by BindGen for C API globals, including function-pointer globals.
            if attrs <= {"extern"} and (self.peek().kind in TYPE_KEYWORDS or self.peek().kind in ("IDENT", "const")):
                return self.parse_var_decl(attrs=attrs)
            self.pos = save
            self._parse_error(
                f"attributes (@...) can only be applied to functions, classes, or global variables (line {tok.line})", tok
            )

        if (tok.kind in TYPE_KEYWORDS or tok.kind == "IDENT") and self._is_decorator_decl_ahead():
            return self.parse_decorator_decl()

        if tok.kind in TYPE_KEYWORDS or tok.kind in ("const", "IDENT"):
            # Un IDENT suivi de ':' ou '(' est un appel isolé au niveau
            # global (cf. `my_namespace:Foo();`), pas une déclaration.
            if tok.kind == "IDENT" and self.peek(1).kind in (":", "(") and not (tok.kind == "IDENT" and self.peek(1).kind == ":" and self._starts_var_decl()):
                expr = self.parse_expr()
                self.expect(";")
                return TopExprStmt(expr)
            # `type nom (` -> fonction ; sinon `type nom [= expr] ;`
            # -> variable globale.
            if self._is_function_ahead():
                return self.parse_function()
            return self.parse_var_decl()

        self._parse_error(f"unexpected top-level declaration: '{tok.kind}' on line {tok.line}", tok)

    def _is_function_ahead(self) -> bool:
        """Detect a function declaration, including pointer return types."""
        i = 0
        while self.peek(i).kind == "@":
            if self.peek(i + 2).kind == "(":
                break
            i += 2
        if self.peek(i).kind == "const":
            i += 1
        # base type
        if self.peek(i).kind not in TYPE_KEYWORDS and self.peek(i).kind != "IDENT":
            return False
        i += 1
        # generic type arguments (only needed for lookahead)
        if self.peek(i).kind == "<":
            depth = 0
            while True:
                k = self.peek(i).kind
                if k == "EOF": return False
                if k == "<": depth += 1
                elif k == ">":
                    depth -= 1
                    if depth == 0:
                        i += 1
                        break
                i += 1
        while self.peek(i).kind == "*":
            i += 1
        if (self.peek(i).kind == "operator" or (self.peek(i).kind == "IDENT" and self.peek(i).value == "operator")):
            return self.peek(i + 1).kind in _OPERATOR_FUNCTION_TOKENS and self.peek(i + 2).kind == "("
        return self.peek(i).kind == "IDENT" and self.peek(i + 1).kind == "("

    def _is_decorator_use_ahead(self) -> bool:
        return self.peek().kind == "@" and self.peek(1).kind == "IDENT" and self.peek(2).kind == "("

    def parse_decorator_uses(self):
        uses = []
        while self._is_decorator_use_ahead():
            at = self.advance()
            name = self.advance().value
            self.expect("(")
            args = []
            if self.peek().kind != ")":
                args.append(self.parse_expr())
                while self.peek().kind == ",":
                    self.advance(); args.append(self.parse_expr())
            self.expect(")")
            uses.append(self._mark_token(DecoratorUse(name, args), at))
        return uses

    def _is_decorator_decl_ahead(self) -> bool:
        i = 1 if self.peek().kind == "const" else 0
        return (self.peek(i).kind in TYPE_KEYWORDS or self.peek(i).kind == "IDENT") and self.peek(i+1).kind == "@" and self.peek(i+2).kind == "IDENT" and self.peek(i+3).kind == "("

    def parse_decorator_decl(self, namespace: Optional[str] = None):
        tok = self.peek()
        prefix_const = self.peek().kind == "const"
        if prefix_const: self.advance()
        ret = self.parse_type()
        if prefix_const or ret != "void": self._parse_error("decorator declarations must use return type 'void'", tok)
        self.expect("@")
        name_tok = self.expect("IDENT")
        self.expect("(")
        params=[]
        if self.peek().kind != ")":
            params.append(self.parse_param())
            while self.peek().kind == ",":
                self.advance(); params.append(self.parse_param())
        self.expect(")"); self.expect(":")
        func_tok=self.expect("IDENT")
        if func_tok.value != "func": self._parse_error("a decorator declaration must use ':func'", func_tok)
        body=self.parse_block()
        return self._mark_token(DecoratorDecl(name_tok.value, params, body, namespace), tok)

    # -- attributs (@extern, ...) --
    def parse_attributes(self) -> set:
        attrs = set()
        while self.peek().kind == "@":
            self.advance()
            name_tok = self.expect("IDENT")
            if name_tok.value not in KNOWN_ATTRIBUTES:
                err = ParseError(f"unknown attribute '@{name_tok.value}' (line {name_tok.line})")
                err._jaguar_line = name_tok.line; err._jaguar_column = max(0, name_tok.column - 1); err._jaguar_end_column = name_tok.end_column
                raise err
            self._attribute_line = name_tok.line
            attrs.add(name_tok.value)
        return attrs

    # -- enum --
    def parse_enum(self) -> EnumDecl:
        line = self.peek().line
        self.expect("enum")
        name_tok = self.expect("IDENT")
        name = name_tok.value
        self.expect("{")
        values = []
        initializers = {}
        while self.peek().kind != "}":
            value_tok = self.expect("IDENT")
            value_name = value_tok.value
            values.append(value_name)
            if self.peek().kind == "=":
                self.advance()
                initializers[value_name] = self.parse_expr()
            if self.peek().kind == ",":
                self.advance()
                if self.peek().kind == "}":
                    break
            elif self.peek().kind != "}":
                self._parse_error(f"expected ',' or '}}' after enum value (line {self.peek().line})", self.peek())
        self.expect("}")
        if self.peek().kind == ";": self.advance()
        node = self._mark_line(EnumDecl(name, values, None, initializers), line)
        setattr(node, "_jaguar_name_column", name_tok.column); setattr(node, "_jaguar_name_end_column", name_tok.end_column)
        return node

    # -- struct --
    def parse_struct(self, namespace: Optional[str] = None) -> StructDecl:
        self.expect("struct")
        name_tok = self.expect("IDENT")
        name = name_tok.value
        self.expect("{")
        fields = []
        while self.peek().kind != "}":
            t = self.parse_type()
            type_span = self._last_type_span
            n_tok = self.expect("IDENT")
            self.expect(";")
            field = Field(t, n_tok.value)
            if type_span:
                setattr(field, "_jaguar_type_column", type_span[1]); setattr(field, "_jaguar_type_end_column", type_span[2])
            setattr(field, "_jaguar_name_column", n_tok.column); setattr(field, "_jaguar_name_end_column", n_tok.end_column)
            setattr(field, "_jaguar_line", type_span[0] if type_span else n_tok.line)
            fields.append(field)
        self.expect("}")
        if self.peek().kind == ";":
            self.advance()
        qname = f"{namespace.replace(':', '_')}_{name}" if namespace else name
        node = StructDecl(qname, fields, namespace)
        setattr(node, "_jaguar_name_column", name_tok.column); setattr(node, "_jaguar_name_end_column", name_tok.end_column)
        return node

    # -- union -------------------------------------------------------------
    def parse_union(self, namespace: Optional[str] = None) -> UnionDecl:
        self.expect("union")
        name_tok = self.expect("IDENT")
        name = name_tok.value
        self.expect("{")
        fields = []
        while self.peek().kind != "}":
            t = self.parse_type()
            type_span = self._last_type_span
            n_tok = self.expect("IDENT")
            self.expect(";")
            field = Field(t, n_tok.value)
            if type_span:
                setattr(field, "_jaguar_type_column", type_span[1]); setattr(field, "_jaguar_type_end_column", type_span[2])
            setattr(field, "_jaguar_name_column", n_tok.column); setattr(field, "_jaguar_name_end_column", n_tok.end_column)
            setattr(field, "_jaguar_line", type_span[0] if type_span else n_tok.line)
            fields.append(field)
        self.expect("}")
        if self.peek().kind == ";":
            self.advance()
        qname = f"{namespace.replace(':', '_')}_{name}" if namespace else name
        node = UnionDecl(qname, fields, namespace)
        setattr(node, "_jaguar_name_column", name_tok.column); setattr(node, "_jaguar_name_end_column", name_tok.end_column)
        return node

    # -- class -------------------------------------------------------------
    def _parse_class_impl(self, class_attrs=None, namespace: Optional[str] = None) -> ClassDecl:
        class_attrs = class_attrs or set()
        self.expect("class")
        name_tok = self.expect("IDENT")
        name = name_tok.value
        base = None
        base_span = None
        if self.peek().kind == ",":
            self.advance()
            base_tok = self.expect("IDENT")
            base = base_tok.value
            base_span = (base_tok.line, base_tok.column, base_tok.end_column)
        self.expect("{")
        fields, methods, signals = [], [], []
        while self.peek().kind != "}":
            # A class-level signal is declared directly in the class body:
            # `signal: value { ... }`. It is intentionally distinct from the
            # existing function-local signal statement.
            if self.peek().kind == "signal":
                signal_tok = self.advance()
                self.expect(":")
                name_tok = self.expect("IDENT")
                if self.peek().kind == ":":
                    self._parse_error("class-level signal expects a member name, not a qualified name", self.peek())
                body = self.parse_block()
                signal = self._mark_token(VariableChangeHandler(name_tok.value, body), signal_tok)
                setattr(signal, "_jaguar_name_column", name_tok.column)
                setattr(signal, "_jaguar_name_end_column", name_tok.end_column)
                signals.append(signal)
                continue

            exposed = False
            if self.peek().kind == "@":
                attrs = self.parse_attributes()
                if attrs - {"exposed"}:
                    self._parse_error(f"invalid attributes on a class member (line {self.peek().line})", self.peek())
                exposed = "exposed" in attrs
            access = "private"
            if self.peek().kind in ("$", "%"):
                access = "public" if self.advance().kind == "$" else "protected"

            is_virtual = False
            if self.peek().kind == "virtual":
                self.advance(); is_virtual = True

            # constructors/destructors are always public
            if self.peek().kind in ("constr", "destr"):
                member_tok = self.peek()
                kind = self.advance().kind
                self.expect("("); params=[]
                if self.peek().kind != ")":
                    params.append(self.parse_param())
                    while self.peek().kind == ",":
                        self.advance(); params.append(self.parse_param())
                self.expect(")")
                if kind == "destr" and params:
                    self._parse_error("destructor 'destr' cannot take parameters", member_tok)
                body = self.parse_block()
                method_node = ClassMethod("void", kind, params, body, "public", False, False, kind=="constr", kind=="destr")
                methods.append(self._mark_token(method_node, member_tok))
                continue

            # Support both `void $foo()` et `void$ foo()` forms.
            field_const = False
            field_pointee_const = False
            if self.peek().kind == "const":
                self.advance(); field_const = True
            ret_type = self.parse_type()
            ret_type_span = self._last_type_span
            if field_const and ret_type.endswith("*"):
                field_const = False; field_pointee_const = True
            if self.peek().kind == "const":
                self.advance()
                if not ret_type.endswith("*"):
                    self._parse_error("'const' after a non-pointer field type is not valid", self.peek())
                field_const = True
            if self.peek().kind in ("$", "%"):
                access = "public" if self.advance().kind == "$" else "protected"
            member_tok = self.peek()
            member_name = self.expect("IDENT").value
            if self.peek().kind == "(":
                self.advance(); params=[]
                if self.peek().kind != ")":
                    params.append(self.parse_param())
                    while self.peek().kind == ",":
                        self.advance(); params.append(self.parse_param())
                self.expect(")")
                is_override = False
                if self.peek().kind == "override":
                    self.advance(); is_override = True
                method_const = False
                if self.peek().kind == "const":
                    self.advance(); method_const = True
                body = self.parse_block()
                if exposed and access != "public":
                    # @exposed is only valid for public class members.
                    self._parse_error(
                        f"an @exposed method must be public (line {self._attribute_line if hasattr(self, '_attribute_line') else self.peek().line})", member_tok
                    )
                method_node = ClassMethod(ret_type, member_name, params, body, access, is_virtual, is_override, False, False, method_const)
                self._mark_token(method_node, member_tok)
                if ret_type_span:
                    setattr(method_node, "_jaguar_type_column", ret_type_span[1]); setattr(method_node, "_jaguar_type_end_column", ret_type_span[2])
                setattr(method_node, "_jaguar_name_column", member_tok.column); setattr(method_node, "_jaguar_name_end_column", member_tok.end_column)
                methods.append(method_node)
            else:
                init=None
                if self.peek().kind == "=":
                    self.advance(); init=self.parse_expr()
                self.expect(";")
                if is_virtual:
                    self._parse_error(f"'virtual' can only be applied to a method (line {self.peek().line})", member_tok)
                if exposed and access != "public":
                    self._parse_error(
                        f"an @exposed variable must be public (line {self.peek().line})", member_tok
                    )
                field_node = ClassField(ret_type, member_name, access, init, field_const, exposed, field_pointee_const)
                self._mark_token(field_node, member_tok)
                if ret_type_span:
                    setattr(field_node, "_jaguar_type_column", ret_type_span[1]); setattr(field_node, "_jaguar_type_end_column", ret_type_span[2])
                setattr(field_node, "_jaguar_name_column", member_tok.column); setattr(field_node, "_jaguar_name_end_column", member_tok.end_column)
                fields.append(field_node)
        self.expect("}")
        if self.peek().kind == ";":
            self.advance()
        qname = f"{namespace.replace(':', '_')}_{name}" if namespace else name
        node = ClassDecl(qname, base, fields, methods, "register" in class_attrs, namespace, signals)
        setattr(node, "_jaguar_name_column", name_tok.column); setattr(node, "_jaguar_name_end_column", name_tok.end_column)
        if base_span:
            setattr(node, "_jaguar_base_column", base_span[1]); setattr(node, "_jaguar_base_end_column", base_span[2])
        return node

    def parse_class(self, class_attrs=None, namespace: Optional[str] = None) -> ClassDecl:
        tok = self.peek()
        node = self._parse_class_impl(class_attrs, namespace)
        return self._mark_token(node, tok)

    # -- namespace ---------------------------------------------------------
    # Namespaces are stored as a path such as "physics:common".
    def parse_namespace(self, parent_namespace: Optional[str] = None):
        self.expect("namespace")
        name = self.expect("IDENT").value
        namespace = f"{parent_namespace}:{name}" if parent_namespace else name
        self.expect("{")
        items = []
        while self.peek().kind != "}":
            tok = self.peek()
            if tok.kind == "enum":
                enum = self.parse_enum()
                enum.namespace = namespace
                items.append(enum)
            elif tok.kind == "struct":
                items.append(self.parse_struct(namespace=namespace))
            elif tok.kind == "union":
                items.append(self.parse_union(namespace=namespace))
            elif tok.kind == "class":
                items.append(self.parse_class(namespace=namespace))
            elif tok.kind == "namespace":
                items.extend(self.parse_namespace(namespace))
            elif (tok.kind in TYPE_KEYWORDS or tok.kind == "IDENT") and self._is_decorator_decl_ahead():
                items.append(self.parse_decorator_decl(namespace=namespace))
            elif tok.kind == "@":
                if self._is_decorator_use_ahead():
                    uses = self.parse_decorator_uses()
                    items.append(self.parse_function(namespace=namespace, decorator_uses=uses))
                    continue
                save = self.pos
                attrs = self.parse_attributes()
                if self.peek().kind == "class":
                    items.append(self.parse_class(attrs, namespace=namespace))
                elif self._is_function_ahead():
                    self.pos = save
                    items.append(self.parse_function(namespace=namespace))
                elif attrs <= {"extern"} and (self.peek().kind in TYPE_KEYWORDS or self.peek().kind in ("IDENT", "const")):
                    items.append(self.parse_var_decl(attrs=attrs, namespace=namespace))
                else:
                    self.pos = save
                    self._parse_error(f"invalid namespace declaration on line {tok.line}", tok)
            elif tok.kind in TYPE_KEYWORDS or tok.kind == "IDENT" or tok.kind == "const":
                if self._is_function_ahead():
                    items.append(self.parse_function(namespace=namespace))
                else:
                    items.append(self.parse_var_decl(namespace=namespace))
            else:
                self._parse_error(
                    f"unexpected namespace element: '{tok.kind}' on line {tok.line}", tok
                )
        self.expect("}")
        return items

    # -- fonction --
    def parse_type(self) -> str:
        tok = self.peek()
        start_tok = tok
        # Function-pointer type: `fn(T1, T2) -> R`.
        if tok.kind == "IDENT" and tok.value == "fn":
            self.advance()
            self.expect("(")
            params = []
            variadic = False
            if self.peek().kind != ")":
                params.append(self.parse_type())
                while self.peek().kind == ",":
                    self.advance()
                    if self.peek().kind == "...":
                        self.advance(); variadic = True; break
                    params.append(self.parse_type())
            self.expect(")")
            self.expect("->")
            ret = self.parse_type()
            if variadic:
                params.append("...")
            result = f"fn({', '.join(params)}) -> {ret}"
            last = self.tokens[self.pos - 1] if self.pos else start_tok
            self._last_type_span = (start_tok.line, start_tok.column, last.end_column or last.column + 1)
            return result
        if tok.kind in TYPE_KEYWORDS or tok.kind == "IDENT":
            self.advance()
            base = canonical_type(tok.value)
            if self.peek().kind == ":":
                parts = [tok.value]
                while self.peek().kind == ":":
                    self.advance()
                    parts.append(self.expect("IDENT").value)
                base = ":".join(parts)
            if self.peek().kind == "<":
                self.advance()
                first = self.parse_type()
                if self.peek().kind == ",":
                    self.advance()
                    second = self.parse_type()
                    self.expect(">")
                    if base not in ("map", "pair"):
                        self._parse_error(f"generic type '{base}' accepts only one parameter", tok)
                    base = f"{base}<{first},{second}>"
                else:
                    self.expect(">")
                    if base not in ("list", "container"):
                        self._parse_error(f"generic type '{base}' expects two parameters" if base in ("map", "pair") else f"unknown generic type '{base}' (line {tok.line})", tok)
                    base = f"{base}<{first}>"
            pointers = 0
            while self.peek().kind == "*":
                self.advance(); pointers += 1
            dims = []
            while self.peek().kind == "[":
                self.advance()
                dim = self.expect("INT")
                self.expect("]")
                if pointers:
                    self._parse_error("fixed arrays of pointers are not supported yet", dim)
                dims.append(dim.value)
            result = base + "*" * pointers + "".join(f"[{d}]" for d in dims)
            last = self.tokens[self.pos - 1] if self.pos else start_tok
            self._last_type_span = (start_tok.line, start_tok.column, last.end_column or last.column + 1)
            return result
        self._parse_error(f"expected a type, found '{tok.kind}' on line {tok.line}", tok)

    def parse_param(self) -> Param:
        leading_const = False
        if self.peek().kind == "const":
            self.advance(); leading_const = True
        t = self.parse_type()
        type_span = self._last_type_span
        pointee_const = leading_const and t.endswith("*")
        is_const = leading_const and not pointee_const
        if self.peek().kind == "const":
            self.advance();
            if not t.endswith("*"):
                self._parse_error("'const' after a non-pointer parameter type is not valid", self.peek())
            is_const = True
        n = self.expect("IDENT")
        default = None
        if self.peek().kind == "=":
            self.advance()
            default = self.parse_expr()
        param = Param(t, n.value, is_const, default, pointee_const)
        if type_span:
            setattr(param, "_jaguar_line", type_span[0])
            setattr(param, "_jaguar_type_column", type_span[1]); setattr(param, "_jaguar_type_end_column", type_span[2])
        else:
            setattr(param, "_jaguar_line", n.line)
        setattr(param, "_jaguar_name_column", n.column); setattr(param, "_jaguar_name_end_column", n.end_column)
        return param

    def _parse_function_impl(self, namespace: Optional[str] = None, decorator_uses=None) -> FunctionDecl:
        attrs = self.parse_attributes()
        is_extern = "extern" in attrs

        prefix_const = False
        if self.peek().kind == "const":
            self.advance(); prefix_const = True
        ret_type = self.parse_type()
        ret_type_span = self._last_type_span
        if (self.peek().kind == "operator" or (self.peek().kind == "IDENT" and self.peek().value == "operator")):
            self.advance()
            op_tok = self.peek()
            if op_tok.kind not in _OPERATOR_FUNCTION_TOKENS:
                self._parse_error("expected an operator token after 'operator'", op_tok)
            self.advance()
            name_tok = op_tok
            function_name = "operator" + op_tok.value
        else:
            name_tok = self.expect("IDENT")
            function_name = name_tok.value
        self.expect("(")
        params = []
        is_variadic = False
        if self.peek().kind != ")":
            params.append(self.parse_param())
            while self.peek().kind == ",":
                self.advance()
                if self.peek().kind == "...":
                    self.advance(); is_variadic = True; break
                params.append(self.parse_param())
        self.expect(")")
        suffix_const = False
        if self.peek().kind == "const":
            self.advance(); suffix_const = True

        # Prototype : `int add(int a, int b);`
        # Il n'a pas de corps Jaguar et sera émis comme une déclaration C.
        if self.peek().kind == ";":
            self.advance()
            node = FunctionDecl(
                ret_type, function_name, params, Block([]), namespace,
                is_extern, prefix_const or suffix_const, True, None, is_variadic, list(decorator_uses or []), None
            )
        else:
            body = self.parse_block()
            node = FunctionDecl(ret_type, function_name, params, body, namespace, is_extern, prefix_const or suffix_const, False, None, is_variadic, list(decorator_uses or []), None)
        if ret_type_span:
            setattr(node, "_jaguar_type_column", ret_type_span[1]); setattr(node, "_jaguar_type_end_column", ret_type_span[2])
        setattr(node, "_jaguar_name_column", name_tok.column); setattr(node, "_jaguar_name_end_column", name_tok.end_column)
        return node

    def parse_function(self, namespace: Optional[str] = None, decorator_uses=None) -> FunctionDecl:
        tok = self.peek()
        node = self._parse_function_impl(namespace, decorator_uses)
        self._mark_token(node, tok)
        # `_parse_function_impl` stores the return-type span/name span on the
        # declaration so semantic diagnostics can highlight the exact symbol.
        return node

    # -- bloc / instructions --
    def parse_block(self) -> Block:
        self.expect("{")
        stmts = []
        while self.peek().kind != "}":
            stmts.append(self.parse_statement())
        self.expect("}")
        return Block(stmts)

    def _starts_var_decl(self) -> bool:
        """Détecte les déclarations typées, `const type nom` et `auto nom`."""
        tok = self.peek()
        if tok.kind in ("const", "auto"):
            return True
        if tok.kind in TYPE_KEYWORDS:
            return True
        if tok.kind == "IDENT" and self.peek(1).kind == "<":
            return True
        if tok.kind == "IDENT" and self.peek(1).kind == "*":
            return True
        if tok.kind == "IDENT" and self.peek(1).kind == ":":
            i = 1
            while self.peek(i).kind == ":":
                if self.peek(i + 1).kind != "IDENT":
                    return False
                i += 2
            # Qualified custom types may be followed by pointer stars, e.g.
            # `namespace:Class* value`.
            while self.peek(i).kind == "*":
                i += 1
            return self.peek(i).kind == "IDENT"
        return tok.kind == "IDENT" and self.peek(1).kind == "IDENT"

    def _parse_var_decl_impl(self, attrs=None, namespace: Optional[str] = None) -> VarDecl:
        type_tok = self.peek()
        leading_const = False
        if self.peek().kind == "const":
            self.advance(); leading_const = True
        is_const = False
        pointee_const = False
        type_span = None
        is_auto = self.peek().kind == "auto"
        if is_auto:
            self.advance(); t = "auto"
            if leading_const: is_const = True
        else:
            t = self.parse_type()
            type_span = self._last_type_span
            if t == "void":
                self._parse_error(f"a variable cannot have type 'void' (line {type_tok.line})", type_tok)
            if leading_const and t.endswith("*"):
                pointee_const = True
            else:
                is_const = leading_const
        if self.peek().kind == "const":
            self.advance()
            if not t.endswith("*"):
                self._parse_error("'const' after a non-pointer variable type is not valid", self.peek())
            is_const = True
        name_tok = self.expect("IDENT")
        name = name_tok.value
        init = None
        if self.peek().kind == "=":
            self.advance(); init = self.parse_expr()
        elif self.peek().kind == "=>":
            self.advance()
            value = self.parse_expr()
            # `T* p => value` is Jaguar's safe allocation shorthand:
            # allocate one T and initialize it. It is intentionally not an
            # alias for assigning an arbitrary integer/null pointer.
            if t.endswith("*"):
                init = NewExpr(t.rstrip("*"), [value])
            elif t.startswith("container<") and t.endswith(">"):
                inner = t[len("container<"):-1]
                init = NewExpr(inner, [value])
            else:
                init = value
        self.expect(";")
        if (is_auto or is_const) and init is None:
            self._parse_error(f"a variable '{'auto' if is_auto else 'const'}' '{name}' must be initialized (line {type_tok.line})", type_tok)
        attrs = attrs or set()
        qname = f"{namespace.replace(':', '_')}_{name}" if namespace else name
        node = VarDecl(t, qname, init, is_const, pointee_const, "extern" in attrs, namespace)
        if type_span:
            setattr(node, "_jaguar_type_column", type_span[1]); setattr(node, "_jaguar_type_end_column", type_span[2])
        setattr(node, "_jaguar_name_column", name_tok.column); setattr(node, "_jaguar_name_end_column", name_tok.end_column)
        return node

    def parse_var_decl(self, attrs=None, namespace: Optional[str] = None) -> VarDecl:
        tok = self.peek()
        node = self._parse_var_decl_impl(attrs, namespace)
        return self._mark_token(node, tok)

    # -- contrôle de flux -------------------------------------------------
    def parse_if(self) -> IfStmt:
        """if (cond) { ... } [else if (cond) { ... }]* [else { ... }]
        Les accolades sont obligatoires (pas de corps sur une instruction
        seule), ce qui supprime toute ambiguïté de "else pendant"."""
        self.expect("if")
        self.expect("(")
        cond = self.parse_expr()
        self.expect(")")
        then_block = self.parse_block()
        else_branch = None
        if self.peek().kind == "else":
            self.advance()
            if self.peek().kind == "if":
                else_branch = self.parse_if()      # else if -> IfStmt imbriqué
            else:
                else_branch = self.parse_block()
        return IfStmt(cond, then_block, else_branch)

    def parse_while(self) -> WhileStmt:
        tok = self.expect("while")
        self.expect("(")
        cond = self.parse_expr()
        self.expect(")")
        return WhileStmt(cond, self.parse_block())

    def parse_loop(self) -> LoopStmt:
        self.expect("loop")
        return LoopStmt(self.parse_block())

    def _is_for_loop_ahead(self) -> bool:
        """`type nom = for_loop` : détecté par lookahead, sans consommer."""
        return (
            (self.peek().kind in TYPE_KEYWORDS or self.peek().kind == "IDENT")
            and self.peek(1).kind == "IDENT"
            and self.peek(2).kind == "="
            and self.peek(3).kind == "for_loop"
        )

    def parse_for_loop(self) -> ForLoopStmt:
        """int i = for_loop(début, fin) { ... }   (fin comprise)"""
        type_tok = self.advance()
        if type_tok.kind not in INTEGER_TYPES:
            err = ParseError(
                f"the for_loop variable must have an integer type "
                f"(int, i8..i64, u8..u64), not '{type_tok.value}' (line {type_tok.line})"
            )
            err._jaguar_line = type_tok.line; err._jaguar_column = type_tok.column; err._jaguar_end_column = type_tok.end_column
            raise err
        name = self.expect("IDENT").value
        self.expect("=")
        self.expect("for_loop")
        self.expect("(")
        start = self.parse_expr()
        self.expect(",")
        end = self.parse_expr()
        self.expect(")")
        body = self.parse_block()
        return ForLoopStmt(type_tok.value, name, start, end, body)

    def parse_assignment(self) -> AssignStmt:
        name = self.expect("IDENT").value
        self.expect("=")
        expr = self.parse_expr()
        self.expect(";")
        return AssignStmt(name, expr)

    def _parse_statement_impl(self):
        tok = self.peek()
        if tok.kind == "using":
            line = tok.line
            self.advance()
            if self.peek().kind == "namespace":
                self.advance()
                parts = [self.expect("IDENT").value]
                while self.peek().kind == ":":
                    self.advance(); parts.append(self.expect("IDENT").value)
                self.expect(";")
                return self._mark_line(UsingNamespaceStmt(":".join(parts)), line)
            first = self.expect("IDENT").value
            if self.peek().kind == ":":
                parts = [first]
                while self.peek().kind == ":":
                    self.advance(); parts.append(self.expect("IDENT").value)
                namespace = ":".join(parts[:-1]); symbol = parts[-1]
                alias = symbol
                if self.peek().kind == "as":
                    self.advance(); alias = self.expect("IDENT").value
                self.expect(";")
                return self._mark_line(UsingSymbolStmt(namespace, symbol, alias), line)
            self.expect("=")
            target = self.parse_type()
            self.expect(";")
            return self._mark_line(TypeAliasStmt(first, target), line)
        if tok.kind == "signal":
            self.advance()
            self.expect(":")
            name_tok = self.expect("IDENT")
            if self.peek().kind == ":":
                # Qualified member signals such as `signal: MyClass:field` are
                # deliberately rejected. A member signal is declared from the
                # class method that owns the member, using `signal: field`.
                self._parse_error("signal on a class member is only valid inside the class; use `signal: field`", self.peek())
            body = self.parse_block()
            return self._mark_token(VariableChangeHandler(name_tok.value, body), tok)
        if tok.kind == "return":
            self.advance()
            if self.peek().kind == ";":
                self.advance()
                return ReturnStmt(None)
            expr = self.parse_expr()
            self.expect(";")
            return ReturnStmt(expr)

        if tok.kind == "if":
            return self.parse_if()

        if tok.kind == "while":
            return self.parse_while()

        if tok.kind == "loop":
            return self.parse_loop()

        if tok.kind in ("break", "continue"):
            self.advance()
            self.expect(";")
            return BreakStmt() if tok.kind == "break" else ContinueStmt()

        if self._is_for_loop_ahead():
            return self.parse_for_loop()

        if tok.kind == "auto" and self.peek(1).kind == "IDENT" and self.peek(2).kind == "=" and self.peek(3).kind == "IDENT" and self.peek(3).value in ("loop_list", "loop_map"):
            self.advance()
            name = self.expect("IDENT").value
            self.expect("=")
            kind = self.advance().value
            self.expect("(")
            collection = self.parse_expr()
            self.expect(")")
            body = self.parse_block()
            return CollectionLoopStmt(kind, name, collection, body)

        if tok.kind == "IDENT" and self.peek(1).kind == "<":
            return self.parse_var_decl()

        if tok.kind == "IDENT" and self.peek(1).kind == "=":
            return self.parse_assignment()

        # Unambiguous custom pointer declaration with suffix const:
        # `A* const p = value;`. Without this lookahead, the expression parser
        # starts from `A` and consumes `*` as multiplication before it can see
        # that `const` is a declaration qualifier.
        if (tok.kind == "IDENT"
                and self.peek(1).kind == "*"
                and self.peek(2).kind == "const"
                and self.peek(3).kind == "IDENT"):
            return self.parse_var_decl()

        if tok.kind in ("IDENT", "this", "*"):
            save=self.pos
            lhs=self.parse_expr()
            if self.peek().kind == "=":
                if isinstance(lhs, (MemberAccess, IndexAccess)):
                    self.advance(); rhs=self.parse_expr(); self.expect(";"); return MemberAssignStmt(lhs,rhs)
                if isinstance(lhs, NamespacedIdent):
                    self.advance(); rhs=self.parse_expr(); self.expect(";")
                    return AssignStmt(f"{lhs.namespace.replace(':', '_')}_{lhs.name}", rhs)
                if isinstance(lhs, UnaryOp) and lhs.op == "*":
                    self.advance(); rhs=self.parse_expr(); self.expect(";"); return PointerAssignStmt(lhs, rhs)
                if isinstance(lhs, Call) and isinstance(lhs.callee, MemberAccess) and lhs.callee.name == "GetMember":
                    self.advance(); rhs=self.parse_expr(); self.expect(";")
                    return MemberAssignStmt(lhs, rhs)
                self.pos=save
            self.pos=save

        if self._starts_var_decl():
            return self.parse_var_decl()

        expr = self.parse_expr()
        self.expect(";")
        return ExprStmt(expr)

    def parse_statement(self):
        tok = self.peek()
        node = self._parse_statement_impl()
        return self._mark_token(node, tok)

    # -- expressions --
    # Précédence, de la plus faible à la plus forte (comme en C) :
    #   ||  <  &&  <  == !=  <  < > <= >=  <  + -  <  * / %  <  - ! (unaires)
    def _parse_binary_level(self, ops, next_level):
        left = next_level()
        while self.peek().kind in ops:
            op = self.advance().value
            right = next_level()
            left = BinOp(op, left, right)
        return left

    def parse_call_arg(self):
        if self.peek().kind == "IDENT" and self.peek(1).kind == "=":
            name_tok = self.advance()
            self.advance()
            expr = self.parse_expr()
            node = NamedArg(name_tok.value, expr)
            self._mark_line(node, name_tok.line, name_tok.column, name_tok.end_column)
            setattr(node, "_jaguar_name_column", name_tok.column)
            setattr(node, "_jaguar_name_end_column", name_tok.end_column)
            return node
        return self.parse_expr()

    def parse_expr(self):
        start = self.peek()
        expr = self.parse_or()
        end = self.tokens[self.pos - 1] if self.pos else start
        self._mark_line(expr, start.line, start.column, end.end_column or end.column + 1)
        return expr

    def parse_or(self):
        return self._parse_binary_level(("||",), self.parse_and)

    def parse_and(self):
        return self._parse_binary_level(("&&",), self.parse_equality)

    def parse_equality(self):
        return self._parse_binary_level(("==", "!="), self.parse_relational)

    def parse_relational(self):
        return self._parse_binary_level(("<", ">", "<=", ">="), self.parse_additive)

    def parse_additive(self):
        return self._parse_binary_level(("+", "-"), self.parse_term)

    def parse_term(self):
        return self._parse_binary_level(("*", "/", "%"), self.parse_unary)

    def parse_unary(self):
        if self.peek().kind in ("-", "!", "*", "&"):
            op = self.advance().value
            operand = self.parse_unary()
            return UnaryOp(op, operand)
        return self.parse_primary()

    def parse_primary(self):
        tok = self.peek()

        # Les casts Jaguar sont volontairement C-style uniquement :
        # `(i32)0.0`. La forme fonctionnelle `i32(0.0)` n'est pas un cast.
        if tok.kind == "(" and (self.peek(1).kind in TYPE_KEYWORDS or self.peek(1).kind == "IDENT"):
            j = 2
            while self.peek(j).kind == "*":
                j += 1
            if self.peek(j).kind == ")":
                self.advance()
                type_tok = self.advance()
                target_type = canonical_type(type_tok.value)
                type_start = (type_tok.column, type_tok.end_column)
                while self.peek().kind == "*":
                    star = self.advance(); target_type += "*"; type_start = (type_start[0], star.end_column)
                self.expect(")")
                node = CastExpr(target_type, self.parse_unary())
                setattr(node, "_jaguar_line", type_tok.line)
                setattr(node, "_jaguar_type_column", type_start[0])
                setattr(node, "_jaguar_type_end_column", type_start[1])
                return node

        if tok.kind == "INT": self.advance(); return IntLit(tok.value)
        if tok.kind == "FLOAT": self.advance(); return FloatLit(tok.value)
        if tok.kind == "STRING": self.advance(); return StringLit(tok.value)
        if tok.kind in ("true", "false"): self.advance(); return BoolLit(tok.kind == "true")
        if tok.kind == "nullptr": self.advance(); return NullPtrLit()
        if tok.kind == "(":
            self.advance(); e=self.parse_expr(); self.expect(")"); return e
        if tok.kind == "{":
            self.advance()
            items=[]
            if self.peek().kind != "}":
                items.append(self.parse_expr())
                while self.peek().kind == ",":
                    self.advance(); items.append(self.parse_expr())
            self.expect("}")
            return ListLiteral(items)
        if tok.kind == "new":
            self.advance()
            t = self.parse_type()
            type_span = self._last_type_span
            self.expect("(")
            args=[]
            if self.peek().kind != ")":
                args.append(self.parse_call_arg())
                while self.peek().kind == ",":
                    self.advance(); args.append(self.parse_call_arg())
            self.expect(")")
            node = NewExpr(t,args)
            if type_span:
                setattr(node, "_jaguar_line", type_span[0])
                setattr(node, "_jaguar_type_column", type_span[1])
                setattr(node, "_jaguar_type_end_column", type_span[2])
            return node
        if tok.kind not in ("IDENT", "this"):
            if tok.kind == "for_loop":
                self._parse_error("for_loop can only be used in the form `int i = for_loop(start, end) { ... }`", tok)
            self._parse_error(f"unexpected expression: '{tok.kind}' on line {tok.line}", tok)

        self.advance()
        expr = Ident(tok.value)
        if self.peek().kind == ":":
            parts=[tok.value]
            while self.peek().kind == ":":
                self.advance(); parts.append(self.expect("IDENT").value)
            expr=NamespacedIdent(":".join(parts[:-1]), parts[-1])

        while True:
            if self.peek().kind in (".", "->"):
                self.advance()
                name_tok = self.expect("IDENT")
                member = MemberAccess(expr, name_tok.value)
                setattr(member, "_jaguar_member_column", name_tok.column)
                setattr(member, "_jaguar_member_end_column", name_tok.end_column)
                expr = member
                continue
            if self.peek().kind == "[":
                self.advance(); idx=self.parse_expr(); self.expect("]")
                access = IndexAccess(expr, idx)
                expr = access
                continue
            if self.peek().kind == "(":
                self.advance(); args=[]
                if self.peek().kind != ")":
                    args.append(self.parse_call_arg())
                    while self.peek().kind == ",":
                        self.advance(); args.append(self.parse_call_arg())
                self.expect(")")
                call = Call(expr,args)
                setattr(call, "_jaguar_callee_column", getattr(expr, "_jaguar_column", None))
                setattr(call, "_jaguar_callee_end_column", getattr(expr, "_jaguar_end_column", None))
                if isinstance(expr, MemberAccess):
                    setattr(call, "_jaguar_callee_column", getattr(expr, "_jaguar_member_column", getattr(expr, "_jaguar_column", None)))
                    setattr(call, "_jaguar_callee_end_column", getattr(expr, "_jaguar_member_end_column", getattr(expr, "_jaguar_end_column", None)))
                expr=call
                continue
            break
        return expr


# =========================================================================
# 4. RESOLVER — surcharge de fonctions & name mangling
# =========================================================================

class ResolverError(Exception):
    pass

LIBC_FUNCTION_NAMES = {
    "abort", "abs", "acos", "acosh", "asin", "asinh", "atan", "atan2", "atanh", "atexit", "atof", "atoi", "atol",
    "bsearch", "calloc", "ceil", "clearerr", "clock", "cos", "cosh", "ctime", "difftime", "div", "exit", "exp", "fabs",
    "fclose", "feof", "ferror", "fflush", "fgetc", "fgets", "fopen", "fprintf", "fputc", "fputs", "fread", "free",
    "freopen", "fscanf", "fseek", "fsetpos", "ftell", "fwrite", "getc", "getchar", "getenv", "gets", "isalnum", "isalpha",
    "iscntrl", "isdigit", "isgraph", "islower", "isprint", "ispunct", "isspace", "isupper", "isxdigit", "labs", "ldexp",
    "ldiv", "localeconv", "log", "log10", "longjmp", "malloc", "mblen", "mbstowcs", "mbtowc", "memchr", "memcmp",
    "memcpy", "memmove", "memset", "mktime", "modf", "perror", "pow", "printf", "putc", "putchar", "puts", "qsort",
    "raise", "rand", "realloc", "remove", "rename", "rewind", "scanf", "setbuf", "setlocale", "setvbuf", "signal",
    "sin", "sinh", "sprintf", "sqrt", "srand", "sscanf", "strcat", "strchr", "strcmp", "strcoll", "strcpy", "strcspn",
    "strerror", "strftime", "strlen", "strncat", "strncmp", "strncpy", "strpbrk", "strrchr", "strspn", "strstr", "strtod",
    "strtok", "strtol", "strtoul", "strxfrm", "system", "tan", "tanh", "time", "tmpfile", "tmpnam", "tolower", "toupper",
    "ungetc", "vfprintf", "vprintf", "vsprintf", "wctomb", "wcstombs",
}


FuncKey = Tuple[Optional[str], str]  # (namespace, nom)


class Resolver:
    """Regroupe les fonctions par (namespace, nom) et calcule le nom C
    final de chacune :
      - @extern            -> nom déclaré tel quel (aucun mangling)
      - nom non surchargé   -> "namespace_nom" (ou "nom" sans namespace)
      - nom surchargé (n>1) -> "namespace_nom_type1_type2_..." (ou "_void"
                                s'il n'y a pas de paramètres)

    Le mangling utilise les noms de types côté Jaguar (ex: "bool", pas
    "_jBool"), ce qui donne des noms C lisibles et stables.
    """

    def __init__(self, program: Program):
        self.program = program
        raw_groups: Dict[FuncKey, List[FunctionDecl]] = {}
        self._all_functions: List[FunctionDecl] = []
        self.decorators: Dict[tuple, DecoratorDecl] = {}
        self.groups: Dict[FuncKey, List[FunctionDecl]] = {}
        self.classes: Dict[str, ClassDecl] = {}
        self.type_aliases: Dict[str, str] = {}
        self.using_namespaces: list[str] = []
        self.using_symbols: Dict[str, Tuple[str, str]] = {}
        self.enums: Dict[str, EnumDecl] = {}
        self.enum_values: Dict[Tuple[str, str], str] = {}
        self.named_types: Dict[Tuple[Optional[str], str], str] = {}
        for item in program.items:
            if isinstance(item, TypeAliasDecl):
                if item.name in self.type_aliases:
                    self._resolver_error(f"type alias '{item.name}' declared multiple times", item)
                self.type_aliases[item.name] = item.target
            elif isinstance(item, UsingNamespaceDecl):
                if item.namespace not in self.using_namespaces:
                    self.using_namespaces.append(item.namespace)
            elif isinstance(item, UsingSymbolDecl):
                if item.alias in self.using_symbols and self.using_symbols[item.alias] != (item.namespace, item.name):
                    self._resolver_error(f"using symbol '{item.alias}' is imported more than once with different targets", item)
                self.using_symbols[item.alias] = (item.namespace, item.name)
            elif isinstance(item, EnumDecl):
                key = f"{item.namespace}:{item.name}" if item.namespace else item.name
                if key in self.enums:
                    self._resolver_error(f"enum '{key}' declared multiple times", item)
                self.enums[key] = item
                for value in item.values:
                    vk=(item.namespace or "", value)
                    if vk in self.enum_values:
                        self._resolver_error(f"enum value '{value}' declared multiple times in namespace '{item.namespace or '<global>'}", item)
                    self.enum_values[vk]=key
                prefix = f"{item.namespace.replace(':', '_')}_" if item.namespace else ""
                source_name = item.name[len(prefix):] if prefix and item.name.startswith(prefix) else item.name
                self.named_types[(item.namespace, source_name)] = (prefix + source_name) if item.namespace else source_name
        def resolve_decl_type(t, namespace=None, seen=None):
            seen = set() if seen is None else seen
            if not isinstance(t, str): return t
            arr = re.match(r"^(.*?)(\[(?:\d+)\])+$", t)
            if arr:
                base = arr.group(1)
                return resolve_decl_type(base, namespace, seen) + t[len(base):]
            if t.endswith("*"):
                base = t.rstrip("*")
                return resolve_decl_type(base, namespace, seen) + "*" * (len(t) - len(base))
            if t in seen:
                self._resolver_error(f"circular type alias involving '{t}'")
            if t in self.type_aliases:
                return resolve_decl_type(self.type_aliases[t], namespace, seen | {t})
            if ":" in t:
                ns, name = t.rsplit(":", 1)
                hit = self.named_types.get((ns, name))
                if hit: return hit
                return canonical_type(t.replace(":", "_"))
            hit = self.named_types.get((namespace, t))
            if hit: return hit
            hit = self.named_types.get((None, t))
            if hit: return hit
            imported = self.using_symbols.get(t)
            if imported:
                ns, name = imported
                hit = self.named_types.get((ns, name))
                if hit: return hit
                enum_key = f"{ns}:{name}"
                if enum_key in self.enums: return f"{ns}_{name}"
            for ns in self.using_namespaces:
                hit = self.named_types.get((ns, t))
                if hit: return hit
                enum_key = f"{ns}:{t}"
                if enum_key in self.enums: return f"{ns}_{t}"
            return canonical_type(t)

        def resolve_alias(t, seen=None):
            seen = set() if seen is None else seen
            if not isinstance(t, str): return t
            if t.endswith("*"):
                base=t.rstrip("*")
                return resolve_alias(base, seen) + "*" * (len(t)-len(base))
            if t in seen:
                self._resolver_error(f"circular type alias involving '{t}'")
            if t in self.type_aliases:
                return resolve_alias(self.type_aliases[t], seen | {t})
            imported = self.using_symbols.get(t)
            if imported:
                ns, name = imported
                enum_key = f"{ns}:{name}"
                if enum_key in self.enums:
                    return f"{ns}_{name}"
                if not ns and name in self.classes:
                    return name
            if "<" in t and t.endswith(">"):
                head=t[:t.index("<")]
                inner=t[t.index("<")+1:-1]
                parts=[]; depth=0; start=0
                for i,ch in enumerate(inner):
                    if ch=='<': depth+=1
                    elif ch=='>': depth-=1
                    elif ch==',' and depth==0:
                        parts.append(inner[start:i].strip()); start=i+1
                parts.append(inner[start:].strip())
                return head + "<" + ",".join(resolve_alias(x, seen) for x in parts) + ">"
            return canonical_type(t)
        self._resolve_alias = resolve_alias
        for item in program.items:
            if isinstance(item, FunctionDecl):
                key = (item.namespace, item.name)
                raw_groups.setdefault(key, []).append(item)
                self._all_functions.append(item)
            elif isinstance(item, DecoratorDecl):
                key = (item.namespace, item.name)
                if key in self.decorators:
                    self._resolver_error(f"decorator '{item.name}' declared multiple times", item)
                self.decorators[key] = item
            elif isinstance(item, ClassDecl):
                if item.name in self.classes:
                    self._resolver_error(f"class '{item.name}' declared multiple times", item)
                self.classes[item.name] = item
                prefix = f"{item.namespace.replace(':', '_')}_" if item.namespace else ""
                source_name = item.name[len(prefix):] if prefix and item.name.startswith(prefix) else item.name
                self.named_types[(item.namespace, source_name)] = item.name
            elif isinstance(item, StructDecl):
                prefix = f"{item.namespace.replace(':', '_')}_" if item.namespace else ""
                source_name = item.name[len(prefix):] if prefix and item.name.startswith(prefix) else item.name
                self.named_types[(item.namespace, source_name)] = item.name
            elif isinstance(item, UnionDecl):
                prefix = f"{item.namespace.replace(':', '_')}_" if item.namespace else ""
                source_name = item.name[len(prefix):] if prefix and item.name.startswith(prefix) else item.name
                self.named_types[(item.namespace, source_name)] = item.name

        builtin_types = set(TYPE_KEYWORDS) | set(TYPE_ALIASES) | {"auto"}

        def split_generic_args(text):
            inner = text[text.find("<") + 1:-1]
            parts=[]; depth=0; start=0
            paren = 0
            for i,ch in enumerate(inner):
                if ch == '<': depth += 1
                elif ch == '>' and (i == 0 or inner[i-1] != '-'): depth -= 1
                elif ch == '(': paren += 1
                elif ch == ')': paren -= 1
                elif ch == ',' and depth == 0 and paren == 0:
                    parts.append(inner[start:i].strip()); start=i+1
            parts.append(inner[start:].strip())
            return parts

        def type_known(t, namespace=None, seen=None):
            seen = set() if seen is None else seen
            if not isinstance(t, str): return True
            t = t.strip()
            while t.endswith('*'): t = t[:-1]
            array_match = re.match(r"^(.*?)(?:\[(?:\d+)\])+$", t)
            if array_match:
                return type_known(array_match.group(1), namespace, seen)
            if t.startswith("fn(") and ") -> " in t:
                close = t.rfind(") -> ")
                inner=t[3:close]
                params=[]
                if inner.strip(): params=split_generic_args("x<"+inner+">")
                params=[x for x in params if x != "..."]
                return all(type_known(x, namespace, seen) for x in params) and type_known(t[close+5:].strip(), namespace, seen)
            if "<" in t and t.endswith(">"):
                head=t[:t.index("<")].strip()
                if head not in ("list", "map", "container", "pair", "dynamic_list"):
                    return False
                return all(type_known(x, namespace, seen) for x in split_generic_args(t))
            t = canonical_type(t)
            if t in builtin_types or t in ("dynamic_list", "list", "map", "container", "pair"):
                return True
            if t in seen: return False
            if t in self.type_aliases:
                return type_known(self.type_aliases[t], namespace, seen | {t})
            if ":" in t:
                ns,name=t.rsplit(":",1)
                return (ns,name) in self.named_types
            return (namespace,t) in self.named_types or (None,t) in self.named_types

        owning_collection_heads = {"list", "map", "container"}

        def resolved_alias_target(t, seen=None):
            if not isinstance(t, str):
                return t
            seen = set() if seen is None else seen
            raw = t.strip()
            while raw.endswith("*"):
                raw = raw[:-1].strip()
            if raw in self.type_aliases and raw not in seen:
                return resolved_alias_target(self.type_aliases[raw], seen | {raw})
            return raw

        def generic_head(t):
            raw = resolved_alias_target(t)
            if "<" not in raw or not raw.endswith(">"):
                return None
            return raw[:raw.index("<")].strip()

        def is_owning_collection_type(t):
            raw = resolved_alias_target(t)
            if raw == "dynamic_list":
                return True
            return generic_head(raw) in owning_collection_heads

        def has_nested_owning_collection(t, seen=None):
            if not isinstance(t, str):
                return False
            seen = set() if seen is None else seen
            raw = resolved_alias_target(t, seen)
            if raw in seen:
                return False
            if raw != t.strip():
                seen = seen | {t.strip()}
            if "<" not in raw or not raw.endswith(">"):
                return False
            head = raw[:raw.index("<")].strip()
            args = split_generic_args(raw)
            for arg in args:
                arg = arg.strip()
                if is_owning_collection_type(arg):
                    return True
                if "<" in resolved_alias_target(arg) and has_nested_owning_collection(arg, seen):
                    return True
            if head == "pair":
                return any(has_nested_owning_collection(arg, seen) for arg in args)
            return False

        def validate_type(t, node, namespace=None):
            if not isinstance(t,str): return
            if has_nested_owning_collection(t):
                self._resolver_error(
                    f"nested owning collection type '{t}' is not supported",
                    node, "type"
                )
            if type_known(t, namespace): return
            bad=t.rstrip("*")
            base=t.rstrip("*")
            if base.startswith("fn(") and ") -> " in base:
                # Prefer the first unresolved component for a precise diagnostic.
                inner=base[3:base.rfind(") -> ")]
                parts=split_generic_args("x<"+inner+">") if inner.strip() else []
                ret=base[base.rfind(") -> ")+5:].strip()
                candidates=parts+[ret]
                bad=next((x for x in candidates if not type_known(x,namespace)), base)
            elif "<" in base and base.endswith(">"):
                parts=split_generic_args(base)
                bad=next((x for x in parts if not type_known(x,namespace)), base)
            self._resolver_error(f"unknown type '{bad}'", node, "type")

        for alias_name, alias_target in self.type_aliases.items():
            # Catch alias cycles/unknown targets at the declaration, before GCC.
            try:
                resolved_alias = resolve_alias(alias_name)
            except ResolverError as err:
                if not hasattr(err, "_jaguar_line"):
                    # Find the declaration by name in a stable way.
                    for x in program.items:
                        if isinstance(x, TypeAliasDecl) and x.name == alias_name:
                            err._jaguar_line = getattr(x, "_jaguar_line", 1)
                            err._jaguar_column = getattr(x, "_jaguar_target_column", getattr(x, "_jaguar_name_column", 0))
                            err._jaguar_end_column = getattr(x, "_jaguar_target_end_column", err._jaguar_column + 1)
                            break
                raise
            if not type_known(resolved_alias, None):
                alias_node = next(x for x in program.items if isinstance(x, TypeAliasDecl) and x.name == alias_name)
                self._resolver_error(f"unknown type '{resolved_alias}'", alias_node, "type")

        def validate_expr(e, namespace=None):
            if e is None: return
            if isinstance(e, CastExpr):
                validate_type(e.target_type, e, namespace); validate_expr(e.operand, namespace)
            elif isinstance(e, NewExpr):
                validate_type(e.type, e, namespace)
                for a in e.args: validate_expr(a.expr if isinstance(a, NamedArg) else a, namespace)
            elif isinstance(e, UnaryOp): validate_expr(e.operand, namespace)
            elif isinstance(e, BinOp): validate_expr(e.left, namespace); validate_expr(e.right, namespace)
            elif isinstance(e, IndexAccess): validate_expr(e.obj, namespace); validate_expr(e.index, namespace)
            elif isinstance(e, MemberAccess): validate_expr(e.obj, namespace)
            elif isinstance(e, Call):
                validate_expr(e.callee, namespace)
                for a in e.args: validate_expr(a.expr if isinstance(a, NamedArg) else a, namespace)
            elif isinstance(e, ListLiteral):
                for x in e.items: validate_expr(x, namespace)
            elif isinstance(e, NamedArg): validate_expr(e.expr, namespace)

        def validate_stmt(st, namespace=None):
            if isinstance(st, VarDecl):
                validate_type(st.type, st, namespace); validate_expr(st.init, namespace)
            elif isinstance(st, ForLoopStmt):
                validate_type(st.var_type, st, namespace); validate_expr(st.start, namespace); validate_expr(st.end, namespace)
                for x in st.body.statements: validate_stmt(x, namespace)
            elif isinstance(st, CollectionLoopStmt):
                validate_expr(st.collection, namespace)
                for x in st.body.statements: validate_stmt(x, namespace)
            elif isinstance(st, ReturnStmt): validate_expr(st.expr, namespace)
            elif isinstance(st, AssignStmt): validate_expr(st.expr, namespace)
            elif isinstance(st, MemberAssignStmt): validate_expr(st.target, namespace); validate_expr(st.expr, namespace)
            elif isinstance(st, PointerAssignStmt): validate_expr(st.target, namespace); validate_expr(st.expr, namespace)
            elif isinstance(st, ExprStmt): validate_expr(st.expr, namespace)
            elif isinstance(st, IfStmt):
                validate_expr(st.cond, namespace)
                for x in st.then_block.statements: validate_stmt(x, namespace)
                if isinstance(st.else_branch, IfStmt): validate_stmt(st.else_branch, namespace)
                elif isinstance(st.else_branch, Block):
                    for x in st.else_branch.statements: validate_stmt(x, namespace)
            elif isinstance(st, WhileStmt):
                validate_expr(st.cond, namespace)
                for x in st.body.statements: validate_stmt(x, namespace)
            elif isinstance(st, LoopStmt):
                for x in st.body.statements: validate_stmt(x, namespace)
            elif isinstance(st, VariableChangeHandler):
                for x in st.body.statements: validate_stmt(x, namespace)
            elif isinstance(st, TypeAliasStmt):
                validate_type(st.target, st, namespace)

        for item in program.items:
            if isinstance(item, FunctionDecl):
                validate_type(item.ret_type, item, item.namespace)
                for p in item.params: validate_type(p.type, p, item.namespace); validate_expr(p.default, item.namespace)
                for st in item.body.statements: validate_stmt(st, item.namespace)
                for use in item.decorators:
                    for a in use.args: validate_expr(a, item.namespace)
            elif isinstance(item, DecoratorDecl):
                for p in item.params: validate_type(p.type, p, item.namespace); validate_expr(p.default, item.namespace)
                for st in item.body.statements: validate_stmt(st, item.namespace)
            elif isinstance(item, StructDecl):
                for f in item.fields: validate_type(f.type, f, item.namespace)
            elif isinstance(item, UnionDecl):
                for f in item.fields: validate_type(f.type, f, item.namespace)
            elif isinstance(item, ClassDecl):
                if item.base: validate_type(item.base, item, item.namespace)
                for f in item.fields: validate_type(f.type, f, item.namespace); validate_expr(f.init, item.namespace)
                for m in item.methods:
                    validate_type(m.ret_type, m, item.namespace)
                    for p in m.params: validate_type(p.type, p, item.namespace); validate_expr(p.default, item.namespace)
                    for st in m.body.statements: validate_stmt(st, item.namespace)
            elif isinstance(item, VarDecl):
                validate_type(item.type, item, item.namespace); validate_expr(item.init, item.namespace)

        # Resolve aliases before signatures are compared, so `using T = float;`
        # behaves exactly like `float` for overloads and code generation.
        def rewrite_type(t, namespace=None):
            return resolve_decl_type(t, namespace)
        for item in program.items:
            if isinstance(item, FunctionDecl):
                item.ret_type = rewrite_type(item.ret_type, item.namespace)
                for p in item.params: p.type = rewrite_type(p.type, item.namespace)
            elif isinstance(item, DecoratorDecl):
                for p in item.params: p.type = rewrite_type(p.type, item.namespace)
            elif isinstance(item, StructDecl):
                for f in item.fields: f.type = rewrite_type(f.type, item.namespace)
            elif isinstance(item, ClassDecl):
                item.base = rewrite_type(item.base, item.namespace) if item.base else None
                for f in item.fields: f.type = rewrite_type(f.type, item.namespace)
                for m in item.methods:
                    m.ret_type = rewrite_type(m.ret_type, item.namespace)
                    for p in m.params: p.type = rewrite_type(p.type, item.namespace)
            elif isinstance(item, UnionDecl):
                for f in item.fields: f.type = rewrite_type(f.type, item.namespace)
            elif isinstance(item, VarDecl):
                item.type = rewrite_type(item.type, item.namespace)

        def rewrite_expr(e):
            if isinstance(e, CastExpr):
                e.target_type = rewrite_type(e.target_type); rewrite_expr(e.operand)
            elif isinstance(e, NewExpr):
                e.type = rewrite_type(e.type)
                for a in e.args: rewrite_expr(a.expr if isinstance(a, NamedArg) else a)
            elif isinstance(e, UnaryOp): rewrite_expr(e.operand)
            elif isinstance(e, BinOp): rewrite_expr(e.left); rewrite_expr(e.right)
            elif isinstance(e, IndexAccess): rewrite_expr(e.obj); rewrite_expr(e.index)
            elif isinstance(e, MemberAccess): rewrite_expr(e.obj)
            elif isinstance(e, Call):
                rewrite_expr(e.callee)
                for a in e.args: rewrite_expr(a.expr if isinstance(a, NamedArg) else a)
            elif isinstance(e, ListLiteral):
                for x in e.items: rewrite_expr(x)
            elif isinstance(e, NamedArg): rewrite_expr(e.expr)

        def rewrite_stmt(st, aliases=None, namespaces=None, symbols=None, current_namespace=None):
            aliases = dict(self.type_aliases if aliases is None else aliases)
            namespaces = list(self.using_namespaces if namespaces is None else namespaces)
            symbols = dict(self.using_symbols) if symbols is None else symbols
            def resolve_local(t, seen=None):
                seen = set() if seen is None else seen
                if not isinstance(t, str): return t
                if t.endswith("*"):
                    base=t.rstrip("*")
                    return resolve_local(base, seen) + "*" * (len(t)-len(base))
                if t in seen: raise ResolverError(f"circular type alias involving '{t}'")
                if t in aliases: return resolve_local(aliases[t], seen | {t})
                imported = symbols.get(t)
                if imported:
                    ns, name = imported
                    enum_key = f"{ns}:{name}"
                    if enum_key in self.enums:
                        return f"{ns}_{name}"
                    if name in self.classes and not ns:
                        return name
                for ns in namespaces:
                    enum_key=f"{ns}:{t}"
                    if enum_key in self.enums:
                        return f"{ns}_{t}"
                return resolve_decl_type(t, current_namespace)
            def annotate_expr(e):
                if e is None: return
                if isinstance(e, Call):
                    setattr(e, "_using_namespaces", list(namespaces))
                    setattr(e, "_using_symbols", dict(symbols))
                    annotate_expr(e.callee)
                    for a in e.args: annotate_expr(a.expr if isinstance(a, NamedArg) else a)
                elif isinstance(e, UnaryOp): annotate_expr(e.operand)
                elif isinstance(e, BinOp): annotate_expr(e.left); annotate_expr(e.right)
                elif isinstance(e, IndexAccess): annotate_expr(e.obj); annotate_expr(e.index)
                elif isinstance(e, MemberAccess): annotate_expr(e.obj)
                elif isinstance(e, CastExpr): e.target_type=resolve_local(e.target_type); annotate_expr(e.operand)
                elif isinstance(e, NewExpr):
                    e.type=resolve_local(e.type)
                    for a in e.args: annotate_expr(a.expr if isinstance(a, NamedArg) else a)
                elif isinstance(e, ListLiteral):
                    for x in e.items: annotate_expr(x)
                elif isinstance(e, NamedArg): annotate_expr(e.expr)
            if isinstance(st, UsingNamespaceStmt):
                if st.namespace not in namespaces: namespaces.append(st.namespace)
                return aliases, namespaces
            if isinstance(st, UsingSymbolStmt):
                symbols[st.alias] = (st.namespace, st.name)
                return aliases, namespaces
            if isinstance(st, TypeAliasStmt):
                aliases[st.name] = resolve_local(st.target)
                return aliases, namespaces
            if isinstance(st, VarDecl):
                st.type = resolve_local(st.type); annotate_expr(st.init)
            elif isinstance(st, ForLoopStmt):
                st.var_type = resolve_local(st.var_type); annotate_expr(st.start); annotate_expr(st.end)
                ca=dict(aliases); cn=list(namespaces)
                for x in st.body.statements: ca, cn = rewrite_stmt(x, ca, cn, dict(symbols), current_namespace)
            elif isinstance(st, CollectionLoopStmt):
                annotate_expr(st.collection)
                ca=dict(aliases); cn=list(namespaces)
                for x in st.body.statements: ca, cn = rewrite_stmt(x, ca, cn, dict(symbols), current_namespace)
            elif isinstance(st, AssignStmt): annotate_expr(st.expr)
            elif isinstance(st, PointerAssignStmt): annotate_expr(st.target); annotate_expr(st.expr)
            elif isinstance(st, MemberAssignStmt): annotate_expr(st.target); annotate_expr(st.expr)
            elif isinstance(st, ExprStmt): annotate_expr(st.expr)
            elif isinstance(st, ReturnStmt): annotate_expr(st.expr)
            elif isinstance(st, IfStmt):
                annotate_expr(st.cond)
                ca=dict(aliases); cn=list(namespaces)
                for x in st.then_block.statements: ca, cn = rewrite_stmt(x, ca, cn, dict(symbols), current_namespace)
                if isinstance(st.else_branch, IfStmt): rewrite_stmt(st.else_branch, dict(aliases), list(namespaces), dict(symbols))
                elif isinstance(st.else_branch, Block):
                    ca=dict(aliases); cn=list(namespaces)
                    for x in st.else_branch.statements: ca, cn = rewrite_stmt(x, ca, cn, dict(symbols), current_namespace)
            elif isinstance(st, WhileStmt):
                annotate_expr(st.cond)
                ca=dict(aliases); cn=list(namespaces)
                for x in st.body.statements: ca, cn = rewrite_stmt(x, ca, cn, dict(symbols), current_namespace)
            elif isinstance(st, LoopStmt):
                ca=dict(aliases); cn=list(namespaces)
                for x in st.body.statements: ca, cn = rewrite_stmt(x, ca, cn, dict(symbols), current_namespace)
            elif isinstance(st, VariableChangeHandler):
                ca=dict(aliases); cn=list(namespaces)
                for x in st.body.statements: ca, cn = rewrite_stmt(x, ca, cn, dict(symbols), current_namespace)
            return aliases, namespaces

        for item in program.items:
            if isinstance(item, FunctionDecl):
                aliases=dict(self.type_aliases); namespaces=list(self.using_namespaces); symbols=dict(self.using_symbols)
                for st in item.body.statements: aliases, namespaces = rewrite_stmt(st, aliases, namespaces, symbols, item.namespace)
                for p in item.params: rewrite_expr(p.default)
                for use in item.decorators:
                    for a in use.args: rewrite_expr(a)
            elif isinstance(item, DecoratorDecl):
                aliases=dict(self.type_aliases); namespaces=list(self.using_namespaces); symbols=dict(self.using_symbols)
                for st in item.body.statements: aliases, namespaces = rewrite_stmt(st, aliases, namespaces, symbols, item.namespace)
                for p in item.params: rewrite_expr(p.default)
            elif isinstance(item, ClassDecl):
                for f in item.fields: f.type = rewrite_type(f.type, item.namespace); rewrite_expr(f.init)
                for m in item.methods:
                    for p in m.params: rewrite_expr(p.default)
                    aliases=dict(self.type_aliases); namespaces=list(self.using_namespaces); symbols=dict(self.using_symbols)
                    for st in m.body.statements: aliases, namespaces = rewrite_stmt(st, aliases, namespaces, symbols)
            elif isinstance(item, VarDecl):
                rewrite_expr(item.init)

        # Fusionne les prototypes et définitions ayant exactement la même
        # signature. Un prototype + une définition est valide ; deux
        # définitions ou deux prototypes identiques ne le sont pas.
        for key, fns in raw_groups.items():
            by_sig: Dict[tuple, List[FunctionDecl]] = {}
            for fn in fns:
                sig = tuple(p.type for p in fn.params)
                by_sig.setdefault(sig, []).append(fn)
            representatives = []
            for sig, same in by_sig.items():
                defs = [fn for fn in same if not fn.is_prototype]
                protos = [fn for fn in same if fn.is_prototype]
                if len(defs) > 1:
                    self._resolver_error(
                        f"function '{key[1]}' declared multiple times with the same signature",
                        defs[1]
                    )
                if len(protos) > 1:
                    self._resolver_error(
                        f"prototype of '{key[1]}' declared multiple times with the same signature",
                        protos[1]
                    )
                if defs and protos:
                    rep = defs[0]
                else:
                    rep = same[0]
                representatives.append(rep)
            self.groups[key] = representatives

        setattr(program, "_using_namespaces", list(self.using_namespaces))
        setattr(program, "_using_symbols", dict(self.using_symbols))
        setattr(program, "_decorators", dict(self.decorators))
        setattr(program, "_type_aliases", dict(self.type_aliases))
        setattr(program, "_enums", dict(self.enums))
        self._resolve_classes()

    @staticmethod
    def _resolver_error(message, node=None, span_kind=None):
        err = ResolverError(message)
        if node is not None:
            if hasattr(node, "_jaguar_line"):
                err._jaguar_line = getattr(node, "_jaguar_line")
            if span_kind == "type" or (span_kind is None and "unknown type" in message):
                col = getattr(node, "_jaguar_type_column", None)
                end = getattr(node, "_jaguar_type_end_column", None)
                if col is not None:
                    err._jaguar_column = col
                    err._jaguar_end_column = end if end is not None else col + 1
                m = re.search(r"unknown type '([^']+)'", message)
                if m:
                    err._jaguar_symbol = m.group(1).rstrip("*")
            if getattr(err, "_jaguar_column", None) is None:
                col = getattr(node, "_jaguar_name_column", None)
                end = getattr(node, "_jaguar_name_end_column", None)
                if col is not None:
                    err._jaguar_column = col
                    err._jaguar_end_column = end if end is not None else col + 1
            base_col = getattr(node, "_jaguar_base_column", None)
            base_end = getattr(node, "_jaguar_base_end_column", None)
            if "unknown base class" in message and base_col is not None:
                err._jaguar_column = base_col
                err._jaguar_end_column = base_end if base_end is not None else base_col + 1
        raise err

    @staticmethod
    def _method_mangle_suffix(m):
        if not m.params:
            return "void"
        return "_".join(
            p.type.replace("*", "_ptr")
                 .replace("<", "_")
                 .replace(">", "_")
                 .replace(",", "_")
                 .replace(":", "_")
            for p in m.params
        )

    def _resolve_classes(self):
        for cls in self.classes.values():
            if cls.base and cls.base not in self.classes:
                self._resolver_error(f"unknown base class '{cls.base}' for '{cls.name}'", cls)
            method_groups = {}
            constructor_groups = {}
            destructors = []
            for m in cls.methods:
                if m.is_constructor:
                    constructor_groups.setdefault(tuple(p.type for p in m.params), []).append(m)
                elif m.is_destructor:
                    destructors.append(m)
                else:
                    method_groups.setdefault(m.name, {}).setdefault(tuple(p.type for p in m.params), []).append(m)

            for same in constructor_groups.values():
                if len(same) > 1:
                    self._resolver_error(
                        f"constructor of '{cls.name}' declared multiple times with the same signature",
                        same[1]
                    )

            if len(destructors) > 1:
                self._resolver_error(
                    f"class '{cls.name}' declares multiple destructors",
                    destructors[1]
                )

            for name, by_sig in method_groups.items():
                for same in by_sig.values():
                    if len(same) > 1:
                        self._resolver_error(
                            f"method '{cls.name}::{name}' declared multiple times with the same signature",
                            same[1]
                        )

            for m in cls.methods:
                if m.is_override:
                    base=self.classes.get(cls.base) if cls.base else None
                    matches=[]
                    while base:
                        matches += [x for x in base.methods if x.name==m.name and not x.is_constructor and not x.is_destructor
                                    and [p.type for p in x.params]==[p.type for p in m.params]
                                    and x.ret_type==m.ret_type
                                    and x.is_const==m.is_const]
                        base=self.classes.get(base.base) if base else None
                    if len(matches)!=1 or not matches[0].is_virtual:
                        self._resolver_error(f"invalid override: {cls.name}::{m.name}: no virtual method with an exact matching signature", m)
                    # An override inherits the base access level and virtual status.
                    m.access = matches[0].access
                    m.is_virtual = True
                if m.is_constructor:
                    suffix = self._method_mangle_suffix(m)
                    m.mangled_name = f"{cls.name}_ctor" if not m.params else f"{cls.name}_ctor_{suffix}"
                elif m.is_destructor:
                    m.mangled_name = f"{cls.name}_destr"
                else:
                    overloaded = len(method_groups.get(m.name, {})) > 1
                    m.mangled_name = (
                        f"{cls.name}_{m.name}_{self._method_mangle_suffix(m)}"
                        if overloaded else f"{cls.name}_{m.name}"
                    )

    def resolve(self) -> Dict[FuncKey, List[FunctionDecl]]:
        # Les noms C sont calculés par signature logique, puis propagés à
        # toutes les déclarations correspondantes (prototype et définition).
        for (namespace, name), fns in self.groups.items():
            if name.startswith("operator") and name[8:] in _OPERATOR_FUNCTION_TOKENS:
                invalid = next((fn for fn in fns if len(fn.params) != 2), None)
                if invalid is not None:
                    self._resolver_error(f"operator '{name[8:]}' requires exactly 2 parameters", invalid)
            if name in LIBC_FUNCTION_NAMES and any(not fn.is_extern for fn in fns):
                offending = next(fn for fn in fns if not fn.is_extern)
                self._resolver_error(f"function name '{name}' is reserved by libc and cannot be used in Jaguar", offending)
            overloaded = len(fns) > 1
            externs = [fn for fn in fns if fn.is_extern]
            if len(externs) > 1:
                self._resolver_error(
                    f"extern function '{name}' cannot be overloaded: all @extern declarations use the same C symbol",
                    externs[1]
                )
            for fn in fns:
                if fn.is_extern:
                    fn.mangled_name = fn.name
                    continue
                prefix = f"{namespace.replace(':', '_')}_" if namespace else ""
                c_name_base = _operator_c_name(name)
                if overloaded:
                    if fn.params:
                        suffix = "_".join(
                            [p.type.replace("*", "_ptr")
                                 .replace("<", "_")
                                 .replace(">", "_")
                                 .replace(",", "_")
                                 .replace(":", "_")
                             for p in fn.params] + (["variadic"] if fn.is_variadic else [])
                        )
                    else:
                        suffix = "void"
                    fn.mangled_name = f"{prefix}{c_name_base}_{suffix}"
                else:
                    fn.mangled_name = f"{prefix}{c_name_base}"
                if fn.decorators:
                    if fn.is_prototype or fn.is_extern:
                        self._resolver_error(f"decorator cannot be applied to prototype or extern function '{name}'", fn)
                    if fn.ret_type != "void":
                        self._resolver_error(f"decorator can only be applied to void function '{name}'", fn)
                    fn.implementation_name = f"{fn.mangled_name}__decor_impl"

        # Même nom C pour les prototypes et leurs définitions.
        for item in self._all_functions:
            if item.mangled_name is not None:
                continue
            key = (item.namespace, item.name)
            sig = (tuple(p.type for p in item.params), item.is_variadic)
            rep = next(fn for fn in self.groups[key] if (tuple(p.type for p in fn.params), fn.is_variadic) == sig)
            item.mangled_name = rep.mangled_name
        return self.groups




# =========================================================================
# 5. IR JAGUAR — représentation intermédiaire backend-neutral
# =========================================================================
#
# Le front-end ne produit plus directement du C. Il sérialise le Program AST
# après résolution/mangling dans un format JSON stable. Les annotations privées
# (_jaguar_*, _using_*, etc.) sont conservées car elles servent aux diagnostics
# et à certains choix de génération des backends.

IR_FORMAT = "jaguar-ir"
IR_VERSION = 1


def _ir_encode(value):
    """Encode récursivement l'AST résolu et ses annotations en JSON-safe data."""
    if dataclasses.is_dataclass(value):
        field_names = {f.name for f in dataclasses.fields(value)}
        fields_data = {
            name: _ir_encode(getattr(value, name))
            for name in field_names
        }
        attrs_data = {
            name: _ir_encode(attr_value)
            for name, attr_value in getattr(value, "__dict__", {}).items()
            if name not in field_names
        }
        return {
            "$type": type(value).__name__,
            "fields": fields_data,
            "attrs": attrs_data,
        }
    if isinstance(value, dict):
        return {
            "$dict": [
                [_ir_encode(k), _ir_encode(v)]
                for k, v in value.items()
            ]
        }
    if isinstance(value, tuple):
        return {"$tuple": [_ir_encode(x) for x in value]}
    if isinstance(value, list):
        return {"$list": [_ir_encode(x) for x in value]}
    if isinstance(value, set):
        return {"$set": [_ir_encode(x) for x in sorted(value, key=str)]}
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"cannot serialize Jaguar IR value of type {type(value).__name__}")


def _ir_types():
    # Keep this dynamic so adding a new AST dataclass automatically makes it
    # serializable without maintaining a second registry by hand.
    result = {}
    for name, value in globals().items():
        if isinstance(value, type) and dataclasses.is_dataclass(value):
            result[name] = value
    return result


def _ir_decode(value, types=None):
    """Decode JSON-safe IR data back into the exact front-end dataclasses."""
    types = types or _ir_types()
    if isinstance(value, list):
        return [_ir_decode(x, types) for x in value]
    if not isinstance(value, dict):
        return value
    if "$dict" in value:
        return {
            _ir_decode(k, types): _ir_decode(v, types)
            for k, v in value["$dict"]
        }
    if "$tuple" in value:
        return tuple(_ir_decode(x, types) for x in value["$tuple"])
    if "$list" in value:
        return [_ir_decode(x, types) for x in value["$list"]]
    if "$set" in value:
        return set(_ir_decode(x, types) for x in value["$set"])
    if "$type" in value:
        type_name = value["$type"]
        cls = types.get(type_name)
        if cls is None:
            raise ValueError(f"unknown Jaguar IR node type '{type_name}'")
        obj = cls.__new__(cls)
        for name, encoded in value.get("fields", {}).items():
            setattr(obj, name, _ir_decode(encoded, types))
        for name, encoded in value.get("attrs", {}).items():
            setattr(obj, name, _ir_decode(encoded, types))
        return obj
    return {k: _ir_decode(v, types) for k, v in value.items()}


def serialize_ir(ir: dict) -> str:
    return json.dumps(ir, ensure_ascii=False, indent=2)


def deserialize_ir(text: str) -> dict:
    try:
        ir = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid Jaguar IR JSON: {exc}") from exc
    if not isinstance(ir, dict) or ir.get("format") != IR_FORMAT:
        raise ValueError("invalid Jaguar IR: expected format 'jaguar-ir'")
    if ir.get("version") != IR_VERSION:
        raise ValueError(
            f"unsupported Jaguar IR version {ir.get('version')!r}; expected {IR_VERSION}"
        )
    if "program" not in ir:
        raise ValueError("invalid Jaguar IR: missing 'program'")
    return ir


def build_ir(source: str, c89: bool = False, source_name: Optional[str] = None) -> dict:
    """Run lexer/parser/resolver and return a backend-neutral resolved IR."""
    tokens = tokenize(source)
    program = Parser(tokens).parse_program()
    Resolver(program).resolve()
    return {
        "format": IR_FORMAT,
        "version": IR_VERSION,
        "language": "Jaguar",
        "options": {"c89": bool(c89)},
        "source": {
            "name": source_name,
            "text": source,
        },
        "program": _ir_encode(program),
    }


def program_from_ir(ir: dict) -> Program:
    program = _ir_decode(ir["program"])
    if not isinstance(program, Program):
        raise ValueError("invalid Jaguar IR: 'program' is not a Program node")
    return program


def groups_from_program(program: Program) -> Dict[FuncKey, List[FunctionDecl]]:
    groups: Dict[FuncKey, List[FunctionDecl]] = {}
    for item in program.items:
        if isinstance(item, FunctionDecl):
            groups.setdefault((item.namespace, item.name), []).append(item)
    return groups


def transpile(source: str, c89: bool = False) -> str:
    """Preserve the historic API name, but now return Jaguar IR JSON."""
    return serialize_ir(build_ir(source, c89=c89))


def transpile_files(source: str, c89: bool = False):
    """Preserve the historic helper name; its payload is now IR, not C."""
    return {"program": transpile(source, c89=c89), "format": IR_FORMAT, "version": IR_VERSION}


# =========================================================================
# 6. DIAGNOSTICS / POINT D'ENTRÉE
# =========================================================================

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




def _map_source_location(source: str, line: int):
    lines = source.splitlines()
    if not lines or line < 1:
        return None, max(1, line)
    # JBS emits one exact source marker immediately before each original line.
    for idx in range(min(line - 1, len(lines) - 1), -1, -1):
        marker = re.match(r"\s*//\s*jbs:source\s+(.+?):(\d+)\s*$", lines[idx])
        if marker:
            return marker.group(1), int(marker.group(2))
    current_file = None
    current_source_line = 1
    for idx, text in enumerate(lines, 1):
        m_file = re.match(r"\s*//\s*=+\s*([^=\n]+?)\s*=+\s*$", text)
        m_using = re.match(r"\s*//\s*jbs:\s*using\s+.*?->\s*(.+?)\s*$", text)
        if m_file:
            candidate = m_file.group(1).strip()
            if candidate and candidate != "Fichier généré par Jaguar Build System (JBS 1.0)":
                current_file = candidate; current_source_line = 1
        elif m_using:
            current_file = m_using.group(1).strip(); current_source_line = 1
        elif current_file is not None:
            if idx == line:
                return current_file, current_source_line
            current_source_line += 1
    return current_file, max(1, current_source_line if current_file else line)




def diagnose_source(source: str, c89: bool = False):
    """Run the Jaguar front-end and return one diagnostic for the first error."""
    try:
        build_ir(source, c89=c89)
    except (LexError, ParseError, ResolverError) as exc:
        return [_diagnostic_from_exception(source, exc)]
    return []


def format_diagnostic(diagnostic, filename=None, prefix="Jaguar Error"):
    location = f"{filename}:{diagnostic['line']}:{diagnostic['column'] + 1}" if filename else f"<stdin>:{diagnostic['line']}:{diagnostic['column'] + 1}"
    return f"{prefix}: {location}: {diagnostic['message']}"


def main(argv):
    out_path = None
    in_path = None
    c89 = False
    emit_c = False  # accepted for CLI compatibility; C generation belongs to jcc-c.py
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
            src = f.read()
        source_name = in_path
    else:
        src = sys.stdin.read()
        source_name = None

    try:
        ir_text = serialize_ir(build_ir(src, c89=c89, source_name=source_name))
    except (LexError, ParseError, ResolverError) as e:
        d = _diagnostic_from_exception(src, e)
        mapped_file, mapped_line = _map_source_location(src, d["line"])
        if mapped_file:
            location = f"{mapped_file}:{mapped_line}:{d['column'] + 1}"
        else:
            location = f"{in_path}:{d['line']}:{d['column'] + 1}" if in_path else f"<stdin>:{d['line']}:{d['column'] + 1}"
        print(f"Jaguar Error: {location}: {d['message']}", file=sys.stderr)
        return 1

    if emit_c:
        print("Jaguar: --emit-c is accepted for CLI compatibility but ignored by jcc; use jcc-c.py for C generation.", file=sys.stderr)

    if out_path:
        out_file = Path(out_path)
        if out_file.suffix.lower() != ".jir":
            out_file = Path(str(out_file) + ".jir")
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_text(ir_text + "\n", encoding="utf-8")
        print(f"Jaguar: IR generated at {out_file}")
    else:
        sys.stdout.write(ir_text + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
