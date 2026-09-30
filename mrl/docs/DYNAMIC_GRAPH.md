# Dynamic graph storage

Graphs grow node and edge slot arrays on demand. A node handle contains a graph identity, a 32-bit slot index, and a generation. Removing a node invalidates its old generation; a later insertion can reuse the slot without making the old handle valid.

The runtime keeps high-water cursors and free-slot stacks, so inserting a large graph does not rescan existing slots. Edge insertion follows the same rule. Allocation failures and arithmetic overflow stop execution through the normal runtime failure path.

Search paths own immutable, reference-counted snapshot storage. Retaining a path or copying a path set keeps a snapshot valid after later searches, graph growth, and graph mutation. Call `mrl_search_result_release`, `mrl_path_release`, or `mrl_pathset_release` when native callers discard these values. Generated MRL releases temporary path results and reusable path-set slots.

`MRL_MAX_PATHS` remains the explicit maximum number of paths returned by one `find_all` call. It is an enumeration budget; it does not limit node or edge storage.
