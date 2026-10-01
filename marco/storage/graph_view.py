"""The merged base-plus-overlay view of the Persistent Overlay Infrastructure.

A base (a compiled model, read through a small reader protocol) and an overlay
store pinned at one ``seq`` give, for one graph id, the graph dictionary in the
shape ``read_kg`` returns with the overlay's additions applied and its tombstoned
nodes and edges removed, together with the origin of every node and edge (the base
build, or the overlay change with its actor and approver). Rules likewise: the
base rules minus the disabled ones, with replacements, plus the added ones.

The view reads; it never writes the base or the overlay, and nothing in it starts a
change. Pending and rejected candidates are not changes, so they never appear.
Deltas are restricted to graphs the base has, plus rules: a delta naming a graph the
base does not have is refused here with :class:`ViewError` (whole new graphs are not
supported through the overlay). Design note: ``docs/architecture/overlay.md``.

The base reader protocol (``mco.native.NativeModel`` satisfies it; :class:`PackBase`
reads a MARCO pack's members), so ``marco`` never imports ``mco``::

    graph_ids() -> [graph_id, ...]
    graph(graph_id) -> dict in read_kg's shape, without the shared hypernym merge
    node_edges(graph_id, name) -> [{"src", "rel", "dst", "list", ...}, ...]
    rules() -> [rule dict, ...] in the order MARCO collects them

Standard library only.
"""
from __future__ import annotations

from copy import deepcopy
import json
import posixpath

from marco.storage import graph_text, ids
from marco.storage import overlay as ov

__all__ = ["ViewError", "PackBase", "GraphView", "pack_rules", "apply_rule_changes", "node_data",
           "NODE_LAYERS", "EDGE_LISTS"]

#: ADD NODE ``data["layer"]``: the ``.kg`` section the node is written in, and its layer.
NODE_LAYERS = {"개념": "공통층", "사례": "사례층", "무관": "무관층", "공리": "공통층"}
#: ADD EDGE ``data["list"]``: ``엣지`` (the argument edges, default) or ``개념엣지`` (relation ``상위`` only).
EDGE_LISTS = ("엣지", "개념엣지")


class ViewError(ov.OverlayError):
    """The overlay cannot be applied to this base as it stands; nothing was applied."""


def pack_rules(manifest, members):
    """The rules of a MARCO pack in the order MARCO collects them: the axiom files the
    model declaration names, in that order, each file's ``rules`` in file order."""
    model = (manifest or {}).get("model")
    if not isinstance(model, dict):
        return []
    out = []
    for path in model.get("axioms") or []:
        doc = json.loads(members[path])
        out += [deepcopy(rule) for rule in (doc.get("rules") or [])]
    return out


class PackBase:
    """The base reader over a MARCO pack: its members (path -> bytes) and manifest.

    Graphs are parsed from their ``.kg`` text with :func:`graph_text.parse` (once each);
    callers get copies."""

    def __init__(self, manifest, members):
        self._members = members
        self._paths = {ids.graph_id(p): p for p in members if p.endswith(".kg")}
        self._rules = pack_rules(manifest, members)
        self._parsed = {}

    def graph_ids(self):
        return sorted(self._paths)

    def member(self, graph):
        """The pack path of graph id ``graph`` (``KeyError`` if the pack has none)."""
        return self._paths[ids.graph_id(graph)]

    def _graph(self, graph):
        gid = ids.graph_id(graph)
        if gid not in self._parsed:
            self._parsed[gid] = graph_text.parse(self._members[self._paths[gid]], self._paths[gid])
        return self._parsed[gid]

    def graph(self, graph):
        return deepcopy(self._graph(graph))

    def node_edges(self, graph, name):
        g = self._graph(graph)
        return [{"edge_id": ids.edge_id(graph, *edge), "src": edge[0], "rel": edge[1], "dst": edge[2], "list": key}
                for key in EDGE_LISTS for edge in g[key] if name in (edge[0], edge[2])]

    def rules(self):
        return deepcopy(self._rules)


