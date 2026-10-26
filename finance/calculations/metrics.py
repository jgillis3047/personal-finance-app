"""Pure financial metric calculations (no database access)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable


@dataclass(frozen=True)
class BalanceRow:
    account_id: int
    balance_cents: int  # positive; owed amount for liabilities
    is_liability: bool
    include: bool = True


def net_worth_cents(rows: Iterable[BalanceRow]) -> tuple[int, int, int]:
    """Return (assets, liabilities, net_worth) in cents. Liabilities returned positive."""
    assets = liabilities = 0
    for r in rows:
        if not r.include:
            continue
        if r.is_liability:
            liabilities += r.balance_cents
        else:
            assets += r.balance_cents
    return assets, liabilities, assets - liabilities


def savings_rate(income_cents: int, spending_cents: int) -> float | None:
    """Share of income not spent. None when there is no income to measure against."""
    if income_cents <= 0:
        return None
    return (income_cents - spending_cents) / income_cents


def utilization(balance_cents: int, limit_cents: int | None) -> float | None:
    if not limit_cents:
        return None
    return balance_cents / limit_cents


@dataclass(frozen=True)
class Snapshot:
    account_id: int
    as_of: date
    balance_cents: int
    is_liability: bool
    seq: int = 0  # tie-breaker: later entry on same date wins


def net_worth_history(snapshots: Iterable[Snapshot]) -> list[tuple[date, int, int, int]]:
    """Net worth on each date that any snapshot exists, carrying each account's
    most recent known balance forward. Returns [(date, assets, liabilities, net)]."""
    snaps = sorted(snapshots, key=lambda s: (s.as_of, s.seq))
    latest: dict[int, Snapshot] = {}
    out: list[tuple[date, int, int, int]] = []
    i = 0
    while i < len(snaps):
        d = snaps[i].as_of
        while i < len(snaps) and snaps[i].as_of == d:
            latest[snaps[i].account_id] = snaps[i]
            i += 1
        a, l, n = net_worth_cents(BalanceRow(s.account_id, s.balance_cents, s.is_liability) for s in latest.values())
        out.append((d, a, l, n))
    return out
