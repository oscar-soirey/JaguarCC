#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
jbs.py — Jaguar Build System

Format JBS 1.1 :

jbs 1.0
version 1.2.0

compile example {
    add.ja
    main.ja
}

Directives disponibles en JBS 1.0 :

    jbs 1.0
    version 1.2.0
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
    shell "scripts/build.sh"
    python scripts/generate.py --release
    crimson find SDL2

`jbs` is the JBS format version. `version` is the project's semantic version.
It is exported as `JBS_VERSION` to directives and written into generated C.

`shell` executes a shell command, `python` executes a Python script with the
same interpreter as JBS, and `crimson` invokes Jaguar Package Manager.
Directives execute in source order.

JBS supports both `//` and multiline `/* ... */` comments.

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
import shutil
import shlex
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


class JBSError(Exception):
    def __init__(self, message: str, file: str | None = None, line: int | None = None, column: int | None = None, end_column: int | None = None):
        super().__init__(message)
        self.file = file
        self.line = line
        self.column = column
        self.end_column = end_column


@dataclass
class BuildTarget:
    name: str
    files: list[str]
    kind: str = "compile"  # compile, compile_static, compile_shared
    links: list[str] | None = None
    entry_locations: list[tuple[int, int, int]] | None = None
    declaration_location: tuple[int, int, int] | None = None


@dataclass
class JBSCommand:
    kind: str
    value: str
    line: int
    column: int
    end_column: int


@dataclass
class JBSConfig:
    version: str
    output_dir: str | None
    c89: bool
    keep_c: bool
    include_dirs: list[str]
    defines: list[str]
    targets: list[BuildTarget]
    commands: list[JBSCommand]


JBS_FORMAT_RE = re.compile(r"^\s*jbs\s+([0-9]+(?:\.[0-9]+)+)\s*$", re.MULTILINE)
LEGACY_FORMAT_RE = re.compile(r"^\s*version\s+1\.0\s*$", re.MULTILINE)
VERSION_RE = re.compile(r"^\s*version\s+([0-9]+)\.([0-9]+)\.([0-9]+)\s*$", re.MULTILINE)
COMMAND_RE = re.compile(r'^\s*(shell|python|crimson)\s+(?:"((?:\\\\.|[^"])*)"|(.*?))\s*$', re.MULTILINE)
TARGET_RE = re.compile(
    r"\b(compile_static|compile_shared|compile)\s+([A-Za-z_][A-Za-z0-9_]*)\s*\{"
)
LINK_RE = re.compile(r"\blink\s+([A-Za-z_][A-Za-z0-9_]*)\s*\{")
USING_RE = re.compile(r"^\s*using\s+(?!namespace\b)([A-Za-z_][A-Za-z0-9_]*)\s*;\s*(?://.*)?$")


def strip_jbs_comments(text: str) -> str:
    # Preserve offsets and line numbers while removing both comment styles.
    def replace_comment(match):
        value = match.group(0)
        return "".join("\n" if c == "\n" else " " for c in value)
    return re.sub(r"//[^\n]*|/\\*[\\s\\S]*?\\*/", replace_comment, text)


def _source_position(text: str, offset: int, length: int = 1):
    line = text.count("\n", 0, offset) + 1
    line_start = text.rfind("\n", 0, offset) + 1
    column = offset - line_start
    return line, column, column + max(1, length)


