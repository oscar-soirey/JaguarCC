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
    compile_static MyLib { ... }
    compile_shared MyLib { ... }
    link game { MyLib libOther.a -lSDL2 }

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
    kind: str = "compile"  # compile, compile_static, compile_shared
    links: list[str] | None = None


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
TARGET_RE = re.compile(
    r"\b(compile_static|compile_shared|compile)\s+([A-Za-z_][A-Za-z0-9_]*)\s*\{"
)
LINK_RE = re.compile(r"\blink\s+([A-Za-z_][A-Za-z0-9_]*)\s*\{")
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

    def parse_blocks(regex, block_kind):
        blocks = []
        pos = 0
        while True:
            match = regex.search(clean, pos)
            if not match:
                break

            if block_kind == "target":
                kind = match.group(1)
                name = match.group(2)
            else:
                kind = "link"
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
                raise JBSError(f"bloc {kind} '{name}' non fermé")

            body = clean[brace_start + 1:i - 1]
            entries = []
            for raw_line in body.splitlines():
                line = raw_line.strip()
                if line:
                    entries.append(line)

            blocks.append((name, kind, entries))
            pos = i
        return blocks

    target_blocks = parse_blocks(TARGET_RE, "target")
    link_blocks = parse_blocks(LINK_RE, "link")

    if not target_blocks:
        raise JBSError(
            "aucun bloc 'compile <nom> { ... }', "
            "'compile_static <nom> { ... }' ou "
            "'compile_shared <nom> { ... }' trouvé"
        )

    link_map: dict[str, list[str]] = {}
    for name, _, entries in link_blocks:
        if name in link_map:
            raise JBSError(f"bloc link '{name}' défini plusieurs fois")
        link_map[name] = entries

    for name, kind, entries in target_blocks:
        files: list[str] = []
        for line in entries:
            if not line.endswith(".ja"):
                raise JBSError(
                    f"entrée invalide dans {kind} {name}: '{line}' "
                    f"(attendu: un fichier .ja)"
                )
            files.append(line)

        if not files:
            raise JBSError(f"le bloc {kind} '{name}' ne contient aucun fichier .ja")

        targets.append(BuildTarget(name, files, kind, link_map.get(name, [])))

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


def build_target(
    jbs_path: Path,
    target: BuildTarget,
    output_dir: str | None,
    jcc_path: Path,
    c89: bool = False,
    keep_c: bool = False,
    include_dirs: list[Path] | None = None,
    defines: list[str] | None = None,
) -> int:
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

    # JCC output stem is always target.name.
    output_path = output_base / target.name
    c_path = output_path.with_suffix(".c")

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

        # First stage: Jaguar -> C.
        # For executable targets, jcc can compile directly. For library
        # targets, jcc must ONLY emit C because there is no main/WinMain.
        print(f"JBS: compilation de '{target.name}' ({target.kind})")
        print("JBS: Jaguar -> C")

        # JCC ne fait ici que Jaguar -> C. Le lien final est toujours fait
        # par GCC afin que les directives `link` fonctionnent aussi pour les
        # exécutables.
        jcc_cmd = [sys.executable, str(jcc_path), str(temp_path)]
        if c89:
            jcc_cmd.append("--c89")
        with open(c_path, "w", encoding="utf-8", newline="") as c_file:
            result = subprocess.run(
                jcc_cmd,
                cwd=str(base_dir),
                stdout=c_file,
                check=False,
            )
        if result.returncode != 0:
            return result.returncode

        if not c_path.is_file():
            raise JBSError(f"jcc n'a pas généré le fichier C attendu: {c_path}")

        # Second stage: C -> requested artifact.
        include_flags = []
        for inc in include_dirs or []:
            include_flags.extend(["-I", str(inc)])

        if target.kind == "compile":
            gcc_cmd = ["gcc", *include_flags, str(c_path), "-o", str(output_path)]
            for lib in target.links or []:
                gcc_cmd.append(resolve_link_arg(lib, output_base, base_dir, include_dirs))

        elif target.kind == "compile_static":
            obj_path = output_base / f"{target.name}.o"
            archive_path = output_base / f"lib{target.name}.a"

            gcc_cmd = ["gcc", *include_flags, "-c", str(c_path), "-o", str(obj_path)]
            if c89:
                gcc_cmd.insert(1, "-std=c89")

            print("JBS: C -> objet")
            result = subprocess.run(gcc_cmd, cwd=str(base_dir), check=False)
            if result.returncode != 0:
                return result.returncode

            ar_cmd = ["ar", "rcs", str(archive_path), str(obj_path)]
            print("JBS: objet -> bibliothèque statique")
            result = subprocess.run(ar_cmd, cwd=str(base_dir), check=False)

            try:
                obj_path.unlink()
            except OSError:
                pass

            if result.returncode != 0:
                return result.returncode

            if not keep_c:
                try:
                    c_path.unlink()
                except OSError:
                    pass

            print(f"JBS: bibliothèque statique -> '{archive_path}'")
            return 0

        elif target.kind == "compile_shared":
            if os.name == "nt":
                dll_path = output_base / f"{target.name}.dll"
                import_lib = output_base / f"{target.name}.dll.a"
                gcc_cmd = [
                    "gcc",
                    *include_flags,
                    "-shared",
                    str(c_path),
                    "-o",
                    str(dll_path),
                    f"-Wl,--out-implib,{import_lib}",
                ]
            else:
                shared_path = output_base / f"lib{target.name}.so"
                gcc_cmd = ["gcc", *include_flags, "-shared", "-fPIC", str(c_path), "-o", str(shared_path)]

            for lib in target.links or []:
                gcc_cmd.append(resolve_link_arg(lib, output_base, base_dir, include_dirs))

        else:
            raise JBSError(f"type de target inconnu: {target.kind}")

        print("JBS: C -> sortie finale")
        result = subprocess.run(gcc_cmd, cwd=str(base_dir), check=False)

        if result.returncode == 0:
            print(f"JBS: sortie -> '{output_path}'")

        if not keep_c and result.returncode == 0:
            try:
                c_path.unlink()
                print(f"JBS: suppression de '{c_path.name}'")
            except FileNotFoundError:
                pass
            except OSError as e:
                print(
                    f"JBS: impossible de supprimer '{c_path.name}': {e}",
                    file=sys.stderr,
                )

        return result.returncode

    finally:
        if temp_path is not None:
            try:
                temp_path.unlink()
            except OSError:
                pass


