# MRL FFI boundary

The source FFI slice has a deliberately small contract. The existing frontend
parser consumes declarations of this form:

```mrl
extern fn c_abs(value: si) -> si = "abs"
```

The quoted symbol must be a C identifier. The loader preserves that symbol
string through module aliasing; aliases affect MRL names only.

After parsing, `lower_extern` produces token-free declaration IR such as
`{"name": "c_abs", "params": [{"name": "value", "type": "si32"}],
"return_type": "si32", "symbol": "abs"}`. Only numeric and boolean scalar
types, plus `ptr<T>` with a numeric or boolean pointee, cross this boundary;
managed MRL strings and aggregates stay outside this minimal ABI.

Foreign calls and pointer operations are valid only inside `unsafe { ... }`:

```mrl
unsafe {
    p = addr(value)
    store(p, 4)
    result = load(p)
    return c_abs(result)
}
```

`addr` accepts a mutable scalar local and returns `ptr<T>`. `load(ptr<T>)`
returns `T`; `store(ptr<T>, T)` has no value. Pointer values are unmanaged and
must not outlive the addressed local. The boundary does not infer foreign
ownership, callbacks, aggregate layouts, or a linker framework.

`mrl/language_ffi.py` provides the parser hook `parse_extern`, source lowering
through `lower_ffi_call`, independent raw-IR validation through `validate_ffi`,
and C emission through `emit_ffi`. The backend must provide the normal MRL
expression callback, C type mapper, line emitter, fresh-name allocator, and
managed-value callback. The FFI helper never marks pointers as managed.

The standalone tests compile a native `abs` call and local pointer load/store,
and reject foreign calls outside unsafe context and addresses of immutable
locals. `tests/test_language_app_e2e.py` also contains the source-level FFI
program through the CLI. It is part of the default test suite and requires no
handwritten C glue.
