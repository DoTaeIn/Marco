"""Why chain (design note §15): from an output back to the inputs it rests on.

The chain is the trace graph walked backwards along ``parent_ids``, the
direct causes (§6). ``input_refs`` (what an operator read) is not followed by
default: the operator of a correction turn reads the statement it corrects,
and that statement's old reading is not a reason for any later answer.
``supersedes`` is never followed (a replaced event is history, not a reason).
Nothing here composes a sentence: saying "why" in words is the realizer's job
(request L1-2 lists what it needs from the chain).

Only the standard library.
"""
from pathlib import Path

FOLLOW = ("parent_ids",)


def _events(source):
    if hasattr(source, "events"):
        return source.events
    if isinstance(source, (str, Path)):
        from marco.trace.ledger import read_many
        return read_many(source)[0]
    return list(source)


class Graph:
    """Events by id and position, for walking."""

    def __init__(self, source):
        self.events = _events(source)
        self.position = {e["event_id"]: i for i, e in enumerate(self.events)}
        self.withdrawn = {e["payload"]["withdrawn"]: e["event_id"] for e in self.events
                          if e["kind"] == "conclusion_withdrawn"}

    def get(self, event_id):
        return self.events[self.position[event_id]]

    def chain(self, event_id, follow=FOLLOW):
        """Every event ``event_id`` rests on, itself included, in ledger order."""
        if event_id not in self.position:
            raise KeyError("no event %s in this ledger" % event_id)
        seen, stack = {event_id}, [event_id]
        while stack:
            event = self.get(stack.pop())
            for name in follow:
                for ref in event.get(name) or ():
                    if ref not in seen and ref in self.position:
                        seen.add(ref)
                        stack.append(ref)
        return [self.events[i] for i in sorted(self.position[x] for x in seen)]

    def inputs(self, event_id, follow=FOLLOW):
        """The ``input_received`` events of the chain: ordered, each once."""
        return [e for e in self.chain(event_id, follow) if e["kind"] == "input_received"]

    def withdrawn_in_chain(self, event_id):
        """Chain events that were already withdrawn when ``event_id`` was written."""
        at = self.position[event_id]
        return [e for e in self.chain(event_id)
                if e["event_id"] in self.withdrawn and self.position[self.withdrawn[e["event_id"]]] < at]


def chain(source, event_id, follow=FOLLOW):
    return Graph(source).chain(event_id, follow)


def why(source, event_id, follow=FOLLOW):
    """From an ``output_created`` id (or any event id) back to the ``input_received`` events
    it rests on, as an ordered list without duplicates."""
    return Graph(source).inputs(event_id, follow)