def parse_jbs(text: str) -> JBSConfig:
    clean = strip_jbs_comments(text)

    jbs_match = JBS_FORMAT_RE.search(clean)
    legacy_format_match = LEGACY_FORMAT_RE.search(clean)
    if jbs_match and jbs_match.group(1) != "1.0":
        line, col, end = _source_position(text, jbs_match.start(1), len(jbs_match.group(1)))
        raise JBSError(
            f"unsupported JBS format version: {jbs_match.group(1)} (only 1.0 is supported)",
            line=line, column=col, end_column=end,
        )

    version_matches = list(VERSION_RE.finditer(clean))
    # Old JBS 1.0 files used `version 1.0` as the format marker. Keep them
    # valid while the new three-component form is reserved for project versions.
    if legacy_format_match and not jbs_match and not version_matches:
        version = "0.0.0"
    else:
        version = "0.0.0"
    if len(version_matches) > 1:
        m = version_matches[1]
        line, col, end = _source_position(text, m.start(0), len(m.group(0).strip()))
        raise JBSError("'version' directive defined multiple times", line=line, column=col, end_column=end)

    version = "0.0.0"
    if version_matches:
        m = version_matches[0]
        version = f"{m.group(1)}.{m.group(2)}.{m.group(3)}"

    output_dir: str | None = None
    out_matches = list(re.finditer(r"^\s*out\s+([^\s{}]+)\s*$", clean, re.MULTILINE))
    if len(out_matches) > 1:
        m = out_matches[1]
        line, col, end = _source_position(text, m.start(0), len(m.group(0).strip()))
        raise JBSError("'out' directive defined multiple times", line=line, column=col, end_column=end)
    if out_matches:
        output_dir = out_matches[0].group(1)

    c89 = bool(re.search(r"^\s*c89\s*$", clean, re.MULTILINE))
    keep_c = bool(re.search(r"^\s*keep_c\s*$", clean, re.MULTILINE))

    defines: list[str] = []
    for match in re.finditer(r"^[ \t]*define[ \t]+([A-Za-z_][A-Za-z0-9_]*)(?:[ \t]+([^\r\n]*))?[ \t]*$", clean, re.MULTILINE):
        name = match.group(1)
        value = (match.group(2) or "").strip()
        defines.append(f"#define {name}" + (f" {value}" if value else ""))

    include_dirs: list[str] = []
    include_matches = list(re.finditer(r"^\s*include\s+([^\s{}]+)\s*$", clean, re.MULTILINE))
    for match in include_matches:
        include_dirs.append(match.group(1))
    if len(include_dirs) != len(set(include_dirs)):
        seen = set()
        duplicate = next(m for m in include_matches if m.group(1) in seen or seen.add(m.group(1)))
        line, col, end = _source_position(text, duplicate.start(1), len(duplicate.group(1)))
        raise JBSError("'include' directive defined multiple times for the same path", line=line, column=col, end_column=end)

    commands: list[JBSCommand] = []
    for match in COMMAND_RE.finditer(clean):
        kind = match.group(1)
        value = match.group(2) if match.group(2) is not None else (match.group(3) or "").strip()
        if match.group(2) is not None:
            try:
                value = bytes(value, "utf-8").decode("unicode_escape")
            except UnicodeDecodeError:
                pass
        if not value:
            line, col, end = _source_position(text, match.start(0), len(match.group(0).strip()))
            raise JBSError(f"{kind} directive requires an argument", line=line, column=col, end_column=end)
        line, col, end = _source_position(text, match.start(1), len(match.group(0).strip()))
        commands.append(JBSCommand(kind, value, line, col, end))

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
                name_start = match.start(2)
            else:
                kind = "link"
                name = match.group(1)
                name_start = match.start(1)

            decl_line, decl_col, decl_end = _source_position(text, name_start, len(name))
            brace_start = clean.find("{", match.start(), match.end())
            depth = 1
            i = brace_start + 1
            while i < len(clean) and depth:
                if clean[i] == "{": depth += 1
                elif clean[i] == "}": depth -= 1
                i += 1
            if depth != 0:
                line, col, end = _source_position(text, brace_start, 1)
                raise JBSError(f"{kind} block '{name}' is not closed", line=line, column=col, end_column=end)

            body = clean[brace_start + 1:i - 1]
            entries = []
            entry_locations = []
            local = 0
            for raw_line in body.splitlines(keepends=True):
                stripped = raw_line.strip()
                if stripped:
                    leading = len(raw_line) - len(raw_line.lstrip())
                    abs_start = brace_start + 1 + local + leading
                    line_no, col, end = _source_position(text, abs_start, len(stripped))
                    entries.append(stripped)
                    entry_locations.append((line_no, col, end))
                local += len(raw_line)

            blocks.append((name, kind, entries, entry_locations, (decl_line, decl_col, decl_end)))
            pos = i
        return blocks

    target_blocks = parse_blocks(TARGET_RE, "target")
    link_blocks = parse_blocks(LINK_RE, "link")

    if not target_blocks:
        line = 1
        nonempty = re.search(r"^\s*\S.*$", text, re.MULTILINE)
        if nonempty:
            line, _, _ = _source_position(text, nonempty.start(0), 1)
        raise JBSError(
            "no 'compile <name> { ... }', "
            "'compile_static <name> { ... }' or "
            "'compile_shared <name> { ... }' block found",
            line=line, column=0, end_column=max(1, len(text.splitlines()[line-1].strip()) if text.splitlines() else 1)
        )

    link_map: dict[str, list[str]] = {}
    for name, _, entries, _, decl_loc in link_blocks:
        if name in link_map:
            raise JBSError(f"link block '{name}' defined multiple times", line=decl_loc[0], column=decl_loc[1], end_column=decl_loc[2])
        link_map[name] = entries

    for name, kind, entries, entry_locations, decl_loc in target_blocks:
        files: list[str] = []
        for idx, line in enumerate(entries):
            if Path(line).suffix.lower() not in (".ja", ".jah"):
                loc = entry_locations[idx]
                raise JBSError(
                    f"invalid entry in {kind} {name}: '{line}' "
                    f"(expected: a .ja or .jah file)",
                    line=loc[0], column=loc[1], end_column=loc[2]
                )
            files.append(line)

        if not files:
            raise JBSError(f"{kind} block '{name}' contains no .ja or .jah files", line=decl_loc[0], column=decl_loc[1], end_column=decl_loc[2])

        targets.append(BuildTarget(name, files, kind, link_map.get(name, []), entry_locations, decl_loc))

    return JBSConfig(version, output_dir, c89, keep_c, include_dirs, defines, targets, commands)


