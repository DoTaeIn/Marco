"""A bounded, local observation environment for ALMA integration tests and CLI use.

The environment exposes only its public observation payload through read
adapters.  The runtime never receives its backing mapping or an evaluation
answer directly.
"""
from copy import deepcopy
import hashlib
import json
import time
import uuid


def _portable(value):
    return json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True))


def _fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def _validate(config):
    if not isinstance(config, dict):
        raise ValueError("invalid_environment")
    goal, initial, reads = config.get("goal"), config.get("initial_observation"), config.get("reads")
    if (not isinstance(goal, dict) or not isinstance(goal.get("text"), str)
            or not isinstance(goal.get("condition"), dict) or not isinstance(goal.get("information_gap"), str)
            or not goal["information_gap"]
            or not isinstance(initial, dict) or not isinstance(initial.get("text"), str)
            or not isinstance(initial.get("measurements"), dict)
            or not isinstance(reads, list) or not reads):
        raise ValueError("invalid_environment")
    for item in reads:
        if (not isinstance(item, dict) or not isinstance(item.get("name"), str)
                or not isinstance(item.get("provides"), list) or not item["provides"]
                or not isinstance(item.get("responses"), dict)):
            raise ValueError("invalid_environment")


def _event_after(runtime, before):
    new = runtime.state["event_index"][before:]
    if not new:
        raise RuntimeError("environment_observation_not_recorded")
    return new[-1]["id"]


def _adapter(responses):
    def read(payload):
        gap = payload.get("information_gap")
        result = responses.get(gap)
        if result is None:
            raise ValueError("environment_information_unavailable")
        return _portable(result)
    return read


def _attach(runtime, config):
    for item in config["reads"]:
        spec = {"name": item["name"], "permission": "read", "provides": item["provides"],
                "input_schema": {"type": "object", "required": ["information_gap"]},
                "output_schema": {"type": "object", "required": ["text", "measurements"]}}
        existing = runtime.state["capabilities"].get(item["name"])
        if existing is None:
            runtime.register_capability(spec, _adapter(item["responses"]))
        elif any(existing["spec"].get(key) != spec[key]
                 for key in ("permission", "provides", "input_schema", "output_schema")):
            raise ValueError("environment_capability_contract_mismatch")
        else:
            runtime.adapters[item["name"]] = _adapter(item["responses"])


