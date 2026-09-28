"""Apply explicit output constraints to an already verified answer.

Never extract an arbitrary number from prose. A complete numeric answer must
match the declared representation; uncertain or explanatory answers stay intact.
"""
import re

def apply(question, answer, *, config=None):
    if config is None:
        from pack_model import development_model
        config = development_model().language["output_contracts"]
    config = config.get("number_only", {})
    if not config:
        return answer
    # Quoted examples and code are content, not output directives.
    text = re.sub(r'```.*?```|`[^`]*`|"[^"]*"|“[^”]*”|‘[^’]*’', "", question, flags=re.S)
    if not any(re.search(pattern, text) for pattern in config["requests"]):
        return answer
    match = re.fullmatch(config["numeric_answer"], answer.strip())
    return match["value"] if match else answer
