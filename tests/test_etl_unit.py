"""Transformations and contract rules, with no database."""
import shutil
from collections import Counter

import pytest

from riten.etl.contract import SOURCES, TOTAL_ROWS, TOTAL_SYNTHETIC
from riten.etl.load import data_version, parse_flag, read_source
from riten.worker import rank_next


def test_contract_totals_match_the_audit():
    assert sum(s.rows for s in SOURCES) == TOTAL_ROWS == 7281
    assert sum(s.synthetic for s in SOURCES) == TOTAL_SYNTHETIC == 2069


@pytest.mark.parametrize("value,expected", [("0", False), ("1", True)])
def test_parse_flag_accepts_source_values(value, expected):
    assert parse_flag(value) is expected


@pytest.mark.parametrize("value", ["", "2", "true", "01", " 1"])
def test_parse_flag_rejects_anything_else(value):
    with pytest.raises(ValueError):
        parse_flag(value)


def test_read_source_rejects_changed_header(tmp_path):
    source = SOURCES[2]
    path = tmp_path / source.file
    path.write_text("budget_id,wrong_column\nBU1,1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="header differs"):
        read_source(path, source)


def test_read_source_rejects_short_row(tmp_path):
    source = SOURCES[5]
    path = tmp_path / source.file
    path.write_text(",".join(source.columns) + "\nCO1,NVIDIA\n", encoding="utf-8")
    with pytest.raises(ValueError, match="line 2"):
        read_source(path, source)


def test_read_source_reports_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        read_source(tmp_path / "absent.csv", SOURCES[0])


def test_data_version_changes_when_a_file_changes(tmp_path, settings):
    for source in SOURCES:
        shutil.copy(settings.data_dir / source.file, tmp_path / source.file)
    before = data_version(tmp_path)
    assert before == data_version(settings.data_dir)
    target = tmp_path / SOURCES[5].file
    target.write_text(target.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    assert data_version(tmp_path) != before


def test_rank_next_orders_by_frequency_and_is_deterministic():
    a, b, c, d = ("actor_profile", "A"), ("actor_profile", "B"), ("actor_profile", "C"), ("actor_profile", "D")
    table = {a: Counter({b: 5, c: 5, d: 2})}
    assert rank_next(table, a, 2) == [b, c]
    assert rank_next(table, a, 3) == [b, c, d]


def test_rank_next_ignores_rare_transitions_and_unknown_views():
    a, b = ("actor_profile", "A"), ("actor_profile", "B")
    assert rank_next({a: Counter({b: 1})}, a, 2) == []
    assert rank_next({}, a, 2) == []
