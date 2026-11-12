from datetime import date, timedelta
from decimal import Decimal
import socket

import pytest
from openpyxl import Workbook

from app.data_loader import METRICS


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError('Tests must never access the network or send live email.')
    monkeypatch.setattr(socket, 'create_connection', blocked)
    monkeypatch.setattr(socket.socket, 'connect', blocked)


@pytest.fixture
def records():
    return [dict(Date=date(2026, 1, 1) + timedelta(days=i),
                 **{metric: Decimal('10') for metric in METRICS}) for i in range(8)]


@pytest.fixture
def excel(tmp_path):
    def write(rows=None, headers=None, edit=None):
        book = Workbook()
        sheet = book.active
        sheet.append(headers or ['Date', *METRICS])
        for row in rows if rows is not None else [
            [date(2026, 1, 1) + timedelta(days=i), 1000, 100, 3.5, 3000, 300, 10] for i in range(8)]:
            sheet.append(row)
        if edit:
            edit(sheet)
        path = tmp_path / 'input.xlsx'
        book.save(path)
        book.close()
        return path
    return write
