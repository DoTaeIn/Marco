# -*- coding: utf-8 -*-
"""Shared reading helpers for the tests.  No assertion and no language here."""
import functools

from experiments.graph_language_repair.core import read_text
from experiments.graph_language_repair.tests.controls import CONTROLS


@functools.lru_cache(maxsize=None)
def reading(name):
    return read_text(CONTROLS[name]["text"])


def roles(document, event=None, role=None, source=None):
    found = []
    for item in document["roles"]:
        if event is not None and item["event"] != event:
            continue
        if role is not None and item["role"] != role:
            continue
        if source is not None and item["source"] != source:
            continue
        found.append(item)
    return found


def role_values(document, event=None, role=None, source=None):
    return sorted(item["value"] for item in roles(document, event, role, source))


def events(document, construction=None, action=None):
    found = []
    for item in document["events"]:
        if construction is not None and item["construction"] != construction:
            continue
        if action is not None and item["action"] != action:
            continue
        found.append(item)
    return found


def rows(document, subject=None, predicate=None, obj=None, claim=None):
    found = []
    for row in document["rows"]:
        one, two, three = row["triple"]
        if subject is not None and one != subject:
            continue
        if predicate is not None and two != predicate:
            continue
        if obj is not None and three != obj:
            continue
        if claim is not None and row["claim"] != claim:
            continue
        found.append(row)
    return found


def hypotheses(document, kind=None, status=None):
    found = []
    for item in document["hypotheses"]:
        if kind is not None and item["kind"] != kind:
            continue
        if status is not None and item["status"] != status:
            continue
        found.append(item)
    return found


def claim_of(document, claim_id):
    for claim in document["claims"]:
        if claim["id"] == claim_id:
            return claim
    raise KeyError(claim_id)


def claims_of_kind(document, kind):
    return [claim for claim in document["claims"] if claim["kind"] == kind]


def entity_of(document, mention_id):
    for row in document["rows"]:
        if row["triple"][0] == mention_id and row["triple"][1] == "mention_of":
            return row["triple"][2]
    for entity in document["entities"]:
        if mention_id in entity["mentions"]:
            return entity["id"]
    return None


def mention_at(document, surface, occurrence=0):
    found = [item for item in document["mentions"] if item["surface"] == surface]
    found.sort(key=lambda item: item["span"])
    return found[occurrence]
