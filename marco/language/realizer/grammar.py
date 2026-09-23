"""Grammar Realizer: particles, endings, inflection, agreement and order.

Every form comes from a declaration: the realizer file of the language
(``<stem>.json``) or the language pack it reuses (particle mates, inflection
grammar, negation, senses, romanization). This module only executes a closed
set of part kinds — ``np``, ``num``, ``lex``, ``verb``, ``quote``, ``list``,
``rel``, ``sym``, ``cite``, ``id``, ``pair``, ``operation`` — in the order an
expression candidate lists them.

A realized clause keeps its words and, for each word, the pieces it is made
of, so the semantic check can compare the said clause with the same clause
said in full.
"""
import copy

from hangul import batchim, inflect, is_hangul, romanize


class RealizationError(ValueError):
    """An expression needs a form its language does not declare."""


def _first(forms):
    return forms[0]["text"]


class Grammar:
    def __init__(self, language):
        self.lang = language
        self.decl = language.decl
        self.ortho = self.decl["orthography"]
        self.keys = self.decl.get("pack_keys", {})

    # ── entities ─────────────────────────────────────────────────────────
    def entity_words(self, value, number=None, said=None):
        """The words of an entity in this language: its own words, a sense link, or a romanized name.

        A compound (the engine's owner-then-item subject) is said the way the
        language declares: juxtaposed, or as a possessive. ``said``: the words of the
        statement the value was recorded from, which settle a singular the spelling
        rules leave open (``singular_of``).
        """
        text = value.get("text", "")
        if value.get("kind") == "compound" and len(text.split()) > 1:
            joint = self._compound_separator()
            head, rest = text.split(joint)[0], joint.join(text.split(joint)[1:])
            owner = self.entity_words({**value, "text": head, "kind": "agent"})
            item = self.entity_words({**value, "text": rest, "kind": "thing"}, number, said)
            compound = self.ortho.get("compound") or {}
            if compound.get("join") == "possessive" and owner:
                owner = owner[:-1] + [owner[-1] + compound["possessive"]]
            return owner + item
        source = value.get("lang")
        if not source or source == self.lang.stem:
            words = text.split()
            if number is None:
                return words
            return self.singular_head([self.noun_number(word, number) for word in words], number, said)
        from marco.language.realizer.packs import language as load
        origin = load(source)
        words = []
        for word in text.split():
            concept = origin.concept(word)
            targets = self.lang.words_for(concept) if concept else []
            if targets:
                words.append(self.choose_number(targets, number))
                continue
            table = origin.romanization
            # Only a name is spelled in another script. A common noun with no
            # sense link stays as the source word: shown, not translated.
            if (value.get("kind") == "agent" and table and word and all(is_hangul(char) for char in word)
                    and self.ortho.get("name_case")):
                spelled = romanize(word, table)
                if spelled:
                    words.append(self.name_case(spelled))
                    continue
            words.append(word)
        return words

    @staticmethod
    def _compound_separator():
        from marco.language.realizer.packs import meaning_declarations
        return meaning_declarations()["compound_subject"]["separator"]

    def name_case(self, word):
        mode = self.ortho.get("name_case")
        if mode == "capitalize":
            return word[:1].upper() + word[1:]
        return word

    def is_name(self, value, words):
        kind = value.get("kind")
        if kind == "agent":
            return True
        if kind in ("thing", "place"):
            return False
        return bool(words) and self.ortho.get("name_case") == "capitalize" and words[0][:1].isupper()

    # ── number ───────────────────────────────────────────────────────────
    def declared_number(self):
        """The pack's own noun-number declaration (``명사수``: the count that is one, the
        spelling rules, the partitive marker, the table of irregular plurals), or {}."""
        return getattr(self.lang.parser, "noun_number", None) or {}

    def is_one(self, number):
        declared = self.declared_number()
        one = declared.get("count_slot_value", 1) if declared else 1
        return number is not None and str(number) == str(one)

    def plural_of(self, word):
        """The plural the pack declares for one word: its irregular table, then its rules."""
        from relational_semantics import declared_plural
        return declared_plural(word, self.declared_number())

    def singular_of(self, word, said=None):
        """The one singular the pack's declarations give back for a plural, or None.

        The irregular table is read first, as a whole word, in both directions (a
        declared plural gives its singular, ``geese`` -> ``goose``, ``knives`` -> ``knife``;
        a zero plural is its own singular); a word the table lists as a singular is
        one already. Otherwise the spelling rules are undone, and only a singular
        whose declared plural is the word itself counts. Two such singulars (``boxes``:
        box or boxe; ``cookies``: cooky or cookie) are told apart only by ``said``, the
        user's own words for the thing: the one of them the user wrote. Otherwise the
        word is left as it is (None). The word's own capital is kept."""
        declared = self.declared_number()
        if not declared or not word:
            return None
        irregular = {str(one).lower(): str(many).lower() for one, many in (declared.get("irregular") or {}).items()}
        lower = word.lower()

        def cased(one):
            return (one[:1].upper() + one[1:]) if word[:1].isupper() else one
        ones = sorted({one for one, many in irregular.items() if many == lower})
        if ones:
            return cased(ones[0]) if len(ones) == 1 else None
        if lower in irregular:
            return word
        found = set()
        for row in declared.get("plural", []):
            added = row.get("append", "")
            if not added or not lower.endswith(added):
                continue
            stem = word[:len(word) - len(added)]
            # A rule that dropped letters dropped the end of one of the tails it follows.
            restored = [tail[len(tail) - int(row["drop"]):] for tail in row.get("after", [])] if row.get("drop") \
                else [""]
            for tail in restored:
                one = stem + tail
                if one and one != word and self.plural_of(one) == word:
                    found.add(one)
        if len(found) > 1 and said:
            written = {str(token).strip("".join(self._marks())).lower() for token in said}
            found = {one for one in found if one.lower() in written}
        return found.pop() if len(found) == 1 else None

    def _marks(self):
        marks = [mark for pair in self.ortho.get("quotes", {}).values() for mark in pair]
        return marks + list(self.ortho.get("punctuation", {}).values()) + list(self.ortho.get("symbols", {}).values())

    def choose_number(self, words, number):
        """Of the words the pack links to one concept, the one that agrees with ``number``.

        A pair is a singular and the plural the pack declares for it (irregular table
        first); a count of one takes the singular, any other count the plural. Without a
        declared pair the shortest word is said."""
        plural = not self.is_one(number)
        if self.declared_number():
            singulars = [w for w in words if self.plural_of(w) not in (None, w) and self.plural_of(w) in words]
            if singulars:
                return self.plural_of(singulars[0]) if plural else singulars[0]
            irregular = {str(one).lower() for one in self.declared_number().get("irregular") or {}}
            if plural and any(w.lower() in irregular for w in words):
                # A singular the irregular table lists, its plural not linked: the table's plural.
                return next(self.plural_of(w) for w in words if w.lower() in irregular)
        if len(words) == 1:
            return words[0]
        rule = (self.decl.get("grammar") or {}).get("noun_number") or {}
        suffix = rule.get("plural_suffix")
        if not suffix:
            return sorted(words, key=len)[0]
        marked = [w for w in words if w.endswith(suffix) and w[:-len(suffix)] in words]
        bare = [w for w in words if w + suffix in words]
        if plural and marked:
            return marked[0]
        if not plural and bare:
            return bare[0]
        return sorted(words, key=len)[0]

    def singular_head(self, words, number, said=None):
        """One of a thing: its head noun in the singular the pack's declarations give back
        unambiguously (``jars of jam`` -> ``jar of jam``, ``geese`` -> ``goose``). The head is
        the word before the pack's partitive marker, else the last. A plural the declarations
        cannot undo in one way leaves the words as they are."""
        declared = self.declared_number()
        if not declared or not words or not self.is_one(number):
            return words
        head = next((words.index(marker) - 1 for marker in declared.get("partitive", [])
                     if marker in words[1:]), len(words) - 1)
        one = self.singular_of(words[head], said)
        if one is None:
            return words
        return words[:head] + [one] + words[head + 1:]

    def noun_number(self, word, number):
        """Agree a noun with its number, only between forms the pack links to one concept."""
        rule = (self.decl.get("grammar") or {}).get("noun_number") or {}
        suffix = rule.get("plural_suffix")
        if not suffix:
            return word
        concept = self.lang.concept(word)
        if not concept:
            return word
        return self.choose_number(self.lang.words_for(concept), number)

    # ── particles ────────────────────────────────────────────────────────
    def coda(self, text):
        """The final consonant that decides a particle's form, or '' when there is none."""
        marks = set()
        for pair in self.ortho.get("quotes", {}).values():
            marks.update(pair)
        marks.update(self.ortho.get("punctuation", {}).values())
        core = text
        while core and core[-1] in marks:
            core = core[:-1]
        if not core:
            return ""
        last = core[-1]
        if is_hangul(last):
            return batchim(last) or ""
        digits = self.ortho.get("digit_codas", {})
        if last in digits:
            return digits[last]
        if self.ortho.get("latin_codas") == "romanization" and self.lang.romanization:
            spelled = {v: k for k, v in self.lang.romanization.get("codas", {}).items() if v}
            lower = core.lower()
            for length in sorted({len(v) for v in spelled}, reverse=True):
                if lower[-length:] in spelled:
                    return spelled[lower[-length:]]
        return ""

    def particle(self, text, case):
        spec = self.decl.get("cases", {}).get(case)
        if spec is None:
            raise RealizationError("undeclared_case:%s" % case)
        if spec.get("then"):
            # Two particles in a row, each formed after what precedes it.
            first = self._one_particle(text, spec)
            return first + self.particle(text + first, spec["then"])
        return self._one_particle(text, spec)

    def _one_particle(self, text, spec):
        if "form" in spec:
            return spec["form"]
        if "closed" in spec and "open" in spec:
            # A pair the language file declares itself (the pack declares no mates for it).
            return spec["closed"] if self.coda(text) else spec["open"]
        if "mate" not in spec:
            return ""
        mates = self.lang.mates.get(spec["mate"])
        if not mates or len(mates) != 2:
            raise RealizationError("undeclared_mate:%s" % spec["mate"])
        closed, open_ = mates
        coda = self.coda(text)
        exception = self.lang.mate_exceptions.get(closed, {})
        if coda and coda in exception.get(self.keys.get("exception_codas", ""), []):
            return exception.get(self.keys.get("exception_form", ""), open_)
        return closed if coda else open_

    def canonical_piece(self, piece, kind):
        """A case particle compared by its mate pair: the form after a closed or open host is one case."""
        if kind != "case":
            return piece
        for pair in self.lang.mates.values():
            if piece in pair:
                return "|".join(sorted(pair))
        return piece

    def question_counter(self, prop):
        """The counter the matched question example declares for its answer, or None.

        The question's render is the pack's declaration of its answer's shape:
        the piece after the value slot is the counter, followed by the copula
        this language would put there. Only a language that counts with counters
        reads it; the declared counter stays the default.
        """
        declared = prop.get("question_render") or {}
        render, slot = declared.get("render") or [], declared.get("slot")
        if not self.decl.get("counters") or not isinstance(slot, str):
            return None
        marker = self.decl.get("render_slot_marker", "")
        pieces = [piece for piece in render if isinstance(piece, str)]
        positions = [i for i, piece in enumerate(pieces) if piece[len(marker):] == slot[1:]]
        if len(positions) != 1 or positions[0] + 1 >= len(pieces):
            return None
        tail = pieces[positions[0] + 1]
        for mark in self.ortho["punctuation"].values():
            if mark and tail.endswith(mark):
                tail = tail[:-len(mark)]
        copula = self.copula(tail, "present", self.sentence_ending("declarative", "formal"), "declarative")
        if copula and tail.endswith(copula):
            tail = tail[:-len(copula)]
        if not tail or any(char.isspace() for char in tail) or tail != tail.strip():
            return None
        return tail

    def preposition(self, case):
        spec = self.decl.get("cases", {}).get(case)
        if spec is None:
            raise RealizationError("undeclared_case:%s" % case)
        return spec.get("before")

    # ── verbs and copula ─────────────────────────────────────────────────
    def inflect(self, stem, tense, ending, kind):
        try:
            return _first(inflect(stem, tense, ending, self.lang.inflection, kind=kind))
        except ValueError as exc:
            raise RealizationError("inflection:%s:%s:%s:%s" % (stem, tense, ending, exc)) from exc

    def strategy(self, name):
        """How this language does a thing, as its file declares: verbs by ``endings`` or by
        ``agreement``; cases by ``particles`` or ``prepositions``."""
        return self.decl["grammar"]["strategies"][name]

    def lexeme(self, lex):
        entry = self.decl.get("lexicon", {}).get(lex)
        if entry is None:
            raise RealizationError("undeclared_lexeme:%s" % lex)
        return entry

    def verb_words(self, part, *, ending, tense, polarity, person, plural):
        """Finite or non-finite verb words for one part."""
        entry = self.lexeme(part["verb"])
        stem, kind = entry["verb"], entry.get("kind", "regular")
        negate = polarity is False and part.get("negation") and part.get("polarity") != "positive"
        if self.strategy("verbs") == "agreement":
            return self._english_verb(stem, part, ending=ending, tense=tense, negate=negate,
                                      person=person, plural=plural)
        if not negate:
            return [self.inflect(stem, tense, ending, kind)]
        spec = self.decl["grammar"]["negation"].get(part["negation"])
        if spec is None:
            raise RealizationError("undeclared_negation:%s" % part["negation"])
        if spec.get("from_pack"):
            spec = {"connective": self.lang.pack_negation.get(self.keys.get("negation_connective", "")),
                    "aux": self.lang.pack_negation.get(self.keys.get("negation_stem", "")),
                    "kind": self.lang.pack_negation.get(self.keys.get("negation_kind", ""))}
        if not spec.get("connective") or not spec.get("aux"):
            raise RealizationError("negation_not_declared")
        return [stem + spec["connective"], self.inflect(spec["aux"], tense, ending, spec.get("kind", "regular"))]

    def _english_form(self, lemma, form):
        lexicon = self.lang.inflection.get("lexicon", {})
        return (lexicon.get(lemma) or {}).get(form)

    def _english_finite(self, lemma, tense, person, plural):
        forms = self.decl["grammar"]["agreement"]
        if tense == "past":
            if plural or person in ("second",):
                declared = self._english_form(lemma, forms["past_plural"])
                if declared:
                    return declared
            return self.inflect(lemma, "past", forms["past"], "regular")
        if person == "first":
            declared = self._english_form(lemma, forms["present_first"])
            if declared:
                return declared
            return lemma
        if plural or person == "second":
            declared = self._english_form(lemma, forms["present_plural"])
            return declared or lemma
        return self.inflect(lemma, "present", forms["third_singular"], "regular")

    def _english_verb(self, lemma, part, *, ending, tense, negate, person, plural):
        if ending in ("participle",):
            return [self.inflect(lemma, "past", "participle", "regular")]
        if ending == "base":
            return [lemma]
        if not negate:
            return [self._english_finite(lemma, tense, person, plural)]
        spec = self.decl["grammar"]["negation"].get(part["negation"])
        if spec is None:
            raise RealizationError("undeclared_negation:%s" % part["negation"])
        if lemma in spec.get("direct", []):
            return [self._english_finite(lemma, tense, person, plural), spec["word"]]
        aux = self.lexeme(spec["aux"])["verb"] if spec["aux"] in self.decl.get("lexicon", {}) else spec["aux"]
        return [self._english_finite(aux, tense, person, plural), spec["word"], lemma]

    def copula(self, host, tense, ending, sentence):
        spec = (self.decl.get("grammar") or {}).get("copula")
        if not spec:
            raise RealizationError("copula_not_declared")
        coda = self.coda(host)
        table = spec.get("after_closed" if coda else "after_open", {})
        if ending in table:
            return table[ending]
        kind = spec.get("question_kind") if sentence == "question" and spec.get("question_kind") else spec["kind"]
        return self.inflect(spec["stem"], tense, ending, kind)

    # ── clauses ──────────────────────────────────────────────────────────
    def sentence_ending(self, sentence, register):
        table = self.decl.get("sentence_endings", {}).get(sentence) or {}
        ending = table.get(register) or table.get(self.decl.get("register", {}).get("default"))
        if ending is None:
            raise RealizationError("undeclared_sentence_ending:%s:%s" % (sentence, register))
        return ending

    def quote(self, text, marks):
        opening, closing = self.ortho["quotes"][marks]
        return opening + text + closing

    def symbol(self, name):
        return self.ortho["symbols"][name]


