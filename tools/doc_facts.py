"""Measure the numbers README.md states, and check that every package has its document.

    python tools/doc_facts.py packages      # packages without a document; prints 0 when complete
    python tools/doc_facts.py counts        # graphs, nodes, edges, code size
    python tools/doc_facts.py runtime       # cold start, turn latency, memory, imported libraries
    python tools/doc_facts.py frozen        # the frozen-exam numbers, read from the recorded reports
    python tools/doc_facts.py frozen --run round3    # another recorded run of the same reports
    python tools/doc_facts.py layout        # root .py files: which stay, which goal S4 moves where
    python tools/doc_facts.py index         # documents under docs/ that docs/README.md does not link; prints 0

Every number is measured from the checkout it runs in, and every report starts
with the commit it measured. A package is a directory with ``__init__.py`` under
one of PACKAGE_ROOTS; its document is ``docs/architecture/<dotted.name>.md`` and
must carry the five headings of the architecture template, in order.

``frozen`` runs nothing. The frozen exams are scored once per round by the
owner; this command only reads the reports that run recorded and prints their
aggregates, each under the file it came from. It prints numbers and labels
only, never a turn, a reply or anything else a dialogue or problem says.
"""
import glob
import json
import os
import re
import statistics
import subprocess
import sys
import time
from urllib.parse import unquote

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKAGE_ROOTS = ("marco", "mco", "alma", "polo")
DOC_DIR = os.path.join("docs", "architecture")
HEADINGS = ("## Purpose", "## Owns", "## Does not own", "## Depends on", "## Public interface")

# The recorded frozen-exam reports. ``{run}`` is the run's name: ``after-w3``,
# ``round3``, ``baseline``. The owner writes these files; nothing here runs an exam.
FROZEN_REPORTS = (
    ("dialogue", os.path.join("docs", "ko", "dialogue-gate-2026-09-22", "{run}.json")),
    ("composition", os.path.join("docs", "ko", "dialogue-gate-2026-09-22", "composition-{run}.json")),
    ("reasoning", os.path.join("docs", "ko", "reasoning-gate-2026-09-24", "{run}.json")),
)
FROZEN_RUN = "after-w3"
COMPARISON_DIR = os.path.join("docs", "ko", "model-comparison-2026-09-24")
COMPARISON_MODELS = ("marco", "qwen", "gpt2", "always_hold")
TARGET_MAP = os.path.join(DOC_DIR, "target-map.json")
DOCS_INDEX = os.path.join("docs", "README.md")


def revision():
    def git(*args):
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    dirty = git("status", "--porcelain", "--untracked-files=no")
    return "%s%s" % (git("rev-parse", "--short", "HEAD"), " (tracked files modified)" if dirty else "")


# ---------------------------------------------------------------- packages

def packages(root=ROOT):
    found = []
    for top in PACKAGE_ROOTS:
        base = os.path.join(root, top)
        if not os.path.isfile(os.path.join(base, "__init__.py")):
            continue
        for here, dirs, files in os.walk(base):
            dirs[:] = sorted(d for d in dirs if not d.startswith((".", "__")))
            if "__init__.py" in files:
                found.append(os.path.relpath(here, root).replace(os.sep, "."))
    return found


def doc_problem(name, root=ROOT):
    path = os.path.join(root, DOC_DIR, name + ".md")
    if not os.path.isfile(path):
        return "no file %s" % os.path.relpath(path, root)
    with open(path, encoding="utf-8") as f:
        lines = [line.rstrip() for line in f]
    at = 0
    for heading in HEADINGS:
        try:
            at = lines.index(heading, at) + 1
        except ValueError:
            return "%s lacks '%s' (or it is out of order)" % (os.path.relpath(path, root), heading)
    return None


def cmd_packages(verbose):
    names = packages()
    missing = [(n, doc_problem(n)) for n in names if doc_problem(n)]
    if verbose:
        print("commit %s, %d packages" % (revision(), len(names)), file=sys.stderr)
        for n in names:
            print("  %-28s %s" % (n, doc_problem(n) or "ok"), file=sys.stderr)
    print(len(missing))
    return 1 if missing else 0


# ---------------------------------------------------------------- counts

def _graph_files():
    return sorted(glob.glob(os.path.join(ROOT, "graphs", "*.kg")))


