"""Development set v3 (goal G3.3): the language, not one generator.

Built like v2 (a dialogue is a plan plus a setting of declared dimensions; every
sentence comes from the small grammar of its language here; every expectation is
computed from the plan's events), with three differences:

* Vocabulary comes from the open-vocabulary probe's public word lists
  (``data/benchmarks/vocab_probe/words.json``: krdict item nouns with their
  English equivalents, English given names from the BSD propernames list, Korean
  given names from the Kiwi lexicon), never from a pack's declared example
  items and never from a seen development set.
* Most statements carry two or three facts, joined every way the round-3 clause
  probe declares (comma, and, gapping, two sentences in one turn, a relative
  clause, -고, -며, 그리고, -는데, the shared predicate after commas), and most
  dialogues open with one.
* The **build** and **check** halves come from **different plans** (the plan
  tables ``BUILD_PLANS`` and ``CHECK_PLANS`` share no plan) and from **disjoint
  halves of the vocabulary** (no name or item of one half is in the other), both
  cut by the recorded seed. Rules are written against the build half only; the
  check half is never read while writing them.

    python data/benchmarks/dialogues_dev3/build.py     # writes dev3_*.json and split.txt
"""
import json
import random
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SEED = 20260926
SCHEMA = "marco1-dialogue-gate-v1"
PER_HALF = 22            # dialogues per language per half: 88 in all
WORDS = ROOT / "data/benchmarks/vocab_probe/words.json"

DIMENSIONS = {
    "ko": {
        "register": ["banmal", "plain", "haeyo", "hapsyo"],
        "numeral_form": ["digits", "native", "digits", "native"],
        "join": ["go", "comma_shared", "myeo", "geurigo", "copula", "possessive_go"],
        "word_order": ["canonical", "object_first", "recipient_first", "receiver_subject"],
        "transfer_verb": ["give", "hand", "lend", "pass_on", "send", "give"],
        "question_form": ["exist", "now", "left", "have", "short"],
        "counter": ["specific", "general"],
        "name_suffix": ["bare", "suffixed"],
    },
    "en": {
        "register": ["neutral", "casual", "formal"],
        "numeral_form": ["digits", "words"],
        "join": ["and", "and_elided", "comma", "comma_and", "gapping", "two_sentences"],
        "word_order": ["double_object", "prepositional", "receiver_subject", "passive"],
        "transfer_verb": ["give", "hand", "pass", "lend", "send", "give"],
        "question_form": ["have", "now", "got", "left", "short"],
        "possession": ["has", "had", "owns", "holding", "got"],
    },
}

# ---------------------------------------------------------------------------
# plans: abstract turns over people A, B, C and items X (and Y)
# ---------------------------------------------------------------------------
# has_many(people): one statement with a count for each (the declared join);
# two_items(A): one holder, two items; counts_give(A, B): two counts and a
# transfer in one statement; relative(A, B): B's count, then A (whose count a
# relative clause states) gives B; give(A, B); give_two(A, B, C): two
# transfers in one statement; use(A); get(B, A): B receives from A.
BUILD_PLANS = {
    "b_joined_follow_why": [("has_many", "AB"), ("give", "A", "B"), ("ask", "B"), ("follow", "A"), ("why", "B")],
    "b_three_total_more": [("has_many", "ABC"), ("give", "B", "C"), ("ask", "C"), ("total", "A", "B"),
                           ("more", "A", "C")],
    "b_two_items_use": [("two_items", "A"), ("has_many", "B"), ("use", "A"), ("ask", "A"), ("ask_y", "A"),
                        ("give", "B", "A"), ("ask", "A")],
    "b_early_correction": [("has_many", "AB"), ("give", "A", "B"), ("correct", "contrast"), ("ask", "B"),
                           ("follow", "A")],
    "b_late_correction_why": [("has_many", "AB"), ("give", "A", "B"), ("ask", "B"), ("correct", "reference"),
                              ("ask", "B"), ("why", "B")],
    "b_pointer_then_name": [("has_many", "AB"), ("give", "A", "B"), ("pronoun", "A", "B"), ("follow", "B"),
                            ("ask", "A")],
    "b_missing_then_counts_give": [("has", "A"), ("missing", "C"), ("counts_give_known", "C", "A"), ("ask", "C"),
                                   ("ask", "A")],
    "b_restart_cross": [("has_many", "AB"), ("give", "B", "A"), ("restart_ask", "A"), ("cross_ask", "B"),
                        ("total", "A", "B")],
}
CHECK_PLANS = {
    "c_relative_more": [("relative", "A", "B"), ("ask", "A"), ("ask", "B"), ("more", "A", "B")],
    "c_chain_follow_why": [("has_many", "ABC"), ("give_two", "A", "B", "C"), ("ask", "C"), ("follow", "B"),
                           ("why", "C")],
    "c_use_get_total": [("has_many", "AB"), ("use", "A"), ("get", "A", "B"), ("ask", "A"), ("total", "A", "B")],
    "c_named_correction": [("counts_give", "A", "B"), ("ask", "A"), ("give", "B", "A"), ("correct", "named"),
                           ("ask", "A"), ("follow", "B")],
    "c_total_then_pointer": [("has_many", "AB"), ("total", "A", "B"), ("pronoun", "A", "B"), ("follow", "A"),
                             ("ask", "B")],
    "c_decline_location": [("has_many", "AB"), ("decline", "B"), ("location", "A"), ("give", "A", "B"),
                           ("ask", "B"), ("ask", "A")],
    "c_restart_correction_why": [("has_many", "AB"), ("give", "B", "A"), ("correct", "restate"),
                                 ("restart_ask", "A"), ("why", "A")],
    "c_missing_then_gapped": [("has", "A"), ("missing", "B"), ("has_many", "BC"), ("ask", "C"),
                              ("total", "B", "C"), ("cross_ask", "A")],
}


