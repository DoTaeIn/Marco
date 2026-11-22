# Answer: 지호

## Answer as a sentence

> 민수에 따르면, 지호가 서연을 돕지 않았다.

Each sentence was built from pieces seen in the lessons and then read back by the reader, which had to arrive at the same meaning. How the first one was built:

| Piece | Why it was chosen |
|---|---|
| 돕지 않았다 | the head word for this meaning in a sentence that states |
| source actor object HEAD | the order such sentences were written in |
| 에 따르면, | after "민수": follows a person (640); marks the source (640); follows a word ending in this sound (65); is followed by a person (440); comes before the actor (640) |
| 가 | after "지호": follows a person (160); marks the actor (160); follows a word ending in this sound (19); is followed by a person (150); comes before the object (160) |
| 을 | after "서연": follows a person (350); marks the object (350); follows a word ending in this sound (186); is followed by a event (350) |
| . | after "돕지 않았다": follows a event (280); follows a word ending in this sound (280) |

Question: `민수에 따르면, 누가 서연을 돕지 않았나?`

Passage: `민수에 따르면, 지호가 서연을 돕지 않았다. 민수에 따르면, 하늘이 서연을 도왔다.`

## Why this answer

The question was turned into a small graph with one unknown. The passage graph was searched for a place where every condition of the question holds. The unknown there is the answer.

Ground 1 for the answer 지호, each condition and the passage text that satisfies it:

| Condition in the question | Passage text |
|---|---|
| source = "민수" | "민수" + "에 따르면" |
| actor = the thing asked for | "지호" + "돕지 않았다" |
| object = "서연" | "돕지 않았다" + "서연" |
| action = "help" | "돕지 않았다" |
| polarity = "negative" | "돕지 않았다" |
| a name given in the question: "민수" | "민수" |
| a name given in the question: "서연" | "서연" |
| the name of what was asked for | "지호" |

Verified: the older executor reached the same answer independently.

## How the passage was read

Text: `민수에 따르면, 지호가 서연을 돕지 않았다. 민수에 따르면, 하늘이 서연을 도왔다.`

Status: **complete** (read as 2 sentences, each with every piece seen in training and a clear lead).

Pieces: [민수|name] [에 따르면, |connector] [지호|name] [가 |connector] [서연|name] [을 |connector] [돕지 않았다|fixed word] [.|connector] [ |connector] [민수|name] [에 따르면, |connector] [하늘|name] [이 |connector] [서연|name] [을 |connector] [도왔다|fixed word] [.|connector]

What it means:
- event "돕지 않았다": source = "민수", actor = "지호", object = "서연", action = "help", polarity = "negative"
- event "도왔다": source = "민수", actor = "하늘", object = "서연", action = "help", polarity = "positive"

Why each piece was read this way:

