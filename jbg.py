#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
jbg.py — Jaguar BindGen

Transforme un header C d'API en binding Jaguar (.ja) utilisable par JBS/JCC.

Exemple :
    python jbg.py myapi.h -o myapi.ja --namespace myapi

Le générateur vise volontairement une API C simple et sûre côté Jaguar :
- fonctions C déclarées avec @extern ;
- types scalaires C -> types Jaguar ;
- const char* -> string ;
- macros #define numériques/chaînes simples conservées ;
- typedefs simples conservés quand ils sont représentables ;
- fonctions utilisant des pointeurs, tableaux, callbacks, variadiques ou des
  types C complexes sont ignorées avec un avertissement.

Le header original peut être conservé dans le .ja via --include-header. Cela
permet au C généré par JCC de retrouver les types/macros définis par l'API.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Modèle interne
# ---------------------------------------------------------------------------

@dataclass
class Function:
    return_type: str
    name: str
    params: List[Tuple[str, str]]


@dataclass
class Constant:
    name: str
    value: str


@dataclass
class Typedef:
    source: str
    target: str


@dataclass
class Binding:
    functions: List[Function]
    constants: List[Constant]
    typedefs: List[Typedef]
    warnings: List[str]


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

SCALAR_TYPES = {
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
    "int": "i32",
    "signed": "i32",
    "signed int": "i32",
    "unsigned": "u32",
    "unsigned int": "u32",
    "long": "i64",
    "long int": "i64",
    "signed long": "i64",
    "signed long int": "i64",
    "unsigned long": "u64",
    "unsigned long int": "u64",
    "long long": "i64",
    "long long int": "i64",
    "signed long long": "i64",
    "signed long long int": "i64",
    "unsigned long long": "u64",
    "unsigned long long int": "u64",
    "float": "f32",
    "double": "f64",
    "_Bool": "bool",
    "bool": "bool",
    "size_t": "u64",
    "ssize_t": "i64",
    "intptr_t": "i64",
    "uintptr_t": "u64",
}

# Types C que l'on accepte comme alias transparents.
QUALIFIERS = {"const", "volatile", "restrict", "register", "static", "extern"}

IDENT_RE = r"[A-Za-z_][A-Za-z0-9_]*"


# ---------------------------------------------------------------------------
# Nettoyage du header
# ---------------------------------------------------------------------------

def strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    text = re.sub(r"//[^\n]*", "", text)
    return text


def join_continuations(text: str) -> str:
    return re.sub(r"\\\r?\n", " ", text)


def normalize_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def split_top_level(text: str, separator: str = ",") -> List[str]:
    out: List[str] = []
    start = 0
    depth_paren = depth_brace = depth_bracket = 0
    for i, ch in enumerate(text):
        if ch == "(": depth_paren += 1
        elif ch == ")": depth_paren -= 1
        elif ch == "{": depth_brace += 1
        elif ch == "}": depth_brace -= 1
        elif ch == "[": depth_bracket += 1
        elif ch == "]": depth_bracket -= 1
        elif ch == separator and depth_paren == depth_brace == depth_bracket == 0:
            out.append(text[start:i].strip())
            start = i + 1
    out.append(text[start:].strip())
    return [x for x in out if x]


def remove_attributes(text: str) -> str:
    # GCC/MSVC attributes courants : __attribute__((...)), __declspec(...),
    # et attributs [[...]]. Ils sont ignorés pour le binding.
    text = re.sub(r"__attribute__\s*\(\(.*?\)\)", " ", text, flags=re.S)
    text = re.sub(r"__declspec\s*\([^)]*\)", " ", text, flags=re.S)
    text = re.sub(r"\[\[.*?\]\]", " ", text, flags=re.S)
    return text


# ---------------------------------------------------------------------------
# Analyse des types/declarations
# ---------------------------------------------------------------------------

