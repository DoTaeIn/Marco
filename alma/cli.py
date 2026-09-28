"""Run a tiny resumable ALMA research loop using MARCO's event core."""
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))
import argparse
from contextlib import nullcontext
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

from alma.runtime import AlmaRuntime
from alma.environment import run_local_environment


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", required=True)
    parser.add_argument("--identity", default="alma")
    parser.add_argument("--graph", default="graphs/graph_일상추론.kg")
    parser.add_argument("--pack", type=Path,
                        help="Use one verified .kgpack for the graph, language, and axioms")
    parser.add_argument("--pack-graph",
                        help="Graph path inside --pack (defaults to --graph)")
    parser.add_argument("--turn")
    parser.add_argument("--memory", choices=("episodic", "semantic", "procedural"))
    parser.add_argument("--recall", choices=("episodic", "semantic", "procedural"),
                        help="Use one typed durable memory by its event/concept/action key")
    parser.add_argument("--recall-key", help="Event ID for episodic, action/concept key otherwise")
    parser.add_argument("--mental-holder", help="Holder for a scoped belief/expectation/goal query")
    parser.add_argument("--mental-kind", choices=("belief", "expectation", "goal"))
    parser.add_argument("--mental-condition-event", action="append",
                        help="Observed event ID used to evaluate structured mental conditions")
    parser.add_argument("--project-state-at",
                        help="Project timed mutable state at a JSON number or quoted timestamp")
    parser.add_argument("--search", help="Search the durable ALMA ledger")
    parser.add_argument("--search-kinds", help="Comma-separated ledger kinds for --search")
    parser.add_argument("--decision", help="Return one historic decision record")
    parser.add_argument("--reconsider", help="Re-evaluate one historic decision without mutating life state")
    parser.add_argument("--backup-state", type=Path, help="Write a new personal-state backup file")
    parser.add_argument("--cycle-steps", type=Path,
                        help="JSON list of data-defined cycle steps")
    parser.add_argument("--resume-cycle", help="cycle ID to continue")
    parser.add_argument("--environment", type=Path,
                        help="JSON local observation environment to start")
    parser.add_argument("--resume-environment", help="environment run ID to continue")
    parser.add_argument("--step-budget", type=int, default=16)
    args = parser.parse_args(argv)
    if args.cycle_steps and args.resume_cycle:
        parser.error("--cycle-steps and --resume-cycle cannot be combined")
    if args.resume_environment and not args.environment:
        parser.error("--resume-environment requires --environment with the same configuration")
    commands = [args.cycle_steps is not None, args.resume_cycle is not None, args.environment is not None,
                args.recall is not None, args.mental_holder is not None, args.turn is not None,
                args.memory is not None, args.search is not None, args.decision is not None,
                args.reconsider is not None, args.backup_state is not None,
                args.project_state_at is not None]
    if sum(commands) > 1:
        parser.error("choose one command")
    if args.search_kinds and args.search is None:
        parser.error("--search-kinds requires --search")
    if args.recall_key and args.recall is None:
        parser.error("--recall-key requires --recall")
    if args.recall is not None and not args.recall_key:
        parser.error("--recall requires --recall-key")
    if (args.mental_holder is None) != (args.mental_kind is None):
        parser.error("--mental-holder and --mental-kind must be used together")
    if args.mental_condition_event and args.mental_holder is None:
        parser.error("--mental-condition-event requires --mental-holder and --mental-kind")
    if args.pack_graph and not args.pack:
        parser.error("--pack-graph requires --pack")
    model, graph_name = None, args.pack_graph or args.graph
    temporary = nullcontext(None)
    if args.pack:
        import marco.storage.kgpack as kgpack
        from pack_model import PackModel
        manifest, assets = kgpack.read(args.pack)
        if graph_name not in assets or not graph_name.endswith(".kg"):
            parser.error("--pack graph is missing: " + graph_name)
        from alma.runtime import LANGUAGE
        from pack_model import descriptor
        # ALMA names its language; a pack built with another default still serves it.
        model = PackModel({**manifest, "model": descriptor(assets, "styles/%s.json" % LANGUAGE)}, assets)
        temporary = TemporaryDirectory(prefix="alma-pack-")
    with temporary as folder:
        graph = Path(graph_name) if folder is None else Path(folder) / Path(graph_name).name
        if folder is not None:
            graph.write_bytes(assets[graph_name])
        runtime = AlmaRuntime(Path(args.state), args.identity, model=model)
        if args.cycle_steps:
            result = runtime.start_cycle(graph, json.loads(args.cycle_steps.read_text(encoding="utf-8")),
                                         step_budget=args.step_budget)
        elif args.resume_cycle:
            result = runtime.resume_cycle(args.resume_cycle, graph, step_budget=args.step_budget)
        elif args.environment:
            result = run_local_environment(runtime, graph,
                                           json.loads(args.environment.read_text(encoding="utf-8")),
                                           step_budget=args.step_budget, run_id=args.resume_environment)
        elif args.turn is not None:
            result = runtime.turn(args.turn, graph)
        elif args.recall is not None:
            result = runtime.recall(args.recall, args.recall_key)
        elif args.mental_holder is not None:
            result = runtime.query_mental(args.mental_holder, args.mental_kind,
                                          observed_event_ids=args.mental_condition_event)
        elif args.project_state_at is not None:
            try:
                effective_at = json.loads(args.project_state_at)
            except json.JSONDecodeError:
                effective_at = args.project_state_at
            result = runtime.project_state_at(effective_at)
        elif args.memory:
            result = runtime.memories(args.memory)
        elif args.search is not None:
            kinds = {value for value in args.search_kinds.split(",") if value} if args.search_kinds else None
            result = runtime.search(args.search, kinds=kinds)
        elif args.decision:
            result = runtime.decision(args.decision)
        elif args.reconsider:
            result = runtime.reconsider(args.reconsider, graph)
        elif args.backup_state:
            result = runtime.backup_state(args.backup_state)
        else:
            result = runtime.snapshot()
    sys.stdout.buffer.write((json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


if __name__ == "__main__":
    main()
