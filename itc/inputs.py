"""Reads and schema-validates the input files for one client and one tax period."""
from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from itc.config import ROOT, load_config
from itc.schemas import ClientProfile, Gstr2bRecord, Invoice, Payment


class _File(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: str = ""


class ClientsFile(_File):
    clients: list[ClientProfile]


class InvoicesFile(_File):
    client_id: str
    period: str
    invoices: list[Invoice]


class Gstr2bFile(_File):
    client_id: str
    period: str
    records: list[Gstr2bRecord]


class PaymentsFile(_File):
    client_id: str
    payments: list[Payment]


def data_dir(config: dict | None = None) -> Path:
    return ROOT / (config or load_config())["data_dir"]


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_clients(config: dict | None = None) -> list[ClientProfile]:
    return ClientsFile.model_validate(_read(data_dir(config) / "SYNTHETIC_clients.json")).clients


def available_periods(client_id: str, config: dict | None = None) -> list[str]:
    files = data_dir(config).glob(f"SYNTHETIC_invoices_{client_id}_*.json")
    return sorted(f.stem.rsplit("_", 1)[1] for f in files)


def load_client_inputs(client_id: str, period: str, config: dict | None = None) -> dict:
    d = data_dir(config)
    profile = next((c for c in load_clients(config) if c.client_id == client_id), None)
    if profile is None:
        raise ValueError(f"unknown client {client_id!r}")
    invoices = InvoicesFile.model_validate(_read(d / f"SYNTHETIC_invoices_{client_id}_{period}.json"))
    gstr2b = Gstr2bFile.model_validate(_read(d / f"SYNTHETIC_gstr2b_{client_id}_{period}.json"))
    payments = PaymentsFile.model_validate(_read(d / f"SYNTHETIC_payments_{client_id}.json"))
    for f in (invoices, gstr2b, payments):
        if f.client_id != client_id:
            raise ValueError(f"file for {f.client_id!r} passed as {client_id!r}")
    return {"profile": profile, "invoices": invoices.invoices, "gstr2b": gstr2b.records,
            "payments": payments.payments}