class Clause:
    """Words of one clause. Each word: its pieces, what it realizes, and flags."""

    def __init__(self):
        self.words = []

    def add(self, pieces, *, kind, role=None, bind=False, quoted=False, cited=False, number=None):
        pieces = [p for p in pieces if p]
        if not pieces:
            return
        self.words.append({"pieces": list(pieces), "kind": kind, "role": role, "bind": bind,
                           "quoted": quoted, "cited": cited, "number": number})

    def attach(self, piece, *, kind):
        if not self.words:
            raise RealizationError("nothing_to_attach_to")
        if piece:
            self.words[-1]["pieces"].append(piece)
            self.words[-1].setdefault("bound", []).append(kind)

    def last_text(self):
        return "".join(self.words[-1]["pieces"]) if self.words else ""

    def pieces(self, canon=None):
        """Every piece in order. ``canon`` maps a bound case piece to its case, so a
        particle whose form follows its host compares equal across hosts."""
        out = []
        for word in self.words:
            bound = word.get("bound", [])
            head = len(word["pieces"]) - len(bound)
            for index, piece in enumerate(word["pieces"]):
                kind = bound[index - head] if index >= head else None
                out.append(canon(piece, kind) if canon else piece)
        return out

    def text(self, separator):
        out = ""
        for index, word in enumerate(self.words):
            joined = "".join(word["pieces"])
            if index and not word["bind"]:
                out += separator
            out += joined
        return out


