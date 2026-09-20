# Jaguar Language 1.1.0

Version 1.0.2 adds dedicated `.ja`, `.jah`, and `.jbs` icons, while keeping the existing completion and build behavior. completion behavior in VS Code. Automatic completion suggestions are no longer pre-selected for Jaguar (`.ja`, `.jah`) and JBS (`.jbs`) files. Pressing **Enter** therefore inserts a new line unless a completion item has been explicitly selected (for example with the arrow keys). Once an item is selected, **Enter** accepts it as usual.

The extension also provides syntax highlighting, language-server completion, JBS completion, Jaguar file icons, build commands, and configurable Jaguar tool paths.

Official website: https://oscar-soirey.github.io/JaguarCC/


VS Code support for the Jaguar programming language and the Jaguar Build System (JBS).

## Official website

[JaguarCC](https://oscar-soirey.github.io/JaguarCC/)

## Features

- Syntax highlighting for `.ja` / `.jah`.
- Completion, hover, and definition support for Jaguar.
- Syntax highlighting and completion for `.jbs`.
- Jaguar icons for `.ja`, `.jah`, and `.jbs` without replacing the user's VS Code File Icon Theme.
- Jaguar logo as the VS Code extension icon.
- `Jaguar: Build Project` command in the editor.
- `Jaguar: Build & Run` command.

## JCC and JBS

**JCC and JBS are not bundled with the extension.**

The VS Code extension is separate from the Jaguar tools. The same tools directory should contain `jcc.py`, `jbs.py`, and `jlanguage_server.py`. The extension launches the external language server from that directory. **JBS remains fully responsible for invoking JCC and handling all build parameters.**

To build a project, the extension intentionally runs exactly:

```text
python jbs.py project.jbs
```

The extension does not add `--jcc`, `--target`, or any other JBS option.

## VS Code settings

The build-related settings are:

```json
"jaguar.buildSystem.python": "python",
"jaguar.buildSystem.toolsDirectory": "",
"jaguar.buildSystem.project": ""
```

### `jaguar.buildSystem.python`

Python executable used to launch JBS. The default is `python`.

### External Language Server

Since 1.1.0, the language server is **not bundled with the VS Code extension**. Install the Jaguar tools together in one directory:

```text
jcc.py
jbs.py
jlanguage_server.py
```

The extension starts the server with:

```powershell
python jlanguage_server.py
```

By default, `jlanguage_server.py` is resolved from `jaguar.buildSystem.toolsDirectory`. You can override it with `jaguar.languageServer.path`. The external language server loads `jcc.py` from its own directory.

### `jaguar.buildSystem.toolsDirectory`

Path to the directory containing `jcc.py`, `jbs.py`, `jlanguage_server.py`, and the other Jaguar tools. This must be configured manually.

Example:

```text
C:\Users\User\Desktop\Jaguar\JaguarCC
```

### `jaguar.buildSystem.project`

Optional path to the `.jbs` file to build. If empty, the extension uses the active `.jbs` file or searches for `.jbs` files in the current directory. It does not search parent directories. If no `.jbs` file is found in the current directory, the build reports an error.

## JBS completion

A file such as:

```jbs
version 1.0
out build
include lib
define DEBUG
c89
keep_c

compile game {
    main.ja
    player.ja
}
```

receives completion suggestions for JBS directives, the `1.0` version, target names, and Jaguar source files present in the project directory.

## Build

`Jaguar: Build Project` is available from `.ja`, `.jah`, and `.jbs` files.

Shortcut: `Ctrl+Alt+B`.

The terminal command is:

```text
python jbs.py project.jbs
```

## Build & Run

`Jaguar: Build & Run` uses the same JBS build command as a normal build and then runs the resulting application from the integrated terminal.

Shortcut: `Ctrl+Alt+R`.

## Icons

Dedicated icons are used for `.ja`, `.jah`, and `.jbs` files, and the Jaguar logo is used as the VS Code extension icon.

The extension does **not** contribute a complete File Icon Theme, so it does not replace icons for other file types or extensions.