def find_ja(base_dir: Path, requested: str, include_dirs: list[Path] | None = None, origin=None) -> Path:
    candidates = [base_dir / requested]
    for directory in include_dirs or []:
        candidates.append(directory / requested)

    for candidate in candidates:
        path = candidate.resolve()
        variants = [path] if path.suffix.lower() in (".ja", ".jah") else [path.with_suffix(".ja"), path.with_suffix(".jah")]
        for variant in variants:
            if variant.is_file():
                return variant

    if origin:
        raise JBSError(f"Jaguar file not found: {requested}", file=origin[0], line=origin[1], column=origin[2], end_column=origin[3])
    raise JBSError(f"Jaguar file not found: {requested}")


def expand_using(source_path: Path, source_text: str, loaded: set[Path], stack: list[Path], include_dirs: list[Path] | None = None, origin=None) -> str:
    """Expandit récursivement les `using name;` et conserve la provenance exacte de chaque ligne Jaguar."""
    source_path = source_path.resolve()
    if source_path in stack:
        cycle = " -> ".join(p.name for p in stack + [source_path])
        if origin:
            raise JBSError(f"using cycle detected: {cycle}", file=origin[0], line=origin[1], column=origin[2], end_column=origin[3])
        raise JBSError(f"using cycle detected: {cycle}")

    stack.append(source_path)
    output: list[str] = []

    line_no = 0
    for line in source_text.splitlines(keepends=True):
        line_no += 1
        match = USING_RE.match(line)
        if not match:
            output.append(f"// jbs:source {source_path.name}:{line_no}\n")
            output.append(line)
            continue

        module_name = match.group(1)
        leading = len(line) - len(line.lstrip())
        using_col = leading
        using_end = using_col + len(match.group(0).strip())
        imported_origin = (source_path.name, line_no, using_col, max(using_col + 1, using_end))
        import_path = find_ja(source_path.parent, module_name, include_dirs, imported_origin)
        if import_path in loaded:
            continue

        loaded.add(import_path)
        imported_text = import_path.read_text(encoding="utf-8")
        output.append(f"// jbs: using {module_name}; -> {import_path.name}\n")
        output.append(expand_using(import_path, imported_text, loaded, stack, include_dirs, imported_origin))
        output.append("\n")

    stack.pop()
    return "".join(output)


def toolchain_bin(jbs_path: Path) -> Path:
    # The bundled toolchain is part of the Jaguar distribution. It is resolved
    # relative to this Python file, never through PATH.
    return Path(__file__).resolve().parent / "toolchain" / "bin"


def toolchain_exe(name: str) -> Path:
    suffix = ".exe" if os.name == "nt" else ""
    return Path(__file__).resolve().parent / "toolchain" / "bin" / (name + suffix)


def find_crimson() -> list[str]:
    """Find Crimson either on PATH or next to jbs.py."""
    for name in ("crimson", "crimson.exe"):
        found = shutil.which(name)
        if found:
            return [found]
    local = Path(__file__).resolve().with_name("crimson.py")
    if local.is_file():
        return [sys.executable, str(local)]
    raise JBSError(
        "Crimson package manager not found. Put 'crimson' on PATH or place crimson.py next to jbs.py."
    )


