"""Marshal the bounded native Horn subset; matching and closure execute in C."""
from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
import ctypes
import json
import struct
import subprocess
import threading
from pathlib import Path

from mrl import toolchain

SOURCE = Path(__file__).with_name("runtime") / "native_graph.c"
_ERROR = {1: "graph_limit", 3: "unsafe_rule", 4: "unsupported_native_rule",
          5: "malformed_native_wire", 6: "native_capacity"}
_MAGIC = 0x4D524C32
_MAX_RESPONSE = 4 * (5 + 64 * (7 + 128 * 8))
_MAX_CLOSURE_RESPONSE = 4 * (5 + 64 * 7)
_MAX_GROWING_CAPACITY = 16384
_LOAD_LOCK = threading.Lock()


def available():
    return toolchain.find_compiler()[0] is not None


def _triple(value):
    return isinstance(value, list) and len(value) == 3 and all(isinstance(x, str) for x in value)


def _support_id(item, index):
    evidence = item.get("evidence") or {}
    return str(item.get("id") or (evidence.get("fact_id") if isinstance(evidence, dict) else None)
               or "fact:%d" % index)


def _validate(case):
    if not isinstance(case, dict) or case.get("operation") not in ("closure", "closure_with_provenance"):
        raise ValueError("unsupported_native_operation")
    facts, rules = case.get("facts"), case.get("rules")
    if not isinstance(facts, list) or not isinstance(rules, list):
        raise ValueError("invalid_native_case")
    provenance = case["operation"] == "closure_with_provenance"
    support_ids = set()
    for index, item in enumerate(facts):
        if (not isinstance(item, dict) or not _triple(item.get("triple"))
                or type(item.get("polarity", True)) is not bool
                or item.get("modality", "asserted") not in ("asserted", "planned", "conditional")
                or (not provenance and "evidence" not in item)
                or (provenance and item.get("evidence") and not isinstance(item["evidence"], dict))):
            raise ValueError("invalid_native_fact")
        if item.get("polarity", True) and item.get("modality", "asserted") == "asserted":
            ident = _support_id(item, index)
            if ident in support_ids:
                raise ValueError("duplicate_native_support_id")
            support_ids.add(ident)
    rule_ids, names = set(), []
    for rule in rules:
        if (not isinstance(rule, dict) or not isinstance(rule.get("id"), str) or not rule["id"]
                or not isinstance(rule.get("body"), list) or not _triple(rule.get("head"))
                or not all(_triple(row) for row in rule["body"])):
            raise ValueError("invalid_native_rule")
        if rule["id"] in rule_ids:
            raise ValueError("duplicate_native_rule_id")
        rule_ids.add(rule["id"])
        if len(rule["body"]) != 1:
            raise ValueError("unsupported_native_rule")
        variables = list(dict.fromkeys(x for x in rule["body"][0] + rule["head"] if x.startswith("?")))
        if len(variables) > 3:
            raise ValueError("unsupported_native_rule")
        names.append(variables)
    if "target" in case and (provenance or not _triple(case["target"])):
        raise ValueError("invalid_native_target")
    options = case.get("options", {})
    allowed = {"limit", "proof_limit", "search_limit"} if provenance else {"limit"}
    if not isinstance(options, dict) or options.keys() - allowed:
        raise ValueError("invalid_native_options")
    limit = options.get("limit", 2048)
    if type(limit) is not int or not 1 <= limit <= 2**31 - 1:
        raise ValueError("invalid_native_options")
    budgets = (limit, options.get("proof_limit", 32), options.get("search_limit", limit * 8))
    if any(type(value) is not int or not 1 <= value <= 2**31 - 1 for value in budgets):
        raise ValueError("invalid_native_options")
    return provenance, names, budgets


def _freeze_map(rows):
    return {"$tuple_map": [{"key": key, "value": value} for key, value in rows]} if rows else {}