def clean_type(t: str) -> str:
    t = normalize_ws(t)
    # Les qualifiers n'ont pas d'effet sur le type Jaguar.
    words = [w for w in t.split() if w not in QUALIFIERS]
    return " ".join(words)


def map_type(c_type: str, aliases: Dict[str, str]) -> Optional[str]:
    """Retourne un type Jaguar, ou None si le type n'est pas représentable."""
    t = clean_type(c_type)

    # Les pointeurs C ne sont volontairement pas exposés. Le type Jaguar
    # `string` est une structure propriétaire (`string *`) et n'est donc pas
    # ABI-compatible avec `const char*` d'une API C. Une conversion sûre
    # nécessiterait un wrapper C ; jbg laisse donc cette fonction de côté.
    if "*" in t or "[" in t or "]" in t:
        return None

    if t in SCALAR_TYPES:
        return SCALAR_TYPES[t]
    if t in aliases:
        return aliases[t]

    return None


def parse_named_param(param: str, index: int, aliases: Dict[str, str]) -> Optional[Tuple[str, str]]:
    param = remove_attributes(param).strip()
    if not param:
        return None
    if param == "void":
        return ("void", "")

    # Un prototype C peut omettre le nom du paramètre (`int`, `float`, ...).
    direct_type = map_type(param, aliases)
    if direct_type is not None:
        type_part = param
        name = f"arg{index}"
    else:
        # Retire le nom du paramètre C à la fin.
        m = re.match(r"^(.*?)\b(" + IDENT_RE + r")\s*$", param)
        if m:
            type_part = m.group(1).strip()
            name = m.group(2)
        else:
            type_part = param
            name = f"arg{index}"

    # Évite de prendre un mot-clé de type comme nom.
    if clean_type(type_part) in SCALAR_TYPES or clean_type(type_part) in aliases:
        name = f"arg{index}"
    elif name in {"const", "volatile", "unsigned", "signed", "long", "short"}:
        type_part = param
        name = f"arg{index}"

    # Tableau/pointeur/callback => non supporté.
    if "(" in type_part or ")" in type_part or "[" in param or "*" in type_part:
        return None

    jt = map_type(type_part, aliases)
    if jt is None:
        return None
    if jt == "void":
        return ("void", "")
    return (jt, name)


