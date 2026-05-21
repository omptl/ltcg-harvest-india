"""CAS PDF parsing wrapper around the `casparser` library.

casparser already handles CAMS, KFintech, and MF Central encrypted PDFs and returns
a JSON-shaped dict. Our job is to normalize that into our pydantic models and
classify each scheme.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from .classifier import classify_scheme, refine_debt_category
from .models import CASData, Scheme, SchemeCategory, Transaction, TxnType


# CAS transaction descriptions are inconsistent across statement providers. We map
# casparser's `type` field where present, else fall back to keyword matching on the
# description string.
_TYPE_KEYWORDS: list[tuple[tuple[str, ...], TxnType]] = [
    (("stt",), TxnType.STT),
    (("stamp", "duty"), TxnType.STAMP_DUTY),
    (("bonus",), TxnType.BONUS),
    (("dividend reinvest", "div reinvest", "idcw reinvest", "reinvestment"),
     TxnType.DIVIDEND_REINVEST),
    (("dividend",), TxnType.DIVIDEND_PAYOUT),
    (("switch out", "switch-out"), TxnType.SWITCH_OUT),
    (("switch in", "switch-in"), TxnType.SWITCH_IN),
    (("redemption", "redeem"), TxnType.REDEMPTION),
    (("sip",), TxnType.SIP),
    (("purchase", "subscription", "lumpsum", "additional"), TxnType.PURCHASE),
    (("segregat",), TxnType.SEGREGATION),
    (("reversal",), TxnType.REVERSAL),
]


def _parse_txn_type(raw_type: str | None, description: str) -> TxnType:
    """Map a casparser type/description to our normalized TxnType. First match wins."""
    text = ((raw_type or "") + " " + (description or "")).lower()
    for keywords, txn_type in _TYPE_KEYWORDS:
        if any(k in text for k in keywords):
            return txn_type
    return TxnType.OTHER


def _parse_date(value: Any) -> datetime.date | None:
    if value is None:
        return None
    if hasattr(value, "year") and hasattr(value, "month"):
        # date or datetime
        try:
            return value.date()  # datetime
        except AttributeError:
            return value
    if isinstance(value, str):
        for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%d/%m/%Y", "%d-%m-%Y"):
            try:
                return datetime.strptime(value, fmt).date()
            except ValueError:
                continue
    return None


def parse_cas(pdf_path: str | Path, password: str) -> CASData:
    """Parse a CAS PDF and return a normalized CASData object.

    Raises RuntimeError if casparser is unavailable, the file is missing, or the
    password is wrong. The exception message is safe to surface to the user.
    """
    import casparser  # imported lazily so tests can import this module without it

    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise RuntimeError(f"CAS file not found: {pdf_path}")

    try:
        raw = casparser.read_cas_pdf(str(pdf_path), password, output="dict")
    except Exception as exc:  # casparser raises various exception types
        raise RuntimeError(f"Could not parse CAS PDF (password correct?): {exc}") from exc

    return _from_casparser_dict(raw)


def _from_casparser_dict(raw: dict) -> CASData:
    investor = raw.get("investor_info", {}) or {}
    statement_period = raw.get("statement_period", {}) or {}

    cas = CASData(
        investor_name=investor.get("name", "") or "",
        pan_masked=_mask(investor.get("pan", "")),
        email_masked=_mask(investor.get("email", "")),
        statement_period_from=_parse_date(statement_period.get("from")),
        statement_period_to=_parse_date(statement_period.get("to")),
    )

    for folio_block in raw.get("folios", []) or []:
        folio_no = folio_block.get("folio", "") or ""
        amc = folio_block.get("amc", "") or ""
        # Some statements indicate NRI on folio holder line; we leave detection coarse.
        for scheme_block in folio_block.get("schemes", []) or []:
            scheme = _scheme_from_block(scheme_block, folio_no, amc)
            if scheme is not None:
                cas.schemes.append(scheme)

    return cas


def _scheme_from_block(block: dict, folio: str, amc: str) -> Scheme | None:
    name = (block.get("scheme") or "").strip()
    if not name:
        return None

    scheme = Scheme(
        folio=folio,
        scheme_name=name,
        amc=amc,
        isin=(block.get("isin") or None),
        scheme_code=(str(block.get("amfi")) if block.get("amfi") else None),
        is_demat=bool(block.get("advisor") and "demat" in str(block.get("advisor", "")).lower()),
    )

    for txn in block.get("transactions", []) or []:
        d = _parse_date(txn.get("date"))
        if d is None:
            continue
        scheme.transactions.append(Transaction(
            date=d,
            txn_type=_parse_txn_type(txn.get("type"), txn.get("description", "")),
            units=float(txn.get("units") or 0.0),
            nav=float(txn.get("nav") or 0.0),
            amount=float(txn.get("amount") or 0.0),
            description=txn.get("description", "") or "",
        ))

    scheme.category = classify_scheme(scheme)
    first_purchase = next(
        (t.date for t in sorted(scheme.transactions, key=lambda x: x.date)
         if t.units and t.units > 0),
        None,
    )
    scheme.category = refine_debt_category(scheme, first_purchase)
    return scheme


def _mask(value: str | None) -> str:
    """Mask all but the last 4 characters of a sensitive identifier."""
    if not value:
        return ""
    value = str(value)
    if len(value) <= 4:
        return "*" * len(value)
    return "*" * (len(value) - 4) + value[-4:]
