import flet as ft
import logging
import os
import pandas as pd
import numpy as np
from typing import Any
import tabbycat_api as tc
import asyncio
from ..sheet_reader import SheetReader, ExcelReader, CSVReader, to_text
from ..base import AppControl, wait_finish
from .google_picker import GoogleFilePicker, GoogleFilePickerResultEvent
from googleapiclient.discovery import build

FIELD_NAMES = ["name", "institution", "email", "base_score", "independent", "adj_core"]
LOGGER = logging.getLogger(__name__)

def bool_value(value: Any) -> bool:
    return value in {"True", "true", "1", 1, "TRUE", "y", "Y", "YES", "yes", "Yes", True}
def notna(value: Any) -> bool:
    return value is not None and value is not pd.NA and value is not np.nan

class AdjudicatorImporterRow(ft.DataRow, AppControl):
    drow: pd.Series
    
    def __init__(self, data: pd.Series):
        self.drow = data
        super().__init__(
            []
        )
        self.sync_cells()
    
    def sync_cells(self):
        def _get_content(index: str):
            match index:
                case "independent":
                    val = self.drow.get(index, np.nan)
                    return ft.Icon(ft.Icons.CHECK if bool_value(val) else None) if notna(val) else ft.Text("-")
                case "adj_core":
                    val = self.drow.get(index, np.nan)
                    return ft.Icon(ft.Icons.CHECK if bool_value(val) else None) if notna(val) else ft.Text("-")
                case _:
                    return ft.Text(to_text(self.drow[index]))
        self.cells = [
            ft.DataCell(_get_content(col)) for col in self.drow.index
        ]
    
    async def get_object(self) -> tc.models.Adjudicator:
        def _value(col: Any) -> Any:
            value = self.drow.get(col, tc.NULL)
            return value if notna(value) else tc.NULL
        return tc.models.Adjudicator(
            name=_value("name"),
            institution=(await self.app.client.get_institutions()).find(code=inst) if (inst:=_value("institution")) is not tc.NULL else None,
            email=_value("email"),
            base_score=_value("base_score"),
            independent=bool_value(v) if (v:=_value("independent")) is not tc.NULL else tc.NULL,
            adj_core=bool_value(v) if (v:=_value("adj_core")) is not tc.NULL else tc.NULL,
            institution_conflicts=[],
            team_conflicts=[],
            adjudicator_conflicts=[],
        )

