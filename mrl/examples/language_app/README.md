# Language app acceptance fixture

`main.mrl` is the source-level acceptance app for the language completion
slice. It imports `knowledge.mrl`, reads a UTF-8 input path from `argv`, adds
the text as a fact, selects and explains the derived fact, saves a checkpoint,
supersedes the input fact, and commits the update. A second process restores the
checkpoint and verifies the committed fact plus historical fact access.

The executable commands are run from a separate working directory so `input.txt` and `state.mrlk` stay
caller-relative:

```powershell
python -m mrl run mrl/examples/language_app/main.mrl -- write input.txt state.mrlk
python -m mrl run mrl/examples/language_app/main.mrl -- restore unused state.mrlk
```

The fixture is intentionally source-only and contains no handwritten C glue.
