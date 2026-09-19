#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
jbs.py — Jaguar Build System

Format JBS 1.0 :

version 1.0

compile example {
    add.ja
    main.ja
}

Directives disponibles en JBS 1.0 :

    version 1.0
    out build
    c89
    keep_c
    include lib
    define COMPILE_DLL
    define PI 3.14
    compile game { ... }

`c89` demande à jcc de générer du C89 strict. `include` ajoute un répertoire
de recherche pour les `using`, en plus du dossier du fichier `.jbs`.

Les fichiers Jaguar peuvent utiliser un autre fichier avec :

    using add;

`using add;` cherche `add.ja` dans le répertoire du .jbs et inclut son
contenu dans l'unité de compilation. Les `using` sont récursifs.

Usage :
    python jbs.py projet.jbs
    python jbs.py projet.jbs -o build
    python jbs.py projet.jbs --target example
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


class JBSError(Exception):
    pass


@dataclass
class BuildTarget:
    name: str
    files: list[str]


@dataclass
class JBSConfig:
    version: str
    output_dir: str | None
    c89: bool
    keep_c: bool
    include_dirs: list[str]
    defines: list[str]
    targets: list[BuildTarget]


VERSION_RE = re.compile(r"^\s*version\s+([0-9]+(?:\.[0-9]+)+)\s*$")
COMPILE_RE = re.compile(r"\bcompile\s+([A-Za-z_][A-Za-z0-9_]*)\s*\{")
USING_RE = re.compile(r"^\s*using\s+([A-Za-z_][A-Za-z0-9_]*)\s*;\s*(?://.*)?$")


def strip_jbs_comments(text: str) -> str:
    # Les commentaires JBS sont volontairement simples : // jusqu'à la fin
    # de la ligne. Les chemins de fichiers ne sont pas censés contenir //.
    return re.sub(r"//.*", "", text)


def parse_jbs(text: str) -> JBSConfig:
    clean = strip_jbs_comments(text)

    version_match = re.search(r"^\s*version\s+([^\s]+)\s*$", clean, re.MULTILINE)
    if not version_match:
        raise JBSError("version JBS manquante (attendu: 'version 1.0')")
    version = version_match.group(1)
    if version != "1.0":
        raise JBSError(f"version JBS non supportée: {version} (seule 1.0 est supportée)")

    output_dir: str | None = None
    out_matches = re.findall(r"^\s*out\s+([^\s{}]+)\s*$", clean, re.MULTILINE)
    if len(out_matches) > 1:
        raise JBSError("directive 'out' définie plusieurs fois")
    if out_matches:
        output_dir = out_matches[0]

    c89 = bool(re.search(r"^\s*c89\s*$", clean, re.MULTILINE))
    keep_c = bool(re.search(r"^\s*keep_c\s*$", clean, re.MULTILINE))

    defines: list[str] = []
    for match in re.finditer(r"^[ \t]*define[ \t]+([A-Za-z_][A-Za-z0-9_]*)(?:[ \t]+([^\r\n]*))?[ \t]*$", clean, re.MULTILINE):
        name = match.group(1)
        value = (match.group(2) or "").strip()
        defines.append(f"#define {name}" + (f" {value}" if value else ""))

    include_dirs: list[str] = []
    for match in re.finditer(r"^\s*include\s+([^\s{}]+)\s*$", clean, re.MULTILINE):
        include_dirs.append(match.group(1))
    if len(include_dirs) != len(set(include_dirs)):
        raise JBSError("directive 'include' définie plusieurs fois pour le même chemin")

    targets: list[BuildTarget] = []
    pos = 0
    while True:
        match = COMPILE_RE.search(clean, pos)
        if not match:
            break

        name = match.group(1)
        brace_start = clean.find("{", match.start(), match.end())
        depth = 1
        i = brace_start + 1
        while i < len(clean) and depth:
            if clean[i] == "{":
                depth += 1
            elif clean[i] == "}":
                depth -= 1
            i += 1
        if depth != 0:
            raise JBSError(f"bloc compile '{name}' non fermé")

        body = clean[brace_start + 1:i - 1]
        files: list[str] = []
        for line_no, raw_line in enumerate(body.splitlines(), 1):
            line = raw_line.strip()
            if not line:
                continue
            if not line.endswith(".ja"):
                raise JBSError(
                    f"entrée invalide dans compile {name}: '{line}' "
                    f"(attendu: un fichier .ja)"
                )
            # Un fichier doit être un chemin simple ou relatif. On laisse les
            # sous-répertoires relatifs fonctionner.
            files.append(line)

        if not files:
            raise JBSError(f"le bloc compile '{name}' ne contient aucun fichier .ja")

        targets.append(BuildTarget(name, files))
        pos = i

    if not targets:
        raise JBSError("aucun bloc 'compile <nom> { ... }' trouvé")

    return JBSConfig(version, output_dir, c89, keep_c, include_dirs, defines, targets)


