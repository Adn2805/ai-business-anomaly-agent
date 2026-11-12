from datetime import date, datetime
from decimal import Decimal

import pytest

from app.data_loader import load_data, ValidationError


def test_valid_sorted(excel):
    rows = load_data(excel(edit=lambda s: setattr(s['A2'], 'value', date(2025, 12, 30))))
    assert len(rows) == 8
    assert rows[0]['Date'] == date(2025, 12, 30)
    assert rows[0]['Conversion_Rate'] == Decimal('3.5')


@pytest.mark.parametrize('cell,value', [
    ('B1', 'Wrong'), ('B1', 'Date'), ('A2', '01/02/2026'), ('A2', '2026-02-30'),
    ('A2', datetime(2026, 1, 1, 12)), ('A2', None),
    ('B2', 'bad'), ('B2', '100'), ('B2', True), ('B2', -1), ('B2', None),
    ('D2', 101), ('D2', -0.1), ('B2', '=1+2'), ('A2', date(2026, 1, 2))])
def test_invalid(excel, cell, value):
    path = excel(edit=lambda s: setattr(s[cell], 'value', value))
    with pytest.raises(ValidationError):
        load_data(path)


def test_percentage_format_rejected(excel):
    path = excel(edit=lambda s: setattr(s['D2'], 'number_format', '0.0%'))
    with pytest.raises(ValidationError, match='ambiguous'):
        load_data(path)


def test_unformatted_numeric_date_rejected(excel):
    def edit(sheet):
        sheet['A2'] = 123
        sheet['A2'].number_format = 'General'
    with pytest.raises(ValidationError, match='Excel dates'):
        load_data(excel(edit=edit))


def test_iso_dates(excel):
    assert load_data(excel(edit=lambda s: setattr(s['A2'], 'value', '2026-01-01')))[0]['Date'] == date(2026, 1, 1)


def test_empty_and_unreadable(excel, tmp_path):
    with pytest.raises(ValidationError):
        load_data(excel(rows=[]))
    with pytest.raises(ValidationError):
        load_data(tmp_path / 'missing.xlsx')


def test_sorting(excel):
    rows = [[date(2026, 1, day), 100, 5, 3, 100, 10, 0] for day in (3, 1, 2)]
    assert [r['Date'].day for r in load_data(excel(rows))] == [1, 2, 3]