def cmd_counts():
    sys.path.insert(0, ROOT)
    os.chdir(ROOT)
    import engine
    engine._shared_net = {}          # count what authors wrote, not the shared dictionary net
    concepts = instances = nulls = axioms = arg_edges = net_edges = failed = 0
    for path in _graph_files():
        try:
            g = engine.read_kg(path)
        except Exception:
            failed += 1
            continue
        concepts += len(g["공통층"]) - len(g["공리"])
        axioms += len(g["공리"])
        instances += len(g["사례층"])
        nulls += len(g["무관층"])
        arg_edges += len(g["엣지"])
        net_edges += len(g.get("개념엣지", []))
    root_py = sorted(glob.glob(os.path.join(ROOT, "*.py")))
    lines = lambda paths: sum(sum(1 for _ in open(p, encoding="utf-8")) for p in paths)
    pkg_py = [p for top in PACKAGE_ROOTS for p in glob.glob(os.path.join(ROOT, top, "**", "*.py"), recursive=True)]
    rows = [
        ("commit", revision()),
        ("graph files (graphs/*.kg)", len(_graph_files())),
        ("graph files that fail to parse", failed),
        ("nodes: concepts", concepts),
        ("nodes: axioms", axioms),
        ("nodes: instances", instances),
        ("nodes: total (concepts + axioms + instances)", concepts + axioms + instances),
        ("null-class entries ([무관])", nulls),
        ("argument edges ([논증])", arg_edges),
        ("concept-network edges ([개념망], authored)", net_edges),
        ("root .py files", len(root_py)),
        ("root .py lines", lines(root_py)),
        ("engine.py lines", lines([os.path.join(ROOT, "engine.py")])),
        ("package .py files (%s)" % ", ".join(PACKAGE_ROOTS), len(pkg_py)),
        ("package .py lines", lines(pkg_py)),
        ("test files (tests/test_*.py)", len(glob.glob(os.path.join(ROOT, "tests", "test_*.py")))),
        ("test files, subfolders included (tests/**/test_*.py)",
         len(glob.glob(os.path.join(ROOT, "tests", "**", "test_*.py"), recursive=True))),
    ]
    for key, value in rows:
        print("%-46s %s" % (key, value))
    return 0


# ---------------------------------------------------------------- runtime

def _questions():
    """A fixed question set: the 24 out-of-domain questions of the routing
    benchmark, plus the first instance phrasing of every 20th graph file."""
    out = json.load(open(os.path.join(ROOT, "data", "benchmarks", "라우팅_밖.json"), encoding="utf-8"))
    import engine
    inside = []
    for path in _graph_files()[::20]:
        g = engine.read_kg(path)
        for phrasings in g["사례층"].values():
            if phrasings:
                inside.append(phrasings[0])
                break
    return list(out) + inside


def _probe():
    import resource
    before = {m.split(".")[0] for m in list(sys.modules)}      # interpreter start-up, site hooks
    sys.path.insert(0, ROOT)
    os.chdir(ROOT)
    start = time.perf_counter()
    import engine
    import_ms = (time.perf_counter() - start) * 1000
    start = time.perf_counter()
    index = engine._index_slots["색인"] = engine.graph_index()      # the router's own cache slot
    index_ms = (time.perf_counter() - start) * 1000
    questions = _questions()
    times = []
    for q in questions:
        start = time.perf_counter()
        engine.answer(q)
        times.append((time.perf_counter() - start) * 1000)
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    rss_mb = rss / (1024 * 1024) if sys.platform == "darwin" else rss / 1024
    stdlib = set(sys.stdlib_module_names)
    local = {os.path.splitext(os.path.basename(p))[0] for p in glob.glob(os.path.join(ROOT, "*.py"))}
    local |= set(PACKAGE_ROOTS)
    third = sorted({m.split(".")[0] for m in list(sys.modules)} - before - stdlib - local)
    third = [m for m in third if not m.startswith("_")]
    first_ms, times = times[0], times[1:]      # the first turn also builds what the engine loads lazily
    times_sorted = sorted(times)
    print(json.dumps({
        "import_engine_ms": round(import_ms, 1),
        "graph_index_ms": round(index_ms, 1),
        "router_index_graphs": len(index["공통층"]),
        "questions": len(times) + 1,
        "first_turn_ms": round(first_ms, 1),
        "turn_ms_median": round(statistics.median(times), 1),
        "turn_ms_p95": round(times_sorted[int(0.95 * (len(times_sorted) - 1))], 1),
        "turn_ms_max": round(times_sorted[-1], 1),
        "max_rss_mb": round(rss_mb, 1),
        "torch_imported": "torch" in sys.modules,
        "third_party_modules": third,
    }))


