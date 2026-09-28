# Writing the dialogues of development set v6

You receive scenario files (`scenarios_build_<language>.jsonl`, `scenarios_check_<language>.jsonl`, language `en` or `ko`) and this file. Nothing else is needed.
Each line of a scenario file is one short dialogue that a person types to an assistant, one message per turn. Only the person's messages are written; the assistant's replies are not.
Your task is to write every turn of every scenario as one natural message.

## The rules

1. Every message is natural everyday language, the way a person would type it to an assistant in that language.
2. A message says exactly what its scenario turn says, and nothing more: no other person, thing, place or number, no greeting, no comment, no story around it.
3. Never copy the wording of a scenario record or of the examples in this file. The examples show a shape with placeholders in parentheses; write your own sentence in that shape.
4. Use the names exactly as the turn's `refer` gives them (a person may be called by the given name, a title and surname, a relation, a job word; keep every word of it the first time, `first` lists who is mentioned for the first time). Name every holder the turn refers to, even when the turn before named them too: no he, she or they in place of a name. Do not add any name, relation or job word the turn does not have. A turn whose `refer` is empty names no holder at all.
5. A count is written as the turn's `count_as` says: `word` means in words (English number words; Korean native numerals with a counter, e.g. 세 개, 스물네 권), `digits` means in digits (e.g. 7, 12개). Write English compound numbers with a hyphen (twenty-four). Never write any number the turn does not have, and never an amount word such as a dozen, a couple, a few, several, a pair, half.
6. Korean messages follow the scenario's `register`: `haeyo` (every message ends in -요), `hapsyo` (-ㅂ니다, -ㅂ니까), `banmal` (plain speech, no -요), `haera` (written plain style: -다, -는가, -나?). English messages follow `casual`, `neutral` or `formal`.
7. A question ends with a question mark and is one sentence, except where a form below asks for two. A statement never ends with a question mark.
8. No quotation marks, parentheses, brackets, line breaks or three dots inside a message. No Latin letters in a Korean message and no Hangul in an English message, except inside a name the turn gives.
9. A turn with `ask_in` is written in that other language (a question in English inside a Korean dialogue, or in Korean inside an English one). Keep the holder's name as written.
10. Write the build files and the check files in two separate sessions, and give each session its own `session` value.

## What a scenario record means

- `id`: the scenario id; copy it into your output. `language`: `en` or `ko`. `register`: see rule 6.
- `holders`: the people and places of the dialogue. `kind` is `name`, `title` (a title and surname, or in Korean a surname and job title), `relation` (introduced by a relation, sometimes to another holder, `anchor`), `apposition` (introduced with a job word), `first_person` (the person typing: I, me, my; 저, 나, 제가) or `place`. `tokens` are the words that name them.
- `things`: the things counted. English: `plural` and `one`; Korean: `noun` and `counter` (the counter word used with a native numeral). A thing with `unit` is counted in bundles.
- `turns`: the messages in order. Each has `n` (its number), `act`, the facts of the act, `refer` (how to call each holder in this message), `first`, `forms` (the shape the message must take, listed below) and `classes` (for information).

The acts:

- `has`: the holder has `count` of the `thing`. A `count` of null means the amount is not said at all (say they have some, with no number).
- `give`: the `giver` gives `count` of the `thing` to the `receiver` with the verb `verb` (see the verbs below). When the receiver is a place, the giver left or entrusted the things there.
- `use`: the holder used up `count` of the `thing` for the `purpose`.
- `ask`: ask how many of the `thing` the holder has now.
- `ask_total`: ask how many of the `thing` the two `holders` have together.
- `ask_more`: ask which of the two `holders` has more of the `thing`.
- `switch`: the question of the turn before, asked again about a new holder, place or thing, by an ellipsis only (only what changed is said).
- `repair`: the person meant the holder `holder`, not `asked`, the one the turn before asked about.
- `why`: ask why the holder has `count` of the `thing` now (the forms say whether the holder and the number are said).

Other fields: `occasion` (the event a holder is responsible for), `vehicle` (what the things are loaded on), `purpose` (what used things went into), `after` and `hold` (for the checker; ignore them).

The verbs of `give`:

