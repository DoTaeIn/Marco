"""Text and structure: language packs, parsing, realization.

Public today: ``realize(meaning, intent, language) -> str``. Pack loading and
parsing still live in the root modules until the refactor moves them here.
"""
__all__ = ["realize"]


def __getattr__(name):
    if name == "realize":
        from marco.language.realizer import realize
        return realize
    raise AttributeError("module %r has no attribute %r" % (__name__, name))
