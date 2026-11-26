# Original public tax replay — 2026-11-26

The original 24 questions, followed by the four separately labelled supplemental questions, were replayed verbatim. The original 14-fact passage text was used byte for byte. Gold was read from the original public question files. No answer feedback or question-derived memory was injected. This is an exposed regression check, not a fresh generalisation evaluation.

## Reference runtime

Imported source revision: `c2c7f96015ee80969fb0e2ece6f36ef96912ed7b`. Assets are the current checkout's frozen public language lesson builders, field metadata, word lessons and listed ways of asking. Every imported source and asset is hashed in `reference/manifest.json`, before and after execution. Both lists remained unchanged. The primary route calls the normal text entry point `answer.answer(original_passage, exact_question, language)`; the supplied original graph is a separately labelled diagnostic. Both routes returned the same scores.

| Configuration | Strict value match /24 | Partial or assumed /24 | Right proposal /24 | Held /24 | Expected hold /24 | Wrong answers /24 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Current language only | 0 | 0 | 0 | 22 | 2 | 0 |
| Plus shipped original field words | 14 | 0 | 0 | 8 | 2 | 0 |
| Plus current field metadata and general word lessons | 14 | 0 | 1 | 7 | 2 | 0 |
| Plus current field metadata and merged field word lessons | 14 | 0 | 1 | 7 | 2 | 0 |

The 14 answers are Q01–Q14. Q15 is the right proposal (`10%`) only with the current metadata/word lessons. A proposal is a question awaiting user confirmation, not an answered question. Q16–Q21 and Q24 remain held; Q22 and Q23 hold as expected. Original field words are `packs/tax_words.json`; current metadata comes from the already existing seventeenth field trial and listed ways from the eighth trial. These additional field explanations, aliases and ways of asking are not part of the original 14 facts and are separated above.

Supplemental4 stays outside the 24 denominator. With any field words, C01/C03/C04 are strict value matches; C02 is an assumed answer under a stated interpretation. Without field words all four hold.

## Controlled final runtime comparison

Final base revision: `c8e2e48988eedfa9290362eda60b8e6b69420edc` plus the frozen working-tree runtime. The full final source SHA-256 map is in `final/manifest.json`; its canonical JSON digest is `777320ff2acb0dadcda043ba0d4537450f4e762abbcd2b1f7b78f8c916cf2daa`. Only `answer.py` and `relate.py` differ from the imported reference runtime. Imported sources and all assets remained unchanged through each replay. The final run has another 224 first outputs.

| Current metadata configuration | Before strict /24 | Final strict /24 | Before right proposals /24 | Final right proposals /24 | Wrong answers or proposals |
| --- | ---: | ---: | ---: | ---: | ---: |
| General word lessons | 14 | 14 | 1 | 3 | 0 |
| Merged field word lessons | 14 | 14 | 1 | 3 | 0 |

Both primary text and supplied-graph diagnostic agree. Q16 and Q17 are the only score transitions: held → right proposal. Q16 would offer `사업개시일부터20일이내`, explicitly leaving `사업을`, `시작하고` unaccounted for; Q17 would offer `홈택스`, leaving `온라인으로`, `이용하면` unaccounted for. They require confirmation and are not counted as answers or complete question understanding. Q15 stays a right proposal. Q01–Q14 stay strict value matches; Q18–Q21/Q24 stay held and Q22/Q23 stay expected holds. Supplemental4 stays 3 strict +1 assumed/partial. Language-only and original-field-word controls do not change.

Result: PASS for unchanged answers and the two additional correct proposals; FAIL for any claim of increased automatic answers on this original24. All per-case states, including unchanged ones, are preserved in `transitions.json`. Historical expanded132 remains a separately labelled lesson-confounded comparison.

## Saved historical comparison

The saved 2026-11-19 report and `audit/result_audit.json` state that expanded132 returned 18/24 values: 15 without an omission flag and three partial (Q16, Q20, Q24); six held. The 15 include Q17. Saved frozen44 returned 10/24 and variants44 14/24. Supplemental4 was four value matches in each condition. The historical `first_results.jsonl` is absent on this checkout; these historical counts are read from saved report/audit, not recomputed from that missing raw file.

The present lesson/model configuration differs from expanded132. Consequently 18 historical answers versus 14 present answers under the current word lessons is not a controlled code-only before/after comparison. Text and supplied-graph agreement does isolate the original passage intake from the present question failures.

## Reproduction and evidence

`reference/raw.jsonl.gz` preserves all 224 first outputs (four configurations × two routes ×28), each with exact question, original gold, full returned object and score. `phase1/` retains the initial local 168-output precheck; it had three configurations and the same scores. Use the reference run for the controlled revision pin.

`REPLAY-HARNESS.txt` contains the executable diagnostic source as data. To repeat, copy it to `/private/tmp/replay_public_tax.py`, run from the repository root with `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python3 /private/tmp/replay_public_tax.py NEW_OUTPUT_NAME IMPORT_ROOT`. The output name must be new. Omitting IMPORT_ROOT imports the current checkout. The harness writes only inside this old-tax folder; it edits no runtime or test files.

A strict value match means the returned value matches gold without this receipt's partial/assumed flags. It is not a certification that all semantic nuances or an independent executor were verified. Raw objects preserve those independent fields.

The full per-question JSONL captures are stored with lossless gzip compression. The harness writes the uncompressed stream.