def _prepare(case):
    """Validate and marshal once for both native transports."""
    provenance, names, budgets = _validate(case)
    symbols = {}
    for item in case["facts"]:
        for value in item["triple"]:
            symbols.setdefault(value, len(symbols))
    for rule in case["rules"]:
        for value in rule["body"][0] + rule["head"]:
            if not value.startswith("?"):
                symbols.setdefault(value, len(symbols))
    terms = []
    for rule, variables in zip(case["rules"], names):
        def term(value):
            return -(variables.index(value) + 1) if value.startswith("?") else symbols[value]
        terms.append(([term(x) for x in rule["body"][0]], [term(x) for x in rule["head"]]))
    payload = [_MAGIC, 2 if provenance else 1, len(case["facts"]), len(case["rules"]), *budgets]
    for item in case["facts"]:
        payload.extend([*(symbols[x] for x in item["triple"]), int(item.get("polarity", True)),
                        int(item.get("modality", "asserted") == "asserted")])
    payload.extend(x for body, _ in terms for x in body)
    payload.extend(x for _, head in terms for x in head)
    return struct.pack("<%di" % len(payload), *payload), list(symbols), names, provenance


@lru_cache(maxsize=32)
def _load_path(path):
    library = ctypes.CDLL(str(Path(path).resolve()))
    pointer, size = ctypes.c_void_p, ctypes.c_size_t
    signatures = {
        "mrl_native_graph_run": (ctypes.c_int, [pointer, size, pointer, size, ctypes.POINTER(size)]),
        "mrl_graph_state_size": (size, []),
        "mrl_graph_state_size_for": (size, [size]),
        "mrl_graph_prepare": (ctypes.c_int, [pointer, size, pointer, size]),
        "mrl_graph_evaluate": (ctypes.c_int, [pointer, size, pointer, size, ctypes.POINTER(size)]),
        "mrl_graph_append": (ctypes.c_int, [pointer, size, pointer, size]),
    }
    for name, (result, arguments) in signatures.items():
        function = getattr(library, name)
        function.restype, function.argtypes = result, arguments
    return library


@lru_cache(maxsize=2)
def _load_library(optimization="release"):
    # Loaded code is a process snapshot; restart after editing native sources.
    library = _load_path(str(toolchain.cached_shared(SOURCE, optimization=optimization)))
    return library, library.mrl_native_graph_run


def _response_bytes(status, output, written):
    if status != 0:
        raise RuntimeError("native_graph_abi_error:%d" % status)
    if not 4 <= written.value <= len(output):
        raise ValueError("malformed_native_wire")
    return ctypes.string_at(output, written.value)


def evaluate(case, *, optimization="release"):
    """Evaluate a fresh input, retaining full validation and structural output."""
    packet, symbols, names, provenance = _prepare(case)
    with _LOAD_LOCK:
        _, run = _load_library(optimization)
    source = ctypes.create_string_buffer(packet)
    output = ctypes.create_string_buffer(_MAX_RESPONSE if provenance else _MAX_CLOSURE_RESPONSE)
    written = ctypes.c_size_t()
    status = run(source, len(packet), output, len(output), ctypes.byref(written))
    return _decode(_response_bytes(status, output, written), case, symbols, names, provenance)