| Piece | Decision about | Chosen | Given | Seen in training | Example ids |
|---|---|---|---|---|---|
| 민수 | kind of a free value | person | '에 따르면, ' | 640 of 640 | tp01, tq01, tp02 |
| 민수 | length of a free value | 2 characters | 'longest seen in training: 3' | 1793 of 1800 | tp01, tq01, tp02 |
| 지호 | kind of a free value | person | '가 ' | 160 of 160 | tp01, tp04, tq04 |
| 지호 | length of a free value | 2 characters | 'longest seen in training: 3' | 1793 of 1800 | tp01, tq01, tp02 |
| 서연 | kind of a free value | person | '을 ' | 350 of 350 | tp02, tp04, tp05 |
| 서연 | length of a free value | 2 characters | 'longest seen in training: 3' | 1793 of 1800 | tp01, tq01, tp02 |
| 돕지 않았다 | meaning of a fixed word | event, action=help, polarity=negative | '돕지 않았다' | 210 of 210 | tp03, tp06, tp08 |
| 민수 | which head | head '돕지 않았다' (offset 0) | '*' | 2080 of 2080 | tp01, tq01, tp02 |
| 민수 | role from the piece after it | source | '에 따르면, ' | 640 of 640 | tp01, tq01, tp02 |
| 민수 | role from the piece before it | source | '' | 480 of 560 | tp01, tq01, tp02 |
| 지호 | which head | head '돕지 않았다' (offset 0) | '*' | 2080 of 2080 | tp01, tq01, tp02 |
| 지호 | role from the piece after it | actor | '가 ' | 160 of 160 | tp01, tp04, tq04 |
| 지호 | role from the piece before it | actor | '에 따르면, ' | 640 of 640 | tp01, tq01, tp02 |
| 서연 | which head | head '돕지 않았다' (offset 0) | '*' | 2080 of 2080 | tp01, tq01, tp02 |
| 서연 | role from the piece after it | object | '을 ' | 350 of 350 | tp02, tp04, tp05 |
| 서연 | role from the piece before it | object | '가 ' | 160 of 160 | tp01, tp04, tq04 |
| 돕지 않았다 | set of roles for this head | actor + object + source | event, action=help, polarity=negative | 300 of 340 | tp03, tq03, tp08 |
| . | what a sentence closed this way does | states | '.' | 280 of 280 | tp01, tp02, tp03 |
| 돕지 않았다 | what a sentence with this word does | states | '돕지 않았다' | 210 of 210 | tp03, tp06, tp08 |
| 민수 | kind of a free value | person | '에 따르면, ' | 640 of 640 | tp01, tq01, tp02 |
| 민수 | length of a free value | 2 characters | 'longest seen in training: 3' | 1793 of 1800 | tp01, tq01, tp02 |
| 하늘 | kind of a free value | person | '이 ' | 340 of 340 | tp02, tq02, tp03 |
| 하늘 | length of a free value | 2 characters | 'longest seen in training: 3' | 1793 of 1800 | tp01, tq01, tp02 |
| 서연 | kind of a free value | person | '을 ' | 350 of 350 | tp02, tp04, tp05 |
| 서연 | length of a free value | 2 characters | 'longest seen in training: 3' | 1793 of 1800 | tp01, tq01, tp02 |
| 도왔다 | meaning of a fixed word | event, action=help, polarity=positive | '도왔다' | 230 of 230 | tp01, tp02, tp04 |
| 민수 | which head | head '도왔다' (offset 0) | '*' | 2080 of 2080 | tp01, tq01, tp02 |
| 민수 | role from the piece after it | source | '에 따르면, ' | 640 of 640 | tp01, tq01, tp02 |
| 민수 | role from the piece before it | source | '' | 480 of 560 | tp01, tq01, tp02 |
| 하늘 | which head | head '도왔다' (offset 0) | '*' | 2080 of 2080 | tp01, tq01, tp02 |
| 하늘 | role from the piece after it | actor | '이 ' | 340 of 340 | tp02, tq02, tp03 |
| 하늘 | role from the piece before it | actor | '에 따르면, ' | 640 of 640 | tp01, tq01, tp02 |
| 서연 | which head | head '도왔다' (offset 0) | '*' | 2080 of 2080 | tp01, tq01, tp02 |
| 서연 | role from the piece after it | object | '을 ' | 350 of 350 | tp02, tp04, tp05 |
| 서연 | role from the piece before it | object | '이 ' | 340 of 340 | tp02, tq02, tp03 |
| 도왔다 | set of roles for this head | actor + object + source | event, action=help, polarity=positive | 340 of 380 | tp01, tq01, tp02 |
| . | what a sentence closed this way does | states | '.' | 280 of 280 | tp01, tp02, tp03 |
| 도왔다 | what a sentence with this word does | states | '도왔다' | 230 of 230 | tp01, tp02, tp04 |

28 routine sequence checks also passed (each connector and what follows it was seen before).

