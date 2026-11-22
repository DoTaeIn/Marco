# -*- coding: utf-8 -*-
"""Mention nodes.

Every surface occurrence of a value is its own mention, named by its character
span.  Spans inside a value span — chunk-aligned starts, and the remainder
after a declared determiner — become their own nested mentions, joined to the
container only by containment edges.  A mention is never merged with a mention
it contains, so a longer named span and a shorter description inside it stay
two things (CONTRACT C2).
"""


class MentionTable(object):
    def __init__(self, chart, store, limits):
        self.chart = chart
        self.store = store
        self.limits = dict(limits)
        self.mentions = {}
        self._determiners = store.form_class("demonstrative")

    def _record(self, span, segment_id, nested_of=None):
        key = "mention:%d-%d" % span
        mention = self.mentions.get(key)
        if mention is None:
            mention = {"id": key, "span": span,
                       "surface": self.chart.value(span),
                       "segment": segment_id,
                       "contains": [], "contained_by": [],
                       "nested_of": []}
            self.mentions[key] = mention
        if nested_of and nested_of not in mention["nested_of"]:
            mention["nested_of"].append(nested_of)
        return mention

    def intern(self, span, segment_id):
        """The mention for a value span, with its nested mentions."""
        span = self.chart.trimmed(*span)
        if span[0] >= span[1]:
            return None
        mention = self._record(span, segment_id)
        for nested in self._nested_spans(span):
            self._record(nested, segment_id, nested_of=mention["id"])
        return mention

    def _nested_spans(self, span):
        """Sub-spans of a value that a later reference could pick out.

        Chunk-aligned only: each whole chunk, each suffix from a chunk start,
        each prefix to a chunk end, and the span minus a leading determiner.
        Every one of them is a mention in its own right; none of them is
        merged with its container except by the determiner-head rule.
        """
        candidates = set()
        for start, end in self.chart.chunk_bounds_within(span):
            if (start, end) != span:
                candidates.add((start, end))
        for start in self.chart.chunk_starts_within(span):
            if start > span[0]:
                candidates.add((start, span[1]))
        for end in self.chart.chunk_ends_within(span):
            if end < span[1]:
                candidates.add((span[0], end))
        surface = self.chart.value(span)
        for form in self._determiners:
            if surface.startswith(form) and len(form) < len(surface):
                candidates.add((span[0] + len(form), span[1]))
        cleaned = set()
        for candidate in candidates:
            trimmed = self.chart.trimmed(*candidate)
            if trimmed[0] < trimmed[1] and trimmed != span:
                cleaned.add(trimmed)
        cap = self.limits.get("max_nested_mentions_per_span")
        ordered = sorted(cleaned, key=lambda item: (-(item[1] - item[0]), item[0]))
        if cap is not None and len(ordered) > cap:
            self.capped = True
        return ordered[:cap] if cap is not None else ordered

    def finish(self):
        """Fill the containment edges once every mention exists."""
        ordered = sorted(self.mentions.values(), key=lambda item: item["span"])
        for outer in ordered:
            for inner in ordered:
                if inner is outer:
                    continue
                if (outer["span"][0] <= inner["span"][0]
                        and inner["span"][1] <= outer["span"][1]):
                    if inner["id"] not in outer["contains"]:
                        outer["contains"].append(inner["id"])
                    if outer["id"] not in inner["contained_by"]:
                        inner["contained_by"].append(outer["id"])
        return ordered
