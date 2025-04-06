import pandas as pd
import numpy as np
import re
from typing import Any, Callable, Self, override
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

def to_snake_case(string: str) -> str:
    # Replace spaces and hyphens with underscores
    matches = re.findall(r"(?:[A-Z][a-z]*)|(?:[a-z]+)|(?:\d+)", string)
    return "_".join([match.lower() for match in matches])

def to_text[T](value: Callable[[], T]|T, nan: str = "-", error: str = "-") -> T:
    """Parses given text while handling nans and errors
    """
    if value is None or value is np.nan or value is pd.NA:
        return nan
    elif callable(value):
        try:
            return to_text(value())
        except Exception:
            return error
    else:
        return value

def column_index_to_letter(index):
    letter = ""
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        letter = chr(65 + remainder) + letter
    return letter

class SheetReader():
    _data: pd.DataFrame | dict[str, pd.DataFrame] = None
    
    @property
    def data(self) -> pd.DataFrame:
        if isinstance(self._data, pd.DataFrame):
            return self._data
        elif isinstance(self._data, dict):
            raise ValueError("Sheet name is not specified. Please specify.")
        else:
            raise ValueError("Data is not loaded.")
    
    @property
    def is_specified(self) -> bool:
        return isinstance(self._data, pd.DataFrame)
    
    @property
    def sheets(self) -> str|None:
        """Function to get the sheet names of the Excel file.

        Returns:
            str|None: Sheet names. None if the sheet is already specified.
        """
        if isinstance(self._data, dict):
            return list(self._data.keys())
        else:
            return None
    
    def set_sheet(self, sheet: int|str):
        if not isinstance(self._data, dict):
            raise ValueError("Data is already loaded or unloaded.")
        if isinstance(sheet, int):
            self._data = list(self._data.values())[sheet]
        elif isinstance(sheet, str):
            self._data = self._data[sheet]
        else:
            raise ValueError("Sheet name must be a string or an integer.")

class ExcelReader(SheetReader):
    def __init__(self, path: str, sheet: str|int|list[str|int]|None = None):
        self._data = pd.read_excel(
            io=path,
            sheet_name=sheet
        )
        if isinstance(self._data, dict):
            for df in self._data.values():
                df.rename(columns={old: to_snake_case(old) for old in df.columns}, inplace=True)
        else:
            self._data.rename(columns={old: to_snake_case(old) for old in self._data.columns}, inplace=True)
        if not self.is_specified and len(self.sheets) == 1:
            self.set_sheet(0)

class CSVReader(SheetReader):
    def __init__(self, path: str):
        self._data = pd.read_csv(
            path
        )
        self._data.rename(columns={old: to_snake_case(old) for old in self._data.columns}, inplace=True)

class SpreadsheetReader(SheetReader):
    spreadsheet_id: str = None
    service: Any = None
    
    def __init__(self, url_or_id: str, access_token: str):
        spreadsheet_id = re.search(r"\/spreadsheets\/d\/([a-zA-Z0-9-_]+)", url_or_id)
        if spreadsheet_id is not None:
            spreadsheet_id = spreadsheet_id.group(1)
        else:
            spreadsheet_id = url_or_id
        self.spreadsheet_id = spreadsheet_id
        credentials = Credentials(token=access_token)
        self.service = build("sheets", "v4", credentials=credentials)
        spreadsheet = self.service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
        self._data = {
            sheet["properties"]["title"]: (sheet["properties"]["gridProperties"]["rowCount"], sheet["properties"]["gridProperties"]["columnCount"]) for sheet in spreadsheet["sheets"]
        }
    
    @override
    def set_sheet(self, sheet: int|str):
        if not isinstance(self._data, dict):
            raise ValueError("Data is already loaded or unloaded.")
        if isinstance(sheet, int):
            sheet_name, size = self._data.items()[sheet]
        elif isinstance(sheet, str):
            sheet_name, size = sheet, self._data[sheet]
        else:
            raise ValueError("Sheet name must be a string or an integer.")
        range = f"{sheet_name}!A1:{column_index_to_letter(size[1])}{size[0]}"
        _data = self.service.spreadsheets().values().get(spreadsheetId=self.spreadsheet_id, range=range, majorDimension="ROWS").execute()["values"]
        max_length = max([len(row) for row in _data])
        _data = [row + [np.nan] * (max_length - len(row)) for row in _data]
        header = [to_snake_case(cell) if cell and pd.notna(cell) else f"column_{i}" for i, cell in enumerate(_data[0])]
        self._data = pd.DataFrame(_data[1:], columns=header)
        self._data.replace("", np.nan, inplace=True)