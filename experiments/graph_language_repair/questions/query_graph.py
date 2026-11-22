"""Bounded declarative query transport to the existing Horn search.

This module interprets graph structure only. It does not interpret language or
choose an answer. All matching and proof construction belong to native search.
"""
from copy import deepcopy
import json
from itertools import combinations

from ..core.search import project_rows, search_rows



def _plain_json(value):
    if value is None or type(value) in (str, bool, int):
        return True
    if type(value) is float:
        return value == value and abs(value) != float('inf')
    if type(value) is list:
        return all(_plain_json(x) for x in value)
    if type(value) is dict:
        return all(type(k) is str and _plain_json(v) for k, v in value.items())
    return False

def _variable(atom):
    return isinstance(atom, str) and atom.startswith('?') and len(atom) > 1


def _triple(value):
    return (isinstance(value, list) and len(value) == 3 and
            all(isinstance(x, str) and x and x != '?' and not x.startswith('$') for x in value) and
            not _variable(value[1]))


def _hold(reason, alternatives=()):
    return {'status': 'hold', 'reason': reason, 'alternatives': list(alternatives)}



def _factor(patterns, project, atoms, rule_ids):
    """Compile a bounded conjunction into equivalent binary Horn rules.

    Every variable crossing a group boundary is preserved in its auxiliary
    head. A conservative greedy failure is reported, never weakened.
    """
    body = deepcopy(patterns)
    auxiliary = []
    while len(body) > 4:
        selected = None
        for size in range(min(4, len(body)), 1, -1):
            for indices in combinations(range(len(body)), size):
                group = [body[i] for i in indices]
                vars_by_atom = [{x for x in p if _variable(x)} for p in group]
                # Ground atoms may join any component without shared variables.
                connected = set(vars_by_atom[0])
                remaining = [v for v in vars_by_atom[1:] if v]
                if not connected and remaining:
                    connected = set(remaining.pop(0))
                while remaining:
                    overlap = next((v for v in remaining if v & connected), None)
                    if overlap is None:
                        break
                    connected.update(overlap)
                    remaining.remove(overlap)
                if remaining:
                    continue
                outside = {x for i, p in enumerate(body) if i not in indices for x in p if _variable(x)} | set(project)
                boundary = sorted(connected & outside)
                if len(boundary) <= 2:
                    selected = indices, group, boundary
                    break
            if selected:
                break
        if selected is None:
            return None
        indices, group, boundary = selected
        predicate = 'query:internal:aux'
        while predicate in atoms:
            predicate += ':'
        atoms.add(predicate)
        rule_id = 'query:internal:aux-rule'
        while rule_id in rule_ids:
            rule_id += ':'
        rule_ids.add(rule_id)
        head = [boundary[0] if boundary else 'query:internal:yes', predicate,
                boundary[1] if len(boundary) > 1 else 'query:internal:yes']
        auxiliary.append({'id': rule_id, 'version': 1, 'head': head, 'body': group})
        body = [p for i, p in enumerate(body) if i not in indices] + [head]
    return auxiliary, body