def node_data(data):
    """An ADD NODE payload's ``data``, checked: ``{"layer", "examples", "source"}``.

    ``examples`` (required) is a non-empty list of strings; ``layer`` is one of
    ``개념`` (default), ``사례``, ``무관``, ``공리``; ``source`` (optional) is the node's
    ``출처``. Raises :class:`ViewError`."""
    if not isinstance(data, dict):
        raise ViewError("ADD_NODE needs data {'examples': [...], 'layer': '개념'|'사례'|'무관'|'공리'}, not %r"
                        % (data,))
    unknown = set(data) - {"layer", "examples", "source"}
    if unknown:
        raise ViewError("ADD_NODE data has unknown keys %s" % sorted(unknown))
    layer = data.get("layer", "개념")
    if layer not in NODE_LAYERS:
        raise ViewError("ADD_NODE layer %r is not one of %s" % (layer, sorted(NODE_LAYERS)))
    examples = data.get("examples")
    if (not isinstance(examples, list) or not examples
            or not all(isinstance(x, str) and x.strip() for x in examples)):
        raise ViewError("ADD_NODE needs a non-empty list of example sentences, not %r" % (examples,))
    source = data.get("source")
    if source is not None and (not isinstance(source, str) or not source.strip()):
        raise ViewError("ADD_NODE source must be a non-empty string")
    return {"layer": layer, "examples": list(examples), "source": source}


def _edge_list(data, rel):
    key = (data or {}).get("list", "엣지") if isinstance(data, dict) or data is None else None
    if key not in EDGE_LISTS:
        raise ViewError("ADD_EDGE data list must be one of %s, not %r" % (EDGE_LISTS, data))
    if key == "개념엣지" and rel != "상위":
        raise ViewError("a 개념엣지 edge has the relation 상위, not %r" % rel)
    return key


def _rule_body(rule_id, body, op):
    if not isinstance(body, dict) or body.get("id") != rule_id:
        raise ViewError("%s %s: the body must be a rule object whose id is %r" % (op, rule_id, rule_id))
    if not isinstance(body.get("head"), list) or not isinstance(body.get("body"), list):
        raise ViewError("%s %s: the rule needs 'head' and 'body' lists" % (op, rule_id))
    return body


def apply_rule_changes(rules, changes):
    """``rules`` (a list of rule dicts) with the overlay's rule changes applied, in order:
    disabled rules removed, replaced rules' bodies substituted in place, added rules
    substituted in place when their id is present and appended otherwise.

    ``changes`` is :meth:`GraphView.rule_changes`: ``[(rule_id, state, body), ...]``."""
    out = [deepcopy(r) for r in rules]
    position = {r.get("id"): i for i, r in enumerate(out) if isinstance(r, dict)}
    drop, tail = set(), []
    for rule_id, state, body in changes:
        if state == "disabled":
            drop.add(rule_id)
        elif rule_id in position:
            out[position[rule_id]] = deepcopy(body)
        elif state == "added":
            tail.append(deepcopy(body))
    return [r for r in out if not (isinstance(r, dict) and r.get("id") in drop)] + tail


def _origin(item):
    origin = item["origin"]
    approval = origin.get("approval") or {}
    return {"kind": "overlay", "change_id": origin["change_id"], "seq": origin["seq"], "actor": origin["actor"],
            "source": origin["source"], "approved_by": approval.get("by"), "approved_at": approval.get("at"),
            "candidate_id": approval.get("candidate_id")}