def resolve_link_arg(value: str, output_base: Path, base_dir: Path, include_dirs=None) -> str:
    """Transforme une entrée JBS link en argument GCC.

    Exemples:
      MyLib       -> -lMyLib
      libMyLib.a -> chemin vers libMyLib.a si présent dans out/
      MyLib.lib  -> chemin vers MyLib.lib si présent dans out/
      -lSDL2      -> -lSDL2
      -Llibs      -> -Llibs
      chemin/... -> chemin tel quel
    """
    value = value.strip()
    if not value:
        return value

    if value.startswith("-"):
        return value

    candidates = [
        output_base / value,
        base_dir / value,
    ]
    for inc in include_dirs or []:
        candidates.append(Path(inc) / value)

    # Alias pratiques :
    #   MyLib.a -> libMyLib.a
    #   MyLib   -> libMyLib.a / MyLib.lib / ...
    value_path = Path(value)
    if value_path.suffix == ".a":
        stem = value_path.stem
        candidates.append(output_base / f"lib{stem}.a")
    elif value_path.suffix == ".so":
        stem = value_path.stem
        candidates.append(output_base / f"lib{stem}.so")
    elif value_path.suffix == ".lib":
        stem = value_path.stem
        candidates.append(output_base / f"lib{stem}.lib")

    candidates.extend([
        output_base / f"lib{value}.a",
        output_base / f"{value}.lib",
        output_base / f"lib{value}.lib",
        output_base / f"lib{value}.so",
        output_base / f"{value}.dll.a",
    ])

    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)

    # Une bibliothèque sans extension est traitée comme un nom GCC.
    if not Path(value).suffix and "/" not in value and "\\" not in value:
        return f"-l{value}"

    return value


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

        if target_name is not None:
            matches = [t for t in targets if t.name == target_name]
            if not matches:
                raise JBSError(f"target introuvable: {target_name}")
            targets_to_build = [matches[0]]
        else:
            # Sans --target, on construit tous les targets dans l'ordre du
            # fichier JBS. Cela permet notamment de construire une bibliothèque
            # puis l'exécutable qui la référence.
            targets_to_build = targets

        jcc_path = Path(__file__).resolve().with_name("jcc.py")
        if not jcc_path.is_file():
            raise JBSError(f"jcc.py introuvable à côté de jbs.py: {jcc_path}")

        for target in targets_to_build:
            result = build_target(
                jbs_path,
                target,
                output,
                jcc_path,
                c89=config.c89,
                keep_c=config.keep_c,
                include_dirs=include_dirs,
                defines=config.defines,
            )
            if result != 0:
                return result
        return 0
    except (OSError, JBSError) as e:
        print(f"Erreur JBS: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
