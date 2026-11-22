# -*- coding: utf-8 -*-
"""Row emission.

A row is the only answer-bearing object.  Every row carries at least one
character span and exactly one claim, so nothing can be read out of this graph
without its source and its epistemic scope (CONTRACT C4).

Meta rows — what the document says about itself: scope, reporter, mention,
containment, link, verification — are attributed to ``claim:0``.  Content rows
— action, polarity, roles, checking outcome — are attributed to the claim the
clause was stated inside.  That split is what stops a report from being read as
truth while still letting a question find the report (CONTRACT C5).
"""


class RowBuilder(object):
    def __init__(self, limits):
        self.rows = []
        self.limits = dict(limits)
        self.capped = False

    def add(self, triple, claim, spans, polarity=True, **meta):
        cap = self.limits.get("max_rows")
        if cap is not None and len(self.rows) >= cap:
            self.capped = True
            return None
        spans = [tuple(span) for span in spans if span is not None]
        if not spans:
            raise ValueError("a row needs at least one source span: %r" % (triple,))
        row = {"id": "row:%d" % len(self.rows),
               "triple": [str(atom) for atom in triple],
               "polarity": bool(polarity),
               "modality": "asserted",
               "claim": claim,
               "spans": spans,
               "depends_on": list(meta.pop("depends_on", ()) or ()),
               "construction": meta.pop("construction", None),
               "reading": meta.pop("reading", None),
               "hypotheses": list(meta.pop("hypotheses", ()) or ()),
               "proof": meta.pop("proof", None),
               "scope_kind": meta.pop("scope_kind", None),
               "layer": meta.pop("layer", "content")}
        row.update(meta)
        self.rows.append(row)
        return row


class ProofBuilder(object):
    def __init__(self):
        self.proofs = []

    def add(self, kind, policy, spans, because, rows=()):
        proof = {"id": "proof:%d" % len(self.proofs), "kind": kind, "policy": policy,
                 "spans": [tuple(span) for span in spans], "because": because,
                 "rows": list(rows)}
        self.proofs.append(proof)
        return proof
