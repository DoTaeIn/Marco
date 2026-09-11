"""Compose numeric values from a model's numeral vocabulary.

Only called for slots explicitly annotated as numeric. Entity text is untouched.
"""


def parse_numeral(text, vocabulary):
    compact = "".join(text.split())
    if compact.isdecimal():
        return str(int(compact))
    atoms = vocabulary.get("atoms", {})
    if compact in atoms:
        return str(atoms[compact])
    for prefix, value in vocabulary.get("tens", {}).items():
        suffix = compact[len(prefix):] if compact.startswith(prefix) else None
        if suffix in atoms and 0 < atoms[suffix] < 10:
            return str(value + atoms[suffix])
    digits, powers = vocabulary.get("digits", {}), vocabulary.get("powers", {})
    if compact in digits:
        return str(digits[compact])
    total, pending, previous = 0, None, float("inf")
    for token in compact:
        if token in digits and 0 < digits[token] < 10:
            if pending is not None:
                return None
            pending = digits[token]
        elif token in powers:
            power = powers[token]
            if power >= previous:
                return None
            total += (pending if pending is not None else 1) * power
            pending, previous = None, power
        else:
            return None
    return str(total + (pending or 0)) if compact else None
