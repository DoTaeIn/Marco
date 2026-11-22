# -*- coding: utf-8 -*-
"""The character chart.

Everything here is a positional scan over the Unicode code points of the text.
A form comes from the graph data; the scan, the overlap resolution and the
boundary test are generic mechanics.  No whitespace token is ever treated as a
unit of meaning: a chunk exists only to decide where a marker may attach and to
offer nested mention starts.
"""


def scan_forms(text, lo, hi, specs):
    """Every position where a declared form matches inside ``[lo, hi)``.

    ``specs`` is a sequence of ``(form, payload)``.  A hit is
    ``{"span": (start, end), "form": form, "payload": payload}``.
    """
    hits = []
    for index in range(lo, hi):
        for form, payload in specs:
            end = index + len(form)
            if end <= hi and text.startswith(form, index):
                hits.append({"span": (index, end), "form": form, "payload": payload})
    hits.sort(key=lambda hit: (hit["span"][0], -hit["span"][1]))
    return hits


def _matches_any(text, index, forms):
    for form in forms:
        if form and text.startswith(form, index):
            return form
    return None


def trim_span(text, start, end, trim_forms):
    """Move the edges of a span past declared trim forms.  The result stays exact."""
    moved = True
    while moved and start < end:
        moved = False
        form = _matches_any(text, start, trim_forms)
        if form is not None and start + len(form) <= end:
            start += len(form)
            moved = True
    moved = True
    while moved and start < end:
        moved = False
        for form in trim_forms:
            if form and end - len(form) >= start and text.startswith(form, end - len(form)):
                end -= len(form)
                moved = True
                break
    return start, end


def _overlaps(left, right):
    return left[0] < right[1] and right[0] < left[1]


def _resolve_overlaps(hits, rank):
    """Keep the best hit of each overlapping group, by the declared ranking."""
    kept = []
    for hit in sorted(hits, key=rank):
        if any(_overlaps(hit["span"], other["span"]) for other in kept):
            continue
        kept.append(hit)
    kept.sort(key=lambda item: item["span"])
    return kept


