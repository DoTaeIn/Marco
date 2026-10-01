"""The ``mco`` command line.

    mco run MODEL [TEXT ...]          one utterance per argument (one conversation);
                                      with no TEXT, read utterances from stdin
    mco compile SOURCE -o OUTPUT      build an .mco from a source tree or .kgpack
                                      (--format native writes MCO Format 1)
    mco inspect MODEL                 describe a model without running it
    mco inspect SNAPSHOT              describe a conversation snapshot without running it
    mco snapshot MODEL -o OUTPUT [TEXT ...]
                                      run the utterances in one conversation (continuing
                                      --resume SNAPSHOT if given), then write its snapshot
    mco benchmark MODEL CASES         run a case file and report accuracy/latency
    mco backends                      list backends and whether they are usable
    mco overlay ACTION MODEL OVERLAY  create, change (commit, propose, approve, reject,
                                      undo) and read (status, history, candidates) an
                                      overlay store; every change names its approver

Exit status: 0 success, 1 an mco error (message on stderr), 2 usage error,
3 benchmark finished with failing cases (``--fail-under``).
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Optional, Sequence, TextIO

from ._version import __version__
from .errors import MCOError

__all__ = ["main"]


def _dump(data: Any, out: TextIO) -> None:
    out.write(json.dumps(data, ensure_ascii=False, indent=2, default=str) + "\n")


def _print_result(result: Any, out: TextIO, verbose: bool) -> None:
    out.write(f"{result.answer}\n")
    out.write(f"  status: {result.status}\n")
    if verbose:
        out.write("  evidence:\n")
        for line in str(result.evidence).splitlines():
            out.write(f"    {line}\n")
        out.write("  trace:\n")
        for line in str(result.trace).splitlines():
            out.write(f"    {line}\n")


def _load_options(args: argparse.Namespace) -> dict[str, Any]:
    options: dict[str, Any] = {}
    if getattr(args, "allow_network", False):
        options["allow_network"] = True
    if getattr(args, "marco_root", None):
        options["marco_root"] = args.marco_root
    if getattr(args, "overlay_dir", None):
        options["overlay_dir"] = args.overlay_dir
    if getattr(args, "overlay", None):
        options["overlay"] = args.overlay
    return options


def _cmd_run(args: argparse.Namespace, out: TextIO) -> int:
    from .model import load
    with load(args.model, backend=args.backend, snapshot=args.resume, **_load_options(args)) as model:
        texts: Sequence[str] = args.text
        interactive = not texts
        if interactive:
            source = sys.stdin
            if source.isatty():
                sys.stderr.write(f"{model.info.name} [{model.backend}] - empty line or Ctrl-D to quit\n")
        results = []

        def handle(text: str) -> None:
            result = model.run(text)
            if args.json:
                results.append(result.to_dict(include_raw=args.raw))
            else:
                _print_result(result, out, args.verbose)
            out.flush()

        if interactive:
            for line in source:
                line = line.strip()
                if not line:
                    if source.isatty():
                        break
                    continue
                handle(line)
        else:
            for text in texts:
                handle(text)
        if args.json:
            _dump(results if len(results) != 1 else results[0], out)
    return 0


def _cmd_compile(args: argparse.Namespace, out: TextIO) -> int:
    from .compiler import compile
    options = {"marco_root": args.marco_root} if args.marco_root else {}
    report = compile(args.source, args.output, name=args.name, build_id=args.build_id,
                     backend=args.backend or "marco-kgpack", graphs=args.graph or None,
                     language=args.language, format=args.format, **options)
    if args.json:
        _dump(report.to_dict(), out)
    else:
        info = report.info
        out.write(f"{report.output}: {info.graphs} graph(s), {info.assets} asset(s), "
                  f"{info.size_bytes} bytes, sha256 {info.sha256[:16]}\n")
    return 0


def _print_snapshot(info: Any, out: TextIO) -> None:
    base, overlay = info.base, info.overlay
    rows = [("path", info.path), ("format", f"marco-snapshot v{info.version}"),
            ("size", f"{info.size_bytes} bytes"), ("sha256", info.sha256),
            ("base", base.get("content_sha256")), ("build", base.get("build_id")),
            ("base format", f"{base.get('format')} {base.get('format_version')}"),
            ("overlay", f"seq {overlay['seq']} ({overlay.get('change_id')})" if overlay else "none attached"),
            ("runtime", info.runtime), ("requires", ", ".join(info.requires) or "-"),
            ("schemas", ", ".join(info.schemas) or "-"), ("conversations", info.conversations),
            ("turns", info.turns), ("excluded", ", ".join(info.excluded) or "-")]
    width = max(len(k) for k, _ in rows)
    for key, value in rows:
        out.write(f"{key:<{width}}  {value if value is not None else '-'}\n")


def _cmd_inspect(args: argparse.Namespace, out: TextIO) -> int:
    from .compiler import inspect
    from .snapshot import inspect_snapshot, is_snapshot
    if is_snapshot(args.model):
        snapshot = inspect_snapshot(args.model, marco_root=args.marco_root)
        if args.json:
            _dump(snapshot.to_dict(), out)
        else:
            _print_snapshot(snapshot, out)
        return 0
    extra = {"overlay": args.overlay, "marco_root": args.marco_root} if args.overlay else {}
    info = inspect(args.model, verify=not args.no_verify, **extra)
    if args.json:
        _dump(info.to_dict(include_manifest=args.manifest), out)
        return 0
    native = info.manifest if info.format == "mco-native" else {}
    fmt = native.get("format") or {}
    version = f"v{fmt['major']}.{fmt['minor']}" if fmt else f"v{info.format_version}"
    rows = [("path", info.path), ("name", info.name), ("format", f"{info.format} {version}"),
            ("build", info.build_id), ("backend", info.backend), ("runnable", info.runnable),
            ("verified", info.verified), ("size", f"{info.size_bytes} bytes"), ("sha256", info.sha256),
            ("language", info.language), ("languages", ", ".join(info.languages) or "-"),
            ("graphs", info.graphs), ("assets", info.assets), ("fingerprint", info.fingerprint),
            ("capabilities", ", ".join(info.capabilities) or "-")]
    manifest = native.get("mco") or {}
    if manifest:
        schema = manifest.get("semantic_schema") or {}
        rows += [("content", manifest.get("content_sha256")), ("generator", manifest.get("generator")),
                 ("schema", f"{schema.get('id')} v{schema.get('version')}"),
                 ("requires", ", ".join(manifest.get("requires") or ()) or "-")]
    tables = native.get("tables")
    if tables:
        rows += [("tables", f"{tables['graphs']} graphs ({tables['tabled']} in tables, "
                            f"{len(tables['source_only'])} source text only), {tables['nodes']} nodes, "
                            f"{tables['edges']} edges, {tables['rules']} rules")]
    width = max(len(k) for k, _ in rows)
    for key, value in rows:
        out.write(f"{key:<{width}}  {value if value is not None else '-'}\n")
    for note in info.notes:
        out.write(f"note: {note}\n")
    chunks = native.get("chunks") or ()
    if chunks:
        out.write(f"chunks: {len(chunks)}\n")
        out.write(f"  {'#':>4}  type  ver  req  {'comp':<4}  {'stored':>10}  {'raw':>10}  what\n")
        for c in chunks:
            out.write(f"  {c['index']:>4}  {c['type']}  {c['version']:>3}  {'yes' if c['required'] else 'no':<3}"
                      f"  {c['compression']:<4}  {c['length']:>10}  {c['raw_length']:>10}"
                      f"  {c.get('role', '-')}\n")
    return 0


def _cmd_snapshot(args: argparse.Namespace, out: TextIO) -> int:
    from .model import load
    with load(args.model, backend=args.backend, snapshot=args.resume, **_load_options(args)) as model:
        results = [model.run(text) for text in args.text]
        session = model._default_session()
        info = session.snapshot(args.output)
    if args.json:
        _dump({"results": [r.to_dict() for r in results], "snapshot": info.to_dict()}, out)
    else:
        for result in results:
            _print_result(result, out, False)
        out.write(f"{info.path}: {info.conversations} conversation, {info.turns} turn(s), "
                  f"{info.size_bytes} bytes, sha256 {info.sha256[:16]}\n")
    return 0


def _cmd_benchmark(args: argparse.Namespace, out: TextIO) -> int:
    from .benchmark import benchmark
    report = benchmark(args.model, args.cases, backend=args.backend, **_load_options(args))
    data = report.to_dict()
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            _dump(data, handle)
    if args.json:
        _dump(data, out)
    else:
        out.write(report.summary() + "\n")
        for case in report.cases:
            if case.passed is False:
                reason = case.error or f"{case.status}: {case.answer}"
                out.write(f"  FAIL {case.id}: {reason}\n")
    if args.fail_under is not None and (report.accuracy or 0.0) < args.fail_under:
        return 3
    return 0


def _deltas(args: argparse.Namespace) -> list[Any]:
    from .errors import InvalidInputError
    deltas: list[Any] = []
    for text in args.delta or ():
        try:
            item = json.loads(text)
        except json.JSONDecodeError as exc:
            raise InvalidInputError(f"--delta is not JSON: {exc}") from exc
        deltas += item if isinstance(item, list) else [item]
    if args.deltas:
        with open(args.deltas, encoding="utf-8") as handle:
            item = json.load(handle)
        deltas += item if isinstance(item, list) else [item]
    if not deltas:
        raise InvalidInputError("give at least one --delta JSON object or a --deltas file")
    return deltas


def _cmd_overlay(args: argparse.Namespace, out: TextIO) -> int:
    from .overlay import create_overlay, open_overlay, overlay_status
    common = {"marco_root": args.marco_root} if args.marco_root else {}
    action = args.action
    if action == "create":
        _dump(create_overlay(args.model, args.overlay, **common), out)
        return 0
    if action == "status":
        _dump(overlay_status(args.model, args.overlay, **common), out)
        return 0
    with open_overlay(args.model, args.overlay, **common) as overlay:
        if action == "commit":
            result: Any = overlay.commit(_deltas(args), approved_by=args.approved_by, reason=args.reason,
                                         actor=args.actor, source="mco CLI")
        elif action == "propose":
            result = {"candidate_id": overlay.propose(_deltas(args), actor=args.actor, reason=args.reason,
                                                      source="mco CLI")}
        elif action == "approve":
            result = overlay.approve(args.candidate, approved_by=args.approved_by)
        elif action == "reject":
            overlay.reject(args.candidate, rejected_by=args.rejected_by, reason=args.reason)
            result = {"rejected": args.candidate}
        elif action == "undo":
            change = int(args.change) if args.change.isdigit() else args.change
            result = overlay.undo(change, approved_by=args.approved_by, reason=args.reason, actor=args.actor,
                                  source="mco CLI")
        elif action == "history":
            result = overlay.history(args.target)
        else:
            result = overlay.candidates(args.status)
    _dump(result, out)
    return 0


def _cmd_backends(args: argparse.Namespace, out: TextIO) -> int:
    from .backends import available_backends
    status = available_backends()
    if args.json:
        _dump({name: {"available": ok, "reason": reason} for name, (ok, reason) in status.items()}, out)
    else:
        for name, (ok, reason) in status.items():
            out.write(f"{name:<14} {'available' if ok else 'unavailable'}{': ' + reason if reason else ''}\n")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mco", description="Run, compile, inspect and benchmark MCO models.")
    parser.add_argument("--version", action="version", version=f"mco {__version__}")
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    def runtime_flags(p: argparse.ArgumentParser) -> None:
        p.add_argument("--backend", help="force a backend (see 'mco backends')")
        p.add_argument("--marco-root", help="MARCO checkout to use (else $MCO_MARCO_ROOT)")
        p.add_argument("--overlay-dir", help="keep learned knowledge in this directory")
        p.add_argument("--overlay", help="attach this overlay store (explicit or approved graph and rule changes)")
        p.add_argument("--allow-network", action="store_true", help="allow external research")

    p = sub.add_parser("run", help="send utterances to a model")
    p.add_argument("model")
    p.add_argument("text", nargs="*", help="utterances, in order, in one conversation")
    p.add_argument("--json", action="store_true", help="print results as JSON")
    p.add_argument("--raw", action="store_true", help="with --json, include the backend payload")
    p.add_argument("-v", "--verbose", action="store_true", help="also print evidence and trace")
    p.add_argument("--resume", metavar="SNAPSHOT", help="continue the conversation saved in this snapshot")
    runtime_flags(p)
    p.set_defaults(func=_cmd_run)

    p = sub.add_parser("snapshot", help="run utterances in one conversation, then write its snapshot")
    p.add_argument("model")
    p.add_argument("text", nargs="*", help="utterances, in order, in one conversation")
    p.add_argument("-o", "--output", required=True, help="the snapshot file to write")
    p.add_argument("--resume", metavar="SNAPSHOT", help="continue the conversation saved in this snapshot")
    p.add_argument("--json", action="store_true")
    runtime_flags(p)
    p.set_defaults(func=_cmd_snapshot)

    p = sub.add_parser("compile", help="compile a source tree or .kgpack into .mco")
    p.add_argument("source")
    p.add_argument("-o", "--output", required=True)
    p.add_argument("--name")
    p.add_argument("--build-id")
    p.add_argument("--graph", action="append", help="glob of graph files to include (repeatable)")
    p.add_argument("--language", help="language asset path, e.g. styles/english.json")
    p.add_argument("--backend")
    p.add_argument("--marco-root")
    p.add_argument("--format", choices=("compat", "native"), default="compat",
                   help="compat: the 0.1.0 container (default); native: MCO Format 1")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_cmd_compile)

    p = sub.add_parser("inspect", help="describe a model or a snapshot without running it")
    p.add_argument("model", help="a model file, or a snapshot file written by 'mco snapshot'")
    p.add_argument("--json", action="store_true")
    p.add_argument("--manifest", action="store_true", help="with --json, include native manifests")
    p.add_argument("--no-verify", action="store_true", help="skip SHA-256 verification")
    p.add_argument("--marco-root", help="MARCO checkout whose snapshot or overlay reader to use")
    p.add_argument("--overlay", help="also show this overlay store's base binding, head and active counts")
    p.set_defaults(func=_cmd_inspect)

    p = sub.add_parser("overlay", help="create, change and read an overlay store beside a model")
    actions = p.add_subparsers(dest="action", required=True, metavar="ACTION")

    def overlay_parser(name: str, help: str) -> argparse.ArgumentParser:
        q = actions.add_parser(name, help=help)
        q.add_argument("model")
        q.add_argument("overlay")
        q.add_argument("--marco-root", help="MARCO checkout to use (else $MCO_MARCO_ROOT)")
        q.set_defaults(func=_cmd_overlay)
        return q

    def delta_flags(q: argparse.ArgumentParser) -> None:
        q.add_argument("--delta", action="append",
                       help='one delta as JSON, e.g. {"op": "ADD_EDGE", "graph": "graphs/x.kg", "src": "a", '
                            '"rel": "증명", "dst": "b"} (repeatable; a JSON list is several)')
        q.add_argument("--deltas", help="a JSON file with one delta or a list of deltas")
        q.add_argument("--reason", required=True)

    overlay_parser("create", "create an empty overlay bound to the model's content and build")
    overlay_parser("status", "show the base binding, head, active counts and pending candidates")
    q = overlay_parser("commit", "record one change, approved by --approved-by")
    delta_flags(q)
    q.add_argument("--approved-by", required=True, help="who approves this change")
    q.add_argument("--actor", help="who made it (default: the approver)")
    q = overlay_parser("propose", "store a candidate change; it changes nothing until approved")
    delta_flags(q)
    q.add_argument("--actor", required=True, help="who proposes it")
    q = overlay_parser("approve", "make a pending candidate a change")
    q.add_argument("candidate")
    q.add_argument("--approved-by", required=True)
    q = overlay_parser("reject", "reject a pending candidate; it is kept and never applies")
    q.add_argument("candidate")
    q.add_argument("--rejected-by", required=True)
    q.add_argument("--reason", required=True)
    q = overlay_parser("undo", "undo a change (seq or change id) by a compensating change")
    q.add_argument("change")
    q.add_argument("--approved-by", required=True)
    q.add_argument("--reason", required=True)
    q.add_argument("--actor")
    q = overlay_parser("history", "every delta on one node, edge or rule id")
    q.add_argument("target")
    q = overlay_parser("candidates", "list candidates")
    q.add_argument("--status", choices=("pending", "approved", "rejected"))

    p = sub.add_parser("benchmark", help="run a case file against a model")
    p.add_argument("model")
    p.add_argument("cases", help="JSON or JSONL case file")
    p.add_argument("--json", action="store_true")
    p.add_argument("--output", help="also write the JSON report here")
    p.add_argument("--fail-under", type=float, help="exit 3 if accuracy is below this fraction")
    runtime_flags(p)
    p.set_defaults(func=_cmd_benchmark)

    p = sub.add_parser("backends", help="list backends")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_cmd_backends)
    return parser


def main(argv: Optional[Sequence[str]] = None, *, stdout: Optional[TextIO] = None) -> int:
    out = stdout or sys.stdout
    args = _parser().parse_args(argv)
    try:
        return int(args.func(args, out))
    except MCOError as exc:
        sys.stderr.write(f"mco: {type(exc).__name__}: {exc}\n")
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
