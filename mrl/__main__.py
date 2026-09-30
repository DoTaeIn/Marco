"""MRL compiler, native builder, and small command-line driver."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from .c_backend import emit_c

_IMPORT = re.compile(r'^\s*import\s+"([^"\\\r\n]+)"(?:\s+as\s+([A-Za-z_][A-Za-z0-9_]*))?\s*$')
_COMMANDS = {"check", "build", "run", "test"}
_DECLARATION_WORDS = {"fn", "struct", "relation", "graph", "enum"}


def _mask_comments(source: str):
    chars = list(source)
    index = 0
    while index < len(chars):
        if chars[index] == '"':
            index += 1
            while index < len(chars):
                if chars[index] == "\\":
                    index += 2
                elif chars[index] == '"':
                    index += 1
                    break
                else:
                    index += 1
            continue
        if chars[index] == "#":
            end = source.find("#", index + 1)
            end = len(chars) - 1 if end < 0 else end
            for cursor in range(index, end + 1):
                if chars[cursor] != "\n":
                    chars[cursor] = " "
            index = end + 1
            continue
        index += 1
    return "".join(chars)


def _tokens(source: str):
    """Yield source tokens while skipping strings and paired # comments."""
    index = 0
    while index < len(source):
        char = source[index]
        if char.isspace():
            index += 1
            continue
        if char == '"':
            start = index
            index += 1
            while index < len(source):
                if source[index] == "\\":
                    index += 2
                elif source[index] == '"':
                    index += 1
                    break
                else:
                    index += 1
            yield start, index, "string"
            continue
        if char == "#":
            end = source.find("#", index + 1)
            index = len(source) if end < 0 else end + 1
            continue
        match = re.match(r"[A-Za-z_][A-Za-z0-9_]*", source[index:])
        if match:
            end = index + len(match.group(0))
            yield index, end, match.group(0)
            index = end
        else:
            yield index, index + 1, char
            index += 1


def _identifier_spans(source: str):
    return [token for token in _tokens(source) if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", token[2])]


def _replace_spans(source: str, replacements):
    pieces, mapping, cursor = [], [], 0
    for (start, end), replacement in sorted(replacements.items()):
        pieces.append(source[cursor:start])
        mapping.extend(range(cursor, start))
        pieces.append(replacement)
        mapping.extend([start] * len(replacement))
        cursor = end
    pieces.append(source[cursor:])
    mapping.extend(range(cursor, len(source)))
    return "".join(pieces), mapping


def _mangle_module(source: str, prefix: str):
    tokens = list(_tokens(source))
    names = [token[2] for token in tokens]
    depth, depths = 0, []
    for token in tokens:
        depths.append(depth)
        if token[2] == "{":
            depth += 1
        elif token[2] == "}":
            depth = max(0, depth - 1)
    declarations = {names[i] for i in range(1, len(tokens)) if depths[i] == 0 and names[i - 1] in _DECLARATION_WORDS}
    if not declarations:
        return source, list(range(len(source)))
    field_indices = {i for i in range(1, len(tokens)) if names[i - 1] == "."}
    field_indices.update(i for i in range(len(tokens) - 1) if names[i + 1] in {":", "="})
    # Local bindings apply from their declaration through the current block.
    # Keep this token pass aligned with the parser; strings/comments are absent.
    blocks, stack = {}, []
    for i, name in enumerate(names):
        if name == "{": stack.append(i)
        elif name == "}" and stack: blocks[stack.pop()] = i
    local_ranges = []
    for i, token in enumerate(tokens):
        if depths[i] != 0 or token[2] != "fn" or i + 1 >= len(tokens) or (i and names[i - 1] == "extern"):
            continue
        open_paren = next(j for j in range(i + 1, len(tokens)) if names[j] == "(")
        open_body = next(j for j in range(open_paren, len(tokens)) if names[j] == "{")
        close_body = blocks[open_body]
        params = {names[j] for j in range(open_paren + 1, open_body - 1) if names[j + 1] == ":"}
        local_ranges.extend((name, open_paren, close_body) for name in params)
        scopes, parens = [close_body], 0
        for j in range(open_body + 1, close_body):
            name = names[j]
            if name == "{": scopes.append(blocks[j])
            elif name == "}": scopes.pop()
            elif name == "(": parens += 1
            elif name == ")": parens -= 1
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name): continue
            if parens == 0 and names[j + 1] == "=":
                local_ranges.append((name, j, scopes[-1]))
            elif parens == 0 and names[j + 1] == ":":
                k = j + 2
                while k < close_body and names[k] not in {"=", ":", "{", "}", "(", ")", ";"}: k += 1
                if names[k] == "=": local_ranges.append((name, j, scopes[-1]))
            elif name == "for" and names[j + 1] == "(":
                body = next(k for k in range(j + 2, close_body) if names[k] == "{")
                local_ranges.append((names[j + 2], j + 2, blocks[body]))
            elif name in {"Some", "Ok", "Err"} and names[j + 1] == "(":
                if j + 4 < close_body and names[j + 3:j + 5] == [")", "{"]:
                    local_ranges.append((names[j + 2], j + 2, blocks[j + 4]))
    replacements = {}
    for i, (start, end, name) in enumerate(tokens):
        if name not in declarations:
            continue
        declaration = i and names[i - 1] in _DECLARATION_WORDS and depths[i] == 0
        call = i + 1 < len(tokens) and names[i + 1] == "("
        if declaration or (i not in field_indices and (call or not any(local == name and start <= i <= end for local, start, end in local_ranges))):
            replacements[(start, end)] = f"{prefix}__{name}"
    return _replace_spans(source, replacements)


