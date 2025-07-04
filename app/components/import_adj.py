import asyncio
import flet as ft
from googleapiclient.discovery import build
from io import BytesIO
import logging
import numpy as np
import os
import pandas as pd
from typing import Any, Optional
import tabbycat_api as tc
from ..sheet_reader import SheetReader, ExcelReader, CSVReader, to_text, to_bool
from ..base import AppControl, wait_finish, try_string
from ..exceptions import ExpectedError
from .google_picker import GoogleFilePicker, GoogleFilePickerResultEvent

FIELD_NAMES = ["name", "institution", "email", "base_score", "independent", "adj_core"]
LOGGER = logging.getLogger(__name__)

def notna(value: Any) -> bool:
    return value is not None and value is not pd.NA and value is not np.nan

class AdjudicatorImporterRow(ft.DataRow, AppControl):
    drow: pd.Series
    
    def __init__(self, data: pd.Series):
        self.drow = data
        def on_select(e: ft.ControlEvent):
            self.selected = not self.selected
            self.update()
        super().__init__(
            [],
            selected=True,
            on_select_changed=on_select
        )
        self.sync_cells()
    
    def sync_cells(self):
        def _get_content(index: str):
            match index:
                case "independent":
                    val = self.drow.get(index, np.nan)
                    return ft.Icon(ft.Icons.CHECK if to_bool(val) else None) if notna(val) else ft.Text("-")
                case "adj_core":
                    val = self.drow.get(index, np.nan)
                    return ft.Icon(ft.Icons.CHECK if to_bool(val) else None) if notna(val) else ft.Text("-")
                case _:
                    return ft.Text(to_text(self.drow[index]))
        self.cells = [
            ft.DataCell(_get_content(col)) for col in self.drow.index
        ]
    
    def build(self):
        super().build()
        if notna(self.drow.get("name")) and self.app.tournament._links.adjudicators.find(
            lambda adj: adj.name == self.drow.get("name")
        ):
            self.selected = False
    
    def get_object(self) -> Optional[tc.models.Adjudicator]:
        if not self.selected:
            return None
        def _value(col: Any) -> Any:
            value = self.drow.get(col, tc.NULL)
            return value if notna(value) else tc.NULL
        return tc.models.Adjudicator(
            name=_value("name"),
            institution=self.app.institutions.find(code=inst) if (inst:=_value("institution")) is not tc.NULL else None,
            email=_value("email"),
            base_score=v if ((v:=_value("base_score")) is not tc.NULL and not np.isnan(v)) else tc.NULL,
            independent=to_bool(v) if (v:=_value("independent")) is not tc.NULL else tc.NULL,
            adj_core=to_bool(v) if (v:=_value("adj_core")) is not tc.NULL else tc.NULL,
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
            columns=[ft.DataColumn(ft.Text("No data"))],
            show_checkbox_column=True
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
        if not self.page.auth:
            raise ExpectedError("Not logged in to Google")
        service = build("drive", "v3", credentials=self.app.oauth_credentials)
        gp = GoogleFilePicker(
            mime_type=["application/vnd.google-apps.spreadsheet", "application/vnd.ms-excel", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "text/csv"],
            on_result=lambda e: future.set_result(e),
            service=service
        )
        self.page.open(
            gp
        )
        result: GoogleFilePickerResultEvent = await future
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
                self.reader = CSVReader(BytesIO(data))
            else:
                self.reader = ExcelReader(path=BytesIO(data))
            self.set_sheet_select()
            self.set_adjudicator_data()
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
            self.set_adjudicator_data()
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
            self.data_table.columns = [
                ft.DataColumn(ft.Text("No data"))
            ]
            self.data_table.rows.clear()
            return
        LOGGER.info("Loading adjudicator data")
        if "base_score" in self.reader.data.columns:
            self.reader.data["base_score"].astype(float)
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
    
    @wait_finish
    async def on_import(self, e):
        selected_rows: list[AdjudicatorImporterRow] = [row for row in self.data_table.rows if isinstance(row, AdjudicatorImporterRow) and row.selected]
        institutions_table: set[str] = {inst for row in selected_rows if pd.notna((inst := row.drow.get("institution")))}
        # Find missing objects
        col = ft.Column(
            [],
            expand=True,
            scroll=ft.ScrollMode.AUTO
        )
        # Missing institutions
        missing_institutions = [inst for inst in institutions_table if self.app.institutions.find(code=inst) is None]
        if missing_institutions:
            col.controls.append(
                ft.ExpansionTile(
                    title=ft.Text("Missing Institutions"),
                    controls=[ft.ListTile(ft.Text(inst)) for inst in missing_institutions],
                    collapsed_text_color=ft.Colors.RED,
                    text_color=ft.Colors.RED,
                    subtitle=ft.Text(f"{len(missing_institutions)} institutions will be created automatically")
                )
            )
        # Teams to create
        col.controls.append(
            ft.ExpansionTile(
                title=ft.Text("Teams to Create"),
                controls=[ft.ListTile(ft.Text(f"{try_string(lambda: row.drow.get("name"), "No name")}")) for row in selected_rows],
                subtitle=ft.Text(f"{len(selected_rows)} adjudicators will be created")
            )
        )
        future = asyncio.Future()
        def on_confirm(e):
            self.page.close(dlg)
            future.set_result(True)
        def on_cancel(e):
            self.page.close(dlg)
            future.set_result(False)
        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("Import Adjudicators?"),
            content=col,
            actions=[
                ft.TextButton("Confirm", on_click=on_confirm),
                ft.TextButton("Cancel", on_click=on_cancel),
            ]
        )
        self.page.open(dlg)
        result = await future
        if not result:
            return
        # Create missing objects
        def generate_seq(i: Optional[int] = None):
            if i is None:
                i = 0
            while True:
                i += 1
                yield i
        tasks: dict[str, asyncio.Task] = {
            **{
                f"institution \"{inst}\"": asyncio.create_task(
                    self.app.tournament.create(
                        tc.models.Institution(
                            name=inst,
                            code=inst
                        )
                    )
                ) for inst in missing_institutions
            }
        }
        # Wait for all tasks to finish
        await asyncio.gather(*tasks.values(), return_exceptions=True)
        exceptions: list[str] = []
        for name, task in tasks.items():
            if task.exception():
                LOGGER.error("Failed to create %s", name, exc_info=task.exception())
                exceptions.append(f"Failed to create {name}: {task.exception()}")
        if len(exceptions):
            self.page.open(
                ft.SnackBar(
                    ft.Text("\n".join(exceptions), color=ft.Colors.BLACK),
                    bgcolor=ft.Colors.RED_100
                )
            )
            return
        await asyncio.gather(
            self.app.update_institutions(),
            self.app.update_break_categories(),
            self.app.update_speaker_categories()
        )
        # Create teams
        tasks = {
            row.drow.get("name"): asyncio.create_task(self.app.tournament.create(obj)) for row in selected_rows
            if (obj := row.get_object()) is not None
        }
        await asyncio.gather(*tasks.values(), return_exceptions=True)
        has_exceptions: bool = False
        results: list[str] = []
        for name, task in tasks.items():
            if task.exception():
                LOGGER.error("Failed to create %s", name, exc_info=task.exception())
                results.append(f"Failed to create adjudicator \"{name}\": {task.exception()}")
                has_exceptions = True
            else:
                results.append(f"Created adjudicator \"{name}\" successfully")
        await asyncio.gather(
            self.app.update_adjudicators()
        )
        self.page.open(
            ft.SnackBar(
                ft.Text("\n".join(results), color=ft.Colors.BLACK),
                bgcolor=ft.Colors.RED_100 if has_exceptions else ft.Colors.GREEN_100
            )
        )