"""The conversation identity graph (M1, docs/architecture/conversation-graph.md).

One node per holder, thing and place the conversation names; every way it named them is an alias edge with the
turn it came from; a count is an edge from a holder to a thing with its value, how the value came about (said by
a statement, or computed by replay from a transfer or a use-up) and the turns it rests on; each question read is a
frame over node ids. The node is the identity, the strings are its aliases.

This module holds the graph and its lookups only. What the words of a statement or a question mean is the
reader's and the conversation's (``marco.reasoning.context``): they build the graph from the replayed facts and
record the aliases a statement cannot give (a pointer resolved, a which-person answer). No language in here.
"""
from copy import deepcopy

KINDS = ("holder", "thing", "place")
FORMS = ("key", "said", "title", "relation", "possessive", "number", "pointer", "particle", "reply", "short")
PREFIX = {"holder": "h", "thing": "t", "place": "p"}


class ConversationGraph:
    def __init__(self):
        self.nodes = {}             # id -> {"id", "kind", "name"}
        self.aliases = []           # {"node", "text", "form", "turn"}
        self.counts = {}            # (holder id, thing id or None) -> {"holder", "thing", "value", "origin", "turns"}
        self.frames = []            # {"turn", "holders", "thing", "op"}
        self._ids = {}              # (kind, name) -> id, stable within the conversation, never reused
        self._next = {kind: 1 for kind in KINDS}
        self._keys = {}             # replay key -> (holder id, thing id)

    # --- nodes and edges ------------------------------------------------------------------------------------
    def node(self, kind, name, turn=None):
        """The node of ``name`` of that kind, made at its first mention (its key alias with the turn)."""
        if kind not in KINDS or not isinstance(name, str) or not name.strip():
            raise ValueError("invalid_node")
        key = (kind, name)
        if key not in self._ids:
            self._ids[key] = "%s%d" % (PREFIX[kind], self._next[kind])
            self._next[kind] += 1
        node_id = self._ids[key]
        if node_id not in self.nodes:
            self.nodes[node_id] = {"id": node_id, "kind": kind, "name": name}
        self.alias(node_id, name, "key", turn)
        return node_id

    def join(self, kind, name, node_id, form="short", turn=None):
        """``name`` of that kind is another way to say the node ``node_id`` (a thing said with fewer of its words:
        striped towels for striped cotton beach towels): the name finds the node, and is its alias."""
        if node_id not in self.nodes or self.nodes[node_id]["kind"] != kind or not isinstance(name, str):
            return None
        self._ids.setdefault((kind, name), node_id)
        self.alias(node_id, name, form, turn)
        return self._ids[(kind, name)]

    def alias(self, node_id, text, form, turn=None):
        if node_id not in self.nodes or form not in FORMS or not isinstance(text, str) or not text.strip():
            return
        row = {"node": node_id, "text": text.strip(), "form": form, "turn": turn}
        if row not in self.aliases:
            self.aliases.append(row)

    def keyed(self, key, holder, thing):
        """The string key the replay counts under, for this holder and thing (the one place strings remain)."""
        self._keys[key] = (holder, thing)

    def keys_of(self, holder, thing):
        """The replay keys counted for this holder and thing (several when one thing was said several ways)."""
        return [key for key, pair in self._keys.items() if pair == (holder, thing)]

    def of_key(self, key):
        """(holder id, thing id) of a replay key, or None."""
        return self._keys.get(key)

    def count(self, holder, thing, value, origin, turns):
        """The count edge holder → thing: its value (an int, or None for a count not known), how it came about
        (``said`` or ``computed``) and the turns it rests on."""
        self.counts[(holder, thing)] = {"holder": holder, "thing": thing, "value": value, "origin": origin,
                                        "turns": sorted(set(turns))}

    def frame(self, turn, holders, thing, op=None):
        self.frames.append({"turn": turn, "holders": list(holders), "thing": thing, "op": op})
        del self.frames[:-8]

    # --- lookups --------------------------------------------------------------------------------------------
    def of_kind(self, kind):
        return [n for n in self.nodes.values() if n["kind"] == kind]

    def id_of(self, kind, name):
        return self._ids.get((kind, name))

    def find(self, text, kinds=None, fold=None, forms=None):
        """The nodes one of whose aliases is ``text`` (folded by ``fold``), of the given kinds and alias forms."""
        fold = fold or (lambda v: v)
        wanted = fold(text.strip()) if isinstance(text, str) else None
        found = []
        for row in self.aliases:
            if wanted is None or fold(row["text"]) != wanted or (forms and row["form"] not in forms):
                continue
            node = self.nodes.get(row["node"])
            if node and (not kinds or node["kind"] in kinds) and node["id"] not in found:
                found.append(node["id"])
        return found

    def holders_of(self, thing):
        return [holder for (holder, t) in self.counts if t == thing]

    def things_of(self, holder):
        return [t for (h, t) in self.counts if h == holder and t is not None]

    def value(self, holder, thing):
        edge = self.counts.get((holder, thing))
        return None if edge is None else edge["value"]

    def names(self, node_id):
        """Every alias text of a node, in the order said."""
        return [row["text"] for row in self.aliases if row["node"] == node_id]

    def key(self, holder, thing):
        """The string key the replay counts under (the one place strings remain until step 3)."""
        h, t = self.nodes.get(holder), self.nodes.get(thing) if thing else None
        if h is None:
            return None
        return h["name"] if t is None else "%s %s" % (h["name"], t["name"])

    # --- the snapshot ---------------------------------------------------------------------------------------
    def to_dict(self):
        return {"nodes": sorted(self.nodes.values(), key=lambda n: (n["kind"], int(n["id"][1:]))),
                "aliases": deepcopy(self.aliases),
                "counts": [dict(edge) for edge in self.counts.values()],
                "frames": deepcopy(self.frames),
                "ids": [[kind, name, node_id] for (kind, name), node_id in sorted(self._ids.items())],
                "next": dict(self._next)}

    @classmethod
    def from_dict(cls, data):
        graph = cls()
        if not isinstance(data, dict):
            return graph
        for kind, name, node_id in data.get("ids") or []:
            if kind in KINDS and isinstance(name, str) and isinstance(node_id, str):
                graph._ids[(kind, name)] = node_id
        for kind, value in (data.get("next") or {}).items():
            if kind in KINDS and isinstance(value, int) and value > 0:
                graph._next[kind] = value
        for node in data.get("nodes") or []:
            if isinstance(node, dict) and node.get("kind") in KINDS and isinstance(node.get("id"), str):
                graph.nodes[node["id"]] = {"id": node["id"], "kind": node["kind"], "name": node.get("name")}
        for row in data.get("aliases") or []:
            if isinstance(row, dict):
                graph.alias(row.get("node"), row.get("text"), row.get("form"), row.get("turn"))
        for edge in data.get("counts") or []:
            if isinstance(edge, dict) and edge.get("holder") in graph.nodes:
                graph.counts[(edge["holder"], edge.get("thing"))] = dict(edge)
        graph.frames = [dict(f) for f in data.get("frames") or [] if isinstance(f, dict)][-8:]
        return graph

    def carried(self):
        """The part of the graph a replay cannot rebuild: node ids and the aliases no statement gave."""
        return {"ids": [[kind, name, node_id] for (kind, name), node_id in sorted(self._ids.items())],
                "next": dict(self._next),
                "aliases": [dict(row) for row in self.aliases if row["form"] in ("pointer", "reply")],
                "frames": deepcopy(self.frames)}