def _qualify_aliases(source: str, aliases: dict[str, str]) -> str:
    spans = list(_identifier_spans(source))
    replacements = {}
    for index, (start, end, name) in enumerate(spans):
        if name not in aliases or index + 1 >= len(spans):
            continue
        next_start, next_end, member = spans[index + 1]
        if source[end:next_start].strip() == ".":
            replacements[(start, next_end)] = f"{aliases[name]}__{member}"
    return _replace_spans(source, replacements)


def _load_source_with_map(path):
    """Expand relative imports and retain original file/line diagnostics."""
    loaded, active = set(), []

    def expand(path: Path, prefix: str | None = None):
        path = path.resolve()
        key = (path, prefix)
        if path in active:
            raise ValueError("cyclic module import: " + " -> ".join(str(item) for item in (*active, path)))
        if key in loaded:
            return []
        active.append(path)
        raw = path.read_text(encoding="utf-8")
        visible = _mask_comments(raw).splitlines()
        body, body_locations, aliases, alias_targets, output = [], [], {}, {}, []
        for line_number, (line, import_line) in enumerate(zip(raw.splitlines(), visible), 1):
            match = _IMPORT.fullmatch(import_line)
            if match:
                name, alias = match.groups()
                relative = Path(name)
                target = (path.parent / relative).resolve()
                if relative.is_absolute() or target.suffix != ".mrl" or not target.is_file():
                    raise ValueError(f"invalid module import {name!r}")
                if alias:
                    if alias in alias_targets and alias_targets[alias] != target:
                        raise ValueError(f"duplicate module alias {alias!r}")
                    alias_targets[alias] = target
                    module_prefix = f"{prefix}__{alias}" if prefix else alias
                    output.extend(expand(target, module_prefix))
                    aliases[alias] = module_prefix
                else:
                    output.extend(expand(target, prefix))
                continue
            body.append(line + "\n")
            body_locations.append((path, line_number))
        text, column_map = _mangle_module("".join(body), prefix) if prefix else ("".join(body), list(range(len("".join(body)))))
        text, qualification_map = _qualify_aliases(text, aliases)
        composed = [column_map[index] for index in qualification_map]
        line_start = 0
        original_starts = [0]
        for match in re.finditer("\n", "".join(body)):
            original_starts.append(match.end())
        for row, (line, location) in enumerate(zip(text.splitlines(keepends=True), body_locations)):
            line_map = [index - original_starts[row] for index in composed[line_start:line_start + len(line.rstrip("\r\n"))]]
            output.append((line, (location[0], location[1], line_map)))
            line_start += len(line)
        active.pop()
        loaded.add(key)
        return output

    rows = expand(Path(path).resolve())
    return "".join(line for line, _ in rows), [location for _, location in rows]


def _load_source(path, seen=()):
    del seen
    return _load_source_with_map(path)[0]


def _source_error(error, locations):
    if not locations:
        return error
    index = min(max(error.line, 1), len(locations)) - 1
    location = locations[index]
    path, line = location[:2]
    column = error.column
    if len(location) > 2 and location[2]:
        column = location[2][min(max(error.column - 1, 0), len(location[2]) - 1)] + 1
    return ValueError(f"{path}:{line}:{column}: {error.message}")


def _source_and_c(source_path: Path):
    if source_path.suffix != ".mrl":
        raise ValueError("source must have a .mrl extension")
    from .frontend import MrlError, compile_source
    expanded, locations = _load_source_with_map(source_path)
    try:
        return emit_c(compile_source(expanded)), locations
    except MrlError as error:
        raise _source_error(error, locations) from error


