"""Graph question API over one already-extracted reading and native search."""
import json
import os

from . import public_api as _old
from .questions.compositional import compile_question_graph
from .questions.query_graph import execute_query_graph

_POLICY = os.path.join(os.path.dirname(__file__), 'graphs', 'interface', 'graph-query-policy.json')


def _policy():
    with open(_POLICY, encoding='utf-8') as stream:
        return json.load(stream)


def answer(reading, question, *, search_rows=None):
    if not isinstance(reading, dict) or not isinstance(question, str):
        raise TypeError('reading must be a dictionary and question must be a string')
    try:
        compiled = compile_question_graph(question)
    except Exception as exc:
        return _error(reading, 'compile', exc)
    return _run(reading, compiled.get('program'), compiled, search_rows)


def answer_program(reading, program, *, search_rows=None):
    if not isinstance(reading, dict) or not isinstance(program, dict):
        raise TypeError('reading and program must be dictionaries')
    return _run(reading, program, None, search_rows)


def _error(reading, stage, exc):
    return _old.to_json_finite({'schema': 'graph-query-api-v1', 'status': 'error',
        'abstained': True, 'answer': None, 'facts': reading.get('rows', []),
        'error': {'stage': stage, 'type': type(exc).__name__, 'message': str(exc)}})


def _run(reading, program, compiled, callback):
    try:
        policy = _policy()
        native = execute_query_graph(reading, program, search_rows_fn=callback)
        candidates = []
        usable = dict(reading)
        usable.setdefault('text', '')
        for result in native.get('alternatives', []):
            alternative = result['interpretation']
            for match in result['matches']:
                values = [match['bindings'].get(v) for v in alternative['project']]
                row_ids = list(dict.fromkeys(row for ref in match['source_refs'] for row in ref.get('rows', [])))
                evidence, proofs, hypotheses, missing = _old._chain(usable, row_ids, values)
                sources = _old._sources_for(usable, evidence)
                missing += [{'kind': 'claim', 'id': s.get('claim')} for s in sources if s.get('missing')]
                events = _old._events_for(usable, evidence)
                projections = []
                for variable, value in zip(alternative['project'], values):
                    origins = []
                    for pattern in alternative['patterns']:
                        for position in (0, 2):
                            if pattern[position] != variable:
                                continue
                            # Only an actual support row grounding the pattern can
                            # establish a value's origin; derived program heads remain conditional.
                            def conforms(row):
                                triple = row.get('triple', [])
                                if len(triple) != 3:
                                    return False
                                local = dict(match['bindings'])
                                for atom, actual in zip(pattern, triple):
                                    if atom.startswith('?'):
                                        if atom in local and local[atom] != actual:
                                            return False
                                        local[atom] = actual
                                    elif atom != actual:
                                        return False
                                return True
                            rows = [r for r in evidence if r.get('role') == 'support' and conforms(r)]
                            if rows:
                                origins.append({'predicate': pattern[1], 'position': position,
                                                'rows': [r['id'] for r in rows]})
                    projections.append({'variable': variable, 'value': value, 'origins': origins})
                origin_ids = {row for projection in projections for origin in projection['origins'] for row in origin['rows']}
                answer_rows = [r for r in evidence if r.get('id') in origin_ids]
                predicates = {o['predicate'] for projection in projections for o in projection['origins']}
                predicate = next(iter(predicates)) if len(projections) == 1 and len(predicates) == 1 else None
                conflicts = _old._conflicts_for(usable, evidence, events, _old.load_status_policy(), answer_predicate=predicate, selected_value=values[0] if len(values) == 1 else None)
                origin_subjects = {r['triple'][0] for r in answer_rows if len(r.get('triple', [])) == 3}
                scope_rows = ([r for r in evidence if r.get('role') == 'support' and
                               len(r.get('triple', [])) == 3 and r['triple'][0] in origin_subjects]
                              if alternative['project'] else evidence)
                claims = {c.get('id'): c for c in usable.get('claims', [])}
                scopes = sorted({r.get('scope_kind') or claims.get(r.get('claim'), {}).get('kind') for r in scope_rows if r.get('scope_kind') or claims.get(r.get('claim'), {}).get('kind')})
                # Each native root support is one correlated proof of the entire
                # projected tuple; never join components from different proofs.
                world = result['world']
                bundles = {b['id']: b for group in world.get('proof_bundles', []) for b in group.get('bundles', [])}
                sources_by_id = {x['premise_id']: x.get('source_ref', {}) for x in world.get('fact_sources', [])}
                row_readings = {r.get('id'): r.get('reading') for r in evidence}
                def proof_rows(ident, seen):
                    if ident in seen:
                        return set()
                    if ident in sources_by_id:
                        return set(sources_by_id[ident].get('rows', []))
                    return set().union(*(proof_rows(child, seen | {ident}) for child in bundles.get(ident, {}).get('premise_fact_ids', [])))
                tuple_readings = set()
                for support in match['support_ids']:
                    supported_rows = proof_rows(support, set())
                    components = []
                    for projection in projections:
                        ids = {rid for origin in projection['origins'] for rid in origin['rows']} & supported_rows
                        components.append({row_readings.get(rid) for rid in ids if row_readings.get(rid)})
                    if components:
                        tuple_readings.update(set.intersection(*components))
                if len(projections) > 1:
                    for conflict in conflicts['contradictions']:
                        applicable = set(conflict.get('query_compatible_readings', []))
                        if conflict.get('kind') == 'reading_conflict' and applicable and applicable <= tuple_readings:
                            conflict['agreed_across_support_readings'] = True
                            conflict['answer_supported_in_readings'] = sorted(applicable)
                candidates.append({'alternative': result['id'], 'values': values,
                    'bindings': match['bindings'], 'source_refs': match['source_refs'],
                    'support_ids': match['support_ids'], 'value_origin': match['value_origin'],
                    'evidence': evidence, 'proofs': proofs, 'hypotheses': hypotheses,
                    'sources': sources, 'missing_references': missing,
                    'conflicts': conflicts, 'qualifications': scopes, 'qualification_claims': sorted({r.get('claim') for r in scope_rows if r.get('claim')}), 'projection_origins': projections, 'tuple_support_readings': sorted(tuple_readings)})
        # Re-run the unchanged native search on the contextual constraints, with
        # each projected role removed. A matching event lacking that role is an
        # additional possible answer, even though it cannot produce a full proof.
        unknown_contexts = []
        for result in native.get('alternatives', []):
            alt = result['interpretation']
            for variable in alt['project']:
                role_patterns = [p for p in alt['patterns'] if p[2] == variable and p[0].startswith('?')]
                if len(role_patterns) != 1:
                    continue
                role = role_patterns[0]
                remaining = [p for p in alt['patterns'] if variable not in p]
                if not remaining or not any(role[0] in p for p in remaining):
                    continue
                context_alt = dict(alt, patterns=remaining, project=[role[0]])
                context = execute_query_graph(reading, {'version': 'query-graph-v1', 'alternatives': [context_alt]}, search_rows_fn=callback)
                context_reasons = context.get('reasons', []) or ([context['reason']] if context.get('reason') else [])
                if (not context.get('alternatives') or
                        any(reason not in policy['soft_engine_reasons'] for reason in context_reasons) or
                        context['alternatives'][0].get('world', {}).get('assembled') is not True):
                    unknown_contexts.append({'alternative': result['id'], 'reason': 'context_search_incomplete'})
                    continue
                # Check role existence separately from conditions on its value.
                # A known value that fails such a condition is not a missing role.
                role_alt = dict(alt, patterns=remaining + [role], project=[role[0], variable])
                role_result = execute_query_graph(reading, {'version': 'query-graph-v1', 'alternatives': [role_alt]}, search_rows_fn=callback)
                role_reasons = role_result.get('reasons', []) or ([role_result['reason']] if role_result.get('reason') else [])
                if (not role_result.get('alternatives') or
                        any(reason not in policy['soft_engine_reasons'] for reason in role_reasons) or
                        role_result['alternatives'][0].get('world', {}).get('assembled') is not True):
                    unknown_contexts.append({'alternative': result['id'], 'reason': 'role_search_incomplete'})
                    continue
                known_events = {match['bindings'].get(role[0])
                                for match in role_result['alternatives'][0].get('matches', [])}
                for match in context['alternatives'][0].get('matches', []):
                    event = match['bindings'].get(role[0])
                    if event is not None and event not in known_events:
                        unknown_contexts.append({'alternative': result['id'], 'variable': variable,
                                                 'event': event, 'predicate': role[1]})
        unresolved = [u for alt in (program or {}).get('alternatives', [])
                      for u in alt.get('unresolved', [])]
        hard = [u for u in unresolved if not isinstance(u, dict) or u.get('reason') not in policy['soft_unresolved']]
        reasons = list(native.get('reasons', []))
        if native.get('reason') and not reasons:
            reasons.append(native['reason'])
        for alt in (program or {}).get('alternatives', []):
            if (alt.get('coverage', 'complete') != 'complete' or alt.get('type_status', 'known') != 'known') and not alt.get('unresolved'):
                hard.append({'reason': 'unexplained_partial_metadata', 'alternative': alt.get('id')})
        if any(x.get('world', {}).get('assembled') is not True for x in native.get('alternatives', [])):
            reasons.append('world_not_assembled')
        if compiled and compiled.get('unconsumed'):
            hard.append({'reason': 'unconsumed_question_material'})
        if any(c['missing_references'] for c in candidates):
            reasons.append('provenance_incomplete')
        hard_engine = [r for r in reasons if r not in policy['soft_engine_reasons']]
        unique = {tuple(c['values']) for c in candidates}
        conflicts = any(any(not x.get('agreed_across_support_readings') and not x.get('excluded_by_question_constraints') for x in c['conflicts']['contradictions']) or
                        any(x.get('rivals_outside_support') for x in c['conflicts']['competing_readings'])
                        for c in candidates)
        scopes = {s for c in candidates for s in c['qualifications']}
        if hard_engine:
            status = 'hold'
        elif hard:
            status = 'partial'
        elif not candidates:
            status = 'no_evidence'
        elif conflicts:
            status = 'conflict'
        elif unknown_contexts:
            status = 'partial'
            hard.append({'reason': 'unknown_projected_role'})
        elif any(not item.get('matches') for item in native.get('alternatives', [])):
            status = 'partial'
            hard.append({'reason': 'unmatched_interpretation'})
        elif len(unique) != 1:
            status = 'ambiguous'
        elif not scopes or any(not c['qualifications'] for c in candidates):
            status = 'hold'
        elif scopes - set(policy['direct_scopes']):
            status = 'source_qualified' if scopes and scopes <= set(policy['reported_scopes'] + policy['direct_scopes']) else 'hold'
        elif unresolved:
            status = 'source_qualified'
        else:
            status = 'answered'
        entry = policy['statuses'][status]
        values = next(iter(unique)) if len(unique) == 1 else ()
        # A value has typed wording only when every supporting interpretation
        # identifies exactly the same base-predicate origin at that position.
        display = []
        typed = []
        for i, value in enumerate(values):
            origin_sets = [{(o['predicate'], o['position']) for o in c['projection_origins'][i]['origins']}
                           for c in candidates if len(c['projection_origins']) > i]
            origin = next(iter(origin_sets[0])) if origin_sets and len(origin_sets[0]) == 1 and all(x == origin_sets[0] for x in origin_sets) else None
            label = policy.get('value_labels', {}).get(origin[0] if origin and origin[1] == 2 else None, {}).get(value)
            typed.append(label is not None)
            display.append(label if label is not None else value)
        rendered = entry['template'].format(value=policy['tuple_separator'].join(display)) if entry['template'] else None
        origin_claims = {claim for c in candidates for claim in c['qualification_claims']}
        reporters = {s.get('reporter') for c in candidates for s in c['sources'] if s.get('claim') in origin_claims and s.get('reporter')}
        reporter_text = policy['tuple_separator'].join(sorted(reporters))
        if rendered and status == 'source_qualified' and reporters:
            rendered = policy['reporter_template'].format(reporter=reporter_text, value=policy['tuple_separator'].join(display))
        if rendered and len(display) == 1 and typed[0]:
            key = 'reporter' if status == 'source_qualified' and reporters else status
            rendered = policy['typed_templates'][key].format(reporter=reporter_text, value=display[0])
        descriptor = next((u.get('surface') for u in hard if isinstance(u, dict) and u.get('reason') in policy['partial_reasons'] and u.get('surface')), None)
        if status == 'partial' and descriptor and all(isinstance(u, dict) and u.get('reason') in policy['partial_reasons'] for u in hard) and len(unique) == 1 and scopes and scopes <= set(policy['direct_scopes'] + policy['reported_scopes']):
            template = policy['partial_reporter_template'] if len(reporters) == 1 else policy['partial_template']
            rendered = template.format(reporter=next(iter(reporters)) if reporters else '', value=policy['tuple_separator'].join(display), condition=descriptor)
        # The requested value is a role in a matched event; retain its signed
        # context in wording rather than presenting a negative event as positive.
        polarities = set()
        for candidate in candidates:
            origin_ids = {row for projection in candidate['projection_origins']
                          for origin in projection['origins'] for row in origin['rows']}
            origins = [r for r in candidate['evidence'] if r.get('id') in origin_ids]
            signed_context = [row for row in reading.get('rows', [])
                              if len(row.get('triple', [])) == 3
                              and row['triple'][1] == policy['polarity_predicate']
                              and row.get('polarity') is True and row.get('modality') == 'asserted'
                              and any(row['triple'][0] == origin['triple'][0]
                                      and row.get('reading') == origin.get('reading')
                                      and row.get('claim') == origin.get('claim') for origin in origins)]
            candidate['signed_context'] = signed_context
            polarities.update(row['triple'][2] for row in signed_context)
        if rendered and policy['negative_polarity'] in polarities and (len(polarities) > 1 or len(display) > 1):
            status = 'hold'
            entry = policy['statuses'][status]
            rendered = None
        elif rendered and policy['negative_polarity'] in polarities and not all(typed):
            rendered = policy['negative_context_wrapper'].format(answer=rendered)
        response = {'schema': 'graph-query-api-v1' , 'status': status,
            'abstained': entry['abstained'], 'answer': rendered,
            'values': list(values) if len(unique) == 1 else None,
            'answer_scope': 'structural_role' if unresolved and not hard else None,
            'requested_type': [u.get('type') for u in unresolved if isinstance(u, dict) and u.get('reason') == 'unknown_wh_type'],
            'type_verification': 'unknown' if unresolved else None,
            'facts': reading.get('rows', []), 'question_graph': compiled,
            'program': program, 'native': native, 'candidates': candidates,
            'diagnostics': {'engine_reasons': reasons, 'hard_unresolved': hard, 'projected_scopes': sorted(scopes), 'unknown_contexts': unknown_contexts, 'matched_polarities': sorted(polarities)},
            'stages': ['compile' if compiled is not None else 'supplied_program', 'native_query', 'policy', 'render'],
            'error': None}
        return _old.to_json_finite(response)
    except Exception as exc:
        return _error(reading, 'execute_or_render', exc)
