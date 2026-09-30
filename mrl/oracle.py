"""Frozen, structural oracle adapter for the MRL graph vertical slice."""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from graph_inference import closure, closure_with_provenance, proof


BASELINE_SHA = "d5d91a21397fc5ac0d3ce0923d8756c867c85eca"


def source_sha256():
    return sha256(Path(__file__).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def graph_inference_sha256():
    source = (Path(__file__).parents[1] / "graph_inference.py").read_bytes()
    return sha256(source.replace(b"\r\n", b"\n")).hexdigest()


def freeze(value):
    """Make tuple-keyed inference maps JSON values without serializing them."""
    if isinstance(value, dict):
        if value and all(isinstance(key, tuple) for key in value):
            return {"$tuple_map": [
                {"key": list(key), "value": freeze(row)} for key, row in value.items()
            ]}
        return {key: freeze(row) for key, row in value.items()}
    if isinstance(value, list):
        return [freeze(row) for row in value]
    return value


def evaluate(case):
    """Run one declarative fixture case without formatting its result."""
    operation = case["operation"]
    try:
        if operation == "closure":
            known = closure(case["facts"], case["rules"], **case.get("options", {}))
            result = {"known": known}
            if "target" in case:
                result["proof"] = proof(known, case["target"])
        elif operation == "closure_with_provenance":
            result = closure_with_provenance(
                case["facts"], case["rules"], **case.get("options", {})
            )
        else:
            raise ValueError("unknown_oracle_operation")
    except ValueError as error:
        return {"error": str(error)}
    return freeze(result)