- ko: `give` 주다 (줬다, 드렸다); `give_formal` 주었다 (주었어요, 주었습니다); `share_out` 나눠 주다; `lend` 빌려주다; `send` 보내다; `entrust` 맡기다 (장소에)
- en: `give` gave; `send` sent; `pass` passed; `lend` lent; `transfer` transferred; `give_back` returned (or gave ... back); `hand_over` handed ... over; `leave_at` left ... at

## The forms

A turn's `forms` say the shape of its message. The description is for the turn's language.

- `fragment` (ko): 먼저 수량 없이 말하고, 바로 뒤에 수량만 짧은 조각으로 덧붙인다 (한 메시지 안에서): (누구)한테 (물건)이 있어. (N) (단위)야. / (누구)가 (누구)한테 (물건)을 줬어. (N) (단위).
- `fragment` (en): Say the fact without the number first, then give the number alone in a short fragment after it, in the same message: (holder) has some (things). (N), to be exact. / (giver) gave (receiver) some (things). (N) of them.
- `title_ege_omit` (ko): 직함이 붙은 사람을 '-에게는'(또는 '-한테는', '-께는')으로 말하고 물건 이름은 생략한다 (바로 앞 턴의 물건이다): (성) (직함)에게는 (N) (단위)가 있습니다.
- `job_apposition` (ko): 직업 이름을 이름 바로 앞에 붙여 소개한다: (직업) (이름) 씨는 ...
- `job_apposition` (en): Introduce the holder with the job word first, then the name: (job), (title) (surname), ...
- `relation_also_vague` (ko): 이미 나온 사람과의 관계로 소개하고 '도'를 붙여, 수량 없이 그 물건을 가지고 있다고만 말한다: (기준 인물) (관계) (이름)도 (물건)을 가지고 있어요.
- `relation_also_vague` (en): Introduce the holder by a relation to someone already named, say they also have some of the thing, with no number: (anchor)'s (relation), (name), also has some (things).
- `responsible_front` (en): Start with the occasion, then say what the holder is responsible for: For (occasion), (holder) is responsible for (N) (things).
- `place_receiver` (ko): 받는 쪽이 장소다: 그 장소에 맡겼다/두고 왔다 ((장소)에 (N) (단위)를 맡겼습니다).
- `place_receiver` (en): The receiver is a place: the giver left the things at the place (left N (things) at the (place)).
- `carry_load` (ko): '싣고 있다'로 말한다: (누구)는 (탈것)에 (물건)을 (N) (단위) 싣고 있어요.
- `double_object` (en): Double object, no 'to': (giver) (verb) (receiver) (N) (things).
- `particle_verb` (en): Split particle verb: the things between the verb and its particle, then 'to' and the receiver: (giver) handed (N) (things) over to (receiver) / gave (N) (things) back to (receiver) / passed (N) (things) on to (receiver).
- `partitive` (ko): 물건 이름 대신 '그중'으로 가리킨다: 그중 하나, 그중 (N) (단위) (그중 두 개를 ...에게 줬어요, 그중 세 개로 ...을 만들었어요).
- `partitive` (en): Refer to the things with a partitive pronoun instead of naming them: one of them, (N) of them (gave two of them to ..., used three of them for ...).
- `omit_subject` (ko): 앞 턴과 주는 사람이 같으니 주어를 말하지 않고 이어서 말한다: 그리고 (받는 사람)에게 (N) (단위)를 주었다.
- `q_plain` (ko): 몇 개 가지고 있는지 묻는 보통 질문.
- `q_plain` (en): An ordinary question of how many the holder has.
- `q_left` (ko): 남은 수를 묻는다: (누구)에게 남은 (물건)은 몇 (단위)인가 / (물건) 몇 개 남았어.
- `q_left` (en): Ask what is left or remains: how many does (holder) have left / are left with (holder) / remain with (holder).
- `q_now` (ko): 시간 부사를 넣어 묻는다: 이제, 지금 ((누구)는 이제 몇 개야?).
- `q_now` (en): Ask with a time adverb: at the moment, now.
- `q_got` (en): Ask with 'has ... got': How many (things) has (holder) got?
- `q_responsible` (ko): '맡고 있다'로 묻는다: (누구)는 (물건)을 몇 (단위) 맡고 있습니까?
- `q_responsible` (en): Ask with 'responsible for': How many (things) is (holder) responsible for?
- `q_bundles` (ko): 단위로 묻는다: (누구)는 (물건)이 몇 묶음입니까
- `q_bundles` (en): Ask by the unit: How many bundles does (holder) have?
- `q_all` (ko): '모두'로 묻는다: (누구)의 (물건)은 모두 몇 (단위)입니까?
- `q_all` (en): Ask for the holder's count in all: How many (things) does (holder) have in all?
- `q_combined` (ko): 두 사람을 이름으로 말하고 합한 수를 묻는다: 합쳐서 / 모두.
- `q_combined` (en): Ask for the two holders' count together, naming both: combined / in total.
- `q_two_total` (ko): 이름 없이 두 사람이 합쳐 몇 개인지 묻는다: 둘이 합쳐서 몇 개예요?
- `q_two_total` (en): Ask for the two holders' count together without their names: the two of them in total.
- `q_more` (ko): 이름이 나온 두 사람 중 누가 더 많은지 묻는다: 둘 중에 누가 더 많이 가지고 있어요?
- `q_more` (en): Ask which of the two named holders has more.
- `switch_holder` (ko): 앞 질문을 새 사람에 대해 생략형으로만: (누구)는요? / (누구)는?
- `switch_holder` (en): Only the new holder, as an ellipsis of the question before: What about (holder)? / And (holder)?
- `switch_place` (ko): 앞 질문을 새 장소에 대해 생략형으로만: (장소)는요? / (장소)는 어떻습니까?
- `switch_place` (en): Only the new place, as an ellipsis of the question before: And in the (place)? / What about the (place)?
- `switch_thing` (ko): 앞 질문을 같은 사람의 다른 물건에 대해 생략형으로만: (물건)은요? / (물건)은?
- `switch_thing` (en): Only the new thing, as an ellipsis of the question before (same holder): And (things)?
- `repair_question` (ko): 뜻한 사람을 밝히고 같은 메시지에서 다시 묻는다: (누구) 말입니다. (누구)는 몇 묶음입니까 / (누구)요. (누구)는 몇 개예요?
- `repair_question` (en): Say which holder you meant and ask again in the same message: I mean (holder). How many does (holder) have? / It's (holder). How many does (holder) hold?
- `repair_bare` (ko): 뜻한 사람의 이름만, 질문 없이: (누구)요. / (누구) 님입니다.
- `repair_bare` (en): Only the name of the holder you meant, no question: (holder), I mean. / (holder) is the one I mean.
- `why_has` (ko): 사람과 수를 넣어 왜냐고 묻는다: 왜 (누구)가 (N) (단위)야?
- `why_has` (en): Why, naming the holder and the number: Why does (holder) have (N)?
- `why_end_up` (ko): '되다'로 묻는다: (누구) (물건)이 왜 (N) (단위)가 되었습니까?
- `why_end_up` (en): Why, with 'end up': Why does (holder) end up with (N)?
- `why_reason` (ko): 까닭이나 이유를 묻는다: (누구)의 (물건)이 (N) (단위)가 된 까닭은 무엇인가?
- `why_reason` (en): Ask for the reason, naming the holder and the number: What is the reason (holder) has (N)?
- `why_that_number` (ko): 사람 없이 수만 넣어: 왜 (N) (단위)예요?
- `why_that_number` (en): Why, with the number only (no holder): Why is that number (N)?
- `why_how` (ko): 방금 답이 어떻게 그렇게 되었는지 묻는다. 사람도 수도 넣지 않는다.
- `why_how` (en): Ask how the last answer came about, with no holder and no number.
- `why_only_me` (ko): 말하는 사람 자신의 수를 '밖에'나 '만'으로: 왜 저는 (N) (단위)밖에 없어요?
- `why_only_me` (en): The speaker asks about their own count with 'only': Why do I only have (N)?