class AdjudicatorImporterPagelet(ft.Pagelet, AppControl):
    reader: SheetReader = None
    def __init__(self):
        self.file_picker = ft.FilePicker(on_result=self.on_result_file_pick, on_upload=self.on_upload_complete)
        self.dropdown_sheet_select = ft.Dropdown(
            label="Select Sheet"
        )
        self.button_sheet_select = ft.ElevatedButton(
            "Select sheet",
            on_click=self.on_select_sheet
        )
        self.data_table = ft.DataTable(
            columns=[ft.DataColumn(ft.Text("No data"))]
        )
        self.button_import = ft.ElevatedButton(
            "Import",
            on_click=self.on_import
        )
        super().__init__(
            ft.Column(
                [
                    ft.Row(
                        [
                            ft.ElevatedButton(
                                "Upload",
                                on_click=lambda _: self.file_picker.pick_files(dialog_title="Select a team list file", allowed_extensions=["xlsx", "xls", "csv"]),
                                icon=ft.Icons.UPLOAD_FILE
                            ),
                            ft.ElevatedButton(
                                "Select from Google Spreadsheets",
                                on_click=self.on_open_google_picker,
                                icon=ft.Icons.ADD_TO_DRIVE
                            )
                        ]
                    ),
                    self.dropdown_sheet_select,
                    self.button_sheet_select,
                    ft.Text(f"Supported columns: {', '.join(FIELD_NAMES)}"),
                    self.button_import,
                    ft.Row(
                        [
                            ft.Column(
                                [self.data_table],
                                expand=True,
                                scroll=ft.ScrollMode.AUTO
                            )
                        ],
                        expand=True,
                        scroll=ft.ScrollMode.AUTO
                    )
                ],
                expand=True
            ),
            expand=True,
        )
    
    def build(self):
        super().build()
        self.page.overlay.append(self.file_picker)
        self.set_sheet_select()
    
    @wait_finish
    async def on_open_google_picker(self, e):
        future = asyncio.Future()
        if self.app.oauth_credentials is None:
            raise Exception("Not logged in to Google. Please log in from top right corner.")
        service = build("drive", "v3", credentials=self.app.oauth_credentials)
        gp = GoogleFilePicker(
            mime_type=["application/vnd.google-apps.spreadsheet", "application/vnd.ms-excel", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "text/csv"],
            on_result=lambda e: future.set_result(e),
            service=service
        )
        self.page.open(
            gp
        )
        #await gp.load_path("root")
        result: GoogleFilePickerResultEvent = await future
        LOGGER.info("Got result")
        if result.data is not None:
            if result.data.get("mimeType") == "application/vnd.google-apps.spreadsheet":
                data: bytes = service.files().export(
                    fileId = result.data.get("id"),
                    mimeType = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                ).execute()
            else:
                data: bytes = service.files().get_media(
                    fileId = result.data.get("id")
                ).execute()
            if result.data.get("mimeType") == "text/csv":
                self.reader = CSVReader(data)
            else:
                self.reader = ExcelReader(path=data)
            self.set_sheet_select()
            self.update()
    
    def on_result_file_pick(self, e: ft.FilePickerResultEvent):
        uf: list[ft.FilePickerUploadFile] = []
        if self.file_picker.result is not None and self.file_picker.result.files is not None:
            for f in self.file_picker.result.files:
                uf.append(
                    ft.FilePickerUploadFile(
                        f.name,
                        upload_url=self.page.get_upload_url(f.name, 600),
                    )
                )
            if len(uf) != 1:
                self.page.open(
                    ft.SnackBar(
                        ft.Text("Please select only one file", color=ft.Colors.BLACK),
                        bgcolor=ft.Colors.RED_100
                    )
                )
            self.file_picker.upload(uf)
    
    def on_upload_complete(self, e: ft.FilePickerUploadEvent):
        if e.progress == 1.0:
            self.page.open(
                ft.SnackBar(
                    ft.Text(f"Upload of {e.file_name} complete", color=ft.Colors.BLACK),
                    bgcolor=ft.Colors.GREEN_100
                )
            )
            # Handle file formats
            file_path = os.path.join(os.getenv("FLET_ASSETS_DIR"), f"uploads/{e.file_name}")
            if e.file_name.endswith(".xlsx") or e.file_name.endswith(".xls"):
                self.reader = ExcelReader(path=file_path)
            elif e.file_name.endswith(".csv"):
                self.reader = CSVReader(file_path)
            else:
                self.page.open(
                    ft.SnackBar(
                        ft.Text("Unsupported file format", color=ft.Colors.BLACK),
                        bgcolor=ft.Colors.RED_100
                    )
                )
                return
            self.set_sheet_select()
            self.update()
    
    def on_select_sheet(self, e):
        self.reader.set_sheet(self.dropdown_sheet_select.value)
        self.set_sheet_select()
        self.set_adjudicator_data()
        self.update()
    
    def set_sheet_select(self):
        if self.reader and not self.reader.is_specified:
            self.dropdown_sheet_select.options = [
                ft.DropdownOption(
                    key=sheet,
                    text=sheet
                ) for sheet in self.reader.sheets
            ]
            self.dropdown_sheet_select.visible = True
            self.button_sheet_select.visible = True
            self.button_import.visible = False
        else:
            self.dropdown_sheet_select.visible = False
            self.button_sheet_select.visible = False
            self.button_import.visible = bool(self.reader)
    
    def set_adjudicator_data(self):
        if not (self.reader and self.reader.is_specified):
            self.page.open(
                ft.SnackBar(
                    ft.Text("Please upload a file first", color=ft.Colors.BLACK),
                    bgcolor=ft.Colors.RED_100
                )
            )
            return
        LOGGER.info("Loading adjudicator data")
        # Set data table
        self.data_table.columns = [
            ft.DataColumn(
                ft.Text(col, weight=ft.FontWeight.BOLD if col in FIELD_NAMES else ft.FontWeight.NORMAL)
            ) for col in self.reader.data.columns
        ]
        self.data_table.rows = [
            AdjudicatorImporterRow(self.reader.data.iloc[i]) for i in range(len(self.reader.data.index))
        ]
        self.set_sheet_select()
        self.update()
    
    async def on_import(self, e):
        self.button_import.disabled = True
        self.update()
        institutions = set(self.reader.data["institution"].dropna().unique()) if "institution" in self.reader.data.columns else []
        # Find missing objects
        col = ft.Column(
            [],
            expand=True,
            scroll=ft.ScrollMode.AUTO
        )
        # Missing institutions
        missing_institutions = [inst for inst in institutions if self.app.institutions.find(code=inst) is None]
        if missing_institutions:
            col.controls.append(
                ft.ExpansionTile(
                    title=ft.Text("Missing Institutions"),
                    controls=[ft.Text(inst) for inst in missing_institutions],
                    collapsed_text_color=ft.Colors.RED,
                    text_color=ft.Colors.RED,
                    subtitle=ft.Text(f"{len(missing_institutions)} institutions will be created automatically")
                )
            )
        # Adjudicators to create
        col.controls.append(
            ft.ExpansionTile(
                title=ft.Text("Adjudicators to Create"),
                controls=[ft.Text(f"{to_text(row.drow.get("name", np.nan))}") for row in self.data_table.rows],
                subtitle=ft.Text(f"{len(self.data_table.rows)} adjudicators will be created")
            )
        )
        async def on_confirm(e):
            self.page.close(dlg)
            try:
                async with asyncio.TaskGroup() as tg:
                    for inst in missing_institutions:
                        tg.create_task(
                            self.app.tournament.create(
                                tc.models.Institution(
                                    name=inst,
                                    code=inst
                                )
                            )
                        )
                # Sync PaginatedInstitutions etc.
                await asyncio.gather(
                    self.app.update_institutions()
                )
                # Create teams
                async with asyncio.TaskGroup() as tg:
                    for row in self.data_table.rows:
                        tg.create_task(
                            self.app.tournament.create(await row.get_object())
                        )
            except* BaseException as e:
                LOGGER.exception(e)
                self.page.open(
                    ft.SnackBar(
                        ft.Text(f"Error with creation: {e}", color=ft.Colors.BLACK),
                        bgcolor=ft.Colors.RED_100
                    )
                )
            else:
                # When all done, display Snack Bar
                self.page.open(
                    ft.SnackBar(
                        ft.Text("Adjudicators created successfully", color=ft.Colors.BLACK),
                        bgcolor=ft.Colors.GREEN_100
                    )
                )
            finally:
                self.button_import.disabled = False
                self.update()
        def on_close(e):
            self.page.close(dlg)
            self.button_import.disabled = False
            self.update()
        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("Import Adjudicators?"),
            content=col,
            actions=[
                ft.TextButton("Confirm", on_click=on_confirm),
                ft.TextButton("Cancel", on_click=lambda _: on_close),
            ]
        )
        self.page.open(dlg)