def run_jbs_commands(commands: list[JBSCommand], base_dir: Path, version: str) -> int:
    """Execute shell/python/crimson directives in source order."""
    env = os.environ.copy()
    env["JBS_VERSION"] = version
    env["JBS_PROJECT_DIR"] = str(base_dir)

    for command in commands:
        print(f"JBS: {command.kind} -> {command.value}")
        try:
            if command.kind == "shell":
                result = subprocess.run(command.value, cwd=str(base_dir), env=env, shell=True, check=False)
            elif command.kind == "python":
                parts = shlex.split(command.value, posix=(os.name != "nt"))
                if not parts:
                    raise JBSError("python directive requires a script", line=command.line, column=command.column, end_column=command.end_column)
                result = subprocess.run([sys.executable, *parts], cwd=str(base_dir), env=env, check=False)
            elif command.kind == "crimson":
                parts = shlex.split(command.value, posix=(os.name != "nt"))
                if not parts:
                    raise JBSError("crimson directive requires arguments", line=command.line, column=command.column, end_column=command.end_column)
                result = subprocess.run([*find_crimson(), *parts], cwd=str(base_dir), env=env, check=False)
            else:
                raise JBSError(f"unknown JBS directive: {command.kind}")
        except ValueError as e:
            raise JBSError(str(e), line=command.line, column=command.column, end_column=command.end_column)

        if result.returncode != 0:
            print(f"JBS Error: {command.kind} directive failed with exit code {result.returncode}", file=sys.stderr)
            return result.returncode
    return 0


def build_target(
    jbs_path: Path,
    target: BuildTarget,
    output_dir: str | None,
    jcc_path: Path,
    c89: bool = False,
    keep_c: bool = False,
    include_dirs: list[Path] | None = None,
    defines: list[str] | None = None,
    jbs_version: str = "0.0.0",
) -> int:
    base_dir = jbs_path.parent.resolve()

    loaded: set[Path] = set()
    combined_parts: list[str] = [
        "// ============================================================\n",
        "// Fichier généré par Jaguar Build System (JBS 1.0)\n",
        f"// Target: {target.name}\n",
        f"// Project version: {jbs_version}\n",
        "// ============================================================\n\n",
    ]
    for define in defines or []:
        combined_parts.append(define + "\n")
    if defines:
        combined_parts.append("\n")

    for file_index, filename in enumerate(target.files):
        origin = None
        if target.entry_locations and file_index < len(target.entry_locations):
            line, col, end = target.entry_locations[file_index]
            origin = (jbs_path.name, line, col, end)
        path = find_ja(base_dir, filename, include_dirs, origin)
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
        print(f"JBS: compiling '{target.name}' ({target.kind})")
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
            raise JBSError(f"jcc did not generate the expected C file: {c_path}")

        # Second stage: C -> requested artifact.
        if target.kind == "compile":
            gcc_cmd = [str(toolchain_exe("gcc")), str(c_path), "-o", str(output_path)]
            for lib in target.links or []:
                gcc_cmd.append(resolve_link_arg(lib, output_base, base_dir))

        elif target.kind == "compile_static":
            obj_path = output_base / f"{target.name}.o"
            archive_path = output_base / f"lib{target.name}.a"

            gcc_cmd = [str(toolchain_exe("gcc")), "-c", str(c_path), "-o", str(obj_path)]
            if c89:
                gcc_cmd.insert(1, "-std=c89")

            print("JBS: C -> object")
            result = subprocess.run(gcc_cmd, cwd=str(base_dir), check=False)
            if result.returncode != 0:
                if not keep_c:
                    try: c_path.unlink()
                    except OSError: pass
                return result.returncode

            ar_exe = toolchain_exe("ar")
            if not ar_exe.is_file():
                if not keep_c:
                    try: c_path.unlink()
                    except OSError: pass
                raise JBSError(f"ar toolchain not found: {ar_exe}")

            ar_cmd = [str(toolchain_exe("ar")), "rcs", str(archive_path), str(obj_path)]
            print("JBS: object -> static library")
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

            print(f"JBS: static library -> '{archive_path}'")
            return 0

        elif target.kind == "compile_shared":
            if os.name == "nt":
                dll_path = output_base / f"{target.name}.dll"
                import_lib = output_base / f"{target.name}.dll.a"
                gcc_cmd = [
                    str(toolchain_exe("gcc")),
                    "-shared",
                    str(c_path),
                    "-o",
                    str(dll_path),
                    f"-Wl,--out-implib,{import_lib}",
                ]
            else:
                shared_path = output_base / f"lib{target.name}.so"
                gcc_cmd = [str(toolchain_exe("gcc")), "-shared", "-fPIC", str(c_path), "-o", str(shared_path)]

            for lib in target.links or []:
                gcc_cmd.append(resolve_link_arg(lib, output_base, base_dir))

        else:
            raise JBSError(f"unknown target type: {target.kind}")

        print("JBS: C -> final output")
        gcc_exe = toolchain_exe("gcc")
        if not gcc_exe.is_file():
            if not keep_c:
                try: c_path.unlink()
                except OSError: pass
            raise JBSError(f"GCC toolchain not found: {gcc_exe}")
        result = subprocess.run(gcc_cmd, cwd=str(base_dir), check=False)

        if result.returncode == 0:
            print(f"JBS: output -> '{output_path}'")

        if not keep_c:
            try:
                c_path.unlink()
                print(f"JBS: removed '{c_path.name}'")
            except FileNotFoundError:
                pass
            except OSError as e:
                print(
                    f"JBS: failed to remove '{c_path.name}': {e}",
                    file=sys.stderr,
                )

        return result.returncode

    finally:
        if temp_path is not None:
            try:
                temp_path.unlink()
            except OSError:
                pass