def cmd_runtime():
    env = dict(os.environ, KG_ENCODER=os.environ.get("KG_ENCODER", "문자"))
    run = lambda: subprocess.run([sys.executable, os.path.abspath(__file__), "_probe"],
                                 cwd=ROOT, env=env, capture_output=True, text=True)
    first = run()                    # warms the on-disk index and vector caches; not reported
    second = run()
    for done in (first, second):
        if done.returncode:
            sys.stderr.write(done.stderr)
            return done.returncode
    warm = json.loads(second.stdout.strip().splitlines()[-1])
    print("%-46s %s" % ("commit", revision()))
    print("%-46s %s" % ("encoder (KG_ENCODER)", env["KG_ENCODER"]))
    print("%-46s %s" % ("python", sys.version.split()[0]))
    print("%-46s %s" % ("graphs in the router index", warm["router_index_graphs"]))
    print("%-46s %s" % ("questions timed (engine.answer)", warm["questions"]))
    print("%-46s %s" % ("start-up: import engine ms", warm["import_engine_ms"]))
    print("%-46s %s" % ("start-up: build index from cache ms", warm["graph_index_ms"]))
    print("%-46s %s" % ("first turn ms (engine loads the rest lazily)", warm["first_turn_ms"]))
    print("%-46s %s" % ("turn latency median ms (turns 2..n)", warm["turn_ms_median"]))
    print("%-46s %s" % ("turn latency p95 ms (turns 2..n)", warm["turn_ms_p95"]))
    print("%-46s %s" % ("turn latency max ms (turns 2..n)", warm["turn_ms_max"]))
    print("%-46s %s" % ("peak resident memory MB", warm["max_rss_mb"]))
    print("%-46s %s" % ("torch imported", warm["torch_imported"]))
    print("%-46s %s" % ("third-party modules the engine loaded", ", ".join(warm["third_party_modules"]) or "none"))
    return 0


# ---------------------------------------------------------------- frozen

def _load_json(root, rel):
    path = os.path.join(root, rel)
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _share(part, whole):
    return "%.1f%%" % (100.0 * part / whole) if whole else "n/a"


def _of(part, whole):
    return "%d / %d (%s)" % (part, whole, _share(part, whole))


def _code(meta):
    meta = meta or {}
    commit = (meta.get("code_commit") or "unknown")[:7]
    return commit + (" (tracked files modified)" if meta.get("code_dirty") else "")


def _languages(counts):
    return ", ".join("%s %d" % (code, n) for code, n in sorted(counts.items()))


def _dialogue_rows(report):
    ds, gate, viol = report["dataset"], report["gate"], report["violations"]
    rows = [
        ("code the owner ran", _code(report.get("meta"))),
        ("dialogues", "%d (%s), %d turns" % (ds["dialogues"], _languages(ds["by_language"]), ds["turns"])),
        ("gate 2: answerable turns correct",
         "%s, needed %d, %s" % (_of(gate["correct"], gate["n"]), gate["needed"],
                                "passed" if gate["passed"] else "not passed")),
        ("  answerable hold / wrong / unverifiable / execution error",
         "%d / %d / %d / %d" % (gate["hold"], gate["wrong"], gate["unverifiable"], gate["execution_error"])),
    ]
    for code, bucket in sorted(report["by_language"].items()):
        rows.append(("  answerable correct, %s" % code, _of(bucket["correct"], bucket["n"])))
    rows += [
        ("gate 3: confident answers without evidence", viol["confident_without_evidence"]["count"]),
        ("gate 3: uses of retracted evidence", viol["retracted_evidence_used"]["count"]),
    ]
    labels = (
        ("record", "statements recorded"),
        ("hold", "missing premise: held, naming what is missing"),
        ("ambiguous", "ambiguous referent: every candidate named"),
        ("unsupported", "unsupported request: declined"),
        ("correction", "correction: same event revised"),
        ("why", "why: every evidence turn cited"),
    )
    for key, label in labels:
        bucket = report["other_labels"].get(key)
        if bucket:
            rows.append((label, "%s; hold %d, wrong %d, unverifiable %d" % (
                _of(bucket["correct"], bucket["n"]), bucket["hold"], bucket["wrong"], bucket["unverifiable"])))
    rows.append(("dialogues with every turn right", report.get("dialogues_fully_passed")))
    return rows


def _composition_rows(report):
    total = report["total"]
    rows = [
        ("code the owner ran", _code(report.get("meta"))),
        ("replies", "%d, over %d dialogues" % (total["spoken"], report["dialogues"])),
        ("gate 5: replies composed from a meaning", "%s; passed through %d, held by the check %d" % (
            _of(total["composed"], total["spoken"]), total["passed_through"], total["held"])),
        ("execution errors (not replies)", len(report.get("execution_errors") or [])),
    ]
    for code, bucket in sorted(report["by_language"].items()):
        rows.append(("  composed, %s" % code, "%d / %d" % (bucket["composed"], bucket["spoken"])))
    rows.append(("  composed, by act", ", ".join(
        "%s %d" % (act, bucket["composed"]) for act, bucket in report["by_act"].items())))
    return rows


