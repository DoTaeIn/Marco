"""Expression learning: a user's way of saying a meaning becomes a candidate.

No language model and no corpus. The parser already turned the user's
sentence into a meaning; this module aligns the sentence with that meaning,
word by word, using only declarations: the pack's numerals, the realizer's
cases (particle mates and forms), counters and verb lexicon, and the
inflection grammar. Every word must be placed — a role, a particle, a
counter, a declared verb form — or nothing is learned.

The result is an expression candidate like the declared ones: parts over
roles, with the register of the user's ending. It is kept only if it realizes
its own source meaning and passes the semantic check. It is listed with the
sentence and conversation it came from, and can be disabled or removed.
"""
import copy

from marco.language.realizer import meaning as mg
from marco.language.realizer.grammar import ClauseRealizer, Grammar, RealizationError
from marco.language.numerals import parse_numeral


def json_key(value):
    return tuple(value) if isinstance(value, list) else value


class LearnedExpressions:
    def __init__(self, realizer):
        self.realizer = realizer
        self.items = []
        self.rejected = []
        self._count = 0

    # listing ----------------------------------------------------------------
    def candidates(self, stem, conversation=None):
        """Learned candidates of this language; one learned in a conversation serves that conversation only."""
        return [item for item in self.items if item["language"] == stem
                and item["learned"].get("conversation") in (None, conversation)]

    def list(self):
        return [{key: copy.deepcopy(item[key]) for key in ("id", "language", "frame", "register", "enabled",
                                                            "learned")} for item in self.items]

    def enable(self, candidate_id):
        for item in self.items:
            if item["id"] == candidate_id:
                item["enabled"] = True

    def disable(self, candidate_id):
        for item in self.items:
            if item["id"] == candidate_id:
                item["enabled"] = False

    def remove(self, candidate_id):
        self.items = [item for item in self.items if item["id"] != candidate_id]

    def remove_conversation(self, conversation):
        self.items = [item for item in self.items if item["learned"].get("conversation") != conversation]

    # observing ----------------------------------------------------------------
    def observe(self, result, source):
        """Learn from the statements this turn recorded."""
        if result.get("status") != "observed":
            return []
        lang = self.realizer.language(source)
        frames = (lang.decl.get("learning") or {}).get("frames", [])
        conversation = (result.get("meaning") or {}).get("conversation")
        rows = [row for row in result.get("transitions") or [] if row.get("operation") == "state_update"]
        if not rows:
            return []
        latest = max((row.get("evidence") or {}).get("turn", -1) for row in rows)
        by_clause = {}
        for row in rows:
            evidence = row.get("evidence") or {}
            if evidence.get("turn") != latest:
                continue
            by_clause.setdefault((evidence.get("text"), evidence.get("start")), []).append(row)
        learned = []
        for (text, _start), clause_rows in by_clause.items():
            if len(clause_rows) != 1 or not text:
                continue
            row = clause_rows[0]
            if (row.get("evidence") or {}).get("ellipsis"):
                continue
            prop = mg.fact_prop([row["subject"], row["predicate"], row["after"]], source)
            if prop is None or prop["frame"] not in frames:
                continue
            candidate = self.induce(lang, prop, text)
            if candidate is None:
                continue
            candidate["learned"] = {"source": text, "turn": latest, "conversation": conversation}
            if any(self.shape(item["parts"], lang) == self.shape(candidate["parts"], lang)
                   and item["register"] == candidate["register"] and item["language"] == source
                   for item in self.items):
                continue
            if self._declared(lang, candidate):
                continue
            verdict = self._verify(lang, prop, candidate)
            if not verdict["ok"]:
                self.rejected.append({"candidate": candidate, "check": verdict})
                continue
            self._count += 1
            candidate["id"] = "learned-%d" % self._count
            candidate["language"] = source
            candidate["enabled"] = True
            self.items.append(candidate)
            learned.append(candidate)
        return learned

    @staticmethod
    def shape(parts, lang=None):
        """What an expression says and in which order: kinds, roles, cases, counters, number
        style. A case the language says nothing for is not part of the shape."""
        keys = ("np", "num", "lex", "verb", "quote", "case", "counter", "style", "cop")
        cases = (lang.decl.get("cases", {}) if lang is not None else {})
        shaped = []
        for part in parts:
            items = [(key, json_key(part.get(key))) for key in keys if key in part]
            if lang is not None and "case" in part and not cases.get(part["case"]):
                items = [item for item in items if item[0] != "case"]
            shaped.append(tuple(items))
        return shaped

    def _declared(self, lang, candidate):
        return any(self.shape(c.get("parts", []), lang) == self.shape(candidate["parts"], lang)
                   for c in lang.decl.get("expressions", {}).get(candidate["frame"], []))

    def _verify(self, lang, prop, candidate):
        """The candidate must say its own source meaning and pass the semantic check."""
        from marco.language.realizer.check import Checker
        grammar = Grammar(lang)
        checker = Checker(lang, grammar, lambda: ClauseRealizer(grammar))
        register = candidate["register"][0]
        try:
            clause = ClauseRealizer(grammar).realize(prop, candidate, register=register)
        except RealizationError as exc:
            return {"ok": False, "failures": [{"reader": "realization", "error": str(exc)}]}
        frames = mg.meaning_declarations()["frames"]
        return checker.check(prop, candidate, clause, elided=(), sentence="declarative", register=register,
                             allow_repair=True, frame_decl=frames.get(prop["frame"]))

    # inducing -------------------------------------------------------------------
    def _case(self, lang, particle):
        for case, spec in lang.decl.get("cases", {}).items():
            if spec.get("form") == particle:
                return case
            mates = lang.mates.get(spec.get("mate")) if spec.get("mate") else None
            if mates and particle in mates:
                return case
        return None

    def _split_particle(self, lang, token, word):
        """``word`` + a declared particle, or ``word`` itself."""
        if token == word:
            return True, None
        if token.startswith(word):
            case = self._case(lang, token[len(word):])
            if case:
                return True, case
        return False, None

    def _verb(self, lang, token):
        grammar = lang.inflection
        registers = (lang.decl.get("register") or {}).get("from_endings", {})
        grammar_obj = Grammar(lang)
        for lex, entry in lang.decl.get("lexicon", {}).items():
            if "verb" not in entry:
                continue
            for tense in grammar.get("tenses", {}):
                for ending, register in registers.items():
                    try:
                        form = grammar_obj.inflect(entry["verb"], tense, ending, entry.get("kind", "regular"))
                    except RealizationError:
                        continue
                    if form == token:
                        return lex, tense, register
        return None

    def induce(self, lang, prop, text):
        tokens = text.split()
        roles = prop["roles"]
        words = {role: value["text"].split() for role, value in roles.items() if "text" in value}
        numeric = mg.meaning_declarations()["frames"][prop["frame"]].get("numbers", [])
        number_role = numeric[0] if len(numeric) == 1 else None
        value = (roles.get(number_role) or {}).get("number") if number_role else None
        counters = {spec["form"]: name for name, spec in lang.decl.get("counters", {}).items()}
        parts, register, tense = [], None, None
        index = 0
        placed = set()
        while index < len(tokens):
            token = tokens[index].strip("".join(lang.decl["orthography"]["punctuation"].values()))
            matched = False
            for role, role_words in words.items():
                if role in placed or len(role_words) != 1:
                    continue
                ok, case = self._split_particle(lang, token, role_words[0])
                if ok:
                    parts.append({"np": [role], **({"case": case} if case else {})})
                    placed.add(role)
                    matched = True
                    break
            if matched:
                index += 1
                continue
            numeral = parse_numeral(token, lang.numerals)
            digits = token[:len(token) - len(token.lstrip("0123456789"))] if token[:1].isdigit() else ""
            if value is not None and number_role not in placed and (numeral == value or digits == value):
                style = "words" if numeral == value and not digits else "digits"
                rest = token[len(digits):] if digits else ""
                part = {"num": number_role}
                if style == "words":
                    part["style"] = "words"
                    following = tokens[index + 1].strip("".join(lang.decl["orthography"]["punctuation"].values())) \
                        if index + 1 < len(tokens) else ""
                    if any(following.startswith(form) for form in counters):
                        rest = following
                        index += 1
                counter = next((form for form in counters if rest.startswith(form)), None)
                if rest and counter is None:
                    return None
                if counter:
                    part["counter"] = counters[counter]
                    tail = rest[len(counter):]
                    if tail:
                        case = self._case(lang, tail)
                        if case is None:
                            return None
                        part["case"] = case
                parts.append(part)
                placed.add(number_role)
                index += 1
                continue
            verb = self._verb(lang, token)
            if verb is not None and register is None:
                lex, tense, register = verb
                parts.append({"verb": lex, "predicate": True})
                index += 1
                continue
            return None
        if placed != set(roles) or register is None:
            return None
        candidate = {"frame": prop["frame"], "register": [register], "parts": parts}
        if tense and tense != "present":
            candidate["tense"] = tense
        return candidate