def resolve_link_arg(value: str, output_base: Path, base_dir: Path) -> str:
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
        # A project file literally named `.jbs` is valid and can be auto-discovered
        # when it is the only conventional project file in the current directory.
        default_jbs = Path(".jbs").resolve()
        if default_jbs.is_file():
            args = [".jbs"]
        else:
            print("Usage: python jbs.py project.jbs [-o output] [--target name]", file=sys.stderr)
            return 1

    jbs_file: str | None = None
    output: str | None = None
    target_name: str | None = None

    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "-o":
            if i + 1 >= len(args):
                print("JBS Error: -o expects an output name", file=sys.stderr)
                return 1
            output = args[i + 1]
            i += 2
        elif arg == "--target":
            if i + 1 >= len(args):
                print("JBS Error: --target expects a target name", file=sys.stderr)
                return 1
            target_name = args[i + 1]
            i += 2
        elif arg.startswith("-"):
            print(f"JBS Error: unknown option: {arg}", file=sys.stderr)
            return 1
        elif jbs_file is None:
            jbs_file = arg
            i += 1
        else:
            print(f"JBS Error: unexpected argument: {arg}", file=sys.stderr)
            return 1

    if jbs_file is None:
        print("JBS Error: no .jbs file provided", file=sys.stderr)
        return 1

    jbs_path = Path(jbs_file).resolve()
    if not jbs_path.is_file():
        print(f"JBS Error: file not found: {jbs_file}", file=sys.stderr)
        return 1
    if jbs_path.suffix != ".jbs" and jbs_path.name != ".jbs":
        print("JBS Error: project file must have the .jbs extension", file=sys.stderr)
        return 1

    try:
        config = parse_jbs(jbs_path.read_text(encoding="utf-8"))
        if output is None:
            output = config.output_dir
        include_dirs = [(jbs_path.parent / d).resolve() for d in config.include_dirs]
        targets = config.targets

        command_result = run_jbs_commands(config.commands, jbs_path.parent.resolve(), config.version)
        if command_result != 0:
            return command_result

        if target_name is not None:
            matches = [t for t in targets if t.name == target_name]
            if not matches:
                raise JBSError(f"target not found: {target_name}")
            targets_to_build = [matches[0]]
        else:
            # Sans --target, on construit tous les targets dans l'ordre du
            # fichier JBS. Cela permet notamment de construire une bibliothèque
            # puis l'exécutable qui la référence.
            targets_to_build = targets

        jcc_path = Path(__file__).resolve().with_name("jcc.py")
        if not jcc_path.is_file():
            raise JBSError(f"jcc.py not found next to jbs.py: {jcc_path}")

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
                jbs_version=config.version,
            )
            if result != 0:
                return result
        return 0
    except (OSError, JBSError) as e:
        if isinstance(e, JBSError) and e.line is not None:
            file_name = e.file or jbs_path.name
            column = (e.column or 0) + 1
            print(f"JBS Error: {file_name}:{e.line}:{column}: {e}", file=sys.stderr)
        else:
            print(f"JBS Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