class GraphView:
    """The base and an overlay store (or ``None``) read together at one pinned ``seq``.

    ``at`` is the overlay seq to read at (the head when ``None``); the view never moves
    after it is made, so later commits do not change it."""

    def __init__(self, base, store=None, at=None, *, base_build_id=None):
        self.base = base
        self.store = store
        self.base_origin = {"kind": "base", "build_id": base_build_id}
        self._base_ids = set(base.graph_ids())
        self._graphs, self._origins, self._texts = {}, {}, {}
        if store is None:
            self.seq, self.change_id = 0, None
            self._nodes, self._edges, self._rules = {}, {}, []
            return
        head, head_id = store.head()
        self.seq = head if at is None else store._pin(at)
        self.change_id = head_id if self.seq == head else (store.change(self.seq)["change_id"] if self.seq else None)
        self._nodes, self._edges = {}, {}
        for state, items in (("added", store.added_nodes(self.seq)), ("tombstoned", store.tombstoned_nodes(self.seq))):
            for item in items:
                self._nodes.setdefault(item["graph_id"], []).append((state, item))
        for state, items in (("added", store.added_edges(self.seq)), ("tombstoned", store.tombstoned_edges(self.seq))):
            for item in items:
                self._edges.setdefault(item["graph_id"], []).append((state, item))
        rules = ([("added", i) for i in store.added_rules(self.seq)]
                 + [("replaced", i) for i in store.replaced_rules(self.seq)]
                 + [("disabled", i) for i in store.disabled_rules(self.seq)])
        self._rules = sorted(rules, key=lambda r: (r[1]["origin"]["seq"], r[1]["id"]))

    # --- which graphs ----------------------------------------------------------------------

    @property
    def key(self):
        """``(seq, change_id)``: what this view was read at."""
        return self.seq, self.change_id

    def touched_graphs(self):
        """The graph ids the overlay has a live node or edge change for at this seq, sorted."""
        return sorted(set(self._nodes) | set(self._edges))

    def unknown_graphs(self):
        """Touched graph ids the base does not have (each makes :meth:`check` refuse)."""
        return [g for g in self.touched_graphs() if g not in self._base_ids]

    def _known(self, graph):
        gid = ids.graph_id(graph)
        if gid not in self._base_ids:
            raise ViewError("graph %s is not in the base; the overlay changes graphs the base has and rules, "
                            "it does not add whole graphs" % gid)
        return gid

    # --- one graph -------------------------------------------------------------------------

    def graph(self, graph):
        """The merged graph dictionary (read_kg's shape) of ``graph`` at this seq."""
        return deepcopy(self._merged(graph)[0])

    def origins(self, graph):
        """``{"nodes": {name: origin}, "edges": {edge_id: origin}}`` for every node and edge of the
        merged graph. An origin is ``{"kind": "base", "build_id"}`` or ``{"kind": "overlay",
        "change_id", "seq", "actor", "source", "approved_by", "approved_at", "candidate_id"}``."""
        return deepcopy(self._merged(graph)[1])

    def graph_with_origins(self, graph):
        g, origins = self._merged(graph)
        return deepcopy(g), deepcopy(origins)

    def node_origin(self, graph, name):
        return deepcopy(self._merged(graph)[1]["nodes"].get(name))

    def edge_origin(self, graph, src, rel, dst):
        try:
            edge = ids.edge_id(graph, src, rel, dst)
        except ValueError:
            return None
        return deepcopy(self._merged(graph)[1]["edges"].get(edge))

    def text(self, graph):
        """The merged graph as ``.kg`` text the engine reads (``graph_text.write``). A graph
        whose text would not read back equal is refused with :class:`ViewError`."""
        gid = self._known(graph)
        if gid not in self._texts:
            g = self._merged(gid)[0]
            try:
                self._texts[gid] = graph_text.write(g, gid)
            except graph_text.GraphTextError as exc:
                raise ViewError("graph %s cannot be written back as .kg text exactly, so overlay changes to it "
                                "are refused: %s" % (gid, exc)) from None
        return self._texts[gid]

    def writable(self, graph):
        """``None`` if the base graph ``graph`` has exact ``.kg`` text, else the reason (overlay
        changes to such a graph are refused)."""
        return graph_text.unwritable(self.base.graph(self._known(graph)))

    def _merged(self, graph):
        gid = self._known(graph)
        if gid in self._graphs:
            return self._graphs[gid], self._origins[gid]
        g = self.base.graph(gid)
        if gid in self._nodes or gid in self._edges:
            reason = graph_text.unwritable(g)
            if reason:
                raise ViewError("graph %s cannot be written back as .kg text exactly, so overlay changes to it "
                                "are refused: %s" % (gid, reason))
        base = self.base_origin
        nodes = {name: base for layer in graph_text.LAYER_KEYS for name in g[layer]}
        edges = {}
        for key in EDGE_LISTS:
            for edge in g[key]:
                try:
                    edges[ids.edge_id(gid, *edge)] = base
                except ValueError:
                    pass
        node_items = self._nodes.get(gid, [])
        edge_items = self._edges.get(gid, [])
        gone_nodes = {item["name"] for state, item in node_items if state == "tombstoned"}
        gone_edges = {item["id"] for state, item in edge_items if state == "tombstoned"}
        if gone_nodes:
            _remove_nodes(g, gone_nodes)
            for name in gone_nodes:
                nodes.pop(name, None)
        for key in EDGE_LISTS:
            g[key] = [e for e in g[key] if _eid(gid, e) not in gone_edges
                      and e[0] not in gone_nodes and e[2] not in gone_nodes]
        for eid in gone_edges:
            edges.pop(eid, None)
        for state, item in node_items:
            if state != "added":
                continue
            data = node_data(item["data"])
            _remove_nodes(g, {item["name"]}, keep_slots=True)
            g[NODE_LAYERS[data["layer"]]][item["name"]] = list(data["examples"])
            if data["layer"] == "공리":
                g["공리"].append(item["name"])
            if data["source"]:
                g.setdefault("출처", {})[item["name"]] = data["source"]
            nodes[item["name"]] = _origin(item)
        for state, item in edge_items:
            if state != "added":
                continue
            key = _edge_list(item["data"], item["rel"])
            edge = [item["src"], item["rel"], item["dst"]]
            if edge not in g[key]:
                g[key].append(edge)
            edges[item["id"]] = _origin(item)
        # an edge whose end node is gone has no origin left to report
        live = {_eid(gid, e) for key in EDGE_LISTS for e in g[key]}
        edges = {k: v for k, v in edges.items() if k in live}
        self._graphs[gid] = g
        self._origins[gid] = {"nodes": nodes, "edges": edges}
        return g, self._origins[gid]

    # --- rules -----------------------------------------------------------------------------

    def rule_changes(self):
        """``[(rule_id, state, body), ...]`` at this seq, oldest change first; ``state`` is
        ``added``, ``replaced`` or ``disabled``. Feed it to :func:`apply_rule_changes`."""
        out = []
        for state, item in self._rules:
            body = item["body"]
            if state != "disabled":
                _rule_body(item["id"], body, "ADD_RULE" if state == "added" else "REPLACE_RULE")
            out.append((item["id"], state, deepcopy(body)))
        return out

    def rules(self):
        """The base rules with the overlay's rule changes applied."""
        return apply_rule_changes(self.base.rules(), self.rule_changes())

    def rule_origins(self):
        """``{rule_id: origin}`` for every rule of :meth:`rules`."""
        out = {r.get("id"): self.base_origin for r in self.base.rules() if isinstance(r, dict)}
        for state, item in self._rules:
            if state == "disabled":
                out.pop(item["id"], None)
            else:
                out[item["id"]] = _origin(item)
        return deepcopy(out)

    # --- checking a change -------------------------------------------------------------------

    def check(self):
        """Refuse, with :class:`ViewError`, an overlay that cannot be applied to this base:
        a delta naming a graph the base does not have, a graph that has no exact ``.kg``
        text, a node without examples, an added edge whose end is not a node of the graph
        (or of a graph it includes), a tombstone or rule change naming something the base
        and the overlay never had, a rule body that is not a rule. Returns the touched
        graph ids."""
        unknown = self.unknown_graphs()
        if unknown:
            self._known(unknown[0])
        for gid in self.touched_graphs():
            self.text(gid)
            names = self._names_with_includes(gid)
            base = self.base.graph(gid)
            base_edges = {_eid(gid, e) for key in EDGE_LISTS for e in base[key]}
            base_nodes = {n for layer in graph_text.LAYER_KEYS for n in base[layer]}
            for state, item in self._edges.get(gid, []):
                if state == "added" and item["data"] and _edge_list(item["data"], item["rel"]) == "개념엣지":
                    continue
                if state == "added":
                    for end in (item["src"], item["dst"]):
                        if end not in names:
                            raise ViewError("ADD_EDGE %s -%s-> %s in %s: %r is not a node of the graph or of a graph "
                                            "it includes" % (item["src"], item["rel"], item["dst"], gid, end))
                elif item["id"] not in base_edges and not self._ever(item["id"], "ADD_EDGE"):
                    raise ViewError("RETRACT_EDGE %s -%s-> %s: graph %s has no such edge"
                                    % (item["src"], item["rel"], item["dst"], gid))
            for state, item in self._nodes.get(gid, []):
                if state == "tombstoned" and item["name"] not in base_nodes and not self._ever(item["id"], "ADD_NODE"):
                    raise ViewError("RETRACT_NODE %s: graph %s has no such node" % (item["name"], gid))
        base_rules = {r.get("id") for r in self.base.rules() if isinstance(r, dict)}
        for rule_id, state, _body in self.rule_changes():
            if rule_id not in base_rules and not self._ever(rule_id, "ADD_RULE"):
                if state != "added":
                    raise ViewError("%s %s: the base has no such rule" % (
                        "DISABLE_RULE" if state == "disabled" else "REPLACE_RULE", rule_id))
        return self.touched_graphs()

    def _ever(self, target_id, op):
        """Whether the overlay had an ``op`` delta on ``target_id`` at or before this seq."""
        return any(row["op"] == op and row["seq"] <= self.seq for row in self.store.history(target_id))

    def _names_with_includes(self, gid):
        """The node names of ``gid`` and the concepts (공통층) it borrows through ``포함``, as
        ``engine._include`` borrows them: a child's concepts after its own includes."""
        g = self._merged(gid)[0]
        return {n for layer in graph_text.LAYER_KEYS for n in g[layer]} | self._borrowed(gid, {gid})

    def _borrowed(self, gid, seen):
        out = set()
        for raw in self._merged(gid)[0].get("포함") or []:
            child = ids.graph_id(posixpath.normpath(posixpath.join(posixpath.dirname(gid), raw)))
            if child in self._base_ids and child not in seen:
                seen.add(child)
                out |= set(self._merged(child)[0]["공통층"]) | self._borrowed(child, seen)
        return out

    # --- building requests that need the base ------------------------------------------------

    def retract_node(self, graph, name, *, revision):
        """A RETRACT NODE request with the base's edges of the node named (``base.node_edges``),
        so the one change also tombstones every base edge that touches it."""
        gid = self._known(graph)
        edges = sorted({(r["src"], r["rel"], r["dst"]) for r in self.base.node_edges(gid, name)},
                       key=lambda e: ids.edge_id(gid, *e))
        return ov.retract_node(gid, name, revision=revision, base_edges=edges)


def _eid(gid, edge):
    try:
        return ids.edge_id(gid, *edge)
    except ValueError:
        return None


def _remove_nodes(g, names, keep_slots=False):
    for layer in graph_text.LAYER_KEYS:
        for name in names:
            g[layer].pop(name, None)
    g["공리"] = [n for n in g["공리"] if n not in names]
    if "출처" in g:
        for name in names:
            g["출처"].pop(name, None)
    if not keep_slots:
        for slot in graph_text.SLOT_KEYS:
            if slot == "출처" or slot not in g:
                continue
            for name in names:
                g[slot].pop(name, None)