Score -13.02, every piece seen in training: yes.
No other reading has every piece seen in training, so there is no lead to report.
The search dropped at least one candidate that scored the same as one it kept.

## How the question was read

Text: `민수에 따르면, 누가 서연을 돕지 않았나?`

Status: **complete** (the only reading whose every piece was seen in training).

Pieces: [민수|name] [에 따르면, |connector] [누가|fixed word] [ |connector] [서연|name] [을 |connector] [돕지 않았나|fixed word] [?|connector]

What it means:
- event "돕지 않았나": source = "민수", actor = the thing asked for, object = "서연", action = "help", polarity = "negative"

Asked for: the actor of that event.

Why each piece was read this way:

| Piece | Decision about | Chosen | Given | Seen in training | Example ids |
|---|---|---|---|---|---|
| 민수 | kind of a free value | person | '에 따르면, ' | 640 of 640 | tp01, tq01, tp02 |
| 민수 | length of a free value | 2 characters | 'longest seen in training: 3' | 1793 of 1800 | tp01, tq01, tp02 |
| 누가 | meaning of a fixed word | person, asked for | '누가' | 220 of 220 | tq01, tq03, tq05 |
| 서연 | kind of a free value | person | '을 ' | 350 of 350 | tp02, tp04, tp05 |
| 서연 | length of a free value | 2 characters | 'longest seen in training: 3' | 1793 of 1800 | tp01, tq01, tp02 |
| 돕지 않았나 | meaning of a fixed word | event, action=help, polarity=negative | '돕지 않았나' | 130 of 130 | tq03, tq06, tq08 |
| 민수 | which head | head '돕지 않았나' (offset 0) | '*' | 2080 of 2080 | tp01, tq01, tp02 |
| 민수 | role from the piece after it | source | '에 따르면, ' | 640 of 640 | tp01, tq01, tp02 |
| 민수 | role from the piece before it | source | '' | 480 of 560 | tp01, tq01, tp02 |
| 누가 | which head | head '돕지 않았나' (offset 0) | '*' | 2080 of 2080 | tp01, tq01, tp02 |
| 누가 | role of this fixed word | actor | '누가' | 220 of 220 | tq01, tq03, tq05 |
| 서연 | which head | head '돕지 않았나' (offset 0) | '*' | 2080 of 2080 | tp01, tq01, tp02 |
| 서연 | role from the piece after it | object | '을 ' | 350 of 350 | tp02, tp04, tp05 |
| 서연 | role from the piece before it | object | ' ' | 220 of 220 | tq01, tq03, tq05 |
| 돕지 않았나 | set of roles for this head | actor + object + source | event, action=help, polarity=negative | 300 of 340 | tp03, tq03, tp08 |
| ? | what a sentence closed this way does | asks | '?' | 280 of 280 | tq01, tq02, tq03 |
| 돕지 않았나 | what a sentence with this word does | asks | '돕지 않았나' | 130 of 130 | tq03, tq06, tq08 |

14 routine sequence checks also passed (each connector and what follows it was seen before).

Score -5.39, every piece seen in training: yes.
No other reading has every piece seen in training, so there is no lead to report.
- Rival (score -25.41): [민수|name] [에 따르면, |connector] [누가|fixed word] [ |connector] [서연을 |IGNORED] [돕지 않았나|fixed word] [?|connector]. Rejected because: unknown text ignored '서연을 '; known piece left unused '을 '.
- Rival (score -27.11): [민수|name] [에 따르면, |connector] [누가|fixed word] [ |connector] [서연을|name] [ |connector] [돕지 않았나|fixed word] [?|connector]. Rejected because: connecting piece after a value ' '; known piece left unused '을 '.

## Method

- Reading uses integer counts from training examples only. No neural network, embedding or token prediction.
- A reading is accepted only if every piece was seen in training and it leads clearly.
- The answer comes from matching the question graph against the passage graph; nothing is generated.
- If a passage event fits the question but does not name what was asked for, no answer is given.

