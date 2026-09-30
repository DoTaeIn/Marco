# MRL language tooling

The package can be used directly from a checkout; no install step or extra
Python package is required.

```powershell
python -m mrl check mrl/examples/primitive.mrl
python -m mrl build mrl/examples/primitive.mrl -o mrl/.build/primitive.exe
python -m mrl run mrl/examples/primitive.mrl -- input.txt
python -m mrl test
```

The original compiler form remains available:

```powershell
python -m mrl mrl/examples/primitive.mrl -o mrl/.build/primitive.c
```

`build` stages generated C and the executable in a temporary directory beside
the requested destination and replaces the destination only after compilation
succeeds. `run` uses a temporary executable, inherits the caller's working
directory, and forwards arguments as an argv list. Compiler output is printed with the native compiler's original
diagnostics. A source file or a recursively imported `.mrl` file is never a
valid output destination.

Relative imports without an alias retain the historical flattening behavior:

```mrl
import "facts.mrl"
```

An explicit alias gives a module namespace:

```mrl
import "math_helpers.mrl" as math
fn main() -> si { return math.increment(4) }
```

The loader qualifies declared functions, structs, relations, and graphs as
`math__name` before frontend parsing, and rewrites `math.name` references to
that spelling. The rewrite is token-aware, so strings and comments are not
modified. A module reached more than once is emitted once, cycles are rejected,
and source diagnostics retain the imported file and original line number.
The compiler and loader therefore share a simple contract: qualification is a
source-loader concern; the frontend receives ordinary identifiers and keeps
its existing declaration and call rules.

Native build support reuses the private C11 compiler discovery and cache in
`mrl.toolchain`. Each compiler invocation gets a private Zig local cache while
the global cache is shared read-mostly, so concurrent builds do not corrupt
one another's per-build state. A fresh checkout needs a complete local C11
compiler (the bundled Windows Zig compiler is used when present). The tooling
does not download compilers or add dependencies.

Native `main() -> si` keeps the existing ABI: it prints its result before
exiting successfully. Source builtins are `argc() -> si`,
`argv(si) -> Result<s, s>`, `read_text(s) -> Result<s, s>`, and
`write_text(s, s) -> Result<si, s>`. A successful write returns the UTF-8 byte
count, including zero for an empty write; errors return owned MRL strings.
Generated entry points initialize and clean up process arguments. On Windows,
`CommandLineToArgvW` preserves quoted empty arguments, escaped quotes, trailing
backslashes, and Unicode before UTF-8 conversion.

The source-only application test runs from a separate caller directory, uses
Unicode file content, and verifies checkpoint plus journal restoration in a
fresh process. Package installation and cross-module type re-export policies
remain unspecified.
