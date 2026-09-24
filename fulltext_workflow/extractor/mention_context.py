"""Source-grounded context for a paper-local entity mention."""
from __future__ import annotations

import re
from collections.abc import Iterable

_DEFINITION = re.compile(
    r"(?P<long>[A-Za-z][A-Za-z0-9,+/ -]{5,100}?)\s*\((?P<short>[A-Z][A-Za-z0-9+-]{1,11})\)"
)
_SENTENCE_END = re.compile(r"[.!?]\s+|\n{2,}")
_NONINITIAL_CLINICAL_EXPANSIONS = {
    "hcc": ("hepatocellular carcinoma",),
    "crc": ("colorectal cancer", "colorectal carcinoma"),
    "npc": ("nasopharyngeal carcinoma",),
}


def _initials(value: str) -> str:
    return ''.join(part[0] for part in re.findall(r'[A-Za-z]+', value)).casefold()


def abbreviation_definitions(sections: Iterable[str]) -> dict[str, tuple[str, str]]:
    """Collect explicit long-form (SHORT) definitions from this paper only."""
    found: dict[str, tuple[str, str]] = {}
    ambiguous: set[str] = set()
    for section in sections:
        for match in _DEFINITION.finditer(section):
            short = match.group('short')
            raw = match.group('long').strip()
            words = raw.split()
            # The regex may start before the actual definition; prefer the
            # shortest suffix whose initials match the printed abbreviation.
            candidates = [' '.join(words[-n:]) for n in range(1, min(len(words), 12) + 1)]
            long_form = next((s for s in candidates if _initials(s) == short.casefold()), None)
            if long_form is None:
                long_form = next(
                    (s for s in candidates
                     if s.casefold() in _NONINITIAL_CLINICAL_EXPANSIONS.get(short.casefold(), ())),
                    None,
                )
            if long_form and len(long_form) > len(short):
                key = short.casefold()
                if key in ambiguous:
                    continue
                if key in found and found[key][0].casefold() != long_form.casefold():
                    found.pop(key)
                    ambiguous.add(key)
                else:
                    printed = re.search(
                        r'\s+'.join(re.escape(word) for word in long_form.split())
                        + r'\s*\(' + re.escape(short) + r'\)',
                        match.group(0), re.I,
                    )
                    if printed:
                        found.setdefault(key, (long_form, printed.group(0)))
    return found


def local_context(source: str, start: int, end: int, max_chars: int = 500) -> str:
    """Return the complete sentence around a located quote, bounded in size."""
    if not source or start < 0 or end > len(source) or start >= end:
        return ''
    left = 0
    right = len(source)
    for match in _SENTENCE_END.finditer(source):
        if match.end() <= start:
            left = match.end()
        elif match.start() >= end or (
            match.start() == end - 1 and source[end - 1] in '.!?'
        ):
            right = match.start() + (1 if source[match.start()] in '.!?' else 0)
            break
    if right - left > max_chars:
        left = max(left, start - (max_chars - (end - start)) // 2)
        right = min(right, left + max_chars)
        if right < end:
            right = end
            left = max(0, right - max_chars)
    return source[left:right].strip()


def method_expansion(name: str, definitions: dict[str, tuple[str, str]]) -> tuple[str, str]:
    """Never infer a long form from a name or from a different paper."""
    key = name.strip().casefold()
    return definitions.get(key, ('', ''))
