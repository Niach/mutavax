"""Unit tests for the class-I predictor selector in stage 5.

The selector reads the ``CANCERSTUDIO_CLASS_I_PREDICTOR`` env var and
maps it to one of pvacseq's supported method names (``NetMHCpan``,
``MHCflurry``, ``MHCflurryEL``). Non-human species ignore the override
because MHCflurry has no DLA/FLA allele data.
"""
from __future__ import annotations

import pytest

from app.services.neoantigen import _class_i_predictor


class TestClassIPredictorSelector:
    def test_default_is_netmhcpan_when_unset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("CANCERSTUDIO_CLASS_I_PREDICTOR", raising=False)
        assert _class_i_predictor("human") == "NetMHCpan"

    def test_empty_string_falls_back_to_netmhcpan(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CANCERSTUDIO_CLASS_I_PREDICTOR", "")
        assert _class_i_predictor("human") == "NetMHCpan"

    def test_whitespace_only_falls_back_to_netmhcpan(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CANCERSTUDIO_CLASS_I_PREDICTOR", "   ")
        assert _class_i_predictor("human") == "NetMHCpan"

    @pytest.mark.parametrize(
        "value", ["NetMHCpan", "MHCflurry", "MHCflurryEL"]
    )
    def test_recognised_values_pass_through_for_human(
        self, monkeypatch: pytest.MonkeyPatch, value: str
    ) -> None:
        monkeypatch.setenv("CANCERSTUDIO_CLASS_I_PREDICTOR", value)
        assert _class_i_predictor("human") == value

    def test_unknown_value_falls_back_to_netmhcpan(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CANCERSTUDIO_CLASS_I_PREDICTOR", "SomeNovelPredictor")
        assert _class_i_predictor("human") == "NetMHCpan"

    @pytest.mark.parametrize(
        "species,override,expected",
        [
            # MHCflurry has no DLA / FLA allele data — the override gets
            # silently dropped for non-human species with a warning.
            ("dog", "MHCflurry", "NetMHCpan"),
            ("cat", "MHCflurry", "NetMHCpan"),
            ("dog", "MHCflurryEL", "NetMHCpan"),
            # NetMHCpan works for all species — no override to suppress.
            ("dog", "NetMHCpan", "NetMHCpan"),
            ("cat", "NetMHCpan", "NetMHCpan"),
        ],
    )
    def test_non_human_species_cannot_swap_to_mhcflurry(
        self,
        monkeypatch: pytest.MonkeyPatch,
        species: str,
        override: str,
        expected: str,
    ) -> None:
        monkeypatch.setenv("CANCERSTUDIO_CLASS_I_PREDICTOR", override)
        assert _class_i_predictor(species) == expected