def _atomic_write(path: Path, data: str):
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(data)
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _module_paths(source: Path):
    paths, active = {source.resolve()}, set()

    def visit(path):
        path = path.resolve()
        if path in active:
            return
        active.add(path)
        try:
            for line in _mask_comments(path.read_text(encoding="utf-8")).splitlines():
                match = _IMPORT.fullmatch(line)
                if match:
                    target = (path.parent / match.group(1)).resolve()
                    if target.suffix == ".mrl" and target.is_file():
                        paths.add(target)
                        visit(target)
        finally:
            active.discard(path)

    visit(source)
    return paths


def _safe_output(source: Path, output: Path):
    output = output.resolve()
    modules = _module_paths(source)
    if output in modules or any(candidate.exists() and output.exists() and candidate.samefile(output) for candidate in modules):
        raise ValueError(f"refusing to overwrite MRL source or imported module: {output}")
    return output


def _compiler_error(error):
    if isinstance(error, subprocess.TimeoutExpired):
        return f"native compiler timed out after {error.timeout}s"
    if isinstance(error, subprocess.CalledProcessError):
        details = error.stderr or error.stdout or b""
        if isinstance(details, bytes):
            details = details.decode(errors="replace")
        return details.strip() or f"native compiler exited with status {error.returncode}"
    return str(error)


def _legacy(argv):
    parser = argparse.ArgumentParser(prog="python -m mrl")
    parser.add_argument("source")
    parser.add_argument("-o", "--output", required=True)
    args = parser.parse_args(argv)
    source = Path(args.source)
    output = _safe_output(source, Path(args.output))
    c_text, _ = _source_and_c(source)
    _atomic_write(output, c_text)
    return 0


def _new_cli(argv):
    parser = argparse.ArgumentParser(prog="python -m mrl")
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check", help="parse and type-check an MRL source")
    check.add_argument("source", type=Path)
    build = commands.add_parser("build", help="compile MRL to a native executable")
    build.add_argument("source", type=Path)
    build.add_argument("-o", "--output", type=Path)
    build.add_argument("--emit-c", type=Path, help="also retain generated C at this path")
    build.add_argument("--optimization", choices=("release", "debug"), default="release")
    run = commands.add_parser("run", help="build and run MRL")
    run.add_argument("source", type=Path)
    run.add_argument("--optimization", choices=("release", "debug"), default="release")
    run.add_argument("args", nargs=argparse.REMAINDER)
    test = commands.add_parser("test", help="run the package's unittest suite")
    test.add_argument("args", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    try:
        if args.command == "check":
            _source_and_c(args.source)
            return 0
        if args.command == "build":
            source = args.source
            default = source.with_suffix(".exe" if os.name == "nt" else "")
            output = _safe_output(source, args.output or default)
            if args.emit_c and output == args.emit_c.resolve():
                raise ValueError("--emit-c must differ from the executable output")
            c_text, _ = _source_and_c(source)
            if output.suffix == ".c":
                _atomic_write(output, c_text)
                return 0
            output.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix="mrl-build-", dir=output.parent.resolve()) as directory:
                staging = Path(directory)
                c_file, executable = staging / "program.c", staging / output.name
                c_file.write_text(c_text, encoding="utf-8")
                from .toolchain import build_c
                build_c(c_file, executable, optimization=args.optimization)
                if args.emit_c:
                    _atomic_write(_safe_output(source, args.emit_c), c_text)
                os.replace(executable, output)
            return 0
        if args.command == "run":
            with tempfile.TemporaryDirectory(prefix="mrl-run-") as directory:
                executable = Path(directory) / ("program.exe" if os.name == "nt" else "program")
                source = args.source
                c_text, _ = _source_and_c(source)
                c_file = Path(directory) / "program.c"
                c_file.write_text(c_text, encoding="utf-8")
                from .toolchain import build_c
                build_c(c_file, executable, optimization=args.optimization)
                forwarded = list(args.args)
                if forwarded and forwarded[0] == "--":
                    forwarded.pop(0)
                return subprocess.run([str(executable), *forwarded], check=False).returncode
        if args.command == "test":
            suite = unittest.defaultTestLoader.discover(str(Path(__file__).parent / "tests"), pattern="test*.py")
            return 0 if unittest.TextTestRunner(verbosity=1).run(suite).wasSuccessful() else 1
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        print(f"mrl: error: {_compiler_error(error)}", file=sys.stderr)
        return 1
    return 2


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        return _new_cli(argv) if argv and argv[0] in _COMMANDS else _legacy(argv)
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        print(f"mrl: error: {_compiler_error(error)}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
