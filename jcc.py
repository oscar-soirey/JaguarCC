#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
jcc.py — Compilateur Jaguar -> C

Pipeline : Lexer -> Parser (récursif descendant) -> AST
           -> Resolver (surcharge de fonctions, name mangling)
           -> CodeGen (émission de C)

Usage :
    python3 jcc.py mon_fichier.ja            # écrit le C sur stdout
    python3 jcc.py mon_fichier.ja -o out.c
    python3 jcc.py mon_fichier.ja --c89      # C89 strict (voir plus bas)
    cat mon_fichier.ja | python3 jcc.py      # lecture depuis stdin

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
  - fonction spéciale main(string param) : voir CodeGen._gen_main pour
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
  - while { ... } : boucle SANS condition ; on en sort avec break (ou
    return). `while (...)` est refusé.
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
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Tuple


# =========================================================================
# 1. LEXER
# =========================================================================

# Types "natifs" C (aucun typedef à générer)
NATIVE_TYPE_KEYWORDS = {"void", "int", "float"}
TYPE_ALIASES = {"int":"i32", "uint":"u32", "short":"i16", "ushort":"u16", "long":"i64", "ulong":"u64", "char":"i8", "uchar":"u8", "sbyte":"i8", "byte":"u8", "float":"f32", "double":"f64"}
def canonical_type(name: str) -> str:
    return TYPE_ALIASES.get(name, name)

# Types "custom" -> nécessitent un typedef généré (ordre d'émission stable).
# Les clés sont les noms côté Jaguar. Le nom réellement émis en C peut
# différer (voir C_TYPE_NAMES ci-dessous).
# NB: bool est défini via "unsigned char" et non "_Bool" pour rester
# valide en C89/ANSI C (le mot-clé _Bool / <stdbool.h> n'existe qu'à
# partir de C99).
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
    "string": "typedef struct _jString string;\nstruct _jString { char *data; size_t length; };",
}
ORDERED_BUILTIN_TYPES = list(BUILTIN_TYPEDEFS.keys())

# Nom C d'un type Jaguar quand il diffère du nom Jaguar.
# "bool" est déjà réservé en C (macro de <stdbool.h>, mot-clé en C23) :
# on émet donc "_jBool" partout dans le C généré.
C_TYPE_NAMES: Dict[str, str] = {
    "bool": "_jBool",
    "string": "string *",
}


def c_type(jaguar_type: str) -> str:
    """Nom du type tel qu'il doit apparaître dans le C généré."""
    return C_TYPE_NAMES.get(jaguar_type, jaguar_type)


TYPE_KEYWORDS = NATIVE_TYPE_KEYWORDS | set(BUILTIN_TYPEDEFS.keys()) | set(TYPE_ALIASES.keys())
INTEGER_TYPES = {"int", "i8", "i16", "i32", "i64", "u8", "u16", "u32", "u64"}
FLOAT_TYPES = {"float", "f32", "f64"}

KEYWORDS = TYPE_KEYWORDS | {
    "struct", "namespace", "class", "virtual", "override", "constr", "destr", "return", "true", "false", "const",
    "if", "else", "while", "break", "continue", "for_loop", "this", "auto",
}

# tokens à deux caractères (testés AVANT les tokens à un caractère)
TWO_CHAR_TOKENS = {"==", "!=", "<=", ">=", "&&", "||"}

# tokens à un seul caractère
SINGLE_CHAR_TOKENS = set("{}();,:.$+-*/%@=<>!")


class LexError(Exception):
    pass


@dataclass
class Token:
    kind: str   # nom du token ("IDENT", "INT", "{", "void", "i32", "@", ...)
    value: str
    line: int


def tokenize(src: str) -> List[Token]:
    tokens: List[Token] = []
    i = 0
    n = len(src)
    line = 1

    while i < n:
        c = src[i]

        if c == "\n":
            line += 1
            i += 1
            continue

        if c in " \t\r":
            i += 1
            continue

        # --- directive préprocesseur : toute la ligne, telle quelle ---
        if c == "#":
            j = src.find("\n", i)
            if j == -1:
                j = n
            tokens.append(Token("PREPROC", src[i:j].rstrip(), line))
            i = j
            continue

        # --- commentaire mono-ligne ---
        if c == "/" and i + 1 < n and src[i + 1] == "/":
            j = src.find("\n", i)
            if j == -1:
                j = n
            i = j
            continue

        # --- commentaire multiligne /* ... */ (couvre aussi /** ... */) ---
        if c == "/" and i + 1 < n and src[i + 1] == "*":
            j = src.find("*/", i + 2)
            if j == -1:
                raise LexError(f"commentaire multiligne non fermé (ligne {line})")
            line += src.count("\n", i, j)
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
                raise LexError(f"chaîne de caractères non terminée (ligne {line})")
            tokens.append(Token("STRING", src[i:j + 1], line))
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
            tokens.append(Token("FLOAT" if is_float else "INT", src[i:j], line))
            i = j
            continue

        # --- identifiants / mots-clés ---
        if c.isalpha() or c == "_":
            j = i
            while j < n and (src[j].isalnum() or src[j] == "_"):
                j += 1
            word = src[i:j]
            kind = word if word in KEYWORDS else "IDENT"
            tokens.append(Token(kind, word, line))
            i = j
            continue

        # --- opérateurs à deux caractères : == != <= >= && || ---
        if src[i:i + 2] in TWO_CHAR_TOKENS:
            two = src[i:i + 2]
            tokens.append(Token(two, two, line))
            i += 2
            continue

        # --- ponctuation simple (dont '@' pour les attributs, '=' pour
        #     l'initialisation des variables) ---
        if c in SINGLE_CHAR_TOKENS:
            tokens.append(Token(c, c, line))
            i += 1
            continue

        raise LexError(f"caractère inattendu {c!r} (ligne {line})")

    tokens.append(Token("EOF", "", line))
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
    """Déclaration de variable : `type nom;` ou `type nom = expr;`
    Utilisé dans un bloc (variable locale) comme au niveau du fichier
    (variable globale)."""
    type: str
    name: str
    init: Optional[object] = None
    is_const: bool = False


@dataclass
class AssignStmt:
    """Affectation : `nom = expr;`"""
    name: str
    expr: object


@dataclass
class MemberAssignStmt:
    target: MemberAccess
    expr: object


@dataclass
class Block:
    statements: list


@dataclass
class IfStmt:
    """if (cond) { ... } [else if (...) { ... }]* [else { ... }]
    else_branch est soit un Block (else), soit un IfStmt (else if)."""
    cond: object
    then_block: Block
    else_branch: Optional[object] = None


@dataclass
class WhileStmt:
    """while { ... } -- boucle sans condition, on en sort par break/return."""
    body: Block


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
    # rempli par le Resolver (nom final choisi pour le C généré)
    mangled_name: Optional[str] = None


