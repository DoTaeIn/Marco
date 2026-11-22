# -*- coding: utf-8 -*-
"""Loading and lookup for the explicit graph data.

Generic mechanics only: this module reads JSON records, checks their shape and
offers lookup by key, kind and form class.  It knows no marker, no predicate and
no policy — every one of those is a record under ``graphs/core/``.
"""
import json
import os

GRAPH_SCHEMA = "graph-language-repair-graph-v1"

_CORE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "graphs", "core")


class GraphDataError(ValueError):
    """The graph data is not shaped the way the store requires."""


class GraphStore(object):
    """An immutable view over the loaded records."""

    def __init__(self, records, files):
        self._records = records
        self._files = tuple(files)
        by_kind = {}
        for record in records.values():
            by_kind.setdefault(record["kind"], []).append(record)
        for kind in by_kind:
            by_kind[kind] = tuple(sorted(by_kind[kind], key=lambda item: item["key"]))
        self._by_kind = by_kind

    @property
    def files(self):
        return self._files

    @property
    def keys(self):
        return tuple(sorted(self._records))

    def get(self, key):
        try:
            return self._records[key]
        except KeyError:
            raise GraphDataError("no graph record %r" % (key,))

    def has(self, key):
        return key in self._records

    def of_kind(self, kind):
        return self._by_kind.get(kind, ())

    def one_of_kind(self, kind):
        found = self.of_kind(kind)
        if len(found) != 1:
            raise GraphDataError("expected exactly one %r record, found %d" % (kind, len(found)))
        return found[0]

    def form_class(self, class_name):
        """Forms of a ``form_class`` record, longest first."""
        for record in self.of_kind("form_class"):
            if record.get("class") == class_name:
                return tuple(sorted(record.get("forms", ()), key=len, reverse=True))
        raise GraphDataError("no form_class record for %r" % (class_name,))

    def mark_forms(self, role):
        """Forms of a ``mark_class`` record, longest first."""
        for record in self.of_kind("mark_class"):
            if record.get("role") == role:
                return tuple(sorted(record.get("forms", ()), key=len, reverse=True))
        raise GraphDataError("no mark_class record for role %r" % (role,))

    def alias_pairs(self):
        """Symmetric set of declared alias surface pairs."""
        pairs = set()
        for record in self.of_kind("alias"):
            surfaces = list(record.get("surfaces", ()))
            for left in surfaces:
                for right in surfaces:
                    if left != right:
                        pairs.add((left, right))
        return pairs

    def limits(self):
        return dict(self.one_of_kind("limits"))


def _check_record(record, where):
    if not isinstance(record, dict):
        raise GraphDataError("%s: a record must be an object" % (where,))
    for field in ("key", "kind"):
        if not isinstance(record.get(field), str) or not record[field]:
            raise GraphDataError("%s: a record needs a non-empty %r" % (where, field))


def load_graph_file(path):
    """Records of one graph file, keyed by ``key``."""
    with open(path, "r", encoding="utf-8") as handle:
        document = json.load(handle)
    if not isinstance(document, dict):
        raise GraphDataError("%s: the file must hold an object" % (path,))
    if document.get("schema") != GRAPH_SCHEMA:
        raise GraphDataError("%s: schema %r is not %r"
                             % (path, document.get("schema"), GRAPH_SCHEMA))
    records = document.get("records")
    if not isinstance(records, list):
        raise GraphDataError("%s: records must be a list" % (path,))
    found = {}
    for index, record in enumerate(records):
        _check_record(record, "%s[%d]" % (path, index))
        if record["key"] in found:
            raise GraphDataError("%s: duplicate key %r" % (path, record["key"]))
        found[record["key"]] = record
    return found


def load_graphs(directory=None, extra_graphs=()):
    """Every ``*.json`` of the directory, plus caller-supplied record lists.

    ``extra_graphs`` entries are either a path to a graph file or a list of
    records.  A caller-supplied key may not shadow a core key.
    """
    directory = _CORE_DIR if directory is None else directory
    records, files = {}, []
    for name in sorted(os.listdir(directory)):
        if not name.endswith(".json"):
            continue
        path = os.path.join(directory, name)
        for key, record in load_graph_file(path).items():
            if key in records:
                raise GraphDataError("duplicate key %r across graph files" % (key,))
            records[key] = record
        files.append(name)
    for index, supplied in enumerate(extra_graphs):
        if isinstance(supplied, str):
            loaded = load_graph_file(supplied)
            files.append(supplied)
        else:
            loaded = {}
            for position, record in enumerate(supplied):
                _check_record(record, "extra_graphs[%d][%d]" % (index, position))
                loaded[record["key"]] = record
            files.append("extra_graphs[%d]" % (index,))
        for key, record in loaded.items():
            if key in records:
                raise GraphDataError("supplied key %r shadows an existing record" % (key,))
            records[key] = record
    return GraphStore(records, files)
