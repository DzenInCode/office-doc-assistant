"""Tests for the parser module."""
from __future__ import annotations

import io

import pandas as pd
import pytest
from openpyxl import Workbook

from src.parser import SUPPORTED_EXTENSIONS, parse


def _xlsx_bytes() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Sales"
    ws.append(["product", "qty", "price"])
    ws.append(["apple", 10, 0.5])
    ws.append(["banana", 5, 0.3])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _csv_bytes() -> bytes:
    df = pd.DataFrame({"x": [1, 2, 3], "y": ["a", "b", "c"]})
    return df.to_csv(index=False).encode()


def test_parse_xlsx_extracts_sheet_and_rows() -> None:
    text = parse("sales.xlsx", _xlsx_bytes())
    assert "Sales" in text
    assert "apple" in text
    assert "banana" in text


def test_parse_csv_roundtrips_dataframe() -> None:
    text = parse("data.csv", _csv_bytes())
    assert "x,y" in text
    assert "1,a" in text


def test_parse_unsupported_extension_raises() -> None:
    with pytest.raises(ValueError, match="Unsupported file type"):
        parse("image.png", b"")


def test_supported_extensions_are_documented() -> None:
    assert ".xlsx" in SUPPORTED_EXTENSIONS
    assert ".csv" in SUPPORTED_EXTENSIONS
    assert ".pdf" in SUPPORTED_EXTENSIONS