@dataclass
class StructDecl:
    name: str
    fields: List[Field]


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
        elif isinstance(s, (WhileStmt, ForLoopStmt)):
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
            raise ParseError(
                f"attendu '{kind}' mais trouvé '{tok.kind}' ({tok.value!r}) ligne {tok.line}"
            )
        return self.advance()

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

        if tok.kind == "struct":
            return self.parse_struct()

        if tok.kind == "class":
            return self.parse_class()

        if tok.kind == "namespace":
            return self.parse_namespace()

        if tok.kind == "@":
            save = self.pos
            attrs = self.parse_attributes()
            if self.peek().kind == "class":
                return self.parse_class(attrs)
            self.pos = save
            if not self._is_function_ahead():
                raise ParseError(
                    f"les attributs (@...) ne s'appliquent qu'aux fonctions ou classes (ligne {tok.line})"
                )
            return self.parse_function()

        if tok.kind in TYPE_KEYWORDS or tok.kind in ("const", "IDENT"):
            # Un IDENT suivi de ':' ou '(' est un appel isolé au niveau
            # global (cf. `my_namespace:Foo();`), pas une déclaration.
            if tok.kind == "IDENT" and self.peek(1).kind in (":", "("):
                expr = self.parse_expr()
                self.expect(";")
                return TopExprStmt(expr)
            # `type nom (` -> fonction ; sinon `type nom [= expr] ;`
            # -> variable globale.
            if self._is_function_ahead():
                return self.parse_function()
            return self.parse_var_decl()

        raise ParseError(f"déclaration de haut niveau inattendue: '{tok.kind}' ligne {tok.line}")

    def _is_function_ahead(self) -> bool:
        """Regarde, sans consommer, si la déclaration qui suit est une
        fonction : `[@attribut]* type nom (`. Sinon c'est une variable."""
        i = 0
        while self.peek(i).kind == "@":
            i += 2
        if self.peek(i).kind == "const":
            i += 1
        return self.peek(i + 2).kind == "("

    # -- attributs (@extern, ...) --
    def parse_attributes(self) -> set:
        attrs = set()
        while self.peek().kind == "@":
            self.advance()
            name_tok = self.expect("IDENT")
            if name_tok.value not in KNOWN_ATTRIBUTES:
                raise ParseError(
                    f"attribut inconnu '@{name_tok.value}' (ligne {name_tok.line})"
                )
            attrs.add(name_tok.value)
        return attrs

    # -- struct --
    def parse_struct(self) -> StructDecl:
        self.expect("struct")
        name = self.expect("IDENT").value
        self.expect("{")
        fields = []
        while self.peek().kind != "}":
            t = self.parse_type()
            n = self.expect("IDENT").value
            self.expect(";")
            fields.append(Field(t, n))
        self.expect("}")
        return StructDecl(name, fields)

    # -- class -------------------------------------------------------------
    def parse_class(self, class_attrs=None) -> ClassDecl:
        class_attrs = class_attrs or set()
        self.expect("class")
        name = self.expect("IDENT").value
        base = None
        if self.peek().kind == ",":
            self.advance()
            base = self.expect("IDENT").value
        self.expect("{")
        fields, methods = [], []
        while self.peek().kind != "}":
            exposed = False
            if self.peek().kind == "@":
                attrs = self.parse_attributes()
                if attrs - {"exposed"}:
                    raise ParseError(f"attributs invalides sur un membre de classe (ligne {self.peek().line})")
                exposed = "exposed" in attrs
            access = "private"
            if self.peek().kind in ("$", "%"):
                access = "public" if self.advance().kind == "$" else "protected"

            is_virtual = False
            if self.peek().kind == "virtual":
                self.advance(); is_virtual = True

            # constructors/destructors are always public
            if self.peek().kind in ("constr", "destr"):
                kind = self.advance().kind
                self.expect("("); params=[]
                if self.peek().kind != ")":
                    params.append(self.parse_param())
                    while self.peek().kind == ",":
                        self.advance(); params.append(self.parse_param())
                self.expect(")")
                body = self.parse_block()
                methods.append(ClassMethod("void", kind, params, body, "public", False, False, kind=="constr", kind=="destr"))
                continue

            # Support both `void $foo()` et `void$ foo()` forms.
            field_const = False
            if self.peek().kind == "const":
                self.advance(); field_const = True
            ret_type = self.parse_type()
            if self.peek().kind in ("$", "%"):
                access = "public" if self.advance().kind == "$" else "protected"
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
                methods.append(ClassMethod(ret_type, member_name, params, body, access, is_virtual, is_override, False, False, method_const))
            else:
                init=None
                if self.peek().kind == "=":
                    self.advance(); init=self.parse_expr()
                self.expect(";")
                if is_virtual:
                    raise ParseError(f"'virtual' ne peut s'appliquer qu'à une méthode (ligne {self.peek().line})")
                methods.append(None) if False else fields.append(ClassField(ret_type, member_name, access, init, field_const, exposed))
        self.expect("}")
        return ClassDecl(name, base, fields, methods, "register" in class_attrs)

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
            if tok.kind == "struct":
                items.append(self.parse_struct())
            elif tok.kind == "class":
                items.append(self.parse_class())
            elif tok.kind == "namespace":
                items.extend(self.parse_namespace(namespace))
            elif tok.kind == "@" or tok.kind in TYPE_KEYWORDS or tok.kind == "IDENT":
                if not self._is_function_ahead():
                    raise ParseError(
                        f"declaration inattendue dans le namespace '{namespace}' : seules les "
                        f"fonctions, les struct et les namespaces y sont supportés "
                        f"(pas de variable globale dans un namespace) ligne {tok.line}"
                    )
                items.append(self.parse_function(namespace=namespace))
            else:
                raise ParseError(
                    f"élément de namespace inattendu: '{tok.kind}' ligne {tok.line}"
                )
        self.expect("}")
        return items

    # -- fonction --
    def parse_type(self) -> str:
        tok = self.peek()
        if tok.kind in TYPE_KEYWORDS or tok.kind == "IDENT":
            self.advance()
            return canonical_type(tok.value)
        raise ParseError(f"type attendu, trouvé '{tok.kind}' ligne {tok.line}")

    def parse_param(self) -> Param:
        is_const = False
        if self.peek().kind == "const":
            self.advance(); is_const = True
        t = self.parse_type()
        n = self.expect("IDENT")
        default = None
        if self.peek().kind == "=":
            self.advance()
            default = self.parse_expr()
        return Param(t, n.value, is_const, default)

    def parse_function(self, namespace: Optional[str] = None) -> FunctionDecl:
        attrs = self.parse_attributes()
        is_extern = "extern" in attrs

        prefix_const = False
        if self.peek().kind == "const":
            self.advance(); prefix_const = True
        ret_type = self.parse_type()
        name_tok = self.expect("IDENT")
        self.expect("(")
        params = []
        if self.peek().kind != ")":
            params.append(self.parse_param())
            while self.peek().kind == ",":
                self.advance()
                params.append(self.parse_param())
        self.expect(")")
        suffix_const = False
        if self.peek().kind == "const":
            self.advance(); suffix_const = True
        body = self.parse_block()
        return FunctionDecl(ret_type, name_tok.value, params, body, namespace, is_extern, prefix_const or suffix_const)

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
        return tok.kind == "IDENT" and self.peek(1).kind == "IDENT"

    def parse_var_decl(self) -> VarDecl:
        type_tok = self.peek()
        is_const = False
        if self.peek().kind == "const":
            self.advance(); is_const = True
        is_auto = self.peek().kind == "auto"
        if is_auto:
            self.advance(); t = "auto"
        else:
            t = self.parse_type()
            if t == "void":
                raise ParseError(f"une variable ne peut pas être de type 'void' (ligne {type_tok.line})")
        name = self.expect("IDENT").value
        init = None
        if self.peek().kind == "=":
            self.advance(); init = self.parse_expr()
        self.expect(";")
        if (is_auto or is_const) and init is None:
            raise ParseError(f"une variable '{'auto' if is_auto else 'const'}' '{name}' doit être initialisée (ligne {type_tok.line})")
        return VarDecl(t, name, init, is_const)

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
        if self.peek().kind == "(":
            raise ParseError(
                "'while' ne prend pas de paramètre : utilise "
                "`while { if (cond) { break; } }` "
                f"(ligne {tok.line})"
            )
        return WhileStmt(self.parse_block())

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
            raise ParseError(
                f"la variable de for_loop doit avoir un type entier "
                f"(int, i8..i64, u8..u64), pas '{type_tok.value}' (ligne {type_tok.line})"
            )
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

    def parse_statement(self):
        tok = self.peek()
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

        if tok.kind in ("break", "continue"):
            self.advance()
            self.expect(";")
            return BreakStmt() if tok.kind == "break" else ContinueStmt()

        if self._is_for_loop_ahead():
            return self.parse_for_loop()

        if tok.kind == "IDENT" and self.peek(1).kind == "=":
            return self.parse_assignment()

        if tok.kind in ("IDENT", "this"):
            save=self.pos
            lhs=self.parse_expr()
            if self.peek().kind == "=":
                if isinstance(lhs, MemberAccess):
                    self.advance(); rhs=self.parse_expr(); self.expect(";"); return MemberAssignStmt(lhs,rhs)
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
            name = self.advance().value
            self.advance()
            return NamedArg(name, self.parse_expr())
        return self.parse_expr()

    def parse_expr(self):
        return self.parse_or()

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
        if self.peek().kind in ("-", "!"):
            op = self.advance().value
            operand = self.parse_unary()
            return UnaryOp(op, operand)
        return self.parse_primary()

    def parse_primary(self):
        tok = self.peek()

        # Les casts Jaguar sont volontairement C-style uniquement :
        # `(i32)0.0`. La forme fonctionnelle `i32(0.0)` n'est pas un cast.
        if tok.kind == "(" and self.peek(1).kind in TYPE_KEYWORDS and self.peek(2).kind == ")":
            self.advance()
            target_type = canonical_type(self.advance().value)
            self.expect(")")
            return CastExpr(target_type, self.parse_unary())

        if tok.kind == "INT": self.advance(); return IntLit(tok.value)
        if tok.kind == "FLOAT": self.advance(); return FloatLit(tok.value)
        if tok.kind == "STRING": self.advance(); return StringLit(tok.value)
        if tok.kind in ("true", "false"): self.advance(); return BoolLit(tok.kind == "true")
        if tok.kind == "(":
            self.advance(); e=self.parse_expr(); self.expect(")"); return e
        if tok.kind not in ("IDENT", "this"):
            if tok.kind == "for_loop":
                raise ParseError("for_loop s'utilise uniquement sous la forme `int i = for_loop(début, fin) { ... }`")
            raise ParseError(f"expression inattendue: '{tok.kind}' ligne {tok.line}")

        self.advance()
        expr = Ident(tok.value)
        if self.peek().kind == ":":
            parts=[tok.value]
            while self.peek().kind == ":":
                self.advance(); parts.append(self.expect("IDENT").value)
            expr=NamespacedIdent(":".join(parts[:-1]), parts[-1])

        while True:
            if self.peek().kind == ".":
                self.advance(); expr=MemberAccess(expr, self.expect("IDENT").value); continue
            if self.peek().kind == "(":
                self.advance(); args=[]
                if self.peek().kind != ")":
                    args.append(self.parse_call_arg())
                    while self.peek().kind == ",":
                        self.advance(); args.append(self.parse_call_arg())
                self.expect(")"); expr=Call(expr,args); continue
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
        self.groups: Dict[FuncKey, List[FunctionDecl]] = {}
        self.classes: Dict[str, ClassDecl] = {}
        for item in program.items:
            if isinstance(item, FunctionDecl):
                key = (item.namespace, item.name)
                self.groups.setdefault(key, []).append(item)
            elif isinstance(item, ClassDecl):
                if item.name in self.classes:
                    raise ResolverError(f"classe '{item.name}' déclarée plusieurs fois")
                self.classes[item.name] = item
        self._resolve_classes()

    def _resolve_classes(self):
        for cls in self.classes.values():
            if cls.base and cls.base not in self.classes:
                raise ResolverError(f"classe de base inconnue '{cls.base}' pour '{cls.name}'")
            seen=set()
            for m in cls.methods:
                if m.is_override:
                    base=self.classes.get(cls.base) if cls.base else None
                    matches=[]
                    while base:
                        matches += [x for x in base.methods if x.name==m.name and not x.is_constructor and not x.is_destructor and [p.type for p in x.params]==[p.type for p in m.params] and x.ret_type==m.ret_type]
                        base=self.classes.get(base.base) if base else None
                    if len(matches)!=1 or not matches[0].is_virtual:
                        raise ResolverError(f"override invalide: {cls.name}::{m.name} : aucune méthode virtuelle de signature exacte")
                    # An override inherits the base access level and virtual status.
                    m.access = matches[0].access
                    m.is_virtual = True
                m.mangled_name=f"{cls.name}_{m.name}"

    def resolve(self) -> Dict[FuncKey, List[FunctionDecl]]:
        for (namespace, name), fns in self.groups.items():
            if name in LIBC_FUNCTION_NAMES and any(not fn.is_extern for fn in fns):
                raise ResolverError(f"le nom de fonction '{name}' est réservé par la libc et ne peut pas être utilisé en Jaguar")
            overloaded = len(fns) > 1
            for fn in fns:
                if fn.is_extern:
                    fn.mangled_name = fn.name
                    continue
                prefix = f"{namespace.replace(':', '_')}_" if namespace else ""
                if overloaded:
                    suffix = "_".join(p.type for p in fn.params) if fn.params else "void"
                    fn.mangled_name = f"{prefix}{name}_{suffix}"
                else:
                    fn.mangled_name = f"{prefix}{name}"
        return self.groups


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
    ("sys", "print"): ("_j_sys_print", 1, "void"),
    ("sys:console", "set_color"): ("_j_sys_console_set_color", 1, "void"),
    ("sys:console", "reset_color"): ("_j_sys_console_reset_color", 0, "void"),
    ("sys", "execute"): ("_j_sys_execute", 2, "int"),
    ("sys:fs", "read"): ("_j_sys_fs_read", 1, "string"),
    ("sys:fs", "write"): ("_j_sys_fs_write", 2, "void"),
    # jcc = bibliothèque standard JaguarCC
    ("jcc", "exit"): ("_j_lib_exit", 1, "void"),
    ("jcc", "abort"): ("_j_lib_abort", 0, "void"),
    ("jcc", "abs_i32"): ("_j_lib_abs_i32", 1, "i32"),
    ("jcc", "min_i32"): ("_j_lib_min_i32", 2, "i32"),
    ("jcc", "max_i32"): ("_j_lib_max_i32", 2, "i32"),
    ("jcc", "clamp_i32"): ("_j_lib_clamp_i32", 3, "i32"),
    ("jcc", "random_i32"): ("_j_lib_random_i32", 2, "i32"),
    ("jcc", "time_ms"): ("_j_lib_time_ms", 0, "i64"),
    ("jcc", "assert"): ("_j_lib_assert", 2, "void"),
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
            "static string *string_from_cstr(const char *src) {",
            "    string *s = (string *)calloc(1, sizeof(string));",
            "    if (!s) return 0;",
            "    if (!src) src = \"\";",
            "    s->length = strlen(src);",
            "    s->data = (char *)malloc(s->length + 1);",
            "    if (!s->data) { free(s); return 0; }",
            "    memcpy(s->data, src, s->length + 1);",
            "    return s;",
            "}",
            "",
            "static string *string_ctor(void) { return string_from_cstr(\"\"); }",
            "static void string_destr(string *self) {",
            "    if (!self) return;",
            "    free(self->data);",
            "    self->data = 0;",
            "    self->length = 0;",
            "}",
            "static i32 string_length(string *self) { return self ? (i32)self->length : 0; }",
            "static _jBool string_empty(string *self) { return (!self || self->length == 0) ? 1 : 0; }",
            "static _jBool string_equals(string *self, string *other) {",
            "    if (!self || !other) return self == other;",
            "    return strcmp(self->data ? self->data : \"\", other->data ? other->data : \"\") == 0;",
            "}",
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
            "    string *out = (string *)calloc(1, sizeof(string));",
            "    if (!out) return 0;",
            "    out->length = a + b; out->data = (char *)malloc(out->length + 1);",
            "    if (!out->data) { free(out); return 0; }",
            "    if (a) memcpy(out->data, self->data, a);",
            "    if (b) memcpy(out->data + a, other->data, b);",
            "    out->data[out->length] = '\\0';",
            "    return out;",
            "}",
            "static string *string_substring(string *self, i32 start, i32 length) {",
            "    size_t a, n; string *out;",
            "    if (!self || start < 0 || length < 0 || (size_t)start > self->length) return string_from_cstr(\"\");",
            "    a = (size_t)start; n = (size_t)length; if (n > self->length - a) n = self->length - a;",
            "    out = (string *)calloc(1, sizeof(string)); if (!out) return 0;",
            "    out->length = n; out->data = (char *)malloc(n + 1); if (!out->data) { free(out); return 0; }",
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
            "static void _j_lib_exit(i32 code) { exit((int)code); }",
            "static void _j_lib_abort(void) { abort(); }",
            "static i32 _j_lib_abs_i32(i32 v) { return v < 0 ? -v : v; }",
            "static i32 _j_lib_min_i32(i32 a, i32 b) { return a < b ? a : b; }",
            "static i32 _j_lib_max_i32(i32 a, i32 b) { return a > b ? a : b; }",
            "static i32 _j_lib_clamp_i32(i32 v, i32 lo, i32 hi) {",
            "    if (v < lo) return lo; if (v > hi) return hi; return v;",
            "}",
            "static i32 _j_lib_random_i32(i32 min, i32 max) {",
            "    static int seeded = 0; long long range;",
            "    if (!seeded) { srand((unsigned int)time(0)); seeded = 1; }",
            "    if (max <= min) return min; range = (long long)max - (long long)min + 1;",
            "    return min + (i32)(rand() % (int)range);",
            "}",
            "static i64 _j_lib_time_ms(void) {",
            "    return (i64)time(0) * 1000LL;",
            "}",
            "static void _j_lib_assert(_jBool condition, string *message) {",
            "    if (!condition) {",
            "        fprintf(stderr, \"Jaguar assertion failed: %s\\n\", (message && message->data) ? message->data : \"\");",
            "        abort();",
            "    }",
            "}",
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
        if "string" not in self.classes:
            self.classes["string"] = _builtin_string_class()
        self._current_class: Optional[ClassDecl] = None
        # c89=False : déclarations laissées à leur place (C99+)
        # c89=True  : déclarations remontées en tête de bloc (C89 strict)
        self.c89 = c89

        # état pendant la génération d'une fonction
        self._in_main = False            # `return;` -> `return 0;` dans main
        self._loop_depth = 0             # pour valider break / continue
        self._readonly_vars = set()      # variables const et de for_loop (non modifiables)
        self._current_class_method_const = False
        self._scope_owned = []
        self._loop_scope_bases = []
        self._tmp_id = 0                 # noms uniques des temporaires de for_loop

        # variables globales : nom -> type Jaguar (pour l'inférence de
        # types dans la résolution de surcharge, et la validation)
        self.global_types: Dict[str, str] = {}
        fn_c_names = {
            fn.mangled_name for fns in groups.values() for fn in fns
        }
        for item in program.items:
            if isinstance(item, VarDecl):
                if item.type == "auto":
                    raise CodeGenError("'auto' n'est pas autorisé pour une variable globale")
                if item.name in self.global_types:
                    raise CodeGenError(
                        f"la variable globale '{item.name}' est déclarée plusieurs fois"
                    )
                if item.name in fn_c_names:
                    raise CodeGenError(
                        f"la variable globale '{item.name}' porte le même nom "
                        f"(en C) qu'une fonction"
                    )
                self.global_types[item.name] = item.type

    def gen(self) -> str:
        used_types = self._used_builtin_types()
        used_system = self._used_system_builtins()
        used_string = "string" in used_types or any(
            fn.ret_type == "string" or any(p.type == "string" for p in fn.params)
            for fns in self.groups.values() for fn in fns
        ) or self._program_uses_string()
        if used_string:
            used_types.update({"string", "i32", "bool"})
        for k in ("jcc",):
            if any(key[0] == k for key in used_system):
                used_types.update({"i32", "i64", "bool", "string"})
        typedef_lines = [
            BUILTIN_TYPEDEFS[t] for t in ORDERED_BUILTIN_TYPES if t in used_types
        ]

        parts = []
        if self.classes:
            parts.append("#include <stdlib.h>")
        # Le runtime doit apparaître après les typedefs : fs:read retourne
        # `string`, donc son helper C a besoin de ce type.
        if typedef_lines:
            parts.append("\n".join(typedef_lines))
        runtime = _system_runtime(used_system, used_string)
        if runtime:
            parts.append(runtime)
        reflection = self._native_reflection_runtime()
        if reflection:
            # Prototypes are enough for code emitted before the implementation.
            if any(c.is_registered for c in self.classes.values() if c.name != "string"):
                parts.append("static void *_j_factory_construct(string *name);")
            parts.append("static void *_j_reflect_get_member(void *obj, const char *name);")
        for item in self.program.items:
            parts.append(self.gen_item(item))
        if reflection:
            parts.append(reflection)

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
            elif isinstance(stmt, IfStmt):
                scan_expr(stmt.cond)
                for x in stmt.then_block.statements:
                    scan_stmt(x)
                if isinstance(stmt.else_branch, IfStmt):
                    scan_stmt(stmt.else_branch)
                elif isinstance(stmt.else_branch, Block):
                    for x in stmt.else_branch.statements:
                        scan_stmt(x)
            elif isinstance(stmt, (WhileStmt, ForLoopStmt)):
                if isinstance(stmt, ForLoopStmt):
                    scan_expr(stmt.start)
                    scan_expr(stmt.end)
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
            if isinstance(s, IfStmt): return expr(s.cond) or any(stmt(x) for x in s.then_block.statements) or (stmt(s.else_branch) if isinstance(s.else_branch, IfStmt) else any(stmt(x) for x in s.else_branch.statements) if isinstance(s.else_branch, Block) else False)
            if isinstance(s, (WhileStmt, ForLoopStmt)): return any(stmt(x) for x in s.body.statements)
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
        return used


    def _native_reflection_runtime(self):
        registered = [c for c in self.classes.values() if c.name != "string" and c.is_registered]
        if not registered and not any(getattr(f, "is_exposed", False) for c in self.classes.values() for f in c.fields):
            return ""
        lines = [
            "/* Jaguar native reflection / factory runtime. */",
            "#include <string.h>",
            "typedef struct _jReflectVTable { const char *type_name; void *(*get_member)(void*, const char*); } _jReflectVTable;",
            "static void *_j_reflect_get_member(void *obj, const char *name) {",
            "    if (!obj || !name) return 0;",
            "    _jReflectVTable *vt = *(_jReflectVTable**)obj;",
            "    return (vt && vt->get_member) ? vt->get_member(obj, name) : 0;",
            "}",
        ]
        if registered:
            lines += ["static void *_j_factory_construct(string *name) {", "    if (!name || !name->data) return 0;"]
            for c in registered:
                lines.append(f'    if (strcmp(name->data, "{c.name}") == 0) return (void*){c.name}_ctor();')
            lines += ["    return 0;", "}"]
        return "\n".join(lines)

    # -- déclarations --
    def gen_item(self, item) -> str:
        if isinstance(item, PreprocLine):
            return item.text
        if isinstance(item, StructDecl):
            return self.gen_struct(item)
        if isinstance(item, ClassDecl):
            return self.gen_class(item)
        if isinstance(item, FunctionDecl):
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
        ctype = c_type(v.type)
        if v.init is None:
            return f"{ctype} {v.name};"
        if v.type == "string":
            raise CodeGenError("les variables globales de type 'string' doivent être initialisées au runtime")
        if not self._is_const_expr(v.init):
            raise CodeGenError(
                f"l'initialiseur de la variable globale '{v.name}' doit être une "
                f"expression constante (littéraux, macros #define, opérations entre "
                f"constantes) : pas d'appel de fonction ni de référence à une "
                f"autre variable"
            )
        return f"{'const ' if v.is_const else ''}{ctype} {v.name} = {self.gen_expr(v.init, {})};"

    def gen_struct(self, s: StructDecl) -> str:
        lines = ["typedef struct {"]
        for f in s.fields:
            lines.append(f"    {c_type(f.type)} {f.name};")
        lines.append(f"}} {s.name};")
        return "\n".join(lines)

    def _class_all_fields(self, cls):
        out=[]
        if cls.base: out += [(cls.base, f) for f in self._class_all_fields(self.classes[cls.base])]
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

    def gen_class(self, cls: ClassDecl) -> str:
        # Emit a C struct with an explicit vtable. Inheritance is represented
        # by embedding the base object as `_base`, preserving public layout.
        lines=[f"typedef struct {cls.name} {cls.name};", f"typedef struct {cls.name}_vtable {cls.name}_vtable;"]
        lines.append(f"struct {cls.name} {{")
        lines.append(f"    {cls.name}_vtable *_vptr;")
        if cls.base: lines.append(f"    {cls.base} _base;")
        for f in cls.fields: lines.append(f"    {'const ' if f.is_const else ''}{c_type(f.type)} {f.name};")
        lines.append("};")
        lines.append(f"struct {cls.name}_vtable {{")
        # Keep reflection metadata first so every class vtable has the same
        # native prefix and can be inspected through _jReflectVTable.
        lines.append("    const char *type_name;")
        lines.append("    void *(*get_member)(void *self, const char *name);")
        virt=[]
        for m in self._all_virtual_methods(cls):
            virt.append(m)
            ps=", ".join(["void *self"] + [("const " if p.is_const else "") + f"{c_type(p.type)} {p.name}" for p in m.params])
            lines.append(f"    {c_type(m.ret_type)} (*{m.name})({ps});")
        lines.append("};")
        # Native reflection: each registered/exposed class gets a typed member lookup.
        exposed = [f for f in self._class_all_fields(cls) if getattr(f[1], "is_exposed", False)]
        lines.append(f"static void *{cls.name}_get_member(void *obj, const char *name) {{")
        lines.append(f"    {cls.name} *self = ({cls.name}*)obj;")
        for owner, f in exposed:
            access_expr = self._base_member_expr("self", cls, f.name)
            lines.append(f"    if (strcmp(name, \"{f.name}\") == 0) return (void*)&{access_expr};")
        lines.append("    return 0;")
        lines.append("}")
        # constructors/prototypes are needed before method bodies
        for m in cls.methods:
            if m.is_constructor or m.is_destructor: continue
            ps=", ".join([f"{cls.name} *self"]+[("const " if p.is_const else "") + f"{c_type(p.type)} {p.name}" for p in m.params])
            lines.append(f"{c_type(m.ret_type)} {cls.name}_{m.name}({ps});")
        # Every Jaguar class gets a destructor entry point, even when the
        # user did not explicitly write `destr()`. This lets automatic scope
        # cleanup always call `<Class>_destr()` and lets an implicit derived
        # destructor destroy its base subobject.
        lines.append(f"void {cls.name}_destr({cls.name} *self);")
        lines.append(f"{cls.name} *{cls.name}_new(void);")
        for m in cls.methods:
            if m.is_constructor:
                ps=", ".join(f"{c_type(p.type)} {p.name}" for p in m.params)
                lines.append(f"{cls.name} *{cls.name}_ctor({ps});")
        if not any(m.is_constructor for m in cls.methods):
            lines.append(f"{cls.name} *{cls.name}_ctor(void);")
        # vtable definition
        lines.append(f"static {cls.name}_vtable {cls.name}_vtable_instance = {{")
        lines.append(f"    \"{cls.name}\",")
        lines.append(f"    {cls.name}_get_member,")
        for m in virt:
            lines.append(f"    ({c_type(m.ret_type)} (*)(void *{', ' if m.params else ''}{', '.join(c_type(p.type)+' '+p.name for p in m.params)})){cls.name}_{m.name},")
        lines.append("};")
        # methods
        old=self._current_class; old_const=self._current_class_method_const; self._current_class=cls
        for m in cls.methods:
            if m.is_constructor or m.is_destructor: continue
            ps=", ".join([f"{cls.name} *self"]+[("const " if p.is_const else "")+f"{c_type(p.type)} {p.name}" for p in m.params])
            self._current_class_method_const=m.is_const
            self._readonly_vars.update(p.name for p in m.params if p.is_const)
            lines.append(f"{c_type(m.ret_type)} {cls.name}_{m.name}({ps}) {self.gen_block(m.body, {p.name:p.type for p in m.params})}")
        # ctor allocates and initializes vptr/base/default fields
        ctor=next((m for m in cls.methods if m.is_constructor),None)
        if ctor or True:
            ctor_params = ctor.params if ctor else []
            ctor_body = ctor.body if ctor else Block([])
            ps=", ".join(f"{c_type(p.type)} {p.name}" for p in ctor_params)
            lines.append(f"{cls.name} *{cls.name}_ctor({ps}) {{")
            lines.append(f"    {cls.name} *self = ({cls.name}*)calloc(1, sizeof({cls.name}));")
            lines.append("    if (!self) return 0;")
            lines.append(f"    self->_vptr = &{cls.name}_vtable_instance;")
            if cls.base:
                bctor=next((m for m in self.classes[cls.base].methods if m.is_constructor),None)
                if bctor:
                    args=", ".join(p.name for p in ctor_params) if [p.type for p in bctor.params]==[p.type for p in ctor_params] else ""
                    if [p.type for p in bctor.params] != [p.type for p in ctor_params]:
                        raise CodeGenError(f"le constructeur de '{cls.name}' doit fournir les mêmes paramètres que celui de '{cls.base}' dans cette implémentation")
                    lines.append(f"    {{ {cls.base} *_base_tmp = {cls.base}_ctor({args}); if (_base_tmp) {{ self->_base = *_base_tmp; free(_base_tmp); }} }}")
            for f in cls.fields:
                if f.init is not None: lines.append(f"    self->{f.name} = {self.gen_expr(f.init, {p.name:p.type for p in ctor_params})};")
            # user ctor body
            old2=self._current_class; self._current_class=cls
            for line in self._gen_body_lines(ctor_body.statements, {p.name:p.type for p in ctor_params}): lines.append("    "+line)
            self._current_class=old2
            lines.append("    return self;"); lines.append("}")
        destr=next((m for m in cls.methods if m.is_destructor),None)
        # A destructor is always generated. If the user supplied one, its
        # body runs first. The base destructor is then invoked automatically.
        # This means `destr()` is optional and inheritance remains safe.
        lines.append(f"void {cls.name}_destr({cls.name} *self) {{")
        old3=self._current_class; self._current_class=cls
        if destr:
            for line in self._gen_body_lines(
                destr.body.statements,
                {p.name:p.type for p in destr.params}
            ):
                lines.append("    "+line)
        if cls.base:
            lines.append(f"    {cls.base}_destr(&self->_base);")
        self._current_class=old3
        lines.append("}")
        self._current_class=old; self._current_class_method_const=old_const
        return "\n".join(lines)

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

    def gen_function(self, fn: FunctionDecl) -> str:
        if self._is_special_main(fn):
            return self._gen_main(fn)

        params_str = ", ".join(("const " if p.is_const else "") + f"{c_type(p.type)} {p.name}" for p in fn.params)
        header = f"{c_type(fn.ret_type)} {fn.mangled_name}({params_str})"
        local_types = {p.name: p.type for p in fn.params}
        return f"{header} {self.gen_block(fn.body, local_types)}"

    def _gen_main(self, fn: FunctionDecl) -> str:
        if len(fn.params) == 0:
            header = "int main(void)"
            prelude_lines: List[str] = []
            local_types: dict = {}
        elif len(fn.params) == 1 and fn.params[0].type == "string":
            param_name = fn.params[0].name
            header = "int main(int argc, char *argv[])"
            prelude_lines = [f'string *{param_name} = string_from_cstr((argc > 1) ? argv[1] : "");']
            local_types = {param_name: "string"}
        else:
            raise CodeGenError(
                "main() doit être déclarée soit sans paramètre, soit avec un "
                "unique paramètre de type 'string' (déclaration de main invalide)"
            )

        # Le prélude (liaison de argv[1]) est lui-même une déclaration : il
        # doit rester en tête, avant les variables locales de l'utilisateur.
        # _in_main : tout `return;` (même dans un if / une boucle imbriquée)
        # devient `return 0;`
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
            raise CodeGenError("impossible de déduire le type de la variable 'auto'")
        return canonical_type(t)

    def _is_owned_class_type(self, type_name: str) -> bool:
        return type_name in self.classes

    def _scope_cleanup_lines(self, owned) -> List[str]:
        out = []
        for name, type_name in reversed(owned):
            out.append(f"{type_name}_destr({name});")
            out.append(f"free({name});")
        return out

    def _all_active_cleanup_lines(self) -> List[str]:
        out = []
        for owned in reversed(self._scope_owned):
            out.extend(self._scope_cleanup_lines(owned))
        return out

    def _loop_cleanup_lines(self) -> List[str]:
        base = self._loop_scope_bases[-1] if self._loop_scope_bases else 0
        out = []
        for owned in reversed(self._scope_owned[base:]):
            out.extend(self._scope_cleanup_lines(owned))
        return out

    def _gen_body_lines(self, statements: list, local_types: dict) -> List[str]:
        decl_lines: List[str] = []
        stmt_lines: List[str] = []
        in_prefix = True
        owned = []
        self._scope_owned.append(owned)

        for s in statements:
            if isinstance(s, VarDecl):
                if s.name in local_types:
                    raise CodeGenError(
                        f"la variable '{s.name}' est déjà déclarée "
                        f"(paramètre ou variable du même nom)"
                    )
                if s.name in self.global_types:
                    raise CodeGenError(
                        f"la variable locale '{s.name}' masque une variable globale "
                        f"du même nom"
                    )
                # L'initialiseur est généré avant d'enregistrer la variable.
                # `auto` est résolu à partir de son expression d'initialisation.
                if s.type == "auto":
                    s.type = self._resolve_auto_type(s.init, local_types)
                if s.init is not None and s.type != "auto" and s.type in self.classes and isinstance(s.init, Call) and isinstance(s.init.callee, NamespacedIdent) and s.init.callee.namespace == "factory" and s.init.callee.name == "construct":
                    if len(s.init.args) != 1:
                        raise CodeGenError("factory:construct() attend exactement un nom de classe")
                    init = f"({s.type}*)_j_factory_construct({self.gen_expr(s.init.args[0].expr if isinstance(s.init.args[0], NamedArg) else s.init.args[0], local_types)})"
                else:
                    init = self.gen_expr(s.init, local_types) if s.init is not None else None
                local_types[s.name] = s.type
                if self._is_owned_class_type(s.type):
                    owned.append((s.name, s.type))
                ctype = c_type(s.type)
                is_class = s.type in self.classes
                if is_class: ctype = s.type + " *"

                const_prefix = "const " if s.is_const else ""
                if s.is_const:
                    self._readonly_vars.add(s.name)
                if not self.c89:
                    # ordre du source conservé, initialiseur compris
                    if init is not None:
                        stmt_lines.append(f"{const_prefix}{ctype} {s.name} = {init};")
                    else:
                        stmt_lines.append(f"{const_prefix}{ctype} {s.name};")
                elif in_prefix:
                    if init is not None:
                        decl_lines.append(f"{const_prefix}{ctype} {s.name} = {init};")
                    else:
                        decl_lines.append(f"{const_prefix}{ctype} {s.name};")
                else:
                    decl_lines.append(f"{const_prefix}{ctype} {s.name};")
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

    def gen_stmt(self, s, local_types: dict) -> List[str]:
        """Lignes C d'une instruction. Une instruction simple donne une
        seule ligne ; if / while / for_loop en donnent plusieurs, dont les
        lignes de corps portent déjà 4 espaces d'indentation."""
        if isinstance(s, ReturnStmt):
            cleanup = self._all_active_cleanup_lines()
            if s.expr is None:
                return cleanup + ["return 0;" if self._in_main else "return;"]
            expr = self.gen_expr(s.expr, local_types)
            return cleanup + [f"return {expr};"]
        if isinstance(s, MemberAssignStmt):
            if self._is_reflection_call(s.target):
                ot, member, obj, name = self._reflection_member(s.target, local_types)
                target = f"(*(({c_type(member.type)}*)_j_reflect_get_member((void*){self.gen_expr(obj, local_types)}, {s.target.args[0].value})))"
                return [f"{target} = {self.gen_expr(s.expr, local_types)};"]
            ot = self.infer_type(s.target.obj, local_types)
            owner, member = self._find_class_member(ot, s.target.name, "field") if ot in self.classes else (None, None)
            if member is not None and getattr(member, "is_const", False):
                raise CodeGenError(f"le membre const '{s.target.name}' ne peut pas être modifié")
            if self._current_class_method_const and isinstance(s.target.obj, Ident) and s.target.obj.name == "this":
                raise CodeGenError(f"une méthode const ne peut pas modifier le membre '{s.target.name}'")
            target = self.gen_member_access(s.target, local_types)
            return [f"{target} = {self.gen_expr(s.expr, local_types)};"]
        if isinstance(s, AssignStmt):
            if s.name not in local_types and s.name not in self.global_types:
                raise CodeGenError(
                    f"affectation à '{s.name}' : variable non déclarée"
                )
            if s.name in self._readonly_vars:
                raise CodeGenError(f"la variable const '{s.name}' ne peut pas être modifiée")
            return [f"{s.name} = {self.gen_expr(s.expr, local_types)};"]
        if isinstance(s, ExprStmt):
            return [f"{self.gen_expr(s.expr, local_types)};"]
        if isinstance(s, IfStmt):
            return self._gen_if(s, local_types)
        if isinstance(s, WhileStmt):
            return self._gen_while(s, local_types)
        if isinstance(s, ForLoopStmt):
            return self._gen_for_loop(s, local_types)
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
            raise CodeGenError(f"'{keyword}' en dehors d'une boucle")

    def _gen_scoped(self, block: Block, local_types: dict) -> List[str]:
        """Corps d'un bloc imbriqué, indenté de 4 espaces. Le bloc reçoit
        une COPIE de la table des variables : ce qu'il déclare disparaît à
        sa sortie (deux blocs frères peuvent donc réutiliser un même nom),
        mais il voit les variables des blocs englobants (et interdit donc
        de les masquer, cf. la règle sur le masquage)."""
        inner = dict(local_types)
        return ["    " + line for line in self._gen_body_lines(block.statements, inner)]

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
        # `while { ... }` n'a pas de condition : boucle infinie en C, dont
        # on sort avec break (ou return).
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
                f"la variable '{name}' est déjà déclarée "
                f"(paramètre ou variable du même nom)"
            )
        if name in self.global_types:
            raise CodeGenError(
                f"la variable de boucle '{name}' masque une variable globale du même nom"
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

    # -- primitives sys:* ------------------------------------------------
    @staticmethod
    def _system_builtin(callee):
        if isinstance(callee, NamespacedIdent):
            return SYSTEM_BUILTINS.get((callee.namespace, callee.name))
        return None

    def _validate_system_call(self, call):
        info = self._system_builtin(call.callee)
        if info is None:
            return None
        c_name, argc, ret_type = info
        if len(call.args) != argc:
            if argc == 0:
                expected = "aucun argument"
            elif argc == 1:
                expected = "1 argument"
            else:
                expected = f"{argc} arguments"
            raise CodeGenError(
                f"'{call.callee.namespace}:{call.callee.name}' attend {expected}, "
                f"{len(call.args)} fourni(s)"
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
    def _ordered_call_args(self, args, params, callee_name="fonction"):
        """Réordonne les arguments et insère les valeurs par défaut."""
        ordered = [None] * len(params)
        by_name = {p.name:i for i,p in enumerate(params)}
        next_pos = 0; named_seen = False
        for arg in args:
            if isinstance(arg, NamedArg):
                named_seen = True
                if arg.name not in by_name:
                    raise CodeGenError(f"paramètre nommé '{arg.name}' inconnu pour {callee_name}")
                i = by_name[arg.name]
            else:
                if named_seen:
                    raise CodeGenError("un argument positionnel ne peut pas suivre un argument nommé")
                while next_pos < len(ordered) and ordered[next_pos] is not None:
                    next_pos += 1
                if next_pos >= len(ordered):
                    raise CodeGenError(f"trop d'arguments pour {callee_name}")
                i = next_pos; next_pos += 1
            if ordered[i] is not None:
                raise CodeGenError(f"paramètre '{params[i].name}' fourni plusieurs fois")
            ordered[i] = arg.expr if isinstance(arg, NamedArg) else arg
        missing = [params[i].name for i,x in enumerate(ordered) if x is None and params[i].default is None]
        if missing:
            raise CodeGenError(f"paramètres manquants pour {callee_name}: {', '.join(missing)}")
        for i, x in enumerate(ordered):
            if x is None:
                ordered[i] = params[i].default
        return ordered

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
        if not candidates:
            return None
        prepared = []
        for fn in candidates:
            try: ordered = self._ordered_call_args(call.args, fn.params, f"'{name}'")
            except CodeGenError: continue
            prepared.append((fn, ordered))
        if len(candidates) == 1:
            self._ordered_call_args(call.args, candidates[0].params, f"'{name}'")
            return candidates[0]

        scored = []
        for fn, ordered in prepared:
            arg_types = [self.infer_type(a, local_types) for a in ordered]
            if len(fn.params) == len(ordered):
                scores = [self._implicit_type_match(p.type, at) for p, at in zip(fn.params, arg_types)]
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
                f"aucune surcharge de '{name}' ne correspond aux types d'arguments fournis"
            )
        raise CodeGenError(f"appel ambigu à la fonction surchargée '{name}'")

    def infer_type(self, e, local_types: dict) -> Optional[str]:
        if isinstance(e, IntLit):
            return _literal("int")
        if isinstance(e, FloatLit):
            return _literal("float")
        if isinstance(e, StringLit):
            return "string"
        if isinstance(e, BoolLit):
            return "bool"
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
            return local_types.get(e.name) or self.global_types.get(e.name) or (e.name if e.name in self.classes else None)
        if isinstance(e, MemberAccess):
            ot=self.infer_type(e.obj, local_types)
            _, f=self._find_class_member(ot,e.name,"field") if ot in self.classes else (None,None)
            if f: return f.type
            _, m=self._find_class_member(ot,e.name,"method") if ot in self.classes else (None,None)
            if m: return m.ret_type
            return None
        if isinstance(e, NamespacedIdent):
            return None
        if isinstance(e, CastExpr):
            return e.target_type
        if isinstance(e, UnaryOp):
            if e.op == "!":
                return "bool"
            return self.infer_type(e.operand, local_types)
        if isinstance(e, BinOp):
            if e.op in _BOOL_RESULT_OPS:
                return "bool"
            return self.infer_type(e.left, local_types) or self.infer_type(e.right, local_types)
        if isinstance(e, Call):
            if isinstance(e.callee, Ident) and e.callee.name in TYPE_KEYWORDS and e.callee.name not in self.classes and e.callee.name != "string":
                raise CodeGenError(f"cast fonctionnel interdit : utilise la syntaxe C-style `({e.callee.name})expression`")
            if self._is_reflection_call(e):
                return self._reflection_member(e, local_types)[1].type
            if isinstance(e.callee, Ident) and e.callee.name in self.classes:
                cls = self.classes[e.callee.name]
                ctor = next((m for m in cls.methods if m.is_constructor), None)
                if ctor is None and e.args:
                    raise CodeGenError(f"'{cls.name}' n'a pas de constructeur prenant des arguments")
                return cls.name
            if isinstance(e.callee, MemberAccess):
                ot = self.infer_type(e.callee.obj, local_types)
                owner, m = self._find_class_member(ot, e.callee.name, "method") if ot in self.classes else (None, None)
                if m is not None:
                    self._check_member_access(owner, m, e.callee.name)
                    return m.ret_type
            if isinstance(e.callee, NamespacedIdent) and e.callee.namespace == "factory" and e.callee.name == "construct":
                return "void_ptr"
            if isinstance(e.callee, NamespacedIdent) and self._current_class and e.callee.namespace in self.classes and self._current_class.base == e.callee.namespace:
                owner, m = self._find_class_member(e.callee.namespace, e.callee.name, "method")
                if m is not None:
                    self._check_member_access(owner, m, e.callee.name)
                    return m.ret_type
            system = self._validate_system_call(e)
            if system is not None:
                return system[2]
            target = self.resolve_call_target(e, local_types)
            return target.ret_type if target else None
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
        cur=cls
        expr=root
        while cur:
            for f in cur.fields:
                if f.name==name: return expr+"->"+f.name
            if cur.base:
                expr += "->_base"
                cur=self.classes[cur.base]
            else: break
        raise CodeGenError(f"membre '{name}' introuvable dans la classe '{cls.name}'")

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
                f"membre {access} '{name}' inaccessible depuis la classe "
                f"'{self._current_class.name if self._current_class else 'ce contexte'}'"
            )

    def gen_member_access(self, e, local_types):
        ot=self.infer_type(e.obj, local_types)
        if ot not in self.classes:
            raise CodeGenError(f"'{ot}' n'est pas une classe")
        owner, member=self._find_class_member(ot,e.name,"field")
        if member is None:
            owner, member=self._find_class_member(ot,e.name,"method")
        if member is None: raise CodeGenError(f"membre '{e.name}' absent de '{ot}'")
        if not getattr(member, "is_exposed", False):
            self._check_member_access(owner, member, e.name)
        if isinstance(member, ClassField):
            if isinstance(e.obj, Ident) and self._current_class and e.obj.name=="this": return self._base_member_expr("self", self._current_class, e.name)
            return self.gen_expr(e.obj,local_types)+"->"+e.name if owner.name==ot else self.gen_expr(e.obj,local_types)+"->_base."+e.name
        return self.gen_expr(e.obj,local_types)+"->"+e.name

    def _is_reflection_call(self, e):
        return (isinstance(e, Call) and isinstance(e.callee, MemberAccess)
                and e.callee.name == "GetMember" and len(e.args) == 1
                and isinstance(e.args[0], StringLit))

    def _reflection_member(self, e, local_types):
        obj = e.callee.obj
        ot = self.infer_type(obj, local_types)
        if ot not in self.classes:
            raise CodeGenError("GetMember() ne peut être utilisé que sur une instance de classe")
        name = e.args[0].value[1:-1]
        owner, member = self._find_class_member(ot, name, "field")
        if member is None or not getattr(member, "is_exposed", False):
            raise CodeGenError(f"le membre '{name}' n'est pas exposé par réflexion sur '{ot}'")
        # @exposed is an explicit reflection boundary: it may expose a
        # private/protected field without changing ordinary member access.
        return ot, member, obj, name

    def gen_expr(self, e, local_types: dict) -> str:
        if isinstance(e, IntLit):
            return e.value
        if isinstance(e, FloatLit):
            return e.value
        if isinstance(e, StringLit):
            return f"string_from_cstr({e.value})"
        if isinstance(e, BoolLit):
            return "1" if e.value else "0"     # pas de <stdbool.h> en C89
        if isinstance(e, Ident):
            if e.name == "this":
                if not self._current_class:
                    raise CodeGenError("'this' n'est disponible que dans une classe")
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
            return e.name
        if isinstance(e, MemberAccess):
            return self.gen_member_access(e, local_types)
        if isinstance(e, NamespacedIdent):
            if e.namespace == "factory" and e.name == "construct":
                return "_j_factory_construct"
            if self._current_class and e.namespace in self.classes:
                owner, m = self._find_class_member(e.namespace, e.name, "method")
                if m is not None and self._current_class.base == e.namespace:
                    return f"{e.namespace}_{e.name}(self" + (", " if m.params else "") + ", ".join(p.name for p in m.params) + ")"
            return self.default_mangle(e.name, e.namespace)
        if isinstance(e, CastExpr):
            # Casts are emitted exclusively in C-style form.
            return f"({c_type(e.target_type)}){self.gen_expr(e.operand, local_types)}"
        if isinstance(e, UnaryOp):
            inner = self.gen_expr(e.operand, local_types)
            # -(-x) et non --x (qui serait un décrément en C) ; !(a && b)
            if isinstance(e.operand, (BinOp, UnaryOp)):
                inner = f"({inner})"
            return f"{e.op}{inner}"
        if isinstance(e, BinOp):
            prec = _BINOP_PREC[e.op]
            left = self._gen_operand(e.left, prec, local_types, is_right=False)
            right = self._gen_operand(e.right, prec, local_types, is_right=True)
            return f"{left} {e.op} {right}"
        if isinstance(e, Call):
            if self._is_reflection_call(e):
                ot, member, obj, name = self._reflection_member(e, local_types)
                return f"(*(({c_type(member.type)}*)_j_reflect_get_member((void*){self.gen_expr(obj, local_types)}, {e.args[0].value})))"
            # Appel direct à une méthode de la classe courante :
            # `printff()` doit devenir `MyClass_printff(self, ...)` et non
            # un appel C libre à `printff()`. Cela doit aussi passer par la
            # résolution normale des paramètres (y compris les paramètres
            # nommés).
            if isinstance(e.callee, Ident) and self._current_class:
                owner, method = self._find_class_member(
                    self._current_class.name, e.callee.name, "method"
                )
                if method is not None:
                    self._check_member_access(owner, method, e.callee.name)
                    ordered_args = self._ordered_call_args(
                        e.args, method.params, f"'{e.callee.name}'"
                    )
                    args = ", ".join(self.gen_expr(a, local_types) for a in ordered_args)
                    if method.is_virtual:
                        return f"self->_vptr->{method.name}((void*)self" + (", " + args if args else "") + ")"
                    return f"{owner.name}_{method.name}(self" + (", " + args if args else "") + ")"

            if isinstance(e.callee, NamespacedIdent) and e.callee.namespace == "factory" and e.callee.name == "construct":
                if len(e.args) != 1 or isinstance(e.args[0], NamedArg):
                    raise CodeGenError("factory:construct() attend exactement un argument positionnel (le nom de classe)")
                return f"_j_factory_construct({self.gen_expr(e.args[0], local_types)})"
            if isinstance(e.callee, Ident) and e.callee.name == "string":
                if len(e.args) != 0:
                    raise CodeGenError("string() ne prend aucun argument ; utilisez un littéral string")
                return "string_ctor()"
            if isinstance(e.callee, MemberAccess):
                ot = self.infer_type(e.callee.obj, local_types)
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
                        raise CodeGenError(f"méthode string::{e.callee.name} inconnue")
                    fn, argc = mapping[e.callee.name]
                    if len(e.args) != argc:
                        raise CodeGenError(f"string::{e.callee.name} attend {argc} argument(s)")
                    return f"{fn}({obj}" + (", " + args if args else "") + ")"
            if isinstance(e.callee, Ident) and e.callee.name in self.classes:
                cls=self.classes[e.callee.name]
                ctor=next((m for m in cls.methods if m.is_constructor),None)
                if ctor is None and e.args: raise CodeGenError(f"'{cls.name}' n'a pas de constructeur prenant des arguments")
                ordered_args=self._ordered_call_args(e.args, ctor.params if ctor else [], f"constructeur '{cls.name}'")
                args=", ".join(self.gen_expr(a,local_types) for a in ordered_args)
                return f"{cls.name}_ctor({args})"
            if isinstance(e.callee, NamespacedIdent) and self._current_class and e.callee.namespace in self.classes and self._current_class.base == e.callee.namespace:
                owner,m=self._find_class_member(e.callee.namespace,e.callee.name,"method")
                if m is not None:
                    ordered_args=self._ordered_call_args(e.args, m.params, f"'{e.callee.name}'")
                    args=", ".join(self.gen_expr(a,local_types) for a in ordered_args)
                    return f"{owner.name}_{m.name}(&self->_base" + (", "+args if args else "") + ")"
            if isinstance(e.callee, MemberAccess):
                ot=self.infer_type(e.callee.obj,local_types)
                owner,m=self._find_class_member(ot,e.callee.name,"method") if ot in self.classes else (None,None)
                if m is not None:
                    # Les appels de méthodes doivent respecter les mêmes règles
                    # d'accès que les accès directs aux champs/membres.
                    self._check_member_access(owner, m, e.callee.name)
                    obj=self.gen_expr(e.callee.obj,local_types)
                    ordered_args=self._ordered_call_args(e.args, m.params, f"'{e.callee.name}'")
                    args=", ".join(self.gen_expr(a,local_types) for a in ordered_args)
                    if m.is_virtual:
                        return f"{obj}->_vptr->{m.name}((void*){obj}" + (", "+args if args else "") + ")"
                    return f"{owner.name}_{m.name}({obj}" + (", "+args if args else "") + ")"
            system = self._validate_system_call(e)
            if system is not None:
                # sys:print accepte les types primitifs imprimables.
                if isinstance(e.callee, NamespacedIdent) and (
                    e.callee.namespace, e.callee.name
                ) == ("sys", "print"):
                    arg_type = self.infer_type(e.args[0], local_types)
                    callee_str = self._system_print_function(arg_type)
                    if callee_str is None:
                        raise CodeGenError(
                            "sys:print ne peut pas imprimer automatiquement "
                            f"une expression de type '{arg_type}'"
                        )
                else:
                    callee_str = system[0]
            else:
                target = self.resolve_call_target(e, local_types)
                if target is not None:
                    callee_str = target.mangled_name
                else:
                    # cible inconnue dans ce fichier : mangling de repli
                    if isinstance(e.callee, NamespacedIdent):
                        callee_str = self.default_mangle(e.callee.name, e.callee.namespace)
                    else:
                        callee_str = e.callee.name
            if system is not None and any(isinstance(a, NamedArg) for a in e.args):
                raise CodeGenError("les paramètres nommés ne sont pas disponibles pour les fonctions intégrées jcc/sys")
            if system is not None:
                ordered_args=e.args
            else:
                ordered_args=self._ordered_call_args(e.args, target.params, f"'{target.name}'") if target is not None else e.args
            args = ", ".join(self.gen_expr(a, local_types) for a in ordered_args)
            return f"{callee_str}({args})"
        raise NotImplementedError(f"expression non gérée: {e!r}")


# =========================================================================
# 6. POINT D'ENTRÉE
# =========================================================================

def transpile(source: str, c89: bool = False) -> str:
    tokens = tokenize(source)
    program = Parser(tokens).parse_program()
    groups = Resolver(program).resolve()
    return CodeGen(program, groups, c89=c89).gen()


def main(argv):
    out_path = None
    in_path = None
    c89 = False
    args = argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "-o" and i + 1 < len(args):
            out_path = args[i + 1]
            i += 2
        elif args[i] == "--c89":
            c89 = True
            i += 1
        else:
            in_path = args[i]
            i += 1

    if in_path:
        with open(in_path, "r", encoding="utf-8") as f:
            src = f.read()
    else:
        src = sys.stdin.read()

    try:
        c_code = transpile(src, c89=c89)
    except (LexError, ParseError, ResolverError, CodeGenError) as e:
        print(f"Erreur Jaguar: {e}", file=sys.stderr)
        return 1

    if out_path:
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(c_code)
    else:
        sys.stdout.write(c_code)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