# ---------------------------------------------------------------------------
# Korean grammar
# ---------------------------------------------------------------------------
NATIVE = {1: "한", 2: "두", 3: "세", 4: "네", 5: "다섯", 6: "여섯", 7: "일곱", 8: "여덟", 9: "아홉", 10: "열",
          11: "열한", 12: "열두", 13: "열세", 14: "열네", 15: "열다섯", 16: "열여섯", 17: "열일곱", 18: "열여덟",
          19: "열아홉", 20: "스무"}


def batchim(word):
    ch = word[-1]
    if "가" <= ch <= "힣":
        return (ord(ch) - 0xAC00) % 28
    return 0 if ch.lower() in "aeiouy" else 1


class Ko:
    VERBS = {"give": "주", "hand": "건네", "lend": "빌려주", "pass_on": "넘겨주", "send": "보내"}
    PAST = {"주": ("줬어", "주었다", "줬어요", "주었습니다"), "건네": ("건넸어", "건넸다", "건넸어요", "건넸습니다"),
            "빌려주": ("빌려줬어", "빌려주었다", "빌려줬어요", "빌려주었습니다"),
            "넘겨주": ("넘겨줬어", "넘겨주었다", "넘겨줬어요", "넘겨주었습니다"),
            "보내": ("보냈어", "보냈다", "보냈어요", "보냈습니다"),
            "받": ("받았어", "받았다", "받았어요", "받았습니다"), "먹": ("먹었어", "먹었다", "먹었어요", "먹었습니다"),
            "쓰": ("썼어", "썼다", "썼어요", "썼습니다"), "잃어버리": ("잃어버렸어", "잃어버렸다", "잃어버렸어요", "잃어버렸습니다")}
    EXIST = ("있어", "있다", "있어요", "있습니다")
    EXIST_PAST = ("있었어", "있었다", "있었어요", "있었습니다")
    HOLD = ("가지고 있어", "가지고 있다", "가지고 있어요", "가지고 있습니다")
    Q_EXIST = ("있어", "있니", "있어요", "있습니까")
    Q_LEFT = ("남았어", "남았니", "남았어요", "남았습니까")
    Q_HOLD = ("가지고 있어", "가지고 있니", "가지고 있어요", "가지고 있습니까")
    REGISTERS = ("banmal", "plain", "haeyo", "hapsyo")

    def __init__(self, dims):
        self.d = dims
        self.r = self.REGISTERS.index(dims["register"])

    def p(self, word, pair):
        return word + (pair[0] if batchim(word) else pair[1])

    def name(self, n):
        if self.d["name_suffix"] == "suffixed" and self.d["register"] == "banmal" and "가" <= n[-1] <= "힣" \
                and batchim(n):
            return n + "이"
        return n

    def top(self, n):
        return self.p(self.name(n), ("은", "는"))

    def subj(self, n):
        return self.p(self.name(n), ("이", "가"))

    def dat(self, n):
        return self.name(n) + ("한테" if self.d["register"] in ("banmal", "haeyo") else "에게")

    def src(self, n):
        return self.name(n) + ("한테서" if self.d["register"] in ("banmal", "haeyo") else "에게서")

    def counter(self, item):
        return item["counter"] if self.d["counter"] == "specific" else "개"

    def amount(self, n, item):
        c = self.counter(item)
        return "%s %s" % (NATIVE[n], c) if self.d["numeral_form"] == "native" and n in NATIVE else "%d%s" % (n, c)

    def copula(self, word, last=True):
        if not last:
            return word + ("이고" if batchim(word) else "고")
        return word + [("이야", "야"), ("이다", "다"), ("이에요", "예요"), ("입니다", "입니다")][self.r][
            0 if batchim(word) else 1]

    def q_copula(self, word):
        """The copula of a question: 몇 개야 / 몇 개지 / 몇 개예요 / 몇 개입니까."""
        return word + [("이야", "야"), ("이지", "지"), ("이에요", "예요"), ("입니까", "입니까")][self.r][
            0 if batchim(word) else 1]

    def s(self, text):
        return text + "."

    def has_many(self, rows, item):
        """rows: [(name, n)]; the declared join."""
        w, join = item["word"], self.d["join"]
        amts = [(h, self.amount(n, item)) for h, n in rows]
        if len(rows) == 1:
            h, a = amts[0]
            return self.s("%s %s %s %s" % (self.top(h), self.p(w, ("이", "가")), a, self.EXIST[self.r]))
        if join == "comma_shared" or len(rows) == 3:
            head = "%s %s %s" % (self.top(amts[0][0]), self.p(w, ("이", "가")), amts[0][1])
            rest = ", ".join("%s %s" % (self.top(h), a) for h, a in amts[1:])
            return self.s("%s, %s %s" % (head, rest, self.EXIST[self.r]))
        (h1, a1), (h2, a2) = amts
        if join == "go":
            return self.s("%s %s %s 있고 %s %s %s" % (self.top(h1), self.p(w, ("이", "가")), a1, self.top(h2), a2,
                                                   self.EXIST[self.r]))
        if join == "myeo":
            return self.s("%s %s %s 있으며 %s %s %s" % (self.top(h1), self.p(w, ("이", "가")), a1, self.top(h2), a2,
                                                     self.EXIST[self.r]))
        if join == "geurigo":
            return "%s 그리고 %s" % (self.s("%s %s %s %s" % (self.top(h1), self.p(w, ("이", "가")), a1, self.EXIST[self.r])),
                                  self.s("%s %s %s" % (self.top(h2), a2, self.EXIST[self.r])))
        if join == "copula":
            return self.s("%s의 %s %s, %s의 %s %s" % (self.name(h1), self.p(w, ("은", "는")), self.copula(a1, False),
                                                   self.name(h2), self.p(w, ("은", "는")), self.copula(a2)))
        # possessive_go
        return self.s("%s %s %s 가지고 있고 %s %s %s" % (self.top(h1), self.p(w, ("을", "를")), a1, self.top(h2), a2,
                                                     self.HOLD[self.r]))

    def two_items(self, h, n1, x, n2, y):
        return self.s("%s %s %s, %s %s %s" % (self.top(h), self.p(x["word"], ("이", "가")), self.amount(n1, x),
                                             self.p(y["word"], ("이", "가")), self.amount(n2, y), self.EXIST[self.r]))

    def counts_give(self, a, na, b, nb, k, item):
        w = item["word"]
        verb = self.PAST[self.VERBS.get(self.d["transfer_verb"], "주")][self.r]
        return self.s("%s %s %s, %s %s 있었는데 %s %s %s %s %s" % (
            self.top(a), self.p(w, ("이", "가")), self.amount(na, item), self.top(b), self.amount(nb, item),
            self.subj(a), self.dat(b), w, self.p(self.amount(k, item), ("을", "를")), verb))

    def relative(self, a, na, b, nb, k, item):
        w = item["word"]
        verb = self.PAST[self.VERBS.get(self.d["transfer_verb"], "주")][self.r]
        return self.s("%s %s %s 있고, %s %s 가진 %s %s %s %s" % (
            self.top(b), self.p(w, ("이", "가")), self.amount(nb, item), self.p(w, ("을", "를")),
            self.amount(na, item), self.subj(a), self.dat(b), self.p(self.amount(k, item), ("을", "를")), verb))

    def give(self, a, b, k, item):
        w, amt = item["word"], self.amount(k, item)
        order = self.d["word_order"]
        verb = self.PAST[self.VERBS.get(self.d["transfer_verb"], "주")][self.r]
        if order == "receiver_subject":
            return self.s("%s %s %s %s %s" % (self.subj(b), self.src(a), w, self.p(amt, ("을", "를")),
                                              self.PAST["받"][self.r]))
        if order == "object_first":
            return self.s("%s %s %s %s %s" % (w, self.p(amt, ("을", "를")), self.subj(a), self.dat(b), verb))
        if order == "recipient_first":
            return self.s("%s %s %s %s %s" % (self.dat(b), self.subj(a), w, self.p(amt, ("을", "를")), verb))
        return self.s("%s %s %s %s %s" % (self.subj(a), self.dat(b), w, self.p(amt, ("을", "를")), verb))

    def give_two(self, a, b, k1, c, k2, item):
        w = item["word"]
        verb = self.PAST[self.VERBS.get(self.d["transfer_verb"], "주")][self.r]
        stem = self.VERBS.get(self.d["transfer_verb"], "주")
        return self.s("%s %s %s %s %s고 %s %s %s %s" % (
            self.subj(a), self.dat(b), w, self.p(self.amount(k1, item), ("을", "를")), stem,
            self.subj(b), self.dat(c), self.p(self.amount(k2, item), ("을", "를")), verb))

    def use(self, a, k, item, how):
        return self.s("%s %s %s %s" % (self.subj(a), item["word"], self.p(self.amount(k, item), ("을", "를")),
                                       self.PAST[{"eat": "먹", "use": "쓰", "lose": "잃어버리"}[how]][self.r]))

    def get(self, taker, giver, k, item):
        return self.s("%s %s %s %s %s" % (self.subj(taker), self.src(giver), item["word"],
                                          self.p(self.amount(k, item), ("을", "를")), self.PAST["받"][self.r]))

    def ask(self, who, item, form=None):
        form = form or self.d["question_form"]
        w, c = item["word"], self.counter(item)
        if form == "exist":
            return "%s %s 몇 %s %s?" % (self.top(who), self.p(w, ("이", "가")), c, self.Q_EXIST[self.r])
        if form == "now":
            return "%s 지금 %s 몇 %s?" % (self.top(who), w, self.q_copula(c))
        if form == "left":
            return "%s %s 몇 %s %s?" % (self.dat(who), self.p(w, ("이", "가")), c, self.Q_LEFT[self.r])
        if form == "have":
            return "%s %s 몇 %s %s?" % (self.top(who), self.p(w, ("을", "를")), c, self.Q_HOLD[self.r])
        return "%s 몇 %s?" % (self.top(who), self.q_copula(c))

    def follow(self, who):
        head = "그럼 " if self.d["register"] in ("banmal", "haeyo") else "그러면 "
        return head + self.top(who) + ("요" if self.d["register"] in ("haeyo", "hapsyo") else "") + "?"

    def total(self, a, b, item):
        c = self.counter(item)
        return "%s %s %s 모두 몇 %s?" % (self.p(self.name(a), ("과", "와")), self.top(b), self.p(item["word"], ("이", "가")),
                                     self.q_copula(c))

    def more(self, a, b, item):
        end = ("많아", "많니", "많아요", "많습니까")[self.r]
        return "%s %s 중 누가 %s 더 %s?" % (self.p(self.name(a), ("과", "와")), self.name(b),
                                       self.p(item["word"], ("이", "가")), end)

    def why(self, who, item):
        tail = ("있는 거야", "있는 거지", "있는 거예요", "있는 겁니까")[self.r]
        return "%s 왜 %s 그만큼 %s?" % (self.top(who), self.p(item["word"], ("이", "가")), tail)

    def pronoun(self, item):
        word = "걔는" if self.d["register"] == "banmal" else "그 사람은"
        return "%s 지금 %s 몇 %s %s?" % (word, item["word"], self.counter(item), self.Q_EXIST[self.r])

    def location(self, who, item):
        return "%s의 %s 어디에 %s?" % (self.name(who), self.p(item["word"], ("은", "는")), self.Q_EXIST[self.r])

    def decline(self, who, kind):
        please = ("줘", "줘", "주세요", "주십시오")[self.r]
        return ["%s 문자 좀 보내 %s." % (self.dat(who), please), "%s 전화 좀 걸어 %s." % (self.dat(who), please),
                "내일 %s 일을 다시 알려 %s." % (self.name(who) + "의", please)][kind]

    def correct(self, style, old, new, item, event):
        c = self.counter(item)
        was = ("였어", "였다", "였어요", "였습니다")[self.r]
        was_c = ("이었어", "이었다", "이었어요", "이었습니다")[self.r]
        new_said = "%d%s%s" % (new, c, was_c if batchim(c) else was)
        if style == "contrast":
            return "아니, %d%s%s 아니라 %s." % (old, c, "이" if batchim(c) else "가", new_said)
        if style == "named":
            return "아, %s %d%s%s 아니라 %s." % (item["word"], old, c, "이" if batchim(c) else "가", new_said)
        if style == "reference":
            said = {"주": "준", "건네": "건넨", "빌려주": "빌려준", "넘겨주": "넘겨준", "보내": "보낸"}[
                self.VERBS.get(self.d["transfer_verb"], "주")]
            if self.d["word_order"] == "receiver_subject":
                said = "받은"
            return "아까 %s 건 %d%s%s 아니라 %d%s%s." % (said, old, c, "이" if batchim(c) else "가", new, c,
                                                     ("야", "이다", "예요", "입니다")[self.r] if not batchim(c) else
                                                     ("이야", "이다", "이에요", "입니다")[self.r])
        head = ("잘못 말했어", "잘못 말했다", "잘못 말했어", "잘못 말했다")[self.r]
        verb = self.PAST["받" if self.d["word_order"] == "receiver_subject"
                         else self.VERBS.get(self.d["transfer_verb"], "주")][self.r]
        return "%s, %s %s." % (head, self.p("%d%s" % (new, c), ("을", "를")), verb)


