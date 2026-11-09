"""Guards against invented figures: every number in generated prose must exist in the evidence it was given."""
import re

_NUM = re.compile(r"(?<![A-Za-z])[-+]?\d[\d,]*(?:\.\d+)?")
# Numbers that carry no factual claim: years, quarter/FY labels, list ordinals.
_IGNORE = re.compile(r"\b(?:FY|Q[1-4]|H[12])\s?'?\d{2,4}\b|\b(?:19|20)\d{2}\b", re.I)


def numbers(text: str) -> list[float]:
    text = _IGNORE.sub(" ", text or "")
    out = []
    for m in _NUM.finditer(text):
        try:
            out.append(float(m.group().replace(",", "")))
        except ValueError:
            pass
    return out


def ungrounded(generated: str, evidence: str, tol: float = 0.011) -> list[float]:
    """Numbers in `generated` that do not appear (± rounding) in `evidence`. Small integers (≤10) are allowed."""
    ev = numbers(evidence)
    bad = []
    for n in numbers(generated):
        if abs(n) <= 10 and n == int(n):
            continue
        if not any(abs(abs(n) - abs(e)) <= max(tol * abs(e), 0.051) for e in ev):
            bad.append(n)
    return bad
