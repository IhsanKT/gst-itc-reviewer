"""Deterministic fake LLM so the tests, the UI and the eval run with no API key.

It is a keyword matcher that also reads the client profile, and it returns the same JSON shape as the real
model. It is NOT a model result: mock evaluation output is labelled MOCK everywhere.

To exercise every downstream path it misbehaves on purpose, always the same way:
- the prompt-injection line flips to NONE on run 1 (runs disagree, so the line is routed);
- gift hampers flip to the food clause on run 2 (disagreement);
- the team-offsite line cites an invented ID on run 1 (the citation validator must reject it).
"""
from __future__ import annotations

import json
import re

from itc.llm import LLMRequest

VEHICLE = ("dzire", "innova", "camry", "honda city", "etios", "sedan", "suv", "traveller", "car ", "cab", "taxi")
FOOD = ("catering", "khana", "dinner", "lunch", "chai", "nashta", "meal", "canteen", "snack", "tiffin", "food")


def _classify(desc: str, profile: dict) -> tuple[str, str]:
    d = desc.lower() + " "
    p = (profile.get("business_activity", "") + " " + " ".join(profile.get("outward_supplies", []))).lower()
    passenger = "passenger transport" in p
    caterer = "catering" in p
    statutory_canteen = "factories act" in p and "canteen" in p

    if "bill of supply" in d or "composition" in d:
        return "S17_5_E", "bill of supply from a composition dealer"
    if "csr" in d or "s.135" in d:
        return "S17_5_FA", "used for CSR"
    if "spouse" in d or "birthday" in d:
        return "S17_5_G", "personal consumption"
    if "gift" in d or "hamper" in d:
        return "S17_5_H", "goods given as gifts"
    if "insurance" in d:
        if any(k in d for k in ("motor", "vehcl", "taxi", "car")):
            return ("S17_5_AB.EX_SPECIFIED_PURPOSE", "insured vehicle carries passengers") if passenger \
                else ("S17_5_AB", "insurance of a blocked motor vehicle")
        return "S17_5_B_I_INSURANCE", "health or life insurance"
    if any(k in d for k in ("service", "repair")) and any(k in d for k in ("taxi", "innova", "honda city")):
        return ("S17_5_AB.EX_SPECIFIED_PURPOSE", "vehicle used for passenger transport") if passenger \
            else ("S17_5_AB", "repair of a blocked motor vehicle")
    if "boat" in d or "vessel" in d:
        return ("S17_5_AA.EX_GOODS_TRANSPORT", "vessel carries goods") if ("goods" in d or "consignment" in d) \
            else ("S17_5_AA", "vessel")
    if any(k in d for k in ("hire", "lease", "rental")) and any(k in d for k in VEHICLE):
        return ("S17_5_B_I_VEHICLE_HIRE.EX_SPECIFIED_PURPOSE", "hired cabs carry passengers") if passenger \
            else ("S17_5_B_I_VEHICLE_HIRE", "hire of a motor vehicle")
    if "truck" in d or "tata ace" in d:
        return "NONE", "goods vehicle, outside 17(5)(a)"
    if any(k in d for k in VEHICLE) or "seater" in d:
        seats = re.search(r"(\d+)[ -]?seat", d)
        if seats and int(seats.group(1)) > 13:
            return "NONE", f"{seats.group(1)} seats is above the 13-seat limit"
        if passenger and "personal" not in d:
            return "S17_5_A.EX_PASSENGER_TRANSPORT", "client transports passengers"
        return "S17_5_A", "passenger motor vehicle, no exception"
    if any(k in d for k in FOOD) and "packaging" not in d:
        if "canteen" in d and statutory_canteen:
            return "S17_5_B_I_FOOD.EX_EMPLOYER_OBLIGATION", "canteen required by the Factories Act"
        if caterer and "catering" in d:
            return "S17_5_B_I_FOOD.EX_SAME_CATEGORY", "client supplies catering"
        return "S17_5_B_I_FOOD", "food and beverages"
    if any(k in d for k in ("health check", "medical", "beauty", "salon", "cosmetic")):
        return "S17_5_B_I_BEAUTY_HEALTH", "health services"
    if any(k in d for k in ("gym", "club", "fitness")):
        return "S17_5_B_II", "club or fitness membership"
    if any(k in d for k in ("leave travel", "ltc", "holiday")):
        return "S17_5_B_III", "vacation travel benefit"
    if "works contract" in d:
        if any(k in d for k in ("exhaust", "machinery", "fixed to foundation")):
            return "S17_5_C.EX_PLANT_AND_MACHINERY", "installation is plant and machinery"
        return "S17_5_C", "works contract for immovable property"
    if any(k in d for k in ("cement", "tmt", "construction")):
        return "S17_5_D", "own-account construction"
    return "NONE", "no 17(5) keyword matched"


def _perturb(desc: str, run_index: int, rule_id: str) -> str:
    d = desc.lower()
    if "ignore all previous rules" in d and run_index == 1:
        return "NONE"
    if "hamper" in d and run_index == 2:
        return "S17_5_B_I_FOOD"
    if "offsite" in d and run_index == 1:
        return "S17_5_B_I_HOTEL"  # deliberately not in the rule pack
    return rule_id


class MockLLM:
    model_id = "mock/keyword-profile-v1"
    temperature = 0.0

    def __init__(self):
        self.calls = 0

    def complete(self, req: LLMRequest) -> str:
        self.calls += 1
        out = []
        for ln in req.lines:
            rule_id, why = _classify(ln["description"], req.profile)
            out.append({"line_id": ln["line_id"], "rule_id": _perturb(ln["description"], req.run_index, rule_id),
                        "reason": f"[mock] {why}"})
        return json.dumps({"lines": out})