class ClauseRealizer:
    """Realize one proposition with one expression candidate."""

    def __init__(self, grammar):
        self.g = grammar

    def realize(self, prop, candidate, *, register, elided=(), sentence="declarative",
                gap=False, parts=None, tense=None):
        """``tense`` replaces the proposition's own tense in this saying only (a clause said in
        the form another clause governs, such as an event before which something held)."""
        clause = Clause()
        self._context = {"prop": prop, "elided": set(elided), "sentence": sentence, "register": register,
                         "gap": gap, "tense": tense}
        for part in (parts if parts is not None else candidate["parts"]):
            self._part(clause, part, prop.get("roles", {}))
        return clause

    # role values ---------------------------------------------------------
    def _value(self, roles, role):
        if role == "$item":
            return self._context.get("item")
        return roles.get(role)

    def _said(self):
        """The words of the statement the proposition was recorded from (its provenance), or None."""
        evidence = self._context["prop"].get("provenance") or {}
        words = [word for key in ("text", "source") for word in str(evidence.get(key) or "").split()]
        return words or None

    def _elided(self, role):
        return role in self._context["elided"]

    def _polarity(self):
        return self._context["prop"].get("polarity", True)

    def _tense(self, part):
        return part.get("tense") or self._context.get("tense") or self._context["prop"].get("tense") or "present"

    def _ending(self, part):
        if "ending" in part:
            return part["ending"]
        if part.get("predicate") or part.get("cop") == "predicate":
            return self.g.sentence_ending(self._context["sentence"], self._context["register"])
        return None

    # parts ---------------------------------------------------------------
    def _part(self, clause, part, roles):
        if part.get("elide_with") and (self._elided(part["elide_with"]) or roles.get(part["elide_with"]) is None):
            return
        kinds = [k for k in ("np", "num", "lex", "verb", "quote", "list", "rel", "sym", "cite", "id",
                             "pair", "operation", "lookup") if k in part]
        if len(kinds) != 1:
            raise RealizationError("part_kind")
        getattr(self, "_" + kinds[0])(clause, part, roles)

    def _finish(self, clause, part, host_text):
        """Case marker and copula after a constituent."""
        if part.get("case") and self.g.strategy("case_marking") == "particles":
            clause.attach(self.g.particle(host_text, part["case"]), kind="case")
        cop = part.get("cop")
        if cop and not (cop == "predicate" and self._context["gap"]):
            ending = self._ending(part) if cop == "predicate" else cop
            clause.attach(self.g.copula(clause.last_text(), self._tense(part), ending, self._context["sentence"]),
                          kind="copula")

    def _np(self, clause, part, roles):
        values = [(role, self._value(roles, role)) for role in part["np"]]
        present = [(role, value) for role, value in values if value is not None and not self._elided(role)]
        if not present:
            return
        number = None
        if part.get("number"):
            number_value = roles.get(part["number"])
            number = (number_value or {}).get("number") if isinstance(number_value, dict) else None
        english = self.g.strategy("case_marking") == "prepositions"
        preposition = self.g.preposition(part["case"]) if english and part.get("case") else None
        if preposition:
            clause.add([preposition], kind="case", role=None)
        for index, (role, value) in enumerate(present):
            words = self.g.entity_words(value, number, self._said())
            if english and part.get("det") and not self.g.is_name(value, words):
                clause.add([self.g.decl["determiners"][part["det"]]], kind="det", role=role)
            for word in words:
                clause.add([word], kind="np", role=role)
        self._finish(clause, part, clause.last_text())

    def _num(self, clause, part, roles):
        role = part["num"]
        value = roles.get(role)
        if value is None or self._elided(role):
            if value is not None and part.get("case") and part.get("elided_case") == "previous" and clause.words \
                    and self.g.strategy("case_marking") == "particles":
                # The amount left out, its case particle stays on the word before it (자두를 주기).
                clause.attach(self.g.particle(clause.last_text(), part["case"]), kind="case")
            return
        digits = str(value.get("number") if isinstance(value, dict) else value)
        numbers = self.g.decl.get("numbers") or {}
        style = part.get("style") or numbers.get("style", "digits")
        counter = part.get("counter")
        spec = self.g.decl.get("counters", {}).get(counter) if counter else None
        unit = self.g.question_counter(self._context["prop"]) if spec else None
        if unit:
            spec = {"form": unit}
        if style == "words" and digits in numbers.get("words", {}):
            # A numeral word stands apart from its counter: two words.
            clause.add([numbers["words"][digits]], kind="num", role=role, bind=bool(part.get("bind")),
                       cited=self._context.get("cited", False), number=digits)
            if spec:
                clause.add([spec["form"]], kind="counter", role=role)
        else:
            pieces = [digits] + ([spec["form"]] if spec else [])
            clause.add(pieces, kind="num", role=role, bind=bool(part.get("bind")),
                       cited=self._context.get("cited", False), number=digits)
        self._finish(clause, part, clause.last_text())

    def _lex(self, clause, part, roles):
        entry = self.g.lexeme(part["lex"])
        if "word" not in entry:
            raise RealizationError("lexeme_not_a_word:%s" % part["lex"])
        clause.add([entry["word"]], kind="lex", role=None, bind=bool(part.get("bind")))
        self._finish(clause, part, clause.last_text())

    def _rel(self, clause, part, roles):
        value = roles.get(part["rel"]) or {}
        word = self.g.decl.get("relation_words", {}).get(value.get("relation"))
        if not word:
            raise RealizationError("undeclared_relation_word:%s" % value.get("relation"))
        clause.add([word], kind="rel", role=part["rel"])
        self._finish(clause, part, clause.last_text())

    def _verb(self, clause, part, roles):
        entry = self.g.lexeme(part["verb"])
        person, plural = part.get("person"), bool(part.get("plural"))
        if part.get("agree"):
            agreed = roles.get(part["agree"]) or {}
            person = person or ("first" if agreed.get("person") == "first" else "third")
        if part.get("agree_number"):
            count = roles.get(part["agree_number"]) or {}
            plural = str(count.get("number")) != "1"
        if person is None:
            person = "third"
        polarity = self._polarity() if part.get("polarity") != "positive" else True
        ending = self._ending(part)
        if ending is None and self.g.strategy("verbs") == "endings":
            raise RealizationError("verb_without_ending:%s" % part["verb"])
        words = self.g.verb_words(part, ending=ending, tense=self._tense(part), polarity=polarity,
                                  person=person, plural=plural)
        for index, word in enumerate(words):
            clause.add([word], kind="verb", role=None, bind=bool(part.get("bind")) and index == 0)
        del entry

    def _quote(self, clause, part, roles):
        value = self._value(roles, part["quote"])
        if value is None:
            return
        if isinstance(value, dict) and "text" in value:
            # A name is said in this language, then marked as the one meant.
            text = self.g.ortho["word_separator"].join(self.g.entity_words(value))
        else:
            text = value.get("quote") if isinstance(value, dict) else str(value)
        clause.add([self.g.quote(text, part.get("marks", "double"))], kind="quote", role=part["quote"],
                   quoted=True, bind=bool(part.get("bind")))
        self._finish(clause, part, text)

    def _lookup(self, clause, part, roles):
        """A word the language file lists under a table, chosen by the role's id (the question
        word for a role, say). No word for the id: the clause cannot be said."""
        value = roles.get(part["lookup"]) or {}
        word = (self.g.decl.get(part["table"]) or {}).get(value.get("id"))
        if not isinstance(word, str) or not word:
            raise RealizationError("undeclared_%s:%s" % (part["table"], value.get("id")))
        clause.add([word], kind="lex", role=None, bind=bool(part.get("bind")))
        self._finish(clause, part, clause.last_text())

    def _id(self, clause, part, roles):
        value = roles.get(part["id"]) or {}
        clause.add([value.get("id", "")], kind="id", role=part["id"], cited=True, bind=bool(part.get("bind")))

    def _sym(self, clause, part, roles):
        clause.add([self.g.symbol(part["sym"])], kind="sym", bind=bool(part.get("bind")))

    def _pair(self, clause, part, roles):
        value = self._value(roles, part["pair"]) or {}
        marks = part.get("marks", "double")
        text = self.g.quote(value.get("source", ""), marks) + self.g.symbol(part["join"]) + \
            self.g.quote(value.get("reading", ""), marks)
        clause.add([text], kind="quote", role="pair", quoted=True, bind=bool(part.get("bind")))

    def _operation(self, clause, part, roles):
        op = self._value(roles, part["operation"]) or {}
        parts = self.g.decl.get("operations", {}).get(op.get("op"))
        if parts is None:
            raise RealizationError("undeclared_operation:%s" % op.get("op"))
        inner = ClauseRealizer(self.g)
        sub = inner.realize({"roles": {k: {"quote": v} for k, v in op.items() if k != "op"}, "polarity": True},
                            {"parts": parts}, sentence=self._context["sentence"],
                            register=self._context["register"])
        clause.add([sub.text(self.g.ortho["word_separator"])], kind="operation", quoted=True,
                   bind=bool(part.get("bind")))

    def _list(self, clause, part, roles):
        value = roles.get(part["list"]) or {}
        items = value.get("list", []) if isinstance(value, dict) else list(value)
        if not items:
            return
        word_separator = self.g.ortho["word_separator"]
        separator = self.g.symbol(part["separator"]) if part.get("separator") else self.g.ortho["list_separator"]
        last = self.g.ortho.get("list_last") if not part.get("separator") else None
        if part.get("last_lex"):
            # The list's last joint is a declared word ("or" where the list offers a choice).
            last = word_separator + self.g.lexeme(part["last_lex"])["word"] + word_separator
        texts = []
        for item in items:
            inner = ClauseRealizer(self.g)
            inner._context = dict(self._context, item=item)
            sub = Clause()
            inner._part(sub, dict(part["each"]), roles)
            texts.append(sub.text(word_separator))
        if part.get("join_case") and len(texts) > 1:
            # Items joined by a case particle on each but the last (a language
            # that says "A and B" with a particle after A).
            joined = word_separator.join([text + self.g.particle(text, part["join_case"]) for text in texts[:-1]]
                                         + texts[-1:])
            clause.add([joined], kind="list", role=part["list"], quoted=True, bind=bool(part.get("bind")))
            self._finish(clause, part, joined)
            return
        if last and len(texts) > 1:
            joined = separator.join(texts[:-1]) + last + texts[-1]
        else:
            joined = separator.join(texts)
        clause.add([joined], kind="list", role=part["list"], quoted=True, bind=bool(part.get("bind")))
        self._finish(clause, part, joined)

    def _cite(self, clause, part, roles):
        opening, closing = self.g.ortho["cite"]
        groups = []
        for group in part["cite"]:
            inner = ClauseRealizer(self.g)
            inner._context = dict(self._context, cited=True)
            sub = Clause()
            for piece in group:
                inner._part(sub, piece, roles)
            groups.append(sub)
        texts = [sub.text(self.g.ortho["word_separator"]) for sub in groups if sub.words]
        numbers = [word["number"] for sub in groups for word in sub.words if word.get("number") is not None]
        clause.add([opening + self.g.ortho["cite_separator"].join(texts) + closing], kind="cite",
                   cited=True, bind=True)
        clause.words[-1]["cited_numbers"] = numbers


def finish_sentence(grammar, text, sentence):
    """Sentence punctuation and the declared capital."""
    mark = grammar.ortho["punctuation"].get(sentence, "")
    if grammar.ortho.get("initial_capital") and text:
        text = text[:1].upper() + text[1:]
    return text + mark


def copy_candidate(candidate):
    return copy.deepcopy(candidate)