def execute_query_graph(reading, program, search_rows_fn=None):
    """Return all interpretations and their native worlds; never select a winner."""
    if not isinstance(program, dict) or program.get('version') != 'query-graph-v1':
        return _hold('invalid_program')
    if set(program) - {'version', 'alternatives'}:
        return _hold('unsupported_operator')
    alternatives = program.get('alternatives')
    if not isinstance(alternatives, list) or not alternatives:
        return _hold('invalid_program')
    ids, outputs = set(), []
    for alternative in alternatives:
        if not isinstance(alternative, dict):
            return _hold('invalid_alternative', outputs)
        if set(alternative) - {'id', 'patterns', 'project', 'rules', 'scope', 'coverage', 'unresolved', 'type_status'}:
            return _hold('unsupported_operator', outputs)
        ident = alternative.get('id')
        patterns, project = alternative.get('patterns'), alternative.get('project')
        rules = alternative.get('rules', [])
        if not isinstance(ident, str) or not ident or ident in ids:
            return _hold('invalid_alternative', outputs)
        ids.add(ident)
        if not isinstance(patterns, list) or not patterns or not all(_triple(p) for p in patterns):
            return _hold('unsupported_pattern', outputs)
        if len(patterns) > 32:
            return {'status': 'hold', 'reason': 'program_limit', 'alternatives': outputs, 'program': deepcopy(program)}
        variables = {x for p in patterns for x in p if _variable(x)}
        if (not isinstance(project, list) or len(project) > 2
                or any(not _variable(v) or v not in variables for v in project)
                or len(set(project)) != len(project)):
            return _hold('unsupported_projection', outputs)
        if alternative.get('scope', 'reading') != 'reading':
            return _hold('unsupported_scope', outputs)
        if alternative.get('coverage', 'complete') not in ('complete', 'partial') or alternative.get('type_status', 'known') not in ('known', 'unknown') or not isinstance(alternative.get('unresolved', []), list):
            return _hold('invalid_metadata', outputs)
        if not isinstance(rules, list):
            return _hold('invalid_rules', outputs)
        rule_ids = set()
        for rule in rules:
            if (not isinstance(rule, dict) or set(rule) - {'id', 'version', 'head', 'body'}
                    or not isinstance(rule.get('id'), str) or not rule['id'] or rule['id'] in rule_ids
                    or not _triple(rule.get('head')) or not isinstance(rule.get('body'), list)
                    or not 1 <= len(rule['body']) <= 4 or not all(_triple(p) for p in rule['body'])):
                return _hold('invalid_rules', outputs)
            if not _plain_json(rule.get('version')):
                return _hold('invalid_rules', outputs)
            rule_ids.add(rule['id'])
            bound = {x for p in rule['body'] for x in p if _variable(x)}
            if any(_variable(x) and x not in bound for x in rule['head']):
                return _hold('invalid_rules', outputs)
        # A collision-free private predicate avoids treating an input row as a proof.
        atoms = {x for row in reading.get('rows', []) for x in row.get('triple', [])}
        atoms.update(x for p in patterns for x in p)
        atoms.update(x for r in rules for p in [r['head']] + r['body'] for x in p)
        predicate = 'query:internal:goal'
        while predicate in atoms:
            predicate += ':'
        rule_id = 'query:internal:rule'
        while rule_id in rule_ids:
            rule_id += ':'
        head = [project[0] if project else 'query:internal:yes', predicate,
                project[1] if len(project) > 1 else 'query:internal:yes']
        query = [project[0] if project else head[0], predicate,
                 project[1] if len(project) > 1 else head[2]]
        atoms.add(predicate)
        rule_ids.add(rule_id)
        factored = _factor(patterns, project, atoms, rule_ids)
        if factored is None:
            return {'status': 'hold', 'reason': 'unsupported_query_width', 'alternatives': outputs, 'program': deepcopy(program)}
        auxiliary, goal_body = factored
        goal = {'id': rule_id, 'version': 1, 'head': head, 'body': goal_body}
        # Conservative predicate dependency closure. All signed and rival rows
        # for every dependency survive; arbitrary predicate variables are refused.
        needed = {p[1] for p in patterns}
        changed = True
        while changed:
            before = len(needed)
            for rule in rules:
                if rule['head'][1] in needed:
                    needed.update(p[1] for p in rule['body'])
            changed = len(needed) != before
        rows = [row for row in reading.get('rows', []) if row['triple'][1] in needed]
        relevant_rules = [r for r in rules if r['head'][1] in needed]
        if len(relevant_rules) + len(auxiliary) + 1 > 16:
            return {'status': 'hold', 'reason': 'rule_limit', 'alternatives': outputs, 'program': deepcopy(program)}
        world = (search_rows_fn or search_rows)(reading, query, rules=relevant_rules + auxiliary + [goal], rows=rows)
        matches = []
        by_premise = {s.get('premise_id'): s for s in world.get('fact_sources', [])}
        bundles = {b.get('id'): b for group in world.get('proof_bundles', []) for b in group.get('bundles', [])}
        row_by_id = {row['id']: row for row in reading.get('rows', [])}
        projected_facts, projected_sources = project_rows(reading, rows)
        canonical = {(tuple(fact['triple']), fact['polarity'], fact['modality']): (fact, source)
                     for fact, source in zip(projected_facts, projected_sources)}
        native_rules = {r['id']: r for r in relevant_rules + auxiliary + [goal]}
        query_rule_ids = {r['id'] for r in relevant_rules}
        all_bundle_ids = [b.get('id') for group in world.get('proof_bundles', []) for b in group.get('bundles', [])]
        all_source_ids = [entry.get('premise_id') for entry in world.get('fact_sources', [])]
        gaps = []
        if (len(set(all_bundle_ids)) != len(all_bundle_ids) or
                len(set(all_source_ids)) != len(all_source_ids) or
                set(all_bundle_ids) & set(all_source_ids)):
            gaps.append('duplicate_proof_identifier')

        def walk(support, active):
            if support in active:
                return [], set(), ['proof_cycle:' + str(support)]
            if support in by_premise:
                entry = by_premise[support]
                source, original = entry.get('source_ref'), entry.get('original_fact', {})
                row_ids = source.get('rows') if isinstance(source, dict) else None
                if (not isinstance(row_ids, list) or not row_ids
                        or any(not isinstance(x, str) for x in row_ids)
                        or len(set(row_ids)) != len(row_ids) or source.get('row') not in row_ids):
                    return [], set(), ['invalid_source:' + str(support)]
                key = (tuple(original.get('triple', [])), original.get('polarity'), original.get('modality'))
                if (original, source) != canonical.get(key):
                    return [], set(), ['source_carrier_mismatch:' + str(support)]
                for row_id in row_ids:
                    row = row_by_id.get(row_id)
                    if (row is None or original.get('polarity') is not True
                            or original.get('modality') != 'asserted'
                            or not row.get('claim') or not row.get('spans')
                            or row.get('triple') != original.get('triple')
                            or row.get('polarity') is not original.get('polarity')
                            or row.get('modality', 'asserted') != original.get('modality')
                            or row.get('claim') not in source.get('claims', [])
                            or any(list(span) not in source.get('spans', []) for span in row.get('spans', []))):
                        return [], set(), ['source_mismatch:' + str(support)]
                    if isinstance(reading.get('text'), str):
                        text_length = len(reading['text'])
                        if any(not isinstance(span, (list, tuple)) or len(span) != 2
                               or any(type(n) is not int for n in span)
                               or not 0 <= span[0] < span[1] <= text_length
                               for span in row['spans']):
                            return [], set(), ['invalid_source_span:' + str(support)]
                return [source], set(), []
            bundle = bundles.get(support)
            if not isinstance(bundle, dict) or bundle.get('valid') is not True:
                return [], set(), ['missing_or_invalid_support:' + str(support)]
            children = bundle.get('premise_fact_ids')
            if not isinstance(children, list) or not children:
                return [], set(), ['missing_dependencies:' + str(support)]
            refs, dependencies, errors = [], set(), []
            if bundle.get('kind') == 'derived':
                rule = native_rules.get(bundle.get('rule'))
                if (rule is None or len(children) != len(rule['body'])
                        or type(bundle.get('rule_version')) is not type(rule.get('version'))
                        or not _plain_json(bundle.get('rule_version'))
                        or json.dumps(bundle.get('rule_version'), sort_keys=True) != json.dumps(rule.get('version'), sort_keys=True)):
                    errors.append('invalid_rule_dependency:' + str(support))
                else:
                    bindings = bundle.get('bindings')
                    if not isinstance(bindings, dict):
                        errors.append('invalid_rule_bindings:' + str(support))
                    else:
                        def grounded(triple):
                            return [bindings.get(x, x) if _variable(x) else x for x in triple]
                        if grounded(rule['head']) != bundle.get('conclusion'):
                            errors.append('invalid_rule_conclusion:' + str(support))
                        for child, pattern in zip(children, rule['body']):
                            child_bundle = bundles.get(child, {})
                            child_entry = by_premise.get(child, {})
                            conclusion = child_bundle.get('conclusion', child_entry.get('original_fact', {}).get('triple'))
                            if grounded(pattern) != conclusion:
                                errors.append('invalid_rule_premise:' + str(support))
                if bundle.get('rule') in query_rule_ids:
                    dependencies.add(bundle['rule'])
            elif bundle.get('kind') != 'asserted':
                errors.append('invalid_support_kind:' + str(support))
            for child in children:
                child_refs, child_rules, child_errors = walk(child, active | {support})
                for ref in child_refs:
                    if ref not in refs:
                        refs.append(ref)
                dependencies.update(child_rules)
                errors.extend(child_errors)
            if bundle.get('kind') == 'asserted':
                if len(children) != 1 or children[0] not in by_premise or bundle.get('conclusion') != by_premise.get(children[0], {}).get('original_fact', {}).get('triple'):
                    errors.append('invalid_asserted_support:' + str(support))
            return refs, dependencies, errors

        for match in world.get('matches', []):
            refs, dependencies, match_gaps = [], set(), []
            bindings = match.get('bindings')
            if (not isinstance(bindings, dict) or
                    [bindings.get(x, x) if _variable(x) else x for x in query] != match.get('triple')):
                match_gaps.append('match_binding_mismatch')
            supports = match.get('support_ids')
            if not isinstance(supports, list) or not supports:
                supports = []
                match_gaps.append('missing_match_support')
            for support in supports:
                bundle = bundles.get(support, {})
                if bundle.get('conclusion') != match.get('triple'):
                    match_gaps.append('support_conclusion_mismatch:' + str(support))
                part_refs, part_rules, part_gaps = walk(support, set())
                for ref in part_refs:
                    if ref not in refs:
                        refs.append(ref)
                dependencies.update(part_rules)
                match_gaps.extend(part_gaps)
            if not refs:
                match_gaps.append('no_source_refs')
            gaps.extend(match_gaps)
            matches.append({'bindings': match.get('bindings'), 'triple': match.get('triple'),
                            'support_ids': supports, 'source_refs': refs,
                            'query_rule_dependencies': sorted(dependencies),
                            'value_origin': 'derived_program_value' if dependencies else 'document_grounded',
                            'provenance_gaps': match_gaps})
        outputs.append({'id': ident, 'matches': matches, 'world': world,
                        'interpretation': deepcopy(alternative), 'provenance_gaps': gaps})
    reasons = []
    if reading.get('limits', {}).get('complete') is not True:
        reasons.append('reading_incomplete')
    for result in outputs:
        alt = result['interpretation']
        if result['world'].get('complete') is not True:
            reasons.append(result['world'].get('reason') or 'search_incomplete')
        if result['provenance_gaps']:
            reasons.append('provenance_incomplete')
        if any(m['query_rule_dependencies'] for m in result['matches']):
            reasons.append('program_rule_derivation')
        if alt.get('coverage', 'complete') != 'complete':
            reasons.append('partial_coverage')
        if alt.get('unresolved', []):
            reasons.append('unresolved_descriptors')
        if alt.get('type_status', 'known') != 'known':
            reasons.append('unknown_type')
    if reasons:
        return {'status': 'hold', 'reason': reasons[0], 'reasons': list(dict.fromkeys(reasons)), 'alternatives': outputs}
    return {'status': 'evidence' if any(x['matches'] for x in outputs) else 'no_evidence',
            'alternatives': outputs}