def find_ja(base_dir: Path, requested: str, include_dirs: list[Path] | None = None) -> Path:
    candidates = [base_dir / requested]
    for directory in include_dirs or []:
        candidates.append(directory / requested)

    for candidate in candidates:
        path = candidate.resolve()
        if path.suffix != ".ja":
            path = path.with_suffix(".ja")
        if path.is_file():
            return path

    raise JBSError(f"fichier Jaguar introuvable: {requested}")


def expand_using(source_path: Path, source_text: str, loaded: set[Path], stack: list[Path], include_dirs: list[Path] | None = None) -> str:
    """Expandit récursivement les `using name;`.

    Le fichier courant est conservé sans sa directive `using`. Le contenu du
    fichier importé est placé à l'endroit du using. Les imports déjà chargés
    ne sont pas réinsérés, ce qui évite les doublons lorsque plusieurs fichiers
    importent le même module.
    """
    source_path = source_path.resolve()
    if source_path in stack:
        cycle = " -> ".join(p.name for p in stack + [source_path])
        raise JBSError(f"cycle de using détecté: {cycle}")

    stack.append(source_path)
    output: list[str] = []

    for line in source_text.splitlines(keepends=True):
        match = USING_RE.match(line)
        if not match:
            output.append(line)
            continue

        module_name = match.group(1)
        import_path = find_ja(source_path.parent, module_name, include_dirs)
        if import_path in loaded:
            continue

        loaded.add(import_path)
        imported_text = import_path.read_text(encoding="utf-8")
        output.append(f"// jbs: using {module_name}; -> {import_path.name}\n")
        output.append(expand_using(import_path, imported_text, loaded, stack, include_dirs))
        output.append("\n")

    stack.pop()
    return "".join(output)