# ---------------------------------------------------------------------------
# English grammar
# ---------------------------------------------------------------------------
class En:
    WORDS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven",
             "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen", "twenty"]
    PAST = {"give": "gave", "hand": "handed", "pass": "passed", "lend": "lent", "send": "sent"}
    PARTICIPLE = {"give": "given", "hand": "handed", "pass": "passed", "lend": "lent", "send": "sent"}
    RECEIVE = {"give": "got", "hand": "received", "pass": "received", "lend": "borrowed", "send": "received"}

    def __init__(self, dims):
        self.d = dims

    def num(self, n):
        return self.WORDS[n] if self.d["numeral_form"] == "words" and n < len(self.WORDS) else str(n)

    def amount(self, n, item):
        return "%s %s" % (self.num(n), item["one"] if n == 1 else item["word"])

    def cap(self, text):
        return text[0].upper() + text[1:]

    def verb(self, subject_plural=False):
        return {"has": "has", "had": "had", "owns": "owns", "holding": "is holding", "got": "'s got"}[
            self.d["possession"]]

    def clause(self, h, n, item, with_item=True):
        v = self.verb()
        sep = "" if v.startswith("'") else " "
        return "%s%s%s %s" % (h, sep, v, self.amount(n, item) if with_item else self.num(n))

    def has_many(self, rows, item):
        join = self.d["join"]
        if len(rows) == 1:
            return self.clause(rows[0][0], rows[0][1], item) + "."
        if len(rows) == 3:
            (a, x), (b, y), (c, z) = rows
            return "%s, %s, and %s." % (self.clause(a, x, item), self.clause(b, y, item, False),
                                        self.clause(c, z, item, False))
        (a, x), (b, y) = rows
        first = self.clause(a, x, item)
        if join == "and":
            return "%s and %s." % (first, self.clause(b, y, item))
        if join == "and_elided":
            return "%s and %s." % (first, self.clause(b, y, item, False))
        if join == "comma":
            return "%s, %s." % (first, self.clause(b, y, item, False))
        if join == "comma_and":
            return "%s, and %s." % (first, self.clause(b, y, item, False))
        if join == "gapping":
            return "%s and %s %s." % (first, b, self.num(y))
        return "%s. %s." % (first, self.clause(b, y, item, False))

    def two_items(self, h, n1, x, n2, y):
        return "%s and %s." % (self.clause(h, n1, x), self.amount(n2, y))

    def counts_give(self, a, na, b, nb, k, item):
        return "%s and %s, and %s %s %s %s." % (self.clause(a, na, item), self.clause(b, nb, item, False), a,
                                                self.PAST[self.d["transfer_verb"]], b, self.num(k))

    def relative(self, a, na, b, nb, k, item):
        return "%s, and %s, who has %s, %s %s %s." % (self.clause(b, nb, item), a, self.num(na),
                                                     self.PAST[self.d["transfer_verb"]], b, self.num(k))

    def give(self, a, b, k, item):
        amt, tv = self.amount(k, item), self.d["transfer_verb"]
        order = self.d["word_order"]
        if order == "prepositional":
            return "%s %s %s to %s." % (a, self.PAST[tv], amt, b)
        if order == "receiver_subject":
            return "%s %s %s from %s." % (b, self.RECEIVE[tv], amt, a)
        if order == "passive":
            return "%s %s %s to %s by %s." % (self.cap(amt), "was" if k == 1 else "were", self.PARTICIPLE[tv], b, a)
        return "%s %s %s %s." % (a, self.PAST[tv], b, amt)

    def give_two(self, a, b, k1, c, k2, item):
        tv = self.PAST[self.d["transfer_verb"]]
        return "%s %s %s %s, and %s %s %s %s." % (a, tv, b, self.amount(k1, item), b, tv, c, self.num(k2))

    def use(self, a, k, item, how):
        return "%s %s %s." % (a, {"eat": "ate", "use": "used", "lose": "lost"}[how], self.amount(k, item))

    def get(self, taker, giver, k, item):
        return "%s got %s from %s." % (taker, self.amount(k, item), giver)

    def ask(self, who, item, form=None):
        form = form or self.d["question_form"]
        w = item["word"]
        return {"have": "How many %s does %s have?" % (w, who), "now": "How many %s does %s have now?" % (w, who),
                "got": "How many %s has %s got?" % (w, who), "left": "How many %s does %s have left?" % (w, who),
                "short": "How many does %s have now?" % who}[form]

    def follow(self, who):
        return {"neutral": "And %s?", "casual": "What about %s?", "formal": "And how about %s?"}[
            self.d["register"]] % who

    def total(self, a, b, item):
        tail = {"neutral": "together", "casual": "altogether", "formal": "in total"}[self.d["register"]]
        return "How many %s do %s and %s have %s?" % (item["word"], a, b, tail)

    def more(self, a, b, item):
        return "Who has more %s now, %s or %s?" % (item["word"], a, b)

    def why(self, who, item):
        return {"neutral": "Why does %s have that many %s?", "casual": "How come %s has that many %s?",
                "formal": "Why does %s have that many %s now?"}[self.d["register"]] % (who, item["word"])

    def pronoun(self, item):
        return "How many %s does that person have now?" % item["word"]

    def location(self, who, item):
        return "Where does %s keep the %s?" % (who, item["word"])

    def decline(self, who, kind):
        return ["Could you text %s for me?", "Please call %s for me.", "Remind %s about this tomorrow."][kind] % who

    def correct(self, style, old, new, item, event):
        a, b = event["from"], event["to"]
        tv = self.PAST[self.d["transfer_verb"]]
        if style == "contrast":
            return "No, it was %s, not %s." % (self.num(new), self.num(old))
        if style == "named":
            return "Actually, %s %s %s %s, not %s." % (a, tv, b, self.amount(new, item), self.num(old))
        if style == "reference":
            return "The one %s %s was %s, not %s." % (a, tv, self.num(new), self.num(old))
        return "Sorry, I misspoke: %s %s %s %s." % (a, tv, b, self.num(new))


