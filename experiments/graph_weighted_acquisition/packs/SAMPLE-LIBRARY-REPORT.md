# Answer: 21일 (not independently verified)

## Answer as a sentence

> 어린이회원의 대출기간은 21일입니다.

Each sentence was built from pieces seen in the lessons and then read back by the reader, which had to arrive at the same meaning. How the first one was built:

| Piece | Why it was chosen |
|---|---|
| 대출기간 | the head word for this meaning in a sentence that states |
| subject HEAD amount | the order such sentences were written in |
| 의 | after "어린이회원": follows a subject (112); marks the subject (112); follows a word ending in this sound (8); is followed by a relation (112) |
| 은 | after "대출기간": follows a relation (42); follows a word ending in this sound (14); is followed by a subject (24); comes before the amount (42) |
| 입니다. | after "21일": follows a subject (24); marks the amount (24); follows a word ending in this sound (8) |

Names matched through the word pack:

- "꼬마회원" is another name for "어린이회원" (word pack)

## Sources

- L02: 대출기간 of 어린이회원 is 21일. Source: made-up example, no real source (as of 2026-11-19). Scope: regular loans

Question: `꼬마회원의 대출기간은 얼마인가?`

Passage: `일반회원의 대출기간은 14일입니다. 어린이회원의 대출기간은 21일입니다. 일반회원의 대출권수는 5권입니다. 어린이회원의 대출권수는 10권입니다. 일반회원의 연체료는 하루100원입니다. 중앙도서관의 운영시간은 9시~22시입니다. 별관의 운영시간은 10시~18시입니다. 중앙도서관의 휴관일은 매주월요일입니다. 중앙도서관의 문의전화는 555이다. 별관의 반납장소는 무인반납함이다.`

## Why this answer

The question was turned into a small graph with one unknown. The passage graph was searched for a place where every condition of the question holds. The unknown there is the answer.

Ground 1 for the answer 21일, each condition and the passage text that satisfies it:

| Condition in the question | Passage text |
|---|---|
| subject = "꼬마회원" | "어린이회원" + "대출기간" |
| amount = the thing asked for | "대출기간" + "21일" |
| kind = "대출기간" | "대출기간" |
| a name given in the question: "꼬마회원" | "어린이회원" |
| the name of what was asked for | "21일" |

**Not independently verified.** The older executor could not check this answer: names were matched loosely or through another name, which the older executor cannot do.

## How the passage was read

Text: `일반회원의 대출기간은 14일입니다. 어린이회원의 대출기간은 21일입니다. 일반회원의 대출권수는 5권입니다. 어린이회원의 대출권수는 10권입니다. 일반회원의 연체료는 하루100원입니다. 중앙도서관의 운영시간은 9시~22시입니다. 별관의 운영시간은 10시~18시입니다. 중앙도서관의 휴관일은 매주월요일입니다. 중앙도서관의 문의전화는 555이다. 별관의 반납장소는 무인반납함이다.`

Status: **complete** (read as 10 sentences, each with every piece seen in training and a clear lead).

Pieces: [일반회원|name] [의 |connector] [대출기간|fixed word] [은 |connector] [14일|name] [입니다.|connector] [ |connector] [어린이회원|name] [의 |connector] [대출기간|fixed word] [은 |connector] [21일|name] [입니다.|connector] [ |connector] [일반회원|name] [의 |connector] [대출권수|fixed word] [는 |connector] [5권|name] [입니다.|connector] [ |connector] [어린이회원|name] [의 |connector] [대출권수|fixed word] [는 |connector] [10권|name] [입니다.|connector] [ |connector] [일반회원|name] [의 |connector] [연체료|fixed word] [는 |connector] [하루100원|name] [입니다.|connector] [ |connector] [중앙도서관|name] [의 |connector] [운영시간|fixed word] [은 |connector] [9시~22시|name] [입니다.|connector] [ |connector] [별관|name] [의 |connector] [운영시간|fixed word] [은 |connector] [10시~18시|name] [입니다.|connector] [ |connector] [중앙도서관|name] [의 |connector] [휴관일|fixed word] [은 |connector] [매주월요일|name] [입니다.|connector] [ |connector] [중앙도서관|name] [의 |connector] [문의전화|fixed word] [는 |connector] [555|name] [이다.|connector] [ |connector] [별관|name] [의 |connector] [반납장소|fixed word] [는 |connector] [무인반납함|name] [이다.|connector]

