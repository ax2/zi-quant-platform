import json

from app.paper_ledger import PaperAccountState, PaperPositionState
from app.paper_state_store import load_paper_account, paper_account_from_dict, paper_account_to_dict, save_paper_account


def test_account_dict_round_trip():
    account = PaperAccountState(
        cash=12345.67,
        positions={"000001.SZ": PaperPositionState("000001.SZ", 1000, 10.5, 88.0)},
    )

    restored = paper_account_from_dict(paper_account_to_dict(account))

    assert restored == account


def test_save_and_load_account(tmp_path):
    account = PaperAccountState(
        cash=20000.0,
        positions={
            "000001.SZ": PaperPositionState("000001.SZ", 1000, 10.0),
            "600000.SH": PaperPositionState("600000.SH", 500, 8.0, -20.0),
        },
    )
    path = tmp_path / "state" / "paper-account.json"

    save_paper_account(account, path)
    restored = load_paper_account(path)

    assert restored == account
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert list(payload["positions"]) == ["000001.SZ", "600000.SH"]


def test_load_defaults_realized_pnl_for_old_payload():
    account = paper_account_from_dict(
        {
            "cash": 1000,
            "positions": {"000001.SZ": {"shares": 100, "avg_cost": 10}},
        }
    )

    assert account.positions["000001.SZ"].realized_pnl == 0.0