# ---------------------------------------------------------------------------
# vocabulary halves
# ---------------------------------------------------------------------------
def vocabulary():
    """{"build"|"check": {"ko"|"en": {"names": [...], "items": [...]}}}: disjoint halves by the seed."""
    words = json.loads(WORDS.read_text(encoding="utf-8"))
    rng = random.Random(SEED)
    latin = sorted(r["name"] for r in words["names"] if r["script"] == "latin")
    hangul = sorted(r["name"] for r in words["names"] if r["script"] == "hangul")
    items = sorted(words["items"], key=lambda r: r["ko"])
    for pool in (latin, hangul, items):
        rng.shuffle(pool)
    halves = {}
    for index, half in enumerate(("build", "check")):
        cut = lambda pool: pool[index * len(pool) // 2:(index + 1) * len(pool) // 2]  # noqa: E731
        chosen = cut(items)
        halves[half] = {
            "ko": {"names": cut(hangul), "other_names": cut(latin),
                   "items": [{"word": r["ko"], "counter": r.get("counter", "개"), "domain": r["category"],
                              "gloss": r["en"]} for r in chosen]},
            "en": {"names": cut(latin), "other_names": cut(hangul),
                   "items": [{"word": plural(r["en"]), "one": r["en"], "domain": r["category"], "gloss": r["ko"]}
                             for r in chosen]}}
    return halves


def plural(word):
    import importlib.util
    spec = importlib.util.spec_from_file_location("vocab_probe_build", ROOT / "data/benchmarks/vocab_probe/build.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.plural(word)


def romanized(name):
    import sys
    sys.path.insert(0, str(ROOT))
    from marco.language.hangul import romanize
    table = json.loads((ROOT / "styles/한국어.json").read_text(encoding="utf-8"))["로마자"]
    spelled = romanize(name, table)
    return spelled[:1].upper() + spelled[1:] if spelled else name


# ---------------------------------------------------------------------------
# one dialogue
# ---------------------------------------------------------------------------
def apply(state, event):
    if event["type"] == "has":
        state[event["holder"], event["item"]] = event["quantity"]
    elif event["type"] == "use":
        state[event["holder"], event["item"]] -= event["quantity"]
    else:
        state[event["from"], event["item"]] -= event["quantity"]
        state[event["to"], event["item"]] = state.get((event["to"], event["item"]), 0) + event["quantity"]


def build_dialogue(lang, did, plan_name, plan, dims, vocab, rng):
    g = Ko(dims) if lang == "ko" else En(dims)
    names = rng.sample(vocab["names"], 3)
    people = dict(zip("ABC", names))
    x, y = rng.sample(vocab["items"], 2)
    start = {}
    while len(set(start.values())) != 3:
        start = {p: rng.randint(4, 12) for p in "ABC"}
    second_start = rng.randint(2, 9)
    ks = [rng.randint(1, 3) for _ in plan]
    state, turns, touched, by_turn = {}, [], {}, {}
    correction = {}

    def record(say, events, tags):
        n = len(turns) + 1
        for ev in events:
            apply(state, ev)
            for key in ("holder", "from", "to"):
                if key in ev:
                    touched.setdefault(ev[key], []).append(n)
        by_turn[n] = events
        rows = []
        for ev in events:
            for key in ("holder", "from", "to"):
                if key in ev and (ev[key], ev["item"]) not in [(r["entity"], r["item"]) for r in rows]:
                    rows.append({"entity": ev[key], "item": ev["item"], "quantity": state[ev[key], ev["item"]]})
        turns.append({"n": n, "say": say, "label": "hold", "tags": tags,
                      "expect": {"act": "record", "entity": None, "quantity": None, "relation": None,
                                 "evidence": {"turns": [n]}, "events": events, "state": rows}})

    def evidence(person):
        return sorted(set(touched.get(person, [])))

    def answer_turn(say, person, item, tags):
        n = len(turns) + 1
        turn = {"n": n, "say": say, "label": "answerable", "tags": sorted(set(tags)),
                "expect": {"act": "answer", "entity": person, "quantity": state[person, item["word"]],
                           "relation": "count", "evidence": {"turns": evidence(person)}, "item": item["word"]}}
        if correction and correction["target"] in touched.get(person, []):
            turn["tags"] = sorted(set(turn["tags"]) | {"correction"})
            old, new, ev = correction["old"], correction["new"], correction["event"]
            if person == ev["to"]:
                retracted, rerun = state[person, item["word"]] - new + old, state[person, item["word"]] + old
            else:
                retracted, rerun = state[person, item["word"]] + new - old, state[person, item["word"]] - old
            if retracted != turn["expect"]["quantity"]:
                turn["expect"]["retracted_quantity"] = retracted
            if rerun not in (turn["expect"]["quantity"], retracted):
                turn["expect"]["reexecuted_quantity"] = rerun
        turns.append(turn)
        return turn

    def tags_for(person):
        moved = any(e["type"] != "has" for t in touched.get(person, []) for e in by_turn[t])
        return ["transfer"] if moved else ["ownership"]

    for index, step in enumerate(plan):
        kind, k = step[0], ks[index]
        if kind in ("has", "has_many"):
            who = [people[c] for c in step[1]]
            rows = [(h, start[c]) for h, c in zip(who, step[1])]
            events = [{"type": "has", "holder": h, "item": x["word"], "quantity": q} for h, q in rows]
            record(g.has_many(rows, x), events, ["ownership"])
        elif kind == "two_items":
            a = people[step[1]]
            events = [{"type": "has", "holder": a, "item": x["word"], "quantity": start[step[1]]},
                      {"type": "has", "holder": a, "item": y["word"], "quantity": second_start}]
            record(g.two_items(a, start[step[1]], x, second_start, y), events, ["ownership"])
        elif kind == "counts_give_known":
            # The first person's count is stated now; the second, stated before,
            # gives them some: two sentences in one turn.
            taker, giver = people[step[1]], people[step[2]]
            k = min(k, state[giver, x["word"]] - 1)
            events = [{"type": "has", "holder": taker, "item": x["word"], "quantity": start[step[1]]},
                      {"type": "transfer", "from": giver, "to": taker, "item": x["word"], "quantity": k}]
            if lang == "ko":
                say = "%s %s" % (g.has_many([(taker, start[step[1]])], x), g.give(giver, taker, k, x))
            else:
                say = "%s %s" % (g.has_many([(taker, start[step[1]])], x), g.give(giver, taker, k, x))
            record(say, events, ["ownership", "transfer"])
        elif kind == "counts_give":
            a, b = people[step[1]], people[step[2]]
            k = min(k, start[step[1]] - 1)
            events = [{"type": "has", "holder": a, "item": x["word"], "quantity": start[step[1]]},
                      {"type": "has", "holder": b, "item": x["word"], "quantity": start[step[2]]},
                      {"type": "transfer", "from": a, "to": b, "item": x["word"], "quantity": k}]
            record(g.counts_give(a, start[step[1]], b, start[step[2]], k, x), events, ["ownership", "transfer"])
        elif kind == "relative":
            a, b = people[step[1]], people[step[2]]
            k = min(k, start[step[1]] - 1)
            events = [{"type": "has", "holder": b, "item": x["word"], "quantity": start[step[2]]},
                      {"type": "has", "holder": a, "item": x["word"], "quantity": start[step[1]]},
                      {"type": "transfer", "from": a, "to": b, "item": x["word"], "quantity": k}]
            record(g.relative(a, start[step[1]], b, start[step[2]], k, x), events, ["ownership", "transfer"])
        elif kind == "give":
            a, b = people[step[1]], people[step[2]]
            k = min(k, state[a, x["word"]] - 1)
            record(g.give(a, b, k, x), [{"type": "transfer", "from": a, "to": b, "item": x["word"], "quantity": k}],
                   ["transfer"])
        elif kind == "give_two":
            a, b, c = people[step[1]], people[step[2]], people[step[3]]
            k1 = min(k, state[a, x["word"]] - 1)
            k2 = min(ks[(index + 1) % len(ks)], state[b, x["word"]] + k1 - 1)
            record(g.give_two(a, b, k1, c, k2, x),
                   [{"type": "transfer", "from": a, "to": b, "item": x["word"], "quantity": k1},
                    {"type": "transfer", "from": b, "to": c, "item": x["word"], "quantity": k2}], ["transfer"])
        elif kind == "use":
            a = people[step[1]]
            k = min(k, state[a, x["word"]] - 1)
            how = ["use", "lose", "eat"][index % 3] if "식" in x["domain"] else ["use", "lose"][index % 2]
            record(g.use(a, k, x, how), [{"type": "use", "holder": a, "item": x["word"], "quantity": k}],
                   ["transfer"])
        elif kind == "get":
            taker, giver = people[step[1]], people[step[2]]
            k = min(k, state[giver, x["word"]] - 1)
            record(g.get(taker, giver, k, x), [{"type": "transfer", "from": giver, "to": taker, "item": x["word"],
                                               "quantity": k}], ["transfer"])
        elif kind in ("ask", "restart_ask", "follow", "cross_ask", "ask_y"):
            p = people[step[1]]
            item = y if kind == "ask_y" else x
            tags = tags_for(p)
            if kind == "follow":
                say, tags = g.follow(p), tags + ["follow_up"]
                if turns and turns[-1]["expect"]["act"] == "clarify":
                    tags.append("ambiguous_referent")
            elif kind == "cross_ask":
                if lang == "ko":
                    say = "How many does %s have now?" % romanized(p)
                else:
                    say = "%s 지금 몇 개 있어?" % (p + ("는" if p[-1].lower() in "aeiouy" else "은"))
                tags = tags + ["cross_language"]
            else:
                # A holder of two items is never asked without naming the item:
                # that question would be ambiguous, not answerable.
                two = len({i for (h, i) in state if h == p}) > 1
                form = ("exist" if lang == "ko" else "have") if (kind == "ask_y" or (
                    two and dims["question_form"] == "short")) else None
                say = g.ask(p, item, form)
            turn = answer_turn(say, p, item, tags)
            if kind == "restart_ask":
                turn["restart_before"] = True
                turn["tags"] = sorted(set(turn["tags"]) | {"restart"})
            if kind == "cross_ask":
                turn["lang"] = "en" if lang == "ko" else "ko"
        elif kind == "total":
            a, b = people[step[1]], people[step[2]]
            turns.append({"n": len(turns) + 1, "say": g.total(a, b, x), "label": "answerable", "tags": ["transfer"],
                          "expect": {"act": "answer", "entity": [a, b],
                                     "quantity": state[a, x["word"]] + state[b, x["word"]], "relation": "total",
                                     "evidence": {"turns": sorted(set(evidence(a) + evidence(b)))},
                                     "item": x["word"]}})
        elif kind == "more":
            a, b = people[step[1]], people[step[2]]
            if state[a, x["word"]] == state[b, x["word"]]:
                return None
            winner = a if state[a, x["word"]] > state[b, x["word"]] else b
            turns.append({"n": len(turns) + 1, "say": g.more(a, b, x), "label": "answerable", "tags": ["transfer"],
                          "expect": {"act": "answer", "entity": winner, "quantity": None, "relation": "more",
                                     "candidates": [a, b], "item": x["word"],
                                     "evidence": {"turns": sorted(set(evidence(a) + evidence(b)))}}})
        elif kind == "why":
            p = people[step[1]]
            turns.append({"n": len(turns) + 1, "say": g.why(p, x), "label": "why", "tags": ["why"],
                          "expect": {"act": "explain", "entity": p, "quantity": state[p, x["word"]],
                                     "relation": "count", "evidence": {"turns": evidence(p)}, "item": x["word"]}})
        elif kind == "pronoun":
            a, b = people[step[1]], people[step[2]]
            turns.append({"n": len(turns) + 1, "say": g.pronoun(x), "label": "ambiguous",
                          "tags": ["ambiguous_referent"],
                          "expect": {"act": "clarify", "entity": None, "quantity": None, "relation": None,
                                     "evidence": {"turns": [len(turns) + 1]}, "candidates": [a, b]}})
        elif kind == "missing":
            p = people[step[1]]
            turns.append({"n": len(turns) + 1, "say": g.ask(p, x), "label": "hold", "tags": ["missing_premise"],
                          "expect": {"act": "hold", "entity": p, "quantity": None, "relation": "count",
                                     "evidence": {"turns": [len(turns) + 1]}, "item": x["word"]}})
        elif kind == "location":
            p = people[step[1]]
            turns.append({"n": len(turns) + 1, "say": g.location(p, x), "label": "hold",
                          "tags": ["missing_premise"],
                          "expect": {"act": "hold", "entity": p, "quantity": None, "relation": "location",
                                     "evidence": {"turns": [len(turns) + 1]}, "item": x["word"]}})
        elif kind == "decline":
            p = people[step[1]]
            turns.append({"n": len(turns) + 1, "say": g.decline(p, rng.randint(0, 2)), "label": "unsupported",
                          "tags": [], "expect": {"act": "decline", "entity": None, "quantity": None,
                                                 "relation": None, "evidence": {"turns": [len(turns) + 1]}}})
        elif kind == "correct":
            target = max(t for t, evs in by_turn.items() if len(evs) == 1 and evs[0]["type"] == "transfer")
            old_event = by_turn[target][0]
            old = old_event["quantity"]
            giver_before = state[old_event["from"], x["word"]] + old
            choices = [q for q in range(1, giver_before) if q != old]
            if not choices:
                return None
            new = rng.choice(choices)
            state[old_event["from"], x["word"]] += old - new
            state[old_event["to"], x["word"]] -= old - new
            new_event = dict(old_event, quantity=new)
            by_turn[target] = [new_event]
            correction.update(target=target, old=old, new=new, event=old_event)
            n = len(turns) + 1
            for key in ("from", "to"):
                touched.setdefault(old_event[key], []).append(n)
            turns.append({"n": n, "say": g.correct(step[1], old, new, x, old_event), "label": "correction",
                          "tags": ["correction"],
                          "expect": {"act": "revise", "entity": None, "quantity": None, "relation": None,
                                     "evidence": {"turns": [target, n]}, "target_turn": target,
                                     "replaces": [old_event], "with": [new_event],
                                     "state": [{"entity": old_event["from"], "item": x["word"],
                                                "quantity": state[old_event["from"], x["word"]]},
                                               {"entity": old_event["to"], "item": x["word"],
                                                "quantity": state[old_event["to"], x["word"]]}]}})
        else:
            raise ValueError(kind)
    # A count answer equal to another holder's count cannot be told apart.
    for t in turns:
        e = t["expect"]
        if e["act"] == "answer" and e["relation"] == "count":
            if any(v == e["quantity"] for (h, i), v in _state_at(turns, t["n"]).items()
                   if i == e["item"] and h != e["entity"]):
                return None
    multi = sum(len(t["expect"]["events"]) > 1 for t in turns if t["expect"]["act"] == "record")
    variation = {"word_order": dims["word_order"], "register": dims["register"],
                 "split": "multi_fact" if len(turns[0]["expect"].get("events") or []) > 1 else "one_fact_per_turn",
                 "correction_position": next((("early" if s[1] in ("contrast", "restate") else "late")
                                              for s in plan if s[0] == "correct"), "none"),
                 "roles": "receiver_subject" if dims["word_order"] == "receiver_subject" else "giver_first_mentioned",
                 "initial_values": {people[c]: start[c] for c in "ABC" if people[c] in touched},
                 "plan": plan_name, "multi_clause_statements": multi}
    variation.update({key: dims[key] for key in DIMENSIONS[lang] if key not in variation})
    return {"schema": SCHEMA, "id": did, "language": lang, "domain": x["domain"].split(" > ")[-1],
            "categories": sorted({tag for t in turns for tag in t["tags"]}), "variation": variation, "turns": turns}


def _state_at(turns, upto):
    """State after the turns before ``upto``, corrections applied (as the scorer replays it)."""
    replaced = {t["expect"]["target_turn"]: t["expect"]["with"] for t in turns[:upto]
                if t["expect"]["act"] == "revise"}
    state = {}
    for t in turns[:upto]:
        if t["expect"]["act"] == "record":
            for ev in replaced.get(t["n"], t["expect"]["events"]):
                if ev["type"] == "has":
                    state[ev["holder"], ev["item"]] = ev["quantity"]
                elif ev["type"] == "use":
                    state[ev["holder"], ev["item"]] -= ev["quantity"]
                else:
                    state[ev["from"], ev["item"]] -= ev["quantity"]
                    state[ev["to"], ev["item"]] = state.get((ev["to"], ev["item"]), 0) + ev["quantity"]
    return state


def dimension_table(lang, half):
    table = [{} for _ in range(PER_HALF)]
    for key, values in DIMENSIONS[lang].items():
        column = (values * (PER_HALF // len(values) + 1))[:PER_HALF]
        random.Random("%d/%s/%s/%s" % (SEED, lang, half, key)).shuffle(column)
        for row, value in zip(table, column):
            row[key] = value
    return table


def generate():
    vocab = vocabulary()
    dialogues, split = [], {"build": [], "check": []}
    for half, plans in (("build", BUILD_PLANS), ("check", CHECK_PLANS)):
        rng = random.Random("%d/%s" % (SEED, half))
        names = list(plans)
        for lang in ("ko", "en"):
            table = dimension_table(lang, half)
            for index in range(PER_HALF):
                plan_name = names[index % len(names)]
                did = "dev3_%s_%s_%02d" % (lang, half[0], index + 1)
                dialogue = None
                while dialogue is None:
                    dialogue = build_dialogue(lang, did, plan_name, plans[plan_name], table[index],
                                              vocab[half][lang], rng)
                dialogues.append(dialogue)
                split[half].append(did)
    return dialogues, split


def main():
    dialogues, split = generate()
    for path in HERE.glob("dev3_*.json"):
        path.unlink()
    for d in dialogues:
        (HERE / (d["id"] + ".json")).write_text(json.dumps(d, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    lines = ["seed %d" % SEED, "build " + " ".join(split["build"]), "check " + " ".join(split["check"])]
    (HERE / "split.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    records = [t for d in dialogues for t in d["turns"] if t["expect"]["act"] == "record"]
    multi = sum(len(t["expect"]["events"]) > 1 for t in records)
    opening = sum(len(d["turns"][0]["expect"].get("events") or []) > 1 for d in dialogues)
    print("dialogues %d (build %d, check %d)  statements %d, multi-fact %d  open with 2-3 facts %d" % (
        len(dialogues), len(split["build"]), len(split["check"]), len(records), multi, opening))


if __name__ == "__main__":
    main()