What it means:
- relation "대출기간": subject = "일반회원", amount = "14일", kind = "대출기간"
- relation "대출기간": subject = "어린이회원", amount = "21일", kind = "대출기간"
- relation "대출권수": subject = "일반회원", amount = "5권", kind = "대출권수"
- relation "대출권수": subject = "어린이회원", amount = "10권", kind = "대출권수"
- relation "연체료": subject = "일반회원", amount = "하루100원", kind = "연체료"
- relation "운영시간": subject = "중앙도서관", amount = "9시~22시", kind = "운영시간"
- relation "운영시간": subject = "별관", amount = "10시~18시", kind = "운영시간"
- relation "휴관일": subject = "중앙도서관", amount = "매주월요일", kind = "휴관일"
- relation "문의전화": subject = "중앙도서관", amount = "555", kind = "문의전화"
- relation "반납장소": subject = "별관", amount = "무인반납함", kind = "반납장소"

Why each piece was read this way:

| Piece | Decision about | Chosen | Given | Seen in training | Example ids |
|---|---|---|---|---|---|
| 일반회원 | kind of a free value | subject | '의 ' | 112 of 112 | lang-000-s, lang-000-q, lang-001-s |
| 일반회원 | length of a free value | 4 characters | 'longest seen in training: 12' | 23 of 176 | lang-010-s, lang-015-c, lang-018-s |
| 대출기간 | meaning of a fixed word | relation, kind=대출기간 | '대출기간' | 14 of 14 | word pack: 대출기간 |
| 14일 | kind of a free value | amount | '입니다.' | 24 of 24 | lang-001-s, lang-003-s, lang-005-s |
| 14일 | length of a free value | 3 characters | 'longest seen in training: 12' | 81 of 176 | lang-000-s, lang-000-q, lang-001-s |
| 일반회원 | which head | head '대출기간' (offset 0) | '*' | 112 of 240 | lang-000-s, lang-000-q, lang-001-s |
| 일반회원 | role from the piece after it | subject | '의 ' | 112 of 112 | lang-000-s, lang-000-q, lang-001-s |
| 일반회원 | role from the piece before it | subject | '' | 112 of 112 | lang-000-s, lang-000-q, lang-001-s |
| 14일 | which head | head '대출기간' (offset -1) | '*' | 128 of 240 | lang-000-s, lang-000-q, lang-001-s |
| 14일 | role from the piece after it | amount | '입니다.' | 24 of 24 | lang-001-s, lang-003-s, lang-005-s |
| 14일 | role from the piece before it | amount | '은 ' | 42 of 42 | lang-000-s, lang-000-q, lang-001-s |
| 대출기간 | set of roles for this head | amount + subject | relation, kind=대출기간 | 96 of 112 | word pack: 대출기간 |
| 입니다. | what a sentence closed this way does | states | '입니다.' | 24 of 24 | lang-001-s, lang-003-s, lang-005-s |
| 대출기간 | what a sentence with this word does | states | '대출기간' | 48 of 112 | word pack: 대출기간 |
| 어린이회원 | kind of a free value | subject | '의 ' | 112 of 112 | lang-000-s, lang-000-q, lang-001-s |
| 어린이회원 | length of a free value | 5 characters | 'longest seen in training: 12' | 12 of 176 | lang-006-c, lang-032-s, lang-034-s |
| 대출기간 | meaning of a fixed word | relation, kind=대출기간 | '대출기간' | 14 of 14 | word pack: 대출기간 |
| 21일 | kind of a free value | amount | '입니다.' | 24 of 24 | lang-001-s, lang-003-s, lang-005-s |
| 21일 | length of a free value | 3 characters | 'longest seen in training: 12' | 81 of 176 | lang-000-s, lang-000-q, lang-001-s |
| 어린이회원 | which head | head '대출기간' (offset 0) | '*' | 112 of 240 | lang-000-s, lang-000-q, lang-001-s |
| 어린이회원 | role from the piece after it | subject | '의 ' | 112 of 112 | lang-000-s, lang-000-q, lang-001-s |
| 어린이회원 | role from the piece before it | subject | '' | 112 of 112 | lang-000-s, lang-000-q, lang-001-s |
| 21일 | which head | head '대출기간' (offset -1) | '*' | 128 of 240 | lang-000-s, lang-000-q, lang-001-s |
| 21일 | role from the piece after it | amount | '입니다.' | 24 of 24 | lang-001-s, lang-003-s, lang-005-s |
| 21일 | role from the piece before it | amount | '은 ' | 42 of 42 | lang-000-s, lang-000-q, lang-001-s |
| 대출기간 | set of roles for this head | amount + subject | relation, kind=대출기간 | 96 of 112 | word pack: 대출기간 |
| 입니다. | what a sentence closed this way does | states | '입니다.' | 24 of 24 | lang-001-s, lang-003-s, lang-005-s |
| 대출기간 | what a sentence with this word does | states | '대출기간' | 48 of 112 | word pack: 대출기간 |
| 일반회원 | kind of a free value | subject | '의 ' | 112 of 112 | lang-000-s, lang-000-q, lang-001-s |
| 일반회원 | length of a free value | 4 characters | 'longest seen in training: 12' | 23 of 176 | lang-010-s, lang-015-c, lang-018-s |
| 대출권수 | meaning of a fixed word | relation, kind=대출권수 | '대출권수' | 14 of 14 | word pack: 대출권수 |
| 5권 | kind of a free value | amount | '입니다.' | 24 of 24 | lang-001-s, lang-003-s, lang-005-s |
| 5권 | length of a free value | 2 characters | 'longest seen in training: 12' | 18 of 176 | lang-000-s, lang-001-s, lang-002-s |
| 일반회원 | which head | head '대출권수' (offset 0) | '*' | 112 of 240 | lang-000-s, lang-000-q, lang-001-s |
| 일반회원 | role from the piece after it | subject | '의 ' | 112 of 112 | lang-000-s, lang-000-q, lang-001-s |
| 일반회원 | role from the piece before it | subject | '' | 112 of 112 | lang-000-s, lang-000-q, lang-001-s |
| 5권 | which head | head '대출권수' (offset -1) | '*' | 128 of 240 | lang-000-s, lang-000-q, lang-001-s |
| 5권 | role from the piece after it | amount | '입니다.' | 24 of 24 | lang-001-s, lang-003-s, lang-005-s |
| 5권 | role from the piece before it | amount | '는 ' | 70 of 70 | lang-008-s, lang-008-q, lang-009-s |
| 대출권수 | set of roles for this head | amount + subject | relation, kind=대출권수 | 96 of 112 | word pack: 대출권수 |
| 입니다. | what a sentence closed this way does | states | '입니다.' | 24 of 24 | lang-001-s, lang-003-s, lang-005-s |
| 대출권수 | what a sentence with this word does | states | '대출권수' | 48 of 112 | word pack: 대출권수 |
| 어린이회원 | kind of a free value | subject | '의 ' | 112 of 112 | lang-000-s, lang-000-q, lang-001-s |
| 어린이회원 | length of a free value | 5 characters | 'longest seen in training: 12' | 12 of 176 | lang-006-c, lang-032-s, lang-034-s |
| 대출권수 | meaning of a fixed word | relation, kind=대출권수 | '대출권수' | 14 of 14 | word pack: 대출권수 |
| 10권 | kind of a free value | amount | '입니다.' | 24 of 24 | lang-001-s, lang-003-s, lang-005-s |
| 10권 | length of a free value | 3 characters | 'longest seen in training: 12' | 81 of 176 | lang-000-s, lang-000-q, lang-001-s |
| 어린이회원 | which head | head '대출권수' (offset 0) | '*' | 112 of 240 | lang-000-s, lang-000-q, lang-001-s |
| 어린이회원 | role from the piece after it | subject | '의 ' | 112 of 112 | lang-000-s, lang-000-q, lang-001-s |
| 어린이회원 | role from the piece before it | subject | '' | 112 of 112 | lang-000-s, lang-000-q, lang-001-s |
| 10권 | which head | head '대출권수' (offset -1) | '*' | 128 of 240 | lang-000-s, lang-000-q, lang-001-s |
| 10권 | role from the piece after it | amount | '입니다.' | 24 of 24 | lang-001-s, lang-003-s, lang-005-s |
| 10권 | role from the piece before it | amount | '는 ' | 70 of 70 | lang-008-s, lang-008-q, lang-009-s |
| 대출권수 | set of roles for this head | amount + subject | relation, kind=대출권수 | 96 of 112 | word pack: 대출권수 |
| 입니다. | what a sentence closed this way does | states | '입니다.' | 24 of 24 | lang-001-s, lang-003-s, lang-005-s |
| 대출권수 | what a sentence with this word does | states | '대출권수' | 48 of 112 | word pack: 대출권수 |
| 일반회원 | kind of a free value | subject | '의 ' | 112 of 112 | lang-000-s, lang-000-q, lang-001-s |
| 일반회원 | length of a free value | 4 characters | 'longest seen in training: 12' | 23 of 176 | lang-010-s, lang-015-c, lang-018-s |
| 연체료 | meaning of a fixed word | relation, kind=연체료 | '연체료' | 14 of 14 | word pack: 연체료 |
| 하루100원 | kind of a free value | amount | '입니다.' | 24 of 24 | lang-001-s, lang-003-s, lang-005-s |
| 하루100원 | length of a free value | 6 characters | 'longest seen in training: 12' | 12 of 176 | lang-024-s, lang-024-q, lang-031-c |
| 일반회원 | which head | head '연체료' (offset 0) | '*' | 112 of 240 | lang-000-s, lang-000-q, lang-001-s |
| 일반회원 | role from the piece after it | subject | '의 ' | 112 of 112 | lang-000-s, lang-000-q, lang-001-s |
| 일반회원 | role from the piece before it | subject | '' | 112 of 112 | lang-000-s, lang-000-q, lang-001-s |
| 하루100원 | which head | head '연체료' (offset -1) | '*' | 128 of 240 | lang-000-s, lang-000-q, lang-001-s |
| 하루100원 | role from the piece after it | amount | '입니다.' | 24 of 24 | lang-001-s, lang-003-s, lang-005-s |
| 하루100원 | role from the piece before it | amount | '는 ' | 70 of 70 | lang-008-s, lang-008-q, lang-009-s |
| 연체료 | set of roles for this head | amount + subject | relation, kind=연체료 | 96 of 112 | word pack: 연체료 |
| 입니다. | what a sentence closed this way does | states | '입니다.' | 24 of 24 | lang-001-s, lang-003-s, lang-005-s |
| 연체료 | what a sentence with this word does | states | '연체료' | 48 of 112 | word pack: 연체료 |
| 중앙도서관 | kind of a free value | subject | '의 ' | 112 of 112 | lang-000-s, lang-000-q, lang-001-s |
| 중앙도서관 | length of a free value | 5 characters | 'longest seen in training: 12' | 12 of 176 | lang-006-c, lang-032-s, lang-034-s |
| 운영시간 | meaning of a fixed word | relation, kind=운영시간 | '운영시간' | 14 of 14 | word pack: 운영시간 |
| 9시~22시 | kind of a free value | amount | '입니다.' | 24 of 24 | lang-001-s, lang-003-s, lang-005-s |
| 9시~22시 | length of a free value | 6 characters | 'longest seen in training: 12' | 12 of 176 | lang-024-s, lang-024-q, lang-031-c |
| 중앙도서관 | which head | head '운영시간' (offset 0) | '*' | 112 of 240 | lang-000-s, lang-000-q, lang-001-s |
| 중앙도서관 | role from the piece after it | subject | '의 ' | 112 of 112 | lang-000-s, lang-000-q, lang-001-s |
| 중앙도서관 | role from the piece before it | subject | '' | 112 of 112 | lang-000-s, lang-000-q, lang-001-s |
| 9시~22시 | which head | head '운영시간' (offset -1) | '*' | 128 of 240 | lang-000-s, lang-000-q, lang-001-s |
| 9시~22시 | role from the piece after it | amount | '입니다.' | 24 of 24 | lang-001-s, lang-003-s, lang-005-s |
| 9시~22시 | role from the piece before it | amount | '은 ' | 42 of 42 | lang-000-s, lang-000-q, lang-001-s |
| 운영시간 | set of roles for this head | amount + subject | relation, kind=운영시간 | 96 of 112 | word pack: 운영시간 |
| 입니다. | what a sentence closed this way does | states | '입니다.' | 24 of 24 | lang-001-s, lang-003-s, lang-005-s |
| 운영시간 | what a sentence with this word does | states | '운영시간' | 48 of 112 | word pack: 운영시간 |
| 별관 | kind of a free value | subject | '의 ' | 112 of 112 | lang-000-s, lang-000-q, lang-001-s |
| 별관 | length of a free value | 2 characters | 'longest seen in training: 12' | 18 of 176 | lang-000-s, lang-001-s, lang-002-s |
| 운영시간 | meaning of a fixed word | relation, kind=운영시간 | '운영시간' | 14 of 14 | word pack: 운영시간 |
| 10시~18시 | kind of a free value | amount | '입니다.' | 24 of 24 | lang-001-s, lang-003-s, lang-005-s |
| 10시~18시 | length of a free value | 7 characters | 'longest seen in training: 12' | 20 of 176 | lang-004-s, lang-004-q, lang-013-s |
| 별관 | which head | head '운영시간' (offset 0) | '*' | 112 of 240 | lang-000-s, lang-000-q, lang-001-s |
| 별관 | role from the piece after it | subject | '의 ' | 112 of 112 | lang-000-s, lang-000-q, lang-001-s |
| 별관 | role from the piece before it | subject | '' | 112 of 112 | lang-000-s, lang-000-q, lang-001-s |
| 10시~18시 | which head | head '운영시간' (offset -1) | '*' | 128 of 240 | lang-000-s, lang-000-q, lang-001-s |
| 10시~18시 | role from the piece after it | amount | '입니다.' | 24 of 24 | lang-001-s, lang-003-s, lang-005-s |
| 10시~18시 | role from the piece before it | amount | '은 ' | 42 of 42 | lang-000-s, lang-000-q, lang-001-s |
| 운영시간 | set of roles for this head | amount + subject | relation, kind=운영시간 | 96 of 112 | word pack: 운영시간 |
| 입니다. | what a sentence closed this way does | states | '입니다.' | 24 of 24 | lang-001-s, lang-003-s, lang-005-s |
| 운영시간 | what a sentence with this word does | states | '운영시간' | 48 of 112 | word pack: 운영시간 |
| 중앙도서관 | kind of a free value | subject | '의 ' | 112 of 112 | lang-000-s, lang-000-q, lang-001-s |
| 중앙도서관 | length of a free value | 5 characters | 'longest seen in training: 12' | 12 of 176 | lang-006-c, lang-032-s, lang-034-s |
| 휴관일 | meaning of a fixed word | relation, kind=휴관일 | '휴관일' | 14 of 14 | word pack: 휴관일 |
| 매주월요일 | kind of a free value | amount | '입니다.' | 24 of 24 | lang-001-s, lang-003-s, lang-005-s |
| 매주월요일 | length of a free value | 5 characters | 'longest seen in training: 12' | 12 of 176 | lang-006-c, lang-032-s, lang-034-s |
| 중앙도서관 | which head | head '휴관일' (offset 0) | '*' | 112 of 240 | lang-000-s, lang-000-q, lang-001-s |
| 중앙도서관 | role from the piece after it | subject | '의 ' | 112 of 112 | lang-000-s, lang-000-q, lang-001-s |
| 중앙도서관 | role from the piece before it | subject | '' | 112 of 112 | lang-000-s, lang-000-q, lang-001-s |
| 매주월요일 | which head | head '휴관일' (offset -1) | '*' | 128 of 240 | lang-000-s, lang-000-q, lang-001-s |
| 매주월요일 | role from the piece after it | amount | '입니다.' | 24 of 24 | lang-001-s, lang-003-s, lang-005-s |
| 매주월요일 | role from the piece before it | amount | '은 ' | 42 of 42 | lang-000-s, lang-000-q, lang-001-s |
| 휴관일 | set of roles for this head | amount + subject | relation, kind=휴관일 | 96 of 112 | word pack: 휴관일 |
| 입니다. | what a sentence closed this way does | states | '입니다.' | 24 of 24 | lang-001-s, lang-003-s, lang-005-s |
| 휴관일 | what a sentence with this word does | states | '휴관일' | 48 of 112 | word pack: 휴관일 |
| 중앙도서관 | kind of a free value | subject | '의 ' | 112 of 112 | lang-000-s, lang-000-q, lang-001-s |
| 중앙도서관 | length of a free value | 5 characters | 'longest seen in training: 12' | 12 of 176 | lang-006-c, lang-032-s, lang-034-s |
| 문의전화 | meaning of a fixed word | relation, kind=문의전화 | '문의전화' | 14 of 14 | word pack: 문의전화 |
| 555 | kind of a free value | amount | '이다.' | 24 of 24 | lang-000-s, lang-002-s, lang-004-s |
| 555 | length of a free value | 3 characters | 'longest seen in training: 12' | 81 of 176 | lang-000-s, lang-000-q, lang-001-s |
| 중앙도서관 | which head | head '문의전화' (offset 0) | '*' | 112 of 240 | lang-000-s, lang-000-q, lang-001-s |
| 중앙도서관 | role from the piece after it | subject | '의 ' | 112 of 112 | lang-000-s, lang-000-q, lang-001-s |
| 중앙도서관 | role from the piece before it | subject | '' | 112 of 112 | lang-000-s, lang-000-q, lang-001-s |
| 555 | which head | head '문의전화' (offset -1) | '*' | 128 of 240 | lang-000-s, lang-000-q, lang-001-s |
| 555 | role from the piece after it | amount | '이다.' | 24 of 24 | lang-000-s, lang-002-s, lang-004-s |
| 555 | role from the piece before it | amount | '는 ' | 70 of 70 | lang-008-s, lang-008-q, lang-009-s |
| 문의전화 | set of roles for this head | amount + subject | relation, kind=문의전화 | 96 of 112 | word pack: 문의전화 |
| 이다. | what a sentence closed this way does | states | '이다.' | 24 of 24 | lang-000-s, lang-002-s, lang-004-s |
| 문의전화 | what a sentence with this word does | states | '문의전화' | 48 of 112 | word pack: 문의전화 |
| 별관 | kind of a free value | subject | '의 ' | 112 of 112 | lang-000-s, lang-000-q, lang-001-s |
| 별관 | length of a free value | 2 characters | 'longest seen in training: 12' | 18 of 176 | lang-000-s, lang-001-s, lang-002-s |
| 반납장소 | meaning of a fixed word | relation, kind=반납장소 | '반납장소' | 14 of 14 | word pack: 반납장소 |
| 무인반납함 | kind of a free value | amount | '이다.' | 24 of 24 | lang-000-s, lang-002-s, lang-004-s |
| 무인반납함 | length of a free value | 5 characters | 'longest seen in training: 12' | 12 of 176 | lang-006-c, lang-032-s, lang-034-s |
| 별관 | which head | head '반납장소' (offset 0) | '*' | 112 of 240 | lang-000-s, lang-000-q, lang-001-s |
| 별관 | role from the piece after it | subject | '의 ' | 112 of 112 | lang-000-s, lang-000-q, lang-001-s |
| 별관 | role from the piece before it | subject | '' | 112 of 112 | lang-000-s, lang-000-q, lang-001-s |
| 무인반납함 | which head | head '반납장소' (offset -1) | '*' | 128 of 240 | lang-000-s, lang-000-q, lang-001-s |
| 무인반납함 | role from the piece after it | amount | '이다.' | 24 of 24 | lang-000-s, lang-002-s, lang-004-s |
| 무인반납함 | role from the piece before it | amount | '는 ' | 70 of 70 | lang-008-s, lang-008-q, lang-009-s |
| 반납장소 | set of roles for this head | amount + subject | relation, kind=반납장소 | 96 of 112 | word pack: 반납장소 |
| 이다. | what a sentence closed this way does | states | '이다.' | 24 of 24 | lang-000-s, lang-002-s, lang-004-s |
| 반납장소 | what a sentence with this word does | states | '반납장소' | 48 of 112 | word pack: 반납장소 |