class PreparedGraph:
    """A validated native graph with immutable rules and transactional fact appends."""

    def __init__(self, case, *, optimization="release", specialized=False, capacity=64):
        if type(capacity) is not int or not 64 <= capacity <= _MAX_GROWING_CAPACITY:
            raise ValueError("invalid_native_capacity")
        self._case = deepcopy(case)
        packet, self._symbols, self._names, self._provenance = _prepare(self._case)
        self._symbol_ids = {value: index for index, value in enumerate(self._symbols)}
        self._capacity = capacity
        self._lock = threading.Lock()
        with _LOAD_LOCK:
            if specialized:
                from mrl.graph_plan import compile_plan
                self._library = _load_path(str(compile_plan(self._case, optimization=optimization)))
            else:
                self._library, _ = _load_library(optimization)
        state_size = self._library.mrl_graph_state_size_for(capacity)
        if not 0 < state_size <= 1024 * 1024:
            raise RuntimeError("invalid_native_state_size")
        self._state = ctypes.create_string_buffer(state_size)
        source = ctypes.create_string_buffer(packet)
        status = self._library.mrl_graph_prepare(source, len(packet), self._state, len(self._state))
        if status:
            raise ValueError(_ERROR.get(status, "native_prepare_error:%d" % status))
        proof_rows = capacity * (min(self._case.get("options", {}).get("proof_limit", 32), 128) + 1)
        output_size = 4 * (5 + capacity * 7 + (proof_rows * 8 if self._provenance else 0))
        self._output = ctypes.create_string_buffer(output_size)
        self._written = ctypes.c_size_t()

    def evaluate(self):
        """Recompute from resident inputs and return a new complete structural result."""
        with self._lock:
            status = self._library.mrl_graph_evaluate(
                self._state, len(self._state), self._output, len(self._output),
                ctypes.byref(self._written))
            return _decode(_response_bytes(status, self._output, self._written), self._case,
                           self._symbols, self._names, self._provenance, capacity=self._capacity)

    def append_facts(self, facts):
        """Send only new fact rows; a failed append leaves both stores unchanged."""
        if not isinstance(facts, list):
            raise ValueError("invalid_native_case")
        with self._lock:
            rows = deepcopy(facts)
            prospective = {**self._case, "facts": self._case["facts"] + rows}
            _validate(prospective)
            symbols, ids = self._symbols.copy(), self._symbol_ids.copy()
            payload = [len(rows)]
            for item in rows:
                for value in item["triple"]:
                    if value not in ids:
                        ids[value] = len(symbols)
                        symbols.append(value)
                payload.extend([*(ids[value] for value in item["triple"]),
                                int(item.get("polarity", True)),
                                int(item.get("modality", "asserted") == "asserted")])
            packet = struct.pack("<%di" % len(payload), *payload)
            source = ctypes.create_string_buffer(packet)
            status = self._library.mrl_graph_append(
                self._state, len(self._state), source, len(packet))
            if status:
                raise ValueError(_ERROR.get(status, "native_append_error:%d" % status))
            self._case, self._symbols, self._symbol_ids = prospective, symbols, ids


def evaluate_subprocess(case, executable):
    """Verify the same wire contract through a prebuilt CLI executable."""
    packet, symbols, names, provenance = _prepare(case)
    run = subprocess.run([str(Path(executable).resolve())], input=packet,
                         capture_output=True, timeout=10, check=True)
    return _decode(run.stdout, case, symbols, names, provenance)


