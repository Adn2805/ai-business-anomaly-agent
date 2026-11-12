"""Strict validation: never impute, aggregate, or infer rate units."""
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
import re

from openpyxl import load_workbook

METRICS = ('Revenue', 'Orders', 'Conversion_Rate', 'Traffic', 'Cost', 'Refunds')


class ValidationError(ValueError):
    pass


def load_data(path):
    path = Path(path)
    if path.suffix.lower() != '.xlsx':
        raise ValidationError('Input must be an .xlsx file.')
    try:
        book = load_workbook(path, read_only=True, data_only=False)
    except Exception as exc:
        raise ValidationError('Cannot read Excel input; check file existence and format.') from exc
    try:
        sheet = book.worksheets[0]
        rows = sheet.iter_rows()
        headers = [c.value for c in next(rows, [])]
        required = ('Date',) + METRICS
        if any(headers.count(name) != 1 for name in required):
            raise ValidationError('Required columns must appear exactly once: ' + ', '.join(required))
        indices = {name: headers.index(name) for name in required}
        records, seen = [], set()
        for number, cells in enumerate(rows, 2):
            if all(c.value is None for c in cells):
                continue
            record = {}
            for name, index in indices.items():
                cell = cells[index]
                value = cell.value
                prefix = f'Row {number}, {name}: '
                if value is None or value == '':
                    raise ValidationError(prefix + 'required value is missing.')
                if cell.data_type in ('f', 'e'):
                    raise ValidationError(prefix + 'formulas and Excel errors are not accepted; supply values.')
                if name == 'Date':
                    if isinstance(value, datetime):
                        if value.time() != datetime.min.time() or value.tzinfo:
                            raise ValidationError(prefix + 'must be a date without a time.')
                        value = value.date()
                    elif isinstance(value, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
                        try:
                            value = date.fromisoformat(value)
                        except ValueError as exc:
                            raise ValidationError(prefix + 'invalid calendar date.') from exc
                    if not isinstance(value, date):
                        raise ValidationError(prefix + 'use Excel dates or YYYY-MM-DD text.')
                else:
                    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
                        raise ValidationError(prefix + 'must be a numeric Excel cell.')
                    try:
                        value = Decimal(str(value))
                    except InvalidOperation as exc:
                        raise ValidationError(prefix + 'invalid number.') from exc
                    if not value.is_finite() or value < 0:
                        raise ValidationError(prefix + 'must be finite and nonnegative.')
                    if name == 'Conversion_Rate':
                        if '%' in cell.number_format:
                            raise ValidationError(prefix + 'percentage-formatted cells are ambiguous; supply 3.5 for 3.5%.')
                        if value > 100:
                            raise ValidationError(prefix + 'must be between 0 and 100 percentage points.')
                record[name] = value
            if record['Date'] in seen:
                raise ValidationError(f'Row {number}: duplicate reporting date.')
            seen.add(record['Date'])
            records.append(record)
        if not records:
            raise ValidationError('Input contains no records.')
        return sorted(records, key=lambda row: row['Date'])
    finally:
        book.close()
