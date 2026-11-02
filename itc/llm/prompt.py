"""Renders the versioned prompt files in prompts/. Invoice text is JSON-encoded and fenced as untrusted data."""
from __future__ import annotations

import json
import re

from itc.config import ROOT
from itc.rulepack import BlockedCreditPack

PROMPTS = ROOT / "prompts"


def load_prompt(version: str) -> tuple[str, str]:
    """Returns (system, user_template) from prompts/<version>.md and checks the version header."""
    text = (PROMPTS / f"{version}.md").read_text(encoding="utf-8")
    header = re.search(r"<!-- prompt_version: (\S+) -->", text)
    if not header or header.group(1) != version:
        raise ValueError(f"prompts/{version}.md does not declare prompt_version {version}")
    system = text.split("# SYSTEM", 1)[1].split("# USER", 1)[0].strip()
    user = text.split("# USER", 1)[1].strip()
    return system, user


def render_rule_pack(pack: BlockedCreditPack) -> str:
    parts = []
    for r in pack.rules:
        parts.append(f"### {r.id}  [{r.clause}] {r.title}\nStatute: {r.text}")
        for ex in r.exceptions:
            parts.append(f"  - Exception {ex.id}: {ex.condition}\n    Statute: {ex.text}")
    for d in pack.definitions:
        parts.append(f"### Definition {d.id} (applies to {', '.join(d.applies_to)})\n{d.text}")
    return "\n".join(parts)


def render_profile(profile: dict) -> str:
    keys = ("legal_name", "business_activity", "outward_supplies", "notes")
    return json.dumps({k: profile[k] for k in keys if profile.get(k)}, indent=2, ensure_ascii=False)


def render_lines(lines: list[dict]) -> str:
    """JSON-encode so quotes and newlines in descriptions cannot break the structure; escape angle brackets so
    a description cannot close the <untrusted_invoice_data> fence."""
    view = [
        {k: ln[k] for k in ("line_id", "supplier_name", "description", "hsn", "doc_type", "taxable_value", "gst_rate")}
        for ln in lines
    ]
    return json.dumps(view, indent=2, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e")


def build_messages(version: str, lines: list[dict], profile: dict, pack: BlockedCreditPack | None) -> list[dict]:
    system, user = load_prompt(version)
    fills = {
        "client_profile": render_profile(profile),
        "invoice_lines": render_lines(lines),
    }
    if pack is not None:
        fills |= {
            "rule_pack": render_rule_pack(pack),
            "rule_pack_version": pack.version,
            "period": pack.period or "",
            "allowed_ids": ", ".join(sorted(pack.citation_ids)),
        }
    for key, value in fills.items():
        user = user.replace("{{" + key + "}}", value)
    leftover = re.findall(r"\{\{(\w+)\}\}", user)
    if leftover:
        raise ValueError(f"unfilled placeholders in {version}: {leftover}")
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def classify_response_format(allowed_ids: list[str]) -> dict:
    """Strict JSON schema. The enum is a first fence; itc/validate.py re-checks every ID in code."""
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "itc_17_5_classification",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "lines": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "line_id": {"type": "string"},
                                "rule_id": {"type": "string", "enum": sorted(allowed_ids)},
                                "reason": {"type": "string"},
                            },
                            "required": ["line_id", "rule_id", "reason"],
                            "additionalProperties": False,
                        },
                    }
                },
                "required": ["lines"],
                "additionalProperties": False,
            },
        },
    }


def norules_response_format() -> dict:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "itc_17_5_no_rule_pack",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "lines": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "line_id": {"type": "string"},
                                "clause": {"type": "string"},
                                "exception_applies": {"type": "boolean"},
                                "reason": {"type": "string"},
                            },
                            "required": ["line_id", "clause", "exception_applies", "reason"],
                            "additionalProperties": False,
                        },
                    }
                },
                "required": ["lines"],
                "additionalProperties": False,
            },
        },
    }
