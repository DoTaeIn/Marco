"""Caller-local source research orchestration.

This is an opt-in, caller-local path: every call makes a NEW capture of the
installed session state and a NEW research report from a caller-selected
search evidence service. Nothing is persisted or mutated.

Installed != used: ``source_parser_binding`` is detached metadata describing
the frozen installed state, not evidence that any installed expression was
used. Use is only what the bound ``source_reading`` records.

World truth is unverified: report claims are untrusted, and the answer keeps
``verified=False``; ``source_observed`` only says what a source said.
"""

from marco.runtime.research import ResearchAnswerer
from marco.runtime.source_reading import SourceReader
from marco.runtime.source_snapshot import capture_source_snapshot


def research_from_session(session, *, model, question, source_scope,
                          search_terms, service, limit=3, sentence_limit=12):
    """Run one source research pass against a frozen snapshot of ``session``.

    Returns exactly ``report``, ``source_reading``, ``source_parser_binding``
    and ``answer``. ``answer`` is None, and ResearchAnswerer is not called,
    unless ``source_reading`` has status 'bound'. Native validation errors
    propagate.
    """
    snapshot = capture_source_snapshot(
        session, model=model, conversation_id=session.conversation_id)
    frozen_parser = snapshot.fresh_parser(session)
    reader = SourceReader(model, source_scope, snapshot=snapshot,
                          session=session)
    report = service.research(
        question,
        search_terms=search_terms,
        limit=limit,
        sentence_limit=sentence_limit,
        language_pack=model.language,
        meaning_reader=reader,
    )
    source_reading = reader.bind(report)
    answer = None
    if source_reading.get('status') == 'bound':
        answer = ResearchAnswerer(snapshot.fresh_parser(session)).answer(
            report, question=question, source_scope=source_scope)
    return {
        'report': report,
        'source_reading': source_reading,
        'source_parser_binding': snapshot.binding,
        'answer': answer,
    }
