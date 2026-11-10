"""Provider-owned translation result; importing it requires no BabelDOC extension."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TranslationOutcome:
    text: str
    warnings: tuple[str, ...] = ()

    @property
    def cacheable(self) -> bool:
        return not self.warnings


def as_translation_outcome(value: str | TranslationOutcome) -> TranslationOutcome:
    if isinstance(value, TranslationOutcome):
        return value
    if not isinstance(value, str):
        raise TypeError("translation must be text or TranslationOutcome")
    return TranslationOutcome(value)