def parse_return_and_name(decl: str) -> Optional[Tuple[str, str, str]]:
    """Analyse `TYPE name(args)` et renvoie (return_type, name, args)."""
    decl = normalize_ws(remove_attributes(decl))
    decl = re.sub(r"\b(?:API|API_EXPORT|EXPORT|DLL_EXPORT|JAGUAR_API)\b", " ", decl)
    decl = normalize_ws(decl)

    # Calling conventions simples.
    decl = re.sub(r"\b(?:__cdecl|__stdcall|__fastcall|WINAPI|CALLBACK)\b", " ", decl)
    decl = normalize_ws(decl)

    m = re.match(r"^(?P<ret>.+?)\s+(?P<name>" + IDENT_RE + r")\s*\((?P<args>.*)\)$", decl, flags=re.S)
    if not m:
        return None
    return m.group("ret").strip(), m.group("name"), m.group("args").strip()


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def parse_header(text: str) -> Binding:
    text = join_continuations(strip_comments(text))
    warnings: List[str] = []
    functions: List[Function] = []
    constants: List[Constant] = []
    typedefs: List[Typedef] = []
    aliases: Dict[str, str] = {}

    # Préprocesseur : on ne traite que les #define simples.
    for line_no, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line.startswith("#define"):
            continue
        m = re.match(r"#define\s+(" + IDENT_RE + r")(?:\s+(.*))?$", line)
        if not m:
            continue
        name, value = m.group(1), (m.group(2) or "").strip()
        # Fonction macro : pas directement appelable comme variable Jaguar.
        if "(" in name or re.match(r"^" + IDENT_RE + r"\s*\(", line[7:]):
            continue
        # Valeurs sûres pour être réinjectées telles quelles dans le C.
        if re.fullmatch(r"[-+]?\d+(?:[uUlL]*)", value) or \
           re.fullmatch(r"[-+]?(?:\d+\.\d*|\.\d+)(?:[eE][-+]?\d+)?[fFlL]?", value) or \
           (len(value) >= 2 and value[0] == '"' and value[-1] == '"') or \
           value in {"0", "1", "true", "false"}:
            constants.append(Constant(name, value))

    # Typedefs simples : typedef <type> Name;
    for m in re.finditer(r"\btypedef\s+([^;{}]+?)\s+(" + IDENT_RE + r")\s*;", text):
        source, target = m.group(1).strip(), m.group(2)
        jt = map_type(source, aliases)
        if jt is not None and jt != "void":
            aliases[target] = jt
            typedefs.append(Typedef(jt, target))

    # Enlève les directives preprocessor pour ne pas les prendre pour des
    # déclarations C.
    body_lines = [l for l in text.splitlines() if not l.lstrip().startswith("#")]
    body = "\n".join(body_lines)
    # Les headers C/C++ utilisent souvent un garde `extern "C" { ... }`.
    # Ce bloc n'a pas d'équivalent Jaguar : on retire uniquement cette
    # enveloppe, sans toucher aux autres accolades.
    body = re.sub(r'\bextern\s+"C"\s*\{', " ", body)
    body = re.sub(r'^\s*\}\s*$', " ", body, flags=re.M)

    # Retire les typedefs déjà consommés et les blocs de struct/enum. Les
    # structures C complexes ne sont pas exposées automatiquement.
    body = re.sub(r"\btypedef\s+[^;{}]+\s+" + IDENT_RE + r"\s*;", " ", body)
    body = re.sub(r"\b(?:typedef\s+)?(?:struct|union|enum)\s+" + IDENT_RE + r"\s*\{.*?\}\s*;", " ", body, flags=re.S)

    # Déclarations terminées par ;. Cela couvre les prototypes C classiques.
    statements = [s.strip() for s in body.split(";") if s.strip()]

    for statement in statements:
        s = normalize_ws(statement)
        if not s or s.startswith("#"):
            continue

        # Ignore les déclarations de variables/globales.
        parsed = parse_return_and_name(s)
        if not parsed:
            continue
        ret, name, arg_text = parsed

        # Variadique.
        if "..." in arg_text:
            warnings.append(f"fonction ignorée: {name} (arguments variadiques)")
            continue

        jt_ret = map_type(ret, aliases)
        if jt_ret is None:
            warnings.append(f"fonction ignorée: {name} (type de retour non supporté: {ret})")
            continue

        params: List[Tuple[str, str]] = []
        unsupported = False
        if arg_text and arg_text.strip() != "void":
            for i, raw_param in enumerate(split_top_level(arg_text), 1):
                p = parse_named_param(raw_param, i, aliases)
                if p is None:
                    unsupported = True
                    break
                if p[0] == "void":
                    unsupported = True
                    break
                params.append(p)

        if unsupported:
            warnings.append(f"fonction ignorée: {name} (paramètre non représentable par Jaguar)")
            continue

        # Les fonctions sans nom de paramètre sont parfaitement valides côté C;
        # on donne des noms stables côté Jaguar.
        used = set()
        fixed = []
        for i, (ptype, pname) in enumerate(params, 1):
            if not pname or pname in used:
                pname = f"arg{i}"
            used.add(pname)
            fixed.append((ptype, pname))
        functions.append(Function(jt_ret, name, fixed))

    # Déduplication des prototypes.
    unique: Dict[Tuple[str, Tuple[str, ...]], Function] = {}
    for fn in functions:
        key = (fn.name, tuple(t for t, _ in fn.params))
        unique.setdefault(key, fn)

    return Binding(list(unique.values()), constants, typedefs, warnings)


