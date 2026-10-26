"""Import a personal budget spreadsheet (e.g. a hand-built "Finances.xlsx").

The importer looks for blocks of rows under recognisable header rows rather
than fixed cell addresses, so moved tables still import:

    Header row                              Imported as
    ------------------------------------    -------------------------------------------
    Income | Amount | Type                  Income sources (monthly)
    Expenses | Amount | ... | Monthly Date  Recurring bills / planned spending
        (a numeric value in an extra column is read as that loan's remaining balance)
    <name> | Allowed Amount/Limit | Owe      Credit card accounts (limit, balance owed)
    Type | Amount                           Asset balances (checking, savings, ...)
    Person | Amount | Type                  "Money owed to me" accounts

Rows whose first cell is "Total" and cells containing formulas are skipped —
values are never invented. Anything the importer can't classify confidently
is imported and flagged "needs review".

Re-importing an updated workbook updates amounts and adds new balance
snapshots; it never deletes records. Importing the exact same file twice is
refused unless ``force=True``.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import openpyxl
from sqlalchemy import select
from sqlalchemy.orm import Session

from finance.categorization.rules import asset_type_for, classify_recurring, debt_type_for
from finance.db.models import ImportRecord
from finance.services import accounts as acct_svc
from finance.services import audit
from finance.services import bills as bill_svc
from finance.services import income as income_svc
from finance.services.categories import find_category
from finance.utils.money import MoneyError, to_cents


class WorkbookImportError(ValueError):
    pass


@dataclass
class ImportResult:
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    flagged: list[str] = field(default_factory=list)
    already_imported: bool = False

    @property
    def total_changes(self) -> int:
        return len(self.created) + len(self.updated)

    def as_text(self) -> str:
        parts = []
        for label, items in (("Created", self.created), ("Updated", self.updated), ("Unchanged", self.unchanged),
                             ("Skipped", self.skipped), ("Needs review", self.flagged)):
            if items:
                parts.append(f"{label} ({len(items)}):\n  - " + "\n  - ".join(items))
        return "\n".join(parts) or "Nothing found to import."


@dataclass
class Block:
    kind: str
    sheet: str
    headers: list[str]
    rows: list[list]  # raw cell values, same width as headers


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #
def _norm(v) -> str:
    return re.sub(r"\s+", " ", str(v)).strip().lower() if v is not None else ""


def _detect_kind(headers: list[str]) -> str | None:
    h = [x for x in headers if x]
    if len(h) < 2 or "amount" not in h and "owe" not in h:
        return None
    first = h[0]
    if any(x in h for x in ("owe", "owed", "balance owed")) and any(
        x in h for x in ("allowed amount", "limit", "credit limit")
    ):
        return "credit"
    if first in ("income", "income source"):
        return "income"
    if first in ("expenses", "expense", "bills", "bill"):
        return "expenses"
    if first in ("person", "who", "name") and "amount" in h:
        return "receivables"
    if first in ("type", "account") and "amount" in h:
        return "balances"
    return None


def _is_formula(v) -> bool:
    return isinstance(v, str) and v.startswith("=")


def parse_workbook(path: str | Path) -> list[Block]:
    wb = openpyxl.load_workbook(path, data_only=False, read_only=False)
    blocks: list[Block] = []
    for ws in wb.worksheets:
        grid = [[c for c in row] for row in ws.iter_rows(values_only=True)]
        used: set[tuple[int, int]] = set()
        for r, row in enumerate(grid):
            for c in range(len(row)):
                if (r, c) in used or not isinstance(row[c], str):
                    continue
                # contiguous header cells to the right
                headers = []
                cc = c
                while cc < len(row) and isinstance(row[cc], str) and row[cc].strip():
                    headers.append(_norm(row[cc]))
                    cc += 1
                kind = _detect_kind(headers)
                if not kind:
                    continue
                width = len(headers)
                body = []
                rr = r + 1
                while rr < len(grid):
                    vals = list(grid[rr][c:c + width]) + [None] * max(0, width - len(grid[rr][c:c + width]))
                    first = vals[0]
                    if first is None and all(v is None for v in vals):
                        # allow a single blank row inside a block, stop on two
                        nxt = grid[rr + 1][c:c + width] if rr + 1 < len(grid) else []
                        if not any(v is not None for v in nxt):
                            break
                        rr += 1
                        continue
                    if _norm(first).startswith("total"):
                        break
                    if isinstance(first, str) and _detect_kind([_norm(v) for v in vals if isinstance(v, str)]):
                        break
                    body.append(vals)
                    rr += 1
                for k in range(c, c + width):
                    used.add((r, k))
                blocks.append(Block(kind, ws.title, headers, body))
    return blocks


def _num(v) -> int | None:
    """Cents from a numeric/str cell, or None for blanks/formulas/text."""
    if v is None or _is_formula(v) or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return to_cents(v)
    try:
        return to_cents(v)
    except MoneyError:
        return None


def _day(v) -> int | None:
    if v is None:
        return None
    if isinstance(v, (int, float)) and 1 <= int(v) <= 31:
        return int(v)
    if hasattr(v, "day"):  # a date cell
        return v.day
    m = re.match(r"^\s*(\d{1,2})\s*(st|nd|rd|th)?\s*$", str(v).lower())
    if m and 1 <= int(m.group(1)) <= 31:
        return int(m.group(1))
    return None


def _clean_name(v) -> str:
    s = re.sub(r"\s+", " ", str(v)).strip()
    s = re.sub(r"\s*\((income|owe|bill)\)\s*$", "", s, flags=re.I)
    return s


def _col(headers: list[str], *names: str) -> int | None:
    for n in names:
        if n in headers:
            return headers.index(n)
    return None


# --------------------------------------------------------------------------- #
# Loading into the database
# --------------------------------------------------------------------------- #
def file_sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def import_workbook(session: Session, path: str | Path, *, as_of: date | None = None, force: bool = False,
                    display_name: str | None = None) -> ImportResult:
    path = Path(path)
    as_of = as_of or date.today()
    sha = file_sha256(path)
    res = ImportResult()
    prior = session.scalar(select(ImportRecord).where(ImportRecord.file_sha256 == sha))
    if prior and not force:
        res.already_imported = True
        return res

    try:
        blocks = parse_workbook(path)
    except Exception as exc:  # openpyxl raises many types
        raise WorkbookImportError(f"Could not read workbook: {exc}") from exc
    if not blocks:
        raise WorkbookImportError("No recognisable tables (Income / Expenses / Credit / balances) were found.")

    order = {"balances": 0, "credit": 1, "receivables": 2, "expenses": 3, "income": 4}
    for b in sorted(blocks, key=lambda b: order[b.kind]):
        globals()[f"_load_{b.kind}"](session, b, res, as_of)

    session.add(ImportRecord(source_type="workbook", filename=display_name or path.name, file_sha256=sha,
                             rows_imported=res.total_changes, summary=res.as_text()))
    audit.record(session, "import", None, "import", {"file": display_name or path.name,
                                                    "created": len(res.created), "updated": len(res.updated)})
    session.flush()
    return res


def _upsert_account(session, res: ImportResult, *, name: str, account_type: str, balance: int, as_of: date,
                    review: str | None = None, **extra):
    label = f"{name} ({account_type.replace('_', ' ')})"
    acct = acct_svc.find_by_name(session, name, account_type)
    if acct is None:
        acct = acct_svc.create_account(session, name=name, account_type=account_type, balance_cents=balance,
                                       as_of=as_of, source="workbook", needs_review=bool(review),
                                       review_note=review, **extra)
        res.created.append(f"Account: {label}")
    else:
        changed = []
        if acct.current_balance_cents != balance:
            acct_svc.set_balance(session, acct.id, balance, as_of=as_of, source="workbook",
                                 note="Updated from workbook import")
            changed.append("balance")
        upd = {k: v for k, v in extra.items() if v is not None and getattr(acct, k) != v}
        if upd:
            acct_svc.update_account(session, acct.id, **upd)
            changed += list(upd)
        (res.updated if changed else res.unchanged).append(f"Account: {label}" + (f" [{', '.join(changed)}]" if changed else ""))
    if acct.needs_review and acct.review_note:
        res.flagged.append(f"{label}: {acct.review_note}")
    return acct


def _load_balances(session, b: Block, res, as_of):
    ni, ai = 0, _col(b.headers, "amount")
    for row in b.rows:
        if not row[ni]:
            continue
        name = _clean_name(row[ni])
        cents = _num(row[ai])
        if cents is None:
            res.skipped.append(f"Balance '{name}': no numeric amount")
            continue
        atype, confident = asset_type_for(name)
        review = None if confident else (
            "Couldn't tell what kind of account this is from its name — imported as 'Other asset'. "
            "If it's actually money you owe, change the type or fold it into the right card/loan.")
        if cents < 0:
            res.skipped.append(f"Balance '{name}': negative amount {cents / 100:.2f} — enter it manually")
            continue
        _upsert_account(session, res, name=name, account_type=atype, balance=cents, as_of=as_of, review=review)


def _load_credit(session, b: Block, res, as_of):
    ni = 0
    li = _col(b.headers, "allowed amount", "limit", "credit limit")
    oi = _col(b.headers, "owe", "owed", "balance owed")
    for row in b.rows:
        if not row[ni]:
            continue
        name = _clean_name(row[ni])
        owe = _num(row[oi])
        limit = _num(row[li]) if li is not None else None
        if owe is None:
            res.skipped.append(f"Credit card '{name}': no numeric balance owed")
            continue
        _upsert_account(session, res, name=name, account_type="credit_card", balance=abs(owe), as_of=as_of,
                        review="Add the APR and minimum payment to enable payoff planning.",
                        credit_limit_cents=limit)


def _load_receivables(session, b: Block, res, as_of):
    ni, ai = 0, _col(b.headers, "amount")
    ti = _col(b.headers, "type", "reason", "for")
    for row in b.rows:
        if not row[ni]:
            continue
        name = _clean_name(row[ni])
        cents = _num(row[ai])
        if cents is None:
            res.skipped.append(f"Owed to me '{name}': no numeric amount")
            continue
        if cents == 0:
            res.skipped.append(f"Owed to me '{name}': $0.00 (not imported)")
            continue
        note = f"For: {row[ti]}" if ti is not None and row[ti] else None
        _upsert_account(session, res, name=name, account_type="receivable", balance=abs(cents), as_of=as_of,
                        notes=note)


def _load_expenses(session, b: Block, res, as_of):
    ni, ai = 0, _col(b.headers, "amount")
    di = _col(b.headers, "monthly date", "due date", "due day", "date", "due")
    gi = _col(b.headers, "aiming to pay monthly", "goal", "target payment")
    extra_cols = [i for i in range(len(b.headers)) if i not in (ni, ai, di, gi)]
    for row in b.rows:
        if not row[ni]:
            continue
        name = _clean_name(row[ni])
        amt = _num(row[ai])
        if amt is None:
            res.skipped.append(f"Expense '{name}': no numeric amount")
            continue
        due_day = _day(row[di]) if di is not None else None
        cls = classify_recurring(name)
        # A numeric value in an otherwise non-numeric column = remaining loan balance
        loan_balance = next((_num(row[i]) for i in extra_cols if _num(row[i]) is not None), None)
        reviews = []
        pays_account = None
        kind = cls.kind
        cat, sub = cls.category, cls.subcategory
        if loan_balance is not None:
            dtype = debt_type_for(name)
            if dtype == "other_debt" and not cls.matched:
                reviews.append("Has a balance in the workbook, imported as 'Other debt' — check the loan type.")
            kind = "debt_payment"
            if cat != "Debt Payments":
                cat, sub = "Debt Payments", {"auto_loan": "Auto Loan", "student_loan": "Student Loan"}.get(dtype, None)
            pays_account = _upsert_account(
                session, res, name=f"{name} loan", account_type=dtype, balance=abs(loan_balance), as_of=as_of,
                review="Add the interest rate (APR) to enable payoff estimates.",
                minimum_payment_cents=amt, payment_due_day=due_day,
            )
        if not cls.matched:
            reviews.append("Couldn't tell what this is from its name — set the category and type.")
        if due_day is None and kind in ("bill", "debt_payment"):
            reviews.append("No due date in the workbook — add one to see it on the bill calendar.")
        goal = _num(row[gi]) if gi is not None else None
        notes = f"Aiming to pay monthly: ${goal / 100:,.2f}" if goal else None
        category = find_category(session, sub, cat) if sub else None
        category = category or find_category(session, cat)
        review = " ".join(reviews) or None

        existing = session.scalar(select(bill_svc.Bill).where(bill_svc.Bill.name == name))
        if existing is None:
            bill_svc.create_bill(
                session, name=name, kind=kind, category_id=category.id if category else None, amount_cents=amt,
                frequency="monthly", due_day=due_day, pays_account_id=pays_account.id if pays_account else None,
                needs_review=bool(review), review_note=review, notes=notes, tracking_start=as_of,
            )
            res.created.append(f"Bill: {name} (${amt / 100:,.2f}/mo)")
        else:
            upd = {}
            if existing.amount_cents != amt:
                upd["amount_cents"] = amt
            if due_day is not None and existing.due_day != due_day:
                upd["due_day"] = due_day
            if pays_account is not None and existing.pays_account_id != pays_account.id:
                upd["pays_account_id"] = pays_account.id
            if upd:
                bill_svc.update_bill(session, existing.id, **upd)
                res.updated.append(f"Bill: {name} [{', '.join(upd)}]")
            else:
                res.unchanged.append(f"Bill: {name}")
            review = existing.review_note if existing.needs_review else None
        if review:
            res.flagged.append(f"Bill '{name}': {review}")


def _load_income(session, b: Block, res, as_of):
    ni, ai = 0, _col(b.headers, "amount")
    ti = _col(b.headers, "type")
    for row in b.rows:
        if not row[ni]:
            continue
        typ = _norm(row[ti]) if ti is not None else ""
        raw_name = str(row[ni])
        # The income table often carries computed rows like "Bills (Owe)" — skip formulas & non-income rows
        if _is_formula(row[ai]) or re.search(r"\b(owe|bills?|dues|expenses?)\b", raw_name.lower() + " " + typ):
            res.skipped.append(f"Income table row '{_clean_name(raw_name)}': calculated/non-income row")
            continue
        amt = _num(row[ai])
        if amt is None:
            res.skipped.append(f"Income '{_clean_name(raw_name)}': no numeric amount")
            continue
        name = _clean_name(raw_name)
        kind = "salary" if re.search(r"job|salary|wage|pay", typ + " " + name.lower()) else (
            "side_business" if re.search(r"side|business|freelance", typ) else "other")
        existing = session.scalar(select(income_svc.IncomeSource).where(income_svc.IncomeSource.name == name))
        if existing is None:
            income_svc.create_income(session, name=name, kind=kind, amount_cents=amt, frequency="monthly",
                                     is_net=True, notes=f"Imported from workbook ({row[ti]})" if ti is not None and row[ti] else None)
            res.created.append(f"Income: {name} (${amt / 100:,.2f}/mo)")
            res.flagged.append(f"Income '{name}': assumed monthly take-home pay — change it if that's gross or paid on a different schedule.")
        elif existing.amount_cents != amt:
            income_svc.update_income(session, existing.id, amount_cents=amt)
            res.updated.append(f"Income: {name} [amount]")
        else:
            res.unchanged.append(f"Income: {name}")
