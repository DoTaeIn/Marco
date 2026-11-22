# Public verification

Run from the repository root with the isolated test interpreter:

```sh
PYTHONDONTWRITEBYTECODE=1 KG_ENCODER=문자 /tmp/glrvenv/bin/python -m pytest experiments/graph_language_repair/tests -q -p no:cacheprovider -c /dev/null --import-mode=importlib --rootdir=/Users/dotaein/Downloads/NAI
```

This public development suite is not the sealed independent evaluation. The isolated interpreter
and pytest must already exist; the runtime itself uses the standard library and unchanged native
search helper.
