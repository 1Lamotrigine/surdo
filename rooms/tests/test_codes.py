"""Генератор кодов комнат."""

import pytest

from rooms.codes import JOIN_CODE_ALPHABET, JOIN_CODE_LENGTH, generate_join_code

AMBIGUOUS_CHARACTERS = set("O0I1")


def test_generated_code_has_expected_length_and_alphabet():
    codes = [generate_join_code() for _ in range(200)]

    assert all(len(code) == JOIN_CODE_LENGTH for code in codes)
    assert all(set(code) <= set(JOIN_CODE_ALPHABET) for code in codes)


def test_generated_code_has_no_ambiguous_characters():
    for _ in range(200):
        assert not (set(generate_join_code()) & AMBIGUOUS_CHARACTERS)


def test_generator_supports_custom_length():
    assert len(generate_join_code(10)) == 10


def test_generator_rejects_non_positive_length():
    with pytest.raises(ValueError):
        generate_join_code(0)
