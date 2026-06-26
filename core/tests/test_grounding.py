"""§7 span-matcher tests — ``exact → whitespace → prefix → none`` and ambiguity counting.

Proves the offset contract (returned offsets index the *unmodified* canonical text) and the
whitespace-recovery story (a newline-mangled span still resolves to the right original offsets).
"""

from __future__ import annotations

from chartextract import ground

DOC = "ER positive (90%). Margins not assessed. PR positive (40%)."


def test_exact_match_offsets_index_real_text():
    m = ground("Margins not assessed", DOC)
    assert m.match_quality == "exact"
    assert DOC[m.char_start : m.char_end] == "Margins not assessed"
    assert m.n_matches == 1


def test_whitespace_recovery_returns_original_offsets():
    # The model returned a span with collapsed/altered whitespace (extra spaces + a newline);
    # it must still resolve to the ORIGINAL text's offsets with match_quality="whitespace".
    text = "Tumor size 1.4 cm.\nER positive (90%)."
    mangled = "Tumor   size\n1.4  cm"
    m = ground(mangled, text)
    assert m.match_quality == "whitespace"
    assert text[m.char_start : m.char_end] == "Tumor size 1.4 cm"
    assert m.n_matches == 1


def test_prefix_only_match():
    # The full span is not present, but its first ~40 chars are — a degraded prefix match.
    text = "Invasive ductal carcinoma, grade 2 of 3, ER positive."
    span = "Invasive ductal carcinoma, grade 2 of 3, with extensive comment not in doc"
    m = ground(span, text)
    assert m.match_quality == "prefix"
    assert m.char_start == 0
    # Offsets cover exactly the matched prefix slice (≤40 chars) and index the real text.
    assert m.char_end - m.char_start <= 40
    assert text.startswith(text[m.char_start : m.char_end])
    assert m.n_matches == 1


def test_fabricated_span_is_none():
    m = ground("Totally invented finding not in the document", DOC)
    assert m.match_quality == "none"
    assert m.char_start is None
    assert m.char_end is None
    assert m.n_matches == 0


def test_empty_and_whitespace_only_span_is_none():
    assert ground("", DOC).match_quality == "none"
    assert ground("   \n\t ", DOC).match_quality == "none"
    assert ground("", DOC).n_matches == 0


def test_ambiguity_counting_exact_branch():
    # A short span occurring twice → n_matches == 2 (ambiguity is only counted on the exact branch).
    m = ground("positive", DOC)
    assert m.match_quality == "exact"
    assert m.n_matches == 2


def test_regex_hostile_span_does_not_crash():
    # A span full of regex metacharacters must not blow up the whitespace branch — it escapes
    # cleanly (here it actually matches exactly) and never raises.
    text = "Result: (a+b)*[c?]^d ... done."
    span = "(a+b)*[c?]^d"
    m = ground(span, text)
    assert m.match_quality == "exact"
    assert text[m.char_start : m.char_end] == span


def test_regex_hostile_unmatched_degrades_to_none_not_crash():
    span = "$^[unclosed(group+*?"
    m = ground(span, "a perfectly ordinary sentence with no metacharacters")
    assert m.match_quality == "none"


def test_huge_token_span_skips_regex_falls_through():
    # A span with thousands of tokens skips the whitespace regex (the cap) and falls through; if
    # its prefix isn't present it degrades to none without hanging.
    span = " ".join(str(i) for i in range(5000))
    m = ground(span, "short document body")
    assert m.match_quality == "none"