def _reasoning_rows(report):
    ds, gate, q, setup = report["dataset"], report["gate"], report["questions"], report["setup"]
    rows = [
        ("code the owner ran", _code(report.get("meta"))),
        ("problems", "%d (%s), %d questions, %d setup statements, %d recorded" % (
            ds["problems"], _languages(ds["by_language"]), ds["questions"], setup["statements"], setup["recorded"])),
        ("gate 6: problems correct among parsed", "%s, needed %d; wrong questions %d; unparsed %s; %s" % (
            _of(gate["correct"], gate["parsed"]), gate["needed"], gate["wrong_questions"],
            _of(gate["unparsed"], gate["problems"]), "passed" if gate["passed"] else "not passed")),
        ("questions correct among parsed", "%s; wrong %d, hold %d, unparsed %d of %d" % (
            _of(q["correct"], q["parsed"]), q["wrong"], q["hold"], q["unparsed"], q["n"])),
    ]
    for code, bucket in sorted(report["by_language"].items()):
        rows.append(("  questions correct among parsed, %s" % code, "%s; wrong %d" % (
            _of(bucket["correct"], bucket["parsed"]), bucket["wrong"])))
    return rows


def _parameters(n):
    if not n:
        return "0"
    return "%.1f B" % (n / 1e9) if n >= 1e9 else "%d M" % round(n / 1e6)


def _comparison_rows(root):
    rows = []
    for name in COMPARISON_MODELS:
        report = _load_json(root, os.path.join(COMPARISON_DIR, name + ".json"))
        if report is None:
            rows.append((name, "no report"))
            continue
        dialogues, reasoning, cost = report["dialogues"], report["reasoning"], report["cost"]
        answerable, invented, questions = dialogues["answerable"], dialogues["invented"], reasoning["questions"]
        rows.append((name, "parameters %s; answerable %d / %d, wrong %d; invented %d / %d; "
                           "reasoning questions %d / %d, wrong %d; median turn %.0f ms; peak memory %.0f MB; code %s" % (
            _parameters(report["meta"]["info"].get("parameters")),
            answerable["correct"], answerable["n"], answerable["wrong"],
            invented["missing_premise"] + invented["unsupported"], invented["n"],
            questions["correct"], questions["n"], questions["wrong"],
            cost["median_ms"], cost["peak_footprint_mb"], _code(report["meta"]))))
    return rows


def frozen_facts(run=FROZEN_RUN, root=ROOT):
    """[(title, source, rows or None)] for the reports of one recorded run, then the model comparison."""
    builders = {"dialogue": _dialogue_rows, "composition": _composition_rows, "reasoning": _reasoning_rows}
    titles = {"dialogue": "dialogue gate", "composition": "composition gate", "reasoning": "reasoning gate"}
    out = []
    for kind, pattern in FROZEN_REPORTS:
        rel = pattern.format(run=run)
        report = _load_json(root, rel)
        out.append((titles[kind], rel, builders[kind](report) if report is not None else None))
    out.append(("model comparison, same exams, one text scorer",
                os.path.join(COMPARISON_DIR, "{%s}.json" % ",".join(COMPARISON_MODELS)), _comparison_rows(root)))
    return out


def gate_summary(run=FROZEN_RUN, root=ROOT):
    """Gate conditions 2, 3, 5, 6 as met / not met, from the recorded reports alone."""
    reports = {kind: _load_json(root, pattern.format(run=run)) for kind, pattern in FROZEN_REPORTS}
    out = []
    dialogue, composition, reasoning = reports["dialogue"], reports["composition"], reports["reasoning"]
    if dialogue:
        gate, viol = dialogue["gate"], dialogue["violations"]
        out.append((2, gate["passed"], "%d / %d" % (gate["correct"], gate["n"])))
        count = viol["confident_without_evidence"]["count"] + viol["retracted_evidence_used"]["count"]
        out.append((3, count == 0, "%d violations" % count))
    if composition:
        total = composition["total"]
        met = total["passed_through"] == 0 and not composition.get("execution_errors")
        out.append((5, met, "%d / %d composed, %d passed through" % (
            total["composed"], total["spoken"], total["passed_through"])))
    if reasoning:
        gate = reasoning["gate"]
        out.append((6, gate["passed"], "%d / %d problems, %d wrong" % (
            gate["correct"], gate["parsed"], gate["wrong_questions"])))
    return out