def _decode(data, case, symbols, names, provenance, *, capacity=64):
    def require(condition):
        if not condition:
            raise ValueError("malformed_native_wire")
    require(len(data) >= 4 and len(data) % 4 == 0)
    values = struct.unpack("<%di" % (len(data) // 4), data)
    position = 0

    def take(count):
        nonlocal position
        require(position + count <= len(values))
        result = values[position:position + count]
        position += count
        return result

    status, = take(1)
    if status:
        require(status in _ERROR and position == len(values))
        return {"error": _ERROR[status]}
    complete, reason, searches, count = take(4)
    require(complete in (0, 1) and reason in (0, 1, 2) and 0 <= count <= capacity and searches >= 0)
    require((complete == 1) == (reason == 0))
    facts, records, seen = [], [], set()
    for _ in range(count):
        s, p, o, rule, parent, evidence, bundle_count = take(7)
        require(all(0 <= x < len(symbols) for x in (s, p, o)) and 0 <= bundle_count <= 128)
        require(provenance or bundle_count == 0)
        triple = [symbols[s], symbols[p], symbols[o]]
        require(tuple(triple) not in seen)
        seen.add(tuple(triple))
        rows = [take(8) for _ in range(bundle_count)]
        facts.append((triple, rule, parent, evidence, rows))
    require(position == len(values))
    for triple, rule, parent, evidence, _ in facts:
        record = {"fact": triple}
        if rule == -1:
            require(parent == -1 and 0 <= evidence < len(case["facts"]))
            item = case["facts"][evidence]
            require(item["triple"] == triple and item.get("polarity", True)
                    and item.get("modality", "asserted") == "asserted")
            record["evidence"] = deepcopy((item.get("evidence") or {}) if provenance else item["evidence"])
        else:
            require(0 <= rule < len(case["rules"]) and 0 <= parent < count and evidence == -1)
            record.update(rule=case["rules"][rule]["id"], parents=[facts[parent][0]])
        records.append(record)
    if not provenance:
        result = {"known": _freeze_map([(row[0], record) for row, record in zip(facts, records)])}
        if "target" in case:
            lookup = {tuple(row[0]): index for index, row in enumerate(facts)}
            index = lookup[tuple(case["target"])]
            chain, visited = [], set()
            while index != -1:
                require(index not in visited)
                visited.add(index)
                chain.append(records[index])
                index = facts[index][2]
            result["proof"] = list(reversed(chain))
        return result

    memo = {}
    def decode_bundle(start):
        # Single-premise links form a chain. Iteration avoids a Python recursion ceiling.
        key, chain, visiting = start, [], set()
        while key not in memo:
            fact_index, bundle_index = key
            require(0 <= fact_index < count and 0 <= bundle_index < len(facts[fact_index][4]))
            require(key not in visiting)
            visiting.add(key)
            triple, _, _, _, rows = facts[fact_index]
            asserted, rule, asserted_input, parent_fact, parent_bundle, *slots = rows[bundle_index]
            require(asserted in (0, 1))
            if asserted:
                require(rule == parent_fact == parent_bundle == -1 and slots == [-1, -1, -1]
                        and 0 <= asserted_input < len(case["facts"]))
                item = case["facts"][asserted_input]
                require(item["triple"] == triple and item.get("polarity", True)
                        and item.get("modality", "asserted") == "asserted")
                ident = _support_id(item, asserted_input)
                memo[key] = {"id": "support:" + ident, "kind": "asserted", "conclusion": triple,
                             "premise_fact_ids": [ident], "rule": None, "rule_version": None,
                             "bindings": {}, "valid": True}
                break
            require(0 <= rule < len(case["rules"]) and asserted_input == -1)
            variables = names[rule]
            require(all(0 <= x < len(symbols) for x in slots[:len(variables)])
                    and all(x == -1 for x in slots[len(variables):]))
            bindings = {name: symbols[x] for name, x in zip(variables, slots)}
            parent = (parent_fact, parent_bundle)
            chain.append((key, triple, rule, bindings, parent))
            key = parent
        for key, triple, rule, bindings, parent in reversed(chain):
            spec = case["rules"][rule]
            version = deepcopy(spec.get("version", spec.get("rule_version")))
            premise = memo[parent]["id"]
            ident = "derive:%s:%s:%s" % (spec["id"], version, json.dumps(
                [triple, sorted(bindings.items()), [premise]], ensure_ascii=False,
                sort_keys=True, separators=(",", ":")))
            memo[key] = {"id": ident, "kind": "derived", "conclusion": triple,
                         "premise_fact_ids": [premise], "rule": spec["id"],
                         "rule_version": version, "bindings": bindings, "valid": True}
        return memo[start]

    bundles = [(triple, [decode_bundle((index, j)) for j in range(len(rows))])
               for index, (triple, _, _, _, rows) in enumerate(facts)]
    return {"facts": _freeze_map([(row[0], record) for row, record in zip(facts, records)]),
            "proof_bundles": _freeze_map(bundles), "complete": bool(complete),
            "reason": (None, "graph_limit", "proof_or_search_limit")[reason], "searches": searches}

