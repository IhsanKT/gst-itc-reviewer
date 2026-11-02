"""Loads the versioned, effective-dated rule packs and validates citations against them.

A pack file may hold several entries with the same id and non-overlapping date ranges. `for_period`
keeps the entries in force on the last day of the tax period, so each id resolves to exactly one text.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from functools import cached_property
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, model_validator

from itc.config import ROOT, load_config
from itc.periods import period_bounds

NONE_ID = "NONE"  # the classifier's answer when no 17(5) clause applies


class RuleException(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    text: str
    condition: str


class Definition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    applies_to: list[str]
    text: str
    source: str
    verified: bool
    notes: str = ""


class _Rule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    clause: str
    title: str
    text: str
    effective_from: date
    effective_to: date | None
    source: str
    verified: bool
    notes: str = ""

    def in_force_on(self, d: date) -> bool:
        return self.effective_from <= d and (self.effective_to is None or d <= self.effective_to)


class BlockedCreditRule(_Rule):
    exceptions: list[RuleException]
    ambiguity: Literal["low", "medium", "high"]
    needs_business_profile: bool

    @model_validator(mode="after")
    def _exception_ids_are_namespaced(self):
        for ex in self.exceptions:
            if not ex.id.startswith(self.id + ".EX_"):
                raise ValueError(f"exception id {ex.id!r} must start with {self.id + '.EX_'!r}")
        return self


class ConditionRule(_Rule):
    check: str | None
    outcome_on_fail: Literal["Deferred", "Blocked"]


class _Pack(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: str
    act: str
    section: str
    covers_from: date
    period: str | None = None  # set once filtered by for_period

    @model_validator(mode="after")
    def _no_overlapping_versions(self):
        by_id = defaultdict(list)
        for r in self.rules:
            by_id[r.id].append(r)
        for rid, entries in by_id.items():
            entries.sort(key=lambda r: r.effective_from)
            for a, b in zip(entries, entries[1:]):
                if a.effective_to is None or a.effective_to >= b.effective_from:
                    raise ValueError(f"{rid}: effective date ranges overlap")
        return self

    def for_period(self, period: str):
        _, end = period_bounds(period)
        if end < self.covers_from:
            raise ValueError(
                f"Section {self.section} pack {self.version} covers periods from {self.covers_from}; {period} is out of scope"
            )
        data = self.model_dump()
        data["rules"] = [r.model_dump() for r in self.rules if r.in_force_on(end)]
        data["period"] = period
        return type(self).model_validate(data)

    def get(self, rule_id: str):
        matches = [r for r in self.rules if r.id == rule_id]
        if len(matches) != 1:
            raise KeyError(f"{rule_id!r}: {len(matches)} entries (call for_period first?)")
        return matches[0]


class BlockedCreditPack(_Pack):
    chapeau: str
    definitions: list[Definition]
    rules: list[BlockedCreditRule]

    @cached_property
    def citation_ids(self) -> set[str]:
        """Every id the classifier may output: clauses, exceptions and NONE."""
        ids = {NONE_ID}
        for r in self.rules:
            ids.add(r.id)
            ids.update(ex.id for ex in r.exceptions)
        return ids

    def resolve(self, rule_id: str) -> tuple[BlockedCreditRule | None, RuleException | None]:
        """Map a citation id to (clause, exception). NONE -> (None, None). Unknown ids raise KeyError."""
        if rule_id not in self.citation_ids:
            raise KeyError(f"{rule_id!r} is not in rule pack {self.version} for {self.period}")
        if rule_id == NONE_ID:
            return None, None
        clause_id, _, _ = rule_id.partition(".")
        rule = self.get(clause_id)
        if rule_id == clause_id:
            return rule, None
        return rule, next(ex for ex in rule.exceptions if ex.id == rule_id)


class ConditionPack(_Pack):
    rules: list[ConditionRule]


def is_valid_citation(rule_id: object, pack: BlockedCreditPack) -> bool:
    return isinstance(rule_id, str) and rule_id in pack.citation_ids


def _read(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_packs(period: str, config: dict | None = None) -> tuple[BlockedCreditPack, ConditionPack]:
    """Load both packs and keep only the entries in force for `period`."""
    cfg = (config or load_config())["rules"]
    blocked = BlockedCreditPack.model_validate(_read(ROOT / cfg["section_17_5"])).for_period(period)
    conditions = ConditionPack.model_validate(_read(ROOT / cfg["section_16"])).for_period(period)
    return blocked, conditions