def cmd_frozen(run):
    print("frozen-exam reports, run '%s': read, not re-run (checkout %s)" % (run, revision()))
    print("gates: " + "; ".join("%d %s (%s)" % (n, "met" if met else "NOT met", what)
                                for n, met, what in gate_summary(run)))
    missing = 0
    for title, source, rows in frozen_facts(run):
        print()
        print("%s: %s" % (title, source))
        if rows is None:
            print("  no such report")
            missing += 1
            continue
        for label, value in rows:
            print("  %-60s %s" % (label, value))
    return 1 if missing else 0


# ---------------------------------------------------------------- layout

def layout_facts(root=ROOT):
    """Root .py modules: those that stay at the root in goal S4 and those it moves, with targets."""
    tmap = _load_json(root, TARGET_MAP) or {}
    modules, splits = tmap.get("modules", {}), tmap.get("splits", {})
    names = sorted(os.path.splitext(os.path.basename(p))[0] for p in glob.glob(os.path.join(root, "*.py")))
    stay = [n for n in names if n in splits or n == "conftest"]
    move = [(n, modules.get(n)) for n in names if n not in stay]
    return {"root": names, "stay": stay, "move": move}


def cmd_layout():
    facts = layout_facts()
    moves = [(n, t) for n, t in facts["move"] if t]
    unmapped = [n for n, t in facts["move"] if not t]
    by_package = {}
    for name, target in moves:
        by_package.setdefault(target.rsplit(".", 1)[0] if "." in target else target, []).append(name)
    print("%-46s %s" % ("commit", revision()))
    print("%-46s %s" % ("root .py files", len(facts["root"])))
    print("%-46s %d: %s" % ("stay at the root in S4 (split files, conftest)", len(facts["stay"]),
                             ", ".join(facts["stay"])))
    print("%-46s %s" % ("moved whole by S4 (target-map.json)", len(moves)))
    for package in sorted(by_package):
        print("  -> %-42s %d: %s" % (package, len(by_package[package]), ", ".join(by_package[package])))
    print("%-46s %s" % ("root .py files not in the target map", len(unmapped)))
    for name in unmapped:
        print("  %s" % name)
    return 0


# ---------------------------------------------------------------- index

_LINK = re.compile(r"\]\(([^)\s]+)\)")


def _nfc(path):
    import unicodedata
    return unicodedata.normalize("NFC", os.path.normpath(path))


def index_facts(root=ROOT):
    """(documents under docs/ that docs/README.md does not link, links in it that name no file)."""
    index = os.path.join(root, DOCS_INDEX)
    with open(index, encoding="utf-8") as f:
        text = f.read()
    linked = set()
    for target in _LINK.findall(text):
        target = unquote(target.split("#", 1)[0])
        if target and "://" not in target and not target.startswith("mailto:"):
            linked.add(_nfc(os.path.join(os.path.dirname(index), target)))
    present = set()
    for here, dirs, files in os.walk(os.path.join(root, "docs")):
        dirs[:] = sorted(d for d in dirs if not d.startswith((".", "__")))
        for name in files:
            if not name.startswith("."):
                present.add(_nfc(os.path.join(here, name)))
    present.discard(_nfc(index))
    rel = lambda paths: sorted(os.path.relpath(p, root) for p in paths)
    broken = [p for p in linked if not os.path.exists(p)]
    return rel(present - linked), rel(broken)


def cmd_index(verbose):
    unlisted, broken = index_facts()
    if verbose:
        print("commit %s" % revision(), file=sys.stderr)
        for path in unlisted:
            print("  not linked: %s" % path, file=sys.stderr)
    for path in broken:
        print("  broken link in %s: %s" % (DOCS_INDEX, path), file=sys.stderr)
    print(len(unlisted))
    return 1 if unlisted or broken else 0


def main(argv):
    if not argv or argv[0] not in ("packages", "counts", "runtime", "frozen", "layout", "index", "_probe"):
        print(__doc__)
        return 2
    if argv[0] == "packages":
        return cmd_packages("-v" in argv)
    if argv[0] == "counts":
        return cmd_counts()
    if argv[0] == "runtime":
        return cmd_runtime()
    if argv[0] == "frozen":
        run = argv[argv.index("--run") + 1] if "--run" in argv[:-1] else FROZEN_RUN
        return cmd_frozen(run)
    if argv[0] == "layout":
        return cmd_layout()
    if argv[0] == "index":
        return cmd_index("-v" in argv)
    _probe()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