class Chart(object):
    """Segments, chunks and the eligible marker, predicate and frame hits."""

    def __init__(self, text, store, limits):
        self.text = text
        self.store = store
        self.limits = dict(limits)
        self.notes = []

        self.space_forms = store.mark_forms("space")
        self.ender_forms = store.mark_forms("segment_ender")
        self.trim_forms = store.mark_forms("trim")
        self.boundary_forms = store.mark_forms("boundary_after_marker")
        self.chunk_policy = None
        for record in store.of_kind("policy"):
            if record.get("role") == "chunk":
                self.chunk_policy = record
        if self.chunk_policy is None:
            raise ValueError("the graph data declares no chunk policy")

        self.segments = self._segments()
        self.chunks = {segment["id"]: self._chunks(segment) for segment in self.segments}
        self.frame_hits = self._frame_hits()
        self.action_hits = self._action_hits()
        self._compose_actions()
        self.marker_hits = self._marker_hits()

    # -- construction ----------------------------------------------------

    def _segments(self):
        text = self.text
        cap = self.limits.get("max_segments")
        spans, start = [], 0
        index = 0
        while index < len(text):
            form = _matches_any(text, index, self.ender_forms)
            if form is None:
                index += 1
                continue
            end = index + len(form)
            while end < len(text) and _matches_any(text, end, self.ender_forms):
                end += 1
            spans.append((start, end))
            while end < len(text) and _matches_any(text, end, self.space_forms):
                end += 1
            start = end
            index = end
        if start < len(text):
            spans.append((start, len(text)))
        segments = []
        for position, (lo, hi) in enumerate(spans):
            lo, hi = self._trim(lo, hi, keep_ender=True)
            if lo >= hi:
                continue
            if cap is not None and len(segments) >= cap:
                self.notes.append("max_segments")
                break
            segments.append({"id": "seg:%d" % len(segments), "span": (lo, hi),
                             "index": len(segments)})
        return segments

    def _trim(self, start, end, keep_ender=False):
        forms = [form for form in self.trim_forms
                 if not (keep_ender and form in self.ender_forms)]
        return trim_span(self.text, start, end, forms)

    def _chunks(self, segment):
        lo, hi = segment["span"]
        cap = self.limits.get("max_chunks_per_segment")
        chunks, index = [], lo
        while index < hi:
            if _matches_any(self.text, index, self.space_forms):
                index += 1
                continue
            start = index
            while index < hi and not _matches_any(self.text, index, self.space_forms):
                index += 1
            if cap is not None and len(chunks) >= cap:
                self.notes.append("max_chunks_per_segment")
                break
            chunks.append((start, index))
        return tuple(chunks)

    def segment_of(self, span):
        for segment in self.segments:
            if segment["span"][0] <= span[0] and span[1] <= segment["span"][1]:
                return segment
        return None

    def _frame_hits(self):
        specs = []
        for record in self.store.of_kind("report_frame"):
            for form in record.get("forms", ()):
                specs.append((form, record))
        hits = []
        for segment in self.segments:
            lo, hi = segment["span"]
            found = scan_forms(self.text, lo, hi, specs)
            found = _resolve_overlaps(found, lambda hit: (-(hit["span"][1] - hit["span"][0]),
                                                          hit["span"][0]))
            for hit in found:
                hits.append({"span": hit["span"], "form": hit["form"],
                             "frame": hit["payload"]["key"], "record": hit["payload"],
                             "position": hit["payload"].get("position", "prefix"),
                             "segment": segment["id"]})
        return hits

    def _action_specs(self):
        specs = []
        for record in self.store.of_kind("action"):
            frame = record.get("frame")
            for form in record.get("forms", ()):
                specs.append((form["surface"], {
                    "action": record["key"], "frame": frame,
                    "voice": form.get("voice", "active"),
                    "polarity": bool(form.get("polarity", True)),
                    "mood": form.get("mood", "declarative"),
                    "host_must_not_end_with": tuple(record.get("host_must_not_end_with", ())),
                    "requires_nonempty_host": bool(record.get("requires_nonempty_host"))}))
        return specs

    def _host_allows(self, hit, segment, chunk_of):
        """Whether what precedes a predicate form inside its chunk is allowed.

        The copula shares its characters with many verb endings, so an action
        record may declare host endings it refuses to attach to.  The test is
        character equality against declared forms.
        """
        payload = hit["payload"]
        blocked = payload.get("host_must_not_end_with", ())
        if not blocked and not payload.get("requires_nonempty_host"):
            return True
        chunk = chunk_of.get(hit["span"][0])
        host_start = chunk[0] if chunk else segment["span"][0]
        host = self.text[host_start:hit["span"][0]]
        if payload.get("requires_nonempty_host") and not host:
            return False
        return not any(host.endswith(form) for form in blocked if form)

    def _eligible_after(self, end, segment, frame_starts):
        if end >= segment["span"][1]:
            return True
        if _matches_any(self.text, end, self.boundary_forms) is not None:
            return True
        return end in frame_starts

    def _action_hits(self):
        specs = self._action_specs()
        hits = []
        for segment in self.segments:
            lo, hi = segment["span"]
            frame_starts = {hit["span"][0] for hit in self.frame_hits
                            if hit["segment"] == segment["id"]}
            frame_spans = [hit["span"] for hit in self.frame_hits
                           if hit["segment"] == segment["id"]]
            chunk_of = {}
            for start, end in self.chunks[segment["id"]]:
                for offset in range(start, end + 1):
                    chunk_of.setdefault(offset, (start, end))
            found = []
            for hit in scan_forms(self.text, lo, hi, specs):
                if any(_overlaps(hit["span"], span) for span in frame_spans):
                    continue
                if not self._eligible_after(hit["span"][1], segment, frame_starts):
                    continue
                if not self._host_allows(hit, segment, chunk_of):
                    continue
                found.append(hit)
            found = _resolve_overlaps(found, lambda hit: (-(hit["span"][1] - hit["span"][0]),
                                                          hit["span"][0]))
            for hit in found:
                payload = hit["payload"]
                hits.append({"span": hit["span"], "surface": hit["form"],
                             "action": payload["action"], "frame": payload["frame"],
                             "voice": payload["voice"], "polarity": payload["polarity"],
                             "mood": payload["mood"], "segment": segment["id"]})
        return hits

    def _compose_actions(self):
        from experiments.graph_language_repair.core.morphology import analyze_predicates
        declared = list(self.action_hits)
        for hit in analyze_predicates(self.text, store=self.store):
            span = tuple(hit["span"])
            if any(_overlaps(span, item["span"]) for item in declared + self.frame_hits):
                continue
            if any(_overlaps(span, item["span"]) and span != item["span"]
                   for item in self.action_hits):
                continue
            segment = self.segment_of(span)
            if segment is None:
                continue
            hit["span"] = span
            hit["segment"] = segment["id"]
            self.action_hits.append(hit)
        self.action_hits.sort(key=lambda item: item["span"])

    def _marker_specs(self):
        specs = []
        for record in self.store.of_kind("marker"):
            for form in record.get("forms", ()):
                specs.append((form, record))
        return specs

    def _marker_hits(self):
        policy = self.chunk_policy
        needs_boundary = bool(policy.get("marker_requires_boundary_after"))
        needs_host = bool(policy.get("marker_requires_nonempty_host"))
        closing_first = bool(policy.get("closing_outranks_internal"))
        blocking = []
        for class_name in policy.get("marker_blocking_form_classes", ()):
            blocking.extend(form.strip() for form in self.store.form_class(class_name))
        blocking = {form for form in blocking if form}
        host_rules = self._host_rules()
        specs = self._marker_specs()
        hits = []
        for segment in self.segments:
            lo, hi = segment["span"]
            chunk_of = {}
            for start, end in self.chunks[segment["id"]]:
                for offset in range(start, end + 1):
                    chunk_of.setdefault(offset, (start, end))
            chunk_starts = {start for start, _ in self.chunks[segment["id"]]}
            blocked = [hit["span"] for hit in self.frame_hits
                       if hit["segment"] == segment["id"]]
            blocked += [hit["span"] for hit in self.action_hits
                        if hit["segment"] == segment["id"]]
            frame_starts = {span[0] for span in blocked}
            internal_specs = [(form, record) for form, record in specs
                              if record.get("attachment") == "internal"]
            found = []
            for hit in scan_forms(self.text, lo, hi, specs):
                start, end = hit["span"]
                if any(_overlaps(hit["span"], span) for span in blocked):
                    continue
                if needs_host and start in chunk_starts:
                    continue
                if needs_host and start == lo:
                    continue
                if (hit["payload"].get("attachment", "closing") == "closing"
                        and policy.get("extend_closing_marker_over_internal_forms")):
                    end, extended = self._extend_over_internal(end, segment, internal_specs)
                    hit["extended_by"] = extended
                    hit["span"] = (start, end)
                if needs_boundary and not self._eligible_after(end, segment, frame_starts):
                    continue
                if blocking:
                    chunk = chunk_of.get(start)
                    if chunk is not None and self.text[chunk[0]:end].strip() in blocking:
                        continue
                if self._host_blocked(hit, chunk_of, host_rules):
                    continue
                if not self._phonology_allows(hit, chunk_of):
                    continue
                found.append(hit)

            def rank(item):
                record = item["payload"]
                attachment = record.get("attachment", "closing")
                closing_rank = 0 if (attachment == "closing" and closing_first) else 1
                return (-(item["span"][1] - item["span"][0]), closing_rank,
                        item["span"][0], record["key"])

            cap = self.limits.get("max_marker_options_per_segment")
            if cap is not None and len(found) > cap:
                self.notes.append("max_marker_options_per_segment")
                found = found[:cap]
            for hit in _resolve_overlaps(found, rank):
                record = hit["payload"]
                start, end = hit["span"]
                hits.append({"span": (start, end), "form": self.text[start:end],
                             "marker": record["key"],
                             "classes": tuple(record.get("classes", ())),
                             "attachment": record.get("attachment", "closing"),
                             "extended_by": tuple(hit.get("extended_by", ())),
                             "segment": segment["id"]})
        return hits

    def _extend_over_internal(self, end, segment, internal_specs):
        """Take immediately following internal marker forms into a closing span.

        ``에서부터`` would otherwise fail the boundary test and lose the origin
        marker entirely, leaving the next value span to start inside ``부터``.
        """
        extended = []
        limit = segment["span"][1]
        moved = True
        while moved and end < limit:
            moved = False
            best = None
            for form, record in internal_specs:
                if self.text.startswith(form, end) and end + len(form) <= limit:
                    if best is None or len(form) > len(best[0]):
                        best = (form, record)
            if best is not None:
                extended.append(best[1]["key"])
                end += len(best[0])
                moved = True
        return end, extended

    def _phonology_allows(self, hit, chunk_of):
        """Apply declared allomorph constraints when the host is analyzable."""
        chunk = chunk_of.get(hit["span"][0])
        if not chunk or hit["span"][0] <= chunk[0]:
            return True
        codepoint = ord(self.text[hit["span"][0] - 1])
        # Unicode's precomposed Hangul syllable arithmetic yields coda index.
        if not 0xAC00 <= codepoint <= 0xD7A3:
            return True
        present = (codepoint - 0xAC00) % 28 != 0
        for policy in self.store.of_kind("marker_phonology_policy"):
            if policy.get("script") != "hangul_syllable_coda":
                continue
            for rule in policy.get("rules", ()):
                if hit["form"] in rule.get("forms", ()):
                    return present == (rule.get("coda") == "present")
        return True

    def _host_rules(self):
        rules = []
        for record in self.store.of_kind("marker_host_policy"):
            for rule in record.get("rules", ()):
                rules.append(rule)
        return rules

    def _host_blocked(self, hit, chunk_of, host_rules):
        """Whether a declared stem ending in front of a marker blocks the hit."""
        if not host_rules:
            return False
        classes = set(hit["payload"].get("classes", ()))
        chunk = chunk_of.get(hit["span"][0])
        if chunk is None:
            return False
        host = self.text[chunk[0]:hit["span"][0]]
        if not host:
            return False
        for rule in host_rules:
            wanted = set(rule.get("marker_classes", ()))
            if wanted and not wanted & classes:
                continue
            for form in rule.get("host_ends_with", ()):
                if form and host.endswith(form):
                    return True
        return False

    # -- queries ---------------------------------------------------------

    def value(self, span):
        return self.text[span[0]:span[1]]

    def trimmed(self, start, end):
        return self._trim(start, end)

    def chunk_starts_within(self, span):
        starts = []
        for segment in self.segments:
            for start, _ in self.chunks[segment["id"]]:
                if span[0] <= start < span[1]:
                    starts.append(start)
        return tuple(sorted(set(starts)))

    def chunk_ends_within(self, span):
        ends = []
        for segment in self.segments:
            for _, end in self.chunks[segment["id"]]:
                if span[0] < end <= span[1]:
                    ends.append(end)
        return tuple(sorted(set(ends)))

    def chunk_bounds_within(self, span):
        bounds = []
        for segment in self.segments:
            for start, end in self.chunks[segment["id"]]:
                if span[0] <= start and end <= span[1]:
                    bounds.append((start, end))
        return tuple(sorted(set(bounds)))

    def markers_within(self, span, segment_id=None, attachment=None):
        found = []
        for hit in self.marker_hits:
            if segment_id is not None and hit["segment"] != segment_id:
                continue
            if hit["span"][0] < span[0] or hit["span"][1] > span[1]:
                continue
            if attachment is not None and hit["attachment"] != attachment:
                continue
            found.append(hit)
        found.sort(key=lambda hit: hit["span"])
        return found

    def actions_within(self, span, segment_id=None):
        found = [hit for hit in self.action_hits
                 if span[0] <= hit["span"][0] and hit["span"][1] <= span[1]
                 and (segment_id is None or hit["segment"] == segment_id)]
        found.sort(key=lambda hit: hit["span"])
        return found
