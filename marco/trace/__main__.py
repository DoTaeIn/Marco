"""``python -m marco.trace <command>``

  record <dialogue-file> [--language ko|en] [--out <dir>] [--name <file>] [--split <name>] [--engine-sites]
         play a dialogue (gate-schema JSON, a directory of them, or a text file with one
         turn per line) through the UI turn handler and record every turn; prints the
         ledger path, and for labelled dialogues the dialogue gate's score of the same run
  why <ledger> <event_id> [--chain] [--refs] [--say ko|en]
         the input_received events an output rests on (with --chain: every event of the chain;
         with --refs: also along input_refs, what operators read; with --say: the chain composed
         as an explanation by the realizer, in that language, marco/trace/explain.py)
  pretty <ledger> [--trace <trace_id>]
         one line per event (design note §32)
  stats <ledger> [--json]
         outputs by status, holds by reason, record rate, graph checks
  cost [--language ko|en] [--repeat N]
         seven-step dialogue ms per turn with recording off and on, bytes per turn

A ``<ledger>`` is a ``.jsonl`` file or a directory of them.
"""
import argparse
import json
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m marco.trace", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("record")
    p.add_argument("dialogue")
    p.add_argument("--language", choices=("ko", "en"))
    p.add_argument("--out", help="ledger directory (default MARCO_TRACE_DIR, else logs/)")
    p.add_argument("--name", help="ledger file name (default <date>.jsonl)")
    p.add_argument("--split", help="only the dialogues a dataset's split.txt lists under this name")
    p.add_argument("--engine-sites", action="store_true",
                   help="the engine sites write their own events too (request G5-1): routing, rules, holds")
    p = sub.add_parser("why")
    p.add_argument("ledger")
    p.add_argument("event_id")
    p.add_argument("--chain", action="store_true")
    p.add_argument("--refs", action="store_true", help="also follow input_refs (what operators read)")
    p.add_argument("--say", choices=("ko", "en"), help="say the why chain in words, composed by the realizer")
    p = sub.add_parser("pretty")
    p.add_argument("ledger")
    p.add_argument("--trace")
    p = sub.add_parser("stats")
    p.add_argument("ledger")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("cost")
    p.add_argument("--language", choices=("ko", "en"), default="en")
    p.add_argument("--repeat", type=int, default=5)
    args = parser.parse_args(argv)

    if args.command == "record":
        from marco.trace import drive
        from marco.trace.ledger import Ledger
        try:
            dialogues = drive.load(args.dialogue, args.language, args.split)
        except drive.FrozenSetRefused as exc:
            print("refused: %s" % exc)
            return 2
        if not dialogues:
            print("no dialogues")
            return 1
        ledger = Ledger(args.out, args.name)
        timing = {}
        answers = drive.record(dialogues, ledger, timing=timing, engine_sites=args.engine_sites)
        turns = sum(len(d["turns"]) for d in dialogues)
        print("ledger %s  dialogues %d  turns %d  events %d  bytes %d  recording %.1f ms/turn" % (
            ledger.path, len(dialogues), turns, len(ledger.events), ledger.bytes_written,
            1000 * timing["record_s"] / max(timing["turns"], 1)))
        if all(t.get("label") for d in dialogues for t in d["turns"]):
            from bench import dialogue_gate
            print(dialogue_gate.format_report(dialogue_gate.score(dialogues, answers)))
        return 0
    if args.command == "why" and args.say:
        from marco.trace.explain import explain
        text, report = explain(args.ledger, args.event_id, args.say)
        print(text or "")
        return 0 if report.get("realized") and not report.get("held") else 1
    if args.command == "why":
        from marco.trace.pretty import line
        from marco.trace.why import Graph
        graph = Graph(args.ledger)
        follow = ("parent_ids", "input_refs") if args.refs else ("parent_ids",)
        events = graph.chain(args.event_id, follow) if args.chain else graph.inputs(args.event_id, follow)
        for event in events:
            print(line(event))
        late = graph.withdrawn_in_chain(args.event_id)
        if late:
            print("withdrawn before this event, yet in its chain: %d" % len(late))
        return 0
    if args.command == "pretty":
        from marco.trace.ledger import read_many
        from marco.trace.pretty import lines
        events, problems = read_many(args.ledger)
        for text in lines(events, args.trace):
            print(text)
        for problem in problems:
            print("problem: %s" % json.dumps(problem, ensure_ascii=False))
        return 0
    if args.command == "stats":
        from marco.trace import stats
        result = stats.table(args.ledger)
        print(json.dumps(result, ensure_ascii=False, indent=1) if args.json else stats.format_table(result))
        return 0
    if args.command == "cost":
        from marco.trace import drive
        result = drive.cost(args.language, args.repeat)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