110 routine sequence checks also passed (each connector and what follows it was seen before).

Score -105.92, every piece seen in training: yes.
No other reading has every piece seen in training, so there is no lead to report.

## How the question was read

Text: `꼬마회원의 대출기간은 얼마인가?`

Status: **complete** (the only reading whose every piece was seen in training).

Pieces: [꼬마회원|name] [의 |connector] [대출기간|fixed word] [은 |connector] [얼마|fixed word] [인가?|connector]

What it means:
- relation "대출기간": subject = "꼬마회원", amount = the thing asked for, kind = "대출기간"

Asked for: the amount of that event.

Why each piece was read this way:

| Piece | Decision about | Chosen | Given | Seen in training | Example ids |
|---|---|---|---|---|---|
| 꼬마회원 | kind of a free value | subject | '의 ' | 112 of 112 | lang-000-s, lang-000-q, lang-001-s |
| 꼬마회원 | length of a free value | 4 characters | 'longest seen in training: 12' | 23 of 176 | lang-010-s, lang-015-c, lang-018-s |
| 대출기간 | meaning of a fixed word | relation, kind=대출기간 | '대출기간' | 14 of 14 | word pack: 대출기간 |
| 얼마 | meaning of a fixed word | amount, asked for | '얼마' | 9 of 9 | lang-008-q, lang-010-q, lang-012-q |
| 꼬마회원 | which head | head '대출기간' (offset 0) | '*' | 112 of 240 | lang-000-s, lang-000-q, lang-001-s |
| 꼬마회원 | role from the piece after it | subject | '의 ' | 112 of 112 | lang-000-s, lang-000-q, lang-001-s |
| 꼬마회원 | role from the piece before it | subject | '' | 112 of 112 | lang-000-s, lang-000-q, lang-001-s |
| 얼마 | which head | head '대출기간' (offset -1) | '*' | 128 of 240 | lang-000-s, lang-000-q, lang-001-s |
| 얼마 | role of this fixed word | amount | '얼마' | 9 of 9 | lang-008-q, lang-010-q, lang-012-q |
| 대출기간 | set of roles for this head | amount + subject | relation, kind=대출기간 | 96 of 112 | word pack: 대출기간 |
| 인가? | what a sentence closed this way does | asks | '인가?' | 24 of 24 | lang-000-q, lang-002-q, lang-004-q |
| 대출기간 | what a sentence with this word does | asks | '대출기간' | 48 of 112 | word pack: 대출기간 |

12 routine sequence checks also passed (each connector and what follows it was seen before).

Score -8.04, every piece seen in training: yes.
No other reading has every piece seen in training, so there is no lead to report.
- Rival (score -21.68): [꼬마회원|name] [의 |connector] [대출기간|fixed word] [은 |connector] [얼마|name] [인가?|connector]. Rejected because: connecting piece after a value '인가?'; what a sentence closed this way does '인가?'.
- Rival (score -28.49): [꼬마회원|name] [의 |connector] [대출기간|fixed word] [은 |connector] [얼마인가|name] [?|connector]. Rejected because: connecting piece after a value '?'; known piece left unused '인가?'.

## Method

- Reading uses integer counts from training examples only. No neural network, embedding or token prediction.
- A reading is accepted only if every piece was seen in training and it leads clearly.
- The answer comes from matching the question graph against the passage graph; nothing is generated.
- If a passage event fits the question but does not name what was asked for, no answer is given.