## The classes

Each turn is tagged with the classes it belongs to. These are the classes, as the goal of this set describes them; X, Y, N, R, THING and PLACE stand for the scenario's holders, things, numbers and places.

- **1_count_words**: Counts as words, not digits. English number words in transfer and ownership statements ("one" to "twenty-four", "some ... seven, to be exact"); Korean native numerals with counters (한·두·세·네·여섯·스무 + 개·권·장·묶음·자루) in transfer statements.
- **2_en_transfer_forms**: English double-object transfer ("gave RECIPIENT N THINGS", no "to") and split particle verbs ("handed N THINGS over to R"), plus "transferred", "returned", "sent", "passed", "left N at PLACE".
- **3_partitive**: Partitive pronoun objects in transfers and use-ups: "one of them", "N of them", 그중 하나, 그중 N개, "used three of them for ...", 그중 N개로 만들었다.
- **4_fragment_count**: A count given in a following fragment: "X has some Y. N, to be exact." / "X한테 Y이 있어. 일곱 개야." / "X가 Y한테 Z를 줬어. 세 개."
- **5_ko_transfer_verbs**: Korean transfer verbs and compounds: 나눠 주다, 빌려주다, 보내다, 맡기다 (leave at a place), 싣고 있다 (carry), 주었다 (plain past formal), and the subject omitted in a second sentence ("그리고 R에게 N개를 주었다").
- **6_holder_forms**: Holder forms: a title after a name with 에게는 and the thing omitted ("X 과장에게는 두 개가 있습니다"); a job-title apposition before a name ("택배 기사 X 씨는"); a relational noun with 도 and a vague count ("X 친구 Y도 Y을 가지고 있어요"); "For the event, X is responsible for N" (fronting + responsible-for + number word); a place as recipient ("left N at the shop" / "편의점에 맡겼습니다").
- **7_leftover_questions**: Leftover and remaining forms: "does X have left", "are left with X", "left for X", "remain with X", "X에게 남은 Y은 몇 개인가", "Y 몇 개 남았어", "X 님께 남은 Y은 몇 권입니까".
- **8_time_adverb_questions**: Aspect and time adverbs in questions: "at the moment", "now", 이제, 지금 ("X는 이제 몇 개야?", "그럼 X는 지금 몇 개예요?").
- **9_other_predicates**: Other question predicates: "has X got", "is X responsible for", "맡고 있습니까", "How many bundles" / "몇 묶음", "모두 몇 개입니까", "combined" / "the two of them in total", "둘 중에 누가 더 (many/few)" asked of two named holders.
- **10_topic_switch**: Topic-switch ellipsis: "What about X?", "And X?", "And in PLACE?", "And THING?", "X는요?", "X는?", "THING은?", "PLACE는 어떻습니까?" (the question of the previous turn asked again about a new holder, place or thing).
- **11_repair_with_question**: Referent repair with the question in the same turn: "I mean X. How many does X hold?", "It's X. How many does X have?", "X 말입니다. X는 몇 묶음입니까", "X요. X는 몇 개예요?"; and bare-name repairs as a turn ("X요.", "X 님입니다.", "X, I mean.", "X is the one I mean.") followed by the question next turn.
- **12_cross_language**: Cross-language turns: a question in the other language inside a dialogue.
- **13_why_with_fact**: Why questions that restate the fact: "Why does X have N?", "Why does X end up with N?", "What is the reason X has N?", "Why is that number N?", a why about how the last answer came about, with no holder or number, "Why do I only have N?", "왜 X가 N개야?", "왜 N개예요?", "X의 Y이 N개가 된 까닭은 무엇인가?", the same in Korean, "X Y가 왜 N개가 되었습니까?".
- **15_unstated_receiver**: A transfer to a holder whose starting count is never stated: the giver's count can be answered, the receiver's cannot (it is asked, and the true answer is that it is not known).

## The output

One JSON object per line (JSON Lines, UTF-8), one line per scenario, in a file per session:

```
{"scenario": "<id>", "language": "<en|ko>", "turns": [{"n": 1, "text": "<message>"}, {"n": 2, "text": "<message>"}], "source": "<the writer's name>", "date": "<YYYY-MM-DD>", "session": "<a name for this session>"}
```

Write every turn of the scenario, in order, with its `n`. `source` names who wrote the messages; `date` is the day they were written.
Messages are checked by a program against the scenario: a message that misses a number, a holder, the thing or the form, or adds anything, is dropped, and so is every later turn when the dropped message was a statement.