# ---------------------------------------------------------------------------
# Génération Jaguar
# ---------------------------------------------------------------------------

def escape_ja_string(s: str) -> str:
    return s.replace('\\', '\\\\').replace('"', '\\"')


def render(binding: Binding, namespace: Optional[str], header_include: Optional[str], source_name: str) -> str:
    lines: List[str] = []
    lines.append("// ============================================================================")
    lines.append(f"// Jaguar binding généré par jbg.py — {os.path.basename(source_name)}")
    lines.append("// ============================================================================")
    lines.append("// Les fonctions @extern gardent exactement leur nom C.")
    lines.append("")

    if header_include:
        lines.append(f'#include "{escape_ja_string(header_include)}"')
        lines.append("")

    for td in binding.typedefs:
        # Jaguar ne possède pas encore de syntaxe typedef : les aliases sont
        # mieux conservés sous forme de commentaires pour éviter de générer
        # une construction invalide.
        lines.append(f"// typedef C: {td.source} {td.target}")
    if binding.typedefs:
        lines.append("")

    for c in binding.constants:
        lines.append(f"#define {c.name} {c.value}")
    if binding.constants:
        lines.append("")

    if namespace:
        lines.append(f"namespace {namespace} {{")
        lines.append("")

    for fn in binding.functions:
        lines.append("    @extern") if namespace else lines.append("@extern")
        params = ", ".join(f"{t} {n}" for t, n in fn.params)
        decl = f"{fn.return_type} {fn.name}({params});"
        lines.append(f"    {decl}" if namespace else decl)
        lines.append("")

    if namespace:
        lines.append("}")

    if not binding.functions and not binding.constants:
        lines.append("// Aucun symbole Jaguar représentable trouvé dans ce header.")

    return "\n".join(lines).rstrip() + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="jbg.py",
        description="Jaguar BindGen — transforme une API C (.h) en binding Jaguar (.ja).",
    )
    p.add_argument("header", help="header C à analyser (.h)")
    p.add_argument("-o", "--output", help="fichier .ja de sortie")
    p.add_argument("--namespace", help="namespace Jaguar dans lequel placer les fonctions")
    p.add_argument(
        "--include-header",
        nargs="?",
        const="__AUTO__",
        default=None,
        help="ajoute #include du header au .ja (désactivé par défaut; sans valeur = nom du header)",
    )
    p.add_argument("--no-include", action="store_true", help="n'ajoute pas de #include au .ja")
    p.add_argument("--quiet", action="store_true", help="masque les avertissements")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not os.path.isfile(args.header):
        print(f"JBG: fichier introuvable: {args.header}", file=sys.stderr)
        return 1

    try:
        with open(args.header, "r", encoding="utf-8", errors="replace") as f:
            source = f.read()
    except OSError as exc:
        print(f"JBG: impossible de lire '{args.header}': {exc}", file=sys.stderr)
        return 1

    binding = parse_header(source)

    if args.output:
        output = args.output
    else:
        output = os.path.splitext(args.header)[0] + ".ja"

    if args.no_include:
        include = None
    elif args.include_header == "none":
        include = None
    elif args.include_header not in (None, "__AUTO__"):
        include = args.include_header
    elif args.include_header == "__AUTO__":
        include = os.path.basename(args.header)
    else:
        include = None

    result = render(binding, args.namespace, include, args.header)

    try:
        parent = os.path.dirname(os.path.abspath(output))
        os.makedirs(parent, exist_ok=True)
        with open(output, "w", encoding="utf-8", newline="\n") as f:
            f.write(result)
    except OSError as exc:
        print(f"JBG: impossible d'écrire '{output}': {exc}", file=sys.stderr)
        return 1

    print(f"JBG: {len(binding.functions)} fonction(s), {len(binding.constants)} constante(s) -> {output}")
    if binding.warnings and not args.quiet:
        for warning in binding.warnings:
            print(f"JBG: avertissement: {warning}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
