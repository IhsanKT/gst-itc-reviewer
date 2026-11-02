"""Baseline 1: a keyword/regex classifier of the kind a firm could build without an LLM.

It reads only the invoice description: no client profile, no exceptions. It answers a 17(5) clause ID or
NONE, and the eval passes that through the same section 16 checks and label precedence as the real system.
"""
from __future__ import annotations

import re

RULES: list[tuple[str, str]] = [
    (r"bill of supply|composition", "S17_5_E"),
    (r"\bcsr\b|s\.135|section 135", "S17_5_FA"),
    (r"\bpersonal\b|spouse|family", "S17_5_G"),
    (r"gift|hamper|free sample", "S17_5_H"),
    (r"(motor|vehicle|vehcl|car|taxi).*insurance|insurance.*(motor|vehicle|vehcl|car|taxi)", "S17_5_AB"),
    (r"(life|health|medical|mediclaim).*insurance|insurance.*(life|health)", "S17_5_B_I_INSURANCE"),
    (r"(service|repair|maintenance).*(car|taxi|innova|vehicle)", "S17_5_AB"),
    (r"\bboat\b|vessel|aircraft|yacht", "S17_5_AA"),
    (r"(hire|lease|rent).*(car|cab|taxi|vehicle)", "S17_5_B_I_VEHICLE_HIRE"),
    (r"\bcar\b|sedan|suv|dzire|innova|camry|honda city|traveller|seater|truck", "S17_5_A"),
    (r"food|meal|lunch|dinner|catering|canteen|tiffin|snack|beverage|khana|chai", "S17_5_B_I_FOOD"),
    (r"health check|medical|beauty|salon|cosmetic|spa\b", "S17_5_B_I_BEAUTY_HEALTH"),
    (r"\bgym\b|club|fitness", "S17_5_B_II"),
    (r"travel|holiday|ltc|tour package|tickets", "S17_5_B_III"),
    (r"works contract", "S17_5_C"),
    (r"cement|steel|construction|civil work", "S17_5_D"),
]


def classify(description: str) -> str:
    d = description.lower()
    for pattern, rule_id in RULES:
        if re.search(pattern, d):
            return rule_id
    return "NONE"
