# `marco.language`

Text and structure: language packs, parsing, realization. Written 2026-09-23
against commit `78bd062`; updated 2026-09-24 against `5f321a3` (goal D2), after
the realizer rounds made `realize` more than a stub.

## Purpose

Be the one place where MARCO turns between language and meaning. Today the
output direction lives here: Hermeneia, the language realization pipeline, and
its check, in [`marco.language.realizer`](marco.language.realizer.md). The input
direction, Noesis for text (packs, parsing, particles), still lives in root
modules; goal S4 moves the whole-file ones under `marco/language/`
(`python tools/doc_facts.py layout` lists them), and the split of the large
ones waits for MARCO 1.

## Owns

- The exported name `realize`, re-exported from
  [`marco.language.realizer`](marco.language.realizer.md)
  ([marco/language/__init__.py](../../marco/language/__init__.py)).
- `__all__ == ["realize"]`.
- The subpackage `marco.language.realizer`.
- The realizer's round report `marco/language/W1-report.md` and the measurements
  folder `marco/language/measurements/` (fluency samples, composition counts).

## Does not own

- Parsing. `relational_semantics.py`, `frame_induction.py`,
  `input_understanding.py` and `semantic_parser.py` are root modules.
- Language packs. `styles/한국어.json` and `styles/english.json` are read by
  `pack_model.py`, `language_components.py` and `reasoning_context.py`.
- Korean particles and inflection (`hangul.py`), which the realizer's grammar
  layer calls.
- The graph engine's authored answer lines (`engine.py`). They pass through
  `realize` unchanged, because no plan composes them.

## Depends on

- `marco.language.realizer`. No other import in `__init__.py`.

## Public interface

| Name | Signature | Proof |
| --- | --- | --- |
| `realize` | `realize(meaning, intent, language) -> str` | `tests/test_language_seam.py::test_realize_is_exported_with_the_declared_signature` asserts `__all__`, the three parameter names and the `str` return annotation |

Its callers are `ReasoningContext.turn` (`reasoning_context.py`), `engine.answer`
(`engine.py`) and `AppState` (`views/kgpack_ui.py`). What the function does:
[marco.language.realizer.md](marco.language.realizer.md).
