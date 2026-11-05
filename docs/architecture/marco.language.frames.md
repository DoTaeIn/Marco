# `marco.language.frames`

## Purpose

L1 language structure shared by declared clause reading and the existing event
frame induction helpers. This page records the new opt-in constituent reader;
the existing induction algorithms and their responsibilities are unchanged.

## Owns

`declared_clause(parser, source)` reads one predicate and its role constituents
from the selected parser's `predicate_frames` declaration. The declaration
names predicate forms, role markers and default positions, head syntax, retained
modifiers, terminal punctuation and leading whole-clause operators. Its meaning
is a signed/modal triple using role references. The reader returns exact source
spans, full character coverage, frame identity and declaration digest.

`relational_semantics.RelationalParser` calls it before source rewrites or clause
segmentation. A clause owned by the declaration is accepted completely or held;
normalization or a broad legacy slot cannot silently rescue rejected text.
Declared operators, predicate forms and role markers cannot be absorbed into
an entity head or modifier. A registered selected query keeps its original
query meaning; a question mark cannot authorize an asserted fact.

## Does not own

Domain vocabulary, relations, answers and inference rules belong to selected
model assets. This reader has no host language/model fallback and adds no
runtime predictive language model. It does not learn a new concept or rule,
mutate dialogue memory, decide inference validity or implement a second parser
engine. Modifiers remain part of an entity reference; they do not establish
independent properties or aliases.

The slice supports a declared single predicate and single clause. Nested
operator scope, quantifiers, relative clauses, generic Korean particle
composition and new generic question grammar remain unsupported. An opt-in
model conservatively holds multiple clauses containing declared predicates.
The ordinary production language packs have no new frame declarations yet.

## Depends on

The standard library, existing Hangul helpers and relational substitution.
`RelationalParser` still sends the resulting meanings through its normal fact,
evidence, query and inference paths. LearningMemory can teach an expression
equivalent to an already readable composed fact under its existing supervised
validation contract; this is not autonomous concept learning.

## Public interface

The declaration schema is `predicate-frames-v1`. `declared_clause` returns
`None` when no declared predicate owns the input, `("hold", reason)` when a
declared clause cannot be fully read, or `("ok", meaning, trace)` when it can.
Malformed or unsupported declarations raise `ValueError`. `declared_source`
retains selected terminal punctuation when legacy clause spans omit it.

The fixture and runnable parser demo are
`examples/marco2_declared_clause_demo.py`; 42 public contract tests live in
`tests/test_marco2_declared_clause_composition.py`. Root review additionally
passed three immutable reserved-word faults and 19 other-selected-graph and
learning checks, plus 162 affected existing checks. Eight separate processes
using actual DialogueSession verified selected meanings, rules and answers,
teaching transfer after restart, history after retraction and independent
answering after a local hold. These are development demonstrations, not a
new independent conversation score or general language coverage claim.
