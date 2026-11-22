# -*- coding: utf-8 -*-
"""Epistemic scope: which claim a clause is stated inside.

A reporting frame in the graph data turns part of a segment into an inner
region that belongs to a reported or attributed claim, and names the reporter
from a declared region rather than from word order guessing.  Because the
reporter is consumed before the inner region starts, an inner subject span can
no longer reach back into the attribution prefix.

The core never moves a clause out of the claim it was stated in.
"""


class ScopeBuilder(object):
    def __init__(self, chart, store):
        self.chart = chart
        self.store = store
        self.claims = [{"id": "claim:0", "kind": "direct_text",
                        "span": (0, len(chart.text)), "frame": None,
                        "reporter_span": None, "reporter_mention": None,
                        "inherits_from": None, "policy": "scope:direct_text"}]
        self.regions = []
        self._depth_cap = 3

    # -- helpers ---------------------------------------------------------

    def _new_claim(self, kind, span, frame, reporter_span, parent):
        claim = {"id": "claim:%d" % len(self.claims), "kind": kind, "span": span,
                 "frame": frame, "reporter_span": reporter_span,
                 "reporter_mention": None,
                 "inherits_from": None if parent == "claim:0" else parent,
                 "policy": "scope:%s" % kind}
        self.claims.append(claim)
        return claim

    def _scope_kind(self, record, reporter_span):
        kind = record.get("scope_kind", "reported_claim")
        if reporter_span is None:
            return kind
        surface = self.chart.text[reporter_span[0]:reporter_span[1]]
        for override in record.get("scope_kind_overrides", ()):
            class_name = override.get("when_reporter_contains_class")
            if class_name is None:
                continue
            for form in self.store.form_class(class_name):
                if form in surface:
                    return override["scope_kind"]
        return kind

    def _reporter_from_marker(self, record, segment, span, limit):
        """The reporter span, starting at the end of the previous closing marker.

        Starting at the region start instead swallowed any preceding time or
        place expression into the reporter, so a source question answered with
        a span containing an adverbial — a wrong answer, not a hold.  This is
        the rule ``chart-marks`` already declares for a value span:
        ``value_span_starts_at: previous_consumed_end``.
        """
        wanted = set(record.get("reporter_marker_classes", ()))
        cursor = span[0]
        for hit in self.chart.markers_within((span[0], limit), segment["id"],
                                             attachment="closing"):
            if hit["span"][0] < cursor:
                continue
            if wanted and not wanted & set(hit["classes"]):
                cursor = hit["span"][1]
                continue
            start, end = self.chart.trimmed(cursor, hit["span"][0])
            if start >= end:
                cursor = hit["span"][1]
                continue
            return (start, end), hit["span"][1]
        return None, span[0]

    def _reporter_before(self, segment, span, limit):
        """The reporter span of a prefix frame, from the previous consumed end."""
        cursor = span[0]
        for hit in self.chart.markers_within((span[0], limit), segment["id"],
                                             attachment="closing"):
            if hit["span"][1] <= limit:
                cursor = max(cursor, hit["span"][1])
        start, end = self.chart.trimmed(cursor, limit)
        return (start, end) if start < end else None

    # -- walk ------------------------------------------------------------

    def build(self):
        for segment in self.chart.segments:
            hits = [hit for hit in self.chart.frame_hits if hit["segment"] == segment["id"]]
            self._region(segment, segment["span"], "claim:0", hits, 0)
        return self.claims, self.regions

    def apply_nonassertive_boundaries(self, drafts):
        """Attach only enclosed predicates to quote or interrogative scopes."""
        policies = self.store.of_kind("scope_boundary_policy")
        if not policies:
            return
        policy = policies[0]
        text = self.chart.text
        pairs = policy.get("quote_pairs", ())
        stack, ranges = [], []
        for index, char in enumerate(text):
            if stack and char == stack[-1][1]:
                start, _ = stack.pop()
                ranges.append((start, index + 1))
                continue
            for opening, closing in pairs:
                if char == opening:
                    stack.append((index, closing))
                    break
        cached = {}
        for draft in drafts:
            start, end = draft.predicate["span"]
            enclosed = [span for span in ranges if span[0] < start and end <= span[1] - 1]
            parent = next(claim for claim in self.claims if claim["id"] == draft.claim_id)
            kind, span = None, None
            segment_span = draft.segment["span"]
            segment_text = text[segment_span[0]:segment_span[1]]
            if any(segment_text.endswith(form) for form in policy.get("interrogative_endings", ())):
                kind, span = policy["interrogative_kind"], segment_span
            elif enclosed and parent["kind"] not in policy.get("preserve_enclosing_report_kinds", ()):
                kind = policy["quoted_kind"]
                span = min(enclosed, key=lambda value: value[1] - value[0])
            if kind:
                key = (draft.claim_id, kind, span)
                if key not in cached:
                    cached[key] = self._new_claim(kind, span, None, None, draft.claim_id)["id"]
                draft.claim_id = cached[key]

    def _region(self, segment, span, claim_id, hits, depth):
        span = self.chart.trimmed(*span)
        if span[0] >= span[1]:
            return
        usable = [hit for hit in hits
                  if span[0] <= hit["span"][0] and hit["span"][1] <= span[1]]
        if not usable or depth >= self._depth_cap:
            self.regions.append({"span": span, "claim": claim_id, "segment": segment})
            return
        prefixes = [hit for hit in usable if hit["position"] == "prefix"]
        hit = prefixes[0] if prefixes else usable[-1]
        remaining = [other for other in usable if other is not hit]

        wants_reporter = hit["record"].get("reporter_from") != "none"
        if not wants_reporter:
            # Agentless hearsay: the sentence says that something is said
            # without saying who says it.  Naming the inner clause's own
            # subject as the reporter would invent a source.
            reporter_span = None
            inner = (span[0], hit["span"][0])
        elif hit["position"] == "prefix":
            reporter_span = self._reporter_before(segment, span, hit["span"][0])
            inner = (hit["span"][1], span[1])
        else:
            reporter_span, inner_start = self._reporter_from_marker(
                hit["record"], segment, span, hit["span"][0])
            inner = (inner_start, hit["span"][0])

        kind = self._scope_kind(hit["record"], reporter_span)
        claim = self._new_claim(kind, span, hit["frame"], reporter_span, claim_id)
        self._region(segment, inner, claim["id"], remaining, depth + 1)
