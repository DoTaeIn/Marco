# Managed values

`s`, `list<T>`, `map<K,V>`, managed records, options, and results are owned values in generated C. Copies retain containers or duplicate strings; assignment and scope exit release the previous owner.

`list<T>` accepts managed elements through generated copy/release hooks. `map<K,V>` supports `s` and signed or unsigned integer keys, owns copied keys and values, and iterates keys with `for (key in map)`.

Generated code keeps the two-argument `mrl_list_new(item_size, capacity)` ABI for native snippets. Managed generated lists use the hook-aware form internally.

Graph payloads copy managed records into graph storage, release them when a node removes connected storage, and release live payloads before program exit.
