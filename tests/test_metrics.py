from datetime import date

from finance.calculations.metrics import (
    BalanceRow, Snapshot, net_worth_cents, net_worth_history, savings_rate, utilization,
)


def test_net_worth_assets_minus_liabilities():
    rows = [BalanceRow(1, 10_000_00, False), BalanceRow(2, 2_500_00, True), BalanceRow(3, 999_00, False, include=False)]
    assert net_worth_cents(rows) == (10_000_00, 2_500_00, 7_500_00)


def test_negative_net_worth():
    assert net_worth_cents([BalanceRow(1, 100, False), BalanceRow(2, 500, True)])[2] == -400


def test_savings_rate():
    assert savings_rate(4200_00, 3611_00) == (4200_00 - 3611_00) / 4200_00
    assert savings_rate(0, 100) is None
    assert savings_rate(1000, 1500) == -0.5


def test_utilization():
    assert utilization(1858_34, 17500_00) == 1858_34 / 17500_00
    assert utilization(100, None) is None
    assert utilization(100, 0) is None


def test_net_worth_history_carries_forward_latest_balance():
    s = [
        Snapshot(1, date(2026, 1, 1), 1000, False, 1),
        Snapshot(2, date(2026, 1, 1), 300, True, 2),
        Snapshot(1, date(2026, 2, 1), 1500, False, 3),  # account 2 unchanged -> still 300 owed
        Snapshot(2, date(2026, 3, 1), 100, True, 4),
        Snapshot(2, date(2026, 3, 1), 50, True, 5),  # same-day correction wins
    ]
    assert net_worth_history(s) == [
        (date(2026, 1, 1), 1000, 300, 700),
        (date(2026, 2, 1), 1500, 300, 1200),
        (date(2026, 3, 1), 1500, 50, 1450),
    ]