def run_local_environment(runtime, graph_path, config, *, step_budget=16, run_id=None):
    """Advance a persisted autonomous run by at most ``step_budget`` decisions.

    Configuration supplies an initial condition, a goal condition, and allowed
    read contracts.  It does not prescribe affect labels, action order, or
    answer text.  The runtime derives the threat from observed measurements,
    selects the only matching declared read contract, and records the adapter
    result through its ordinary natural-language event route.
    """
    _validate(config)
    if not isinstance(step_budget, int) or step_budget <= 0:
        raise ValueError("invalid_step_budget")
    _attach(runtime, config)
    runs = runtime.state.setdefault("autonomous_runs", [])
    config_hash = _fingerprint(config)
    if run_id is None:
        row = {"id": "environment:" + uuid.uuid4().hex, "config_sha256": config_hash,
               "graph_path_hint": str(graph_path), "phase": "initial_observation", "status": "active",
               "cursor": 0, "results": [], "started_at": time.time()}
        runs.append(row)
        runtime._log("SYSTEM", "environment_started", environment_id=row["id"], config_sha256=config_hash)
        runtime._save()
    else:
        row = next((item for item in runs if item["id"] == run_id), None)
        if row is None:
            raise ValueError("unknown_environment_run")
        if row.get("config_sha256") != config_hash:
            raise ValueError("environment_config_mismatch")
        if row.get("status") in {"completed", "safe_hold"}:
            return deepcopy(row)
        if row.get("status") == "paused_budget":
            row["status"] = "active"

    used = 0
    while row["status"] == "active" and used < step_budget:
        phase = row["phase"]
        if phase == "initial_observation":
            initial = config["initial_observation"]
            before = len(runtime.state["event_index"])
            runtime.turn(initial["text"], graph_path)
            event_id = _event_after(runtime, before)
            goal = runtime.set_goal(config["goal"]["text"], relation=config["goal"].get("relation"),
                                    control=config["goal"].get("control", "unknown"),
                                    condition=config["goal"]["condition"])
            affect = runtime.assess_goal_from_observation(goal["id"], cause_event_id=event_id,
                                                          measurements=initial["measurements"])
            row.update({"goal_id": goal["id"], "initial_event_id": event_id, "initial_affect": affect,
                        "phase": "seek_information"})
            row["results"].append({"phase": phase, "event_id": event_id, "affect": affect["label"]})
        elif phase == "seek_information":
            gap = config["goal"].get("information_gap")
            recalled = runtime.recall("episodic", row["initial_event_id"])
            if recalled["status"] != "answered":
                row.update({"phase": "held", "status": "safe_hold", "reason": recalled["reason"]})
                row["results"].append({"phase": phase, "memory_recall": recalled})
            else:
                action = runtime.propose_next_action(source_event_id=recalled["provenance"]["source_event_id"],
                                                      goal_id=row["goal_id"], information_gap=gap)
                selected = runtime.select_capability_for_action(action["id"])
                if selected["status"] != "ready":
                    row.update({"phase": "held", "status": "safe_hold", "reason": selected["reason"]})
                    row["results"].append({"phase": phase, "memory_recall": recalled, "selection": selected})
                else:
                    outcome = runtime.execute_selected_action(action["id"], {"information_gap": gap},
                                                              request_id="environment:%s:%s" % (row["id"], action["id"]))
                    if outcome["capability_result"]["status"] != "done":
                        row.update({"phase": "held", "status": "safe_hold",
                                    "reason": outcome["capability_result"]["status"]})
                        row["results"].append({"phase": phase, "memory_recall": recalled,
                                               "selection": selected, "outcome": outcome})
                    else:
                        row.update({"action_id": action["id"], "read_output": outcome["capability_result"]["output"],
                                    "phase": "observe_result"})
                        row["results"].append({"phase": phase, "memory_recall": recalled,
                                               "selection": selected, "outcome": outcome})
        elif phase == "observe_result":
            output = row["read_output"]
            before = len(runtime.state["event_index"])
            runtime.turn(output["text"], graph_path)
            event_id = _event_after(runtime, before)
            affect = runtime.assess_goal_from_observation(row["goal_id"], cause_event_id=event_id,
                                                          measurements=output["measurements"])
            if affect["label"] == "resolved":
                runtime.resolve_goal(row["goal_id"], "achieved", source_event_id=event_id)
                runtime.experience_preference(row["read_output"].get("item", "information_read"), utility=1,
                                              affect_label="resolved", context="environment", event_id=event_id)
                row.update({"result_event_id": event_id, "final_affect": affect, "phase": "complete",
                            "status": "completed", "finished_at": time.time()})
            else:
                row.update({"result_event_id": event_id, "final_affect": affect, "phase": "held",
                            "status": "safe_hold", "reason": "goal_remains_unmet"})
            row["results"].append({"phase": phase, "event_id": event_id, "affect": affect["label"]})
        else:
            raise RuntimeError("invalid_environment_phase")
        row["cursor"] += 1
        used += 1
        runtime._log("SYSTEM", "environment_step", environment_id=row["id"], phase=phase,
                     cursor=row["cursor"], status=row["status"])
        runtime._save()
    if row["status"] == "active":
        row["status"] = "paused_budget"
        row["paused_at"] = time.time()
        runtime._log("SYSTEM", "environment_paused", environment_id=row["id"], cursor=row["cursor"])
        runtime._save()
    return deepcopy(row)