def build_target(jbs_path: Path, target: BuildTarget, output_dir: str | None, jcc_path: Path, c89: bool = False, keep_c: bool = False, include_dirs: list[Path] | None = None, defines: list[str] | None = None) -> int:
    base_dir = jbs_path.parent.resolve()

    loaded: set[Path] = set()
    combined_parts: list[str] = [
        "// ============================================================\n",
        "// Fichier généré par Jaguar Build System (JBS 1.0)\n",
        f"// Target: {target.name}\n",
        "// ============================================================\n\n",
    ]
    for define in defines or []:
        combined_parts.append(define + "\n")
    if defines:
        combined_parts.append("\n")

    for filename in target.files:
        path = find_ja(base_dir, filename, include_dirs)
        if path in loaded:
            continue
        loaded.add(path)
        source = path.read_text(encoding="utf-8")
        combined_parts.append(f"// ===== {path.name} =====\n")
        combined_parts.append(expand_using(path, source, loaded, [], include_dirs))
        combined_parts.append("\n\n")

    combined_source = "".join(combined_parts)
    output_base = (base_dir / output_dir).resolve() if output_dir else base_dir
    output_base.mkdir(parents=True, exist_ok=True)
    output_path = output_base / target.name

    # jcc.py accepte un fichier source. On lui donne un fichier temporaire
    # dans le dossier du projet afin que les diagnostics restent faciles à lire.
    temp_path: Path | None = None
    try:
        fd, temp_name = tempfile.mkstemp(
            prefix=f".jbs_{target.name}_",
            suffix=".ja",
            dir=str(base_dir),
            text=True,
        )
        os.close(fd)
        temp_path = Path(temp_name)
        temp_path.write_text(combined_source, encoding="utf-8")

        cmd = [sys.executable, str(jcc_path), str(temp_path), "-o", str(output_path)]
        if c89:
            cmd.insert(-2, "--c89")
        print(f"JBS: compilation de '{target.name}'")
        print("JBS: -> " + " ".join(cmd))
        result = subprocess.run(cmd, cwd=str(base_dir), check=False)

        # JCC génère <sortie>.c avant de compiler l'exécutable. Par défaut,
        # JBS supprime ce fichier une fois la compilation terminée.
        if not keep_c and result.returncode == 0:
            c_path = output_path.with_suffix(".c")
            try:
                c_path.unlink()
                print(f"JBS: suppression de '{c_path.name}'")
            except FileNotFoundError:
                pass
            except OSError as e:
                print(f"JBS: impossible de supprimer '{c_path.name}': {e}", file=sys.stderr)

        return result.returncode
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink()
            except OSError:
                pass


def main(argv: list[str]) -> int:
    args = argv[1:]
    if not args:
        print("Usage: python jbs.py projet.jbs [-o sortie] [--target nom]", file=sys.stderr)
        return 1

    jbs_file: str | None = None
    output: str | None = None
    target_name: str | None = None

    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "-o":
            if i + 1 >= len(args):
                print("Erreur JBS: -o attend un nom de sortie", file=sys.stderr)
                return 1
            output = args[i + 1]
            i += 2
        elif arg == "--target":
            if i + 1 >= len(args):
                print("Erreur JBS: --target attend un nom de target", file=sys.stderr)
                return 1
            target_name = args[i + 1]
            i += 2
        elif arg.startswith("-"):
            print(f"Erreur JBS: option inconnue: {arg}", file=sys.stderr)
            return 1
        elif jbs_file is None:
            jbs_file = arg
            i += 1
        else:
            print(f"Erreur JBS: argument inattendu: {arg}", file=sys.stderr)
            return 1

    if jbs_file is None:
        print("Erreur JBS: aucun fichier .jbs fourni", file=sys.stderr)
        return 1

    jbs_path = Path(jbs_file).resolve()
    if not jbs_path.is_file():
        print(f"Erreur JBS: fichier introuvable: {jbs_file}", file=sys.stderr)
        return 1
    if jbs_path.suffix != ".jbs":
        print("Erreur JBS: le fichier projet doit avoir l'extension .jbs", file=sys.stderr)
        return 1

    try:
        config = parse_jbs(jbs_path.read_text(encoding="utf-8"))
        if output is None:
            output = config.output_dir
        include_dirs = [(jbs_path.parent / d).resolve() for d in config.include_dirs]
        targets = config.targets
        if target_name is None:
            if len(targets) != 1:
                names = ", ".join(t.name for t in targets)
                raise JBSError(
                    f"plusieurs targets disponibles ({names}); utilisez --target <nom>"
                )
            target = targets[0]
        else:
            matches = [t for t in targets if t.name == target_name]
            if not matches:
                raise JBSError(f"target introuvable: {target_name}")
            target = matches[0]

        jcc_path = Path(__file__).resolve().with_name("jcc.py")
        if not jcc_path.is_file():
            raise JBSError(f"jcc.py introuvable à côté de jbs.py: {jcc_path}")

        return build_target(jbs_path, target, output, jcc_path, c89=config.c89, keep_c=config.keep_c, include_dirs=include_dirs, defines=config.defines)
    except (OSError, JBSError) as e:
        print(f"Erreur JBS: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))