"""Answer checks: numbers must appear in the cited evidence, and uncited claims need support."""

from __future__ import annotations

import re

from wsw_brain.brain.grounding import check_answer, is_claim, numbers_in, overlap

CITATION = re.compile(r"\[u:([^\]\s]+)\]")
EVIDENCE = {
    "m1:u00001": "The starter plan costs 4,999 rupees a month and launches on 2 November.",
    "m1:u00002": "Payment terms stay at 45 days for every vendor.",
}


def test_numbers_are_normalised_before_comparison() -> None:
    assert numbers_in("Starter costs Rs. 4,999 a month.") == {"4999"}
    assert numbers_in("Budget of 1,50,000 rupees") == {"150000"}
    assert numbers_in("भुगतान ४५ दिनों में") == {"45"}  # Devanagari digits for 45
    assert numbers_in("Friday [u:m1:u00002] and [d:doc-1:c0003]") == set()  # citation ids are not numbers
    assert numbers_in("Growth was 2.5 percent.") == {"2.5"}


def test_cited_numbers_must_appear_in_the_cited_evidence() -> None:
    good = check_answer("Starter costs 4999 rupees a month [u:m1:u00001].", EVIDENCE, CITATION)
    assert good.text == "Starter costs 4999 rupees a month [u:m1:u00001]." and not good.unsupported_numbers
    bad = check_answer("Starter costs Rs. 5,999 a month [u:m1:u00001].", EVIDENCE, CITATION)
    assert bad.unsupported_numbers == {"5999"}
    assert bad.number_sentences == ["Starter costs Rs. 5,999 a month [u:m1:u00001]."]
    wrong_source = check_answer("Payment terms are 4,999 days [u:m1:u00002].", EVIDENCE, CITATION)
    assert wrong_source.unsupported_numbers == {"4999"}  # in the evidence, but not in the line it cites


def test_uncited_sentences_need_overlap_with_the_evidence() -> None:
    answer = (
        "Starter costs 4,999 rupees a month [u:m1:u00001]. "
        "The starter plan launches on 2 November. "
        "Marketing doubled its budget for the festive season."
    )
    checked = check_answer(answer, EVIDENCE, CITATION)
    assert checked.withheld == ["Marketing doubled its budget for the festive season."]
    assert (
        checked.text
        == "Starter costs 4,999 rupees a month [u:m1:u00001]. The starter plan launches on 2 November."
    )
    assert not checked.unsupported_numbers


def test_markers_after_the_full_stop_stay_with_their_sentence() -> None:
    checked = check_answer("Payment terms stay at 45 days. [u:m1:u00002] That is all.", EVIDENCE, CITATION)
    assert checked.sentences[0] == "Payment terms stay at 45 days. [u:m1:u00002]"
    assert not checked.unsupported_numbers and checked.withheld == []


def test_non_claims_are_kept_without_citations() -> None:
    assert not is_claim("I couldn't find that in the meeting record.")
    assert not is_claim("The documents do not mention the budget.")
    assert not is_claim("In short:")
    assert is_claim("Marketing doubled its budget for the festive season.")
    assert overlap("The starter plan launches soon.", EVIDENCE["m1:u00001"]) >= 3
    checked = check_answer("I don't know who approved it.", EVIDENCE, CITATION)
    assert checked.text == "I don't know who approved it." and checked.withheld == []
