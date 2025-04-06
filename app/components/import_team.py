import flet as ft
import logging
import os
import pandas as pd
import re
import numpy as np
from typing import Any
import tabbycat_api as tc
import asyncio
from ..sheet_reader import SheetReader, ExcelReader, CSVReader, to_text, to_snake_case
from ..base import AppControl, wait_finish
from .google_picker import GoogleFilePicker, GoogleFilePickerResultEvent
from googleapiclient.discovery import build

FIELD_NAMES = ["institution", "break_categories", "reference", "short_reference", "use_institution_prefix", "speaker_1_name", "speaker_1_email", "speaker_1_categories", "speaker_2_name", "speaker_2_email", "speaker_2_categories", "speaker_3_name", "speaker_3_email", "speaker_3_categories"]
LOGGER = logging.getLogger(__name__)

class TeamImporterRow(ft.DataRow, AppControl):
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
                case _:
                    return ft.Text(to_text(self.drow[index]))
        self.cells = [
            ft.DataCell(_get_content(col)) for col in self.drow.index
        ]
    
    async def get_object(self) -> tc.models.Team:
        def notna(value: Any) -> bool:
            return value is not None and value is not pd.NA and value is not np.nan
        def _value(col: Any) -> Any:
            value = self.drow.get(col, tc.NULL)
            return value if notna(value) else tc.NULL
        
        valid_speakers: set[int] = set()
        speakers: list[tc.models.Speaker] = []
        for i in range(1, 10):
            if any(
                (
                    notna(self.drow.get(col, None))
                    for col in {f"speaker_{i}_name", f"speaker_{i}_email", f"speaker_{i}_categories"}
                )
            ):
                valid_speakers.add(i)
                speakers.append(
                    tc.models.Speaker(
                        name=_value(f"speaker_{i}_name"),
                        email=_value(f"speaker_{i}_email"),
                        categories=[self.app.tournament._links.speaker_categories.find(name=cat) for cat in cats] if (cats:=_value(f"speaker_{i}_categories")) is not tc.NULL else tc.NULL,
                    )
                )
        return tc.models.Team(
            institution=(await self.app.client.get_institutions()).find(code=inst) if (inst:=_value("institution")) is not tc.NULL else tc.NULL,
            break_categories=[self.app.tournament._links.break_categories.find(name=cat) for cat in _value("break_categories")] if (cats:=_value("break_categories")) is not tc.NULL else tc.NULL,
            reference=_value("reference"),
            short_reference=_value("short_reference") or ref[:35] if (ref:=_value("reference")) is not tc.NULL else tc.NULL,
            use_institution_prefix=_value("use_institution_prefix"),
            speakers=speakers
        )

class TeamImporterPagelet(ft.Pagelet, AppControl):
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
                            ),
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
        service = build("drive", "v3", credentials=self.app.oauth_credentials)
        gp = GoogleFilePicker(
            mime_type=["application/vnd.google-apps.spreadsheet", "application/vnd.ms-excel", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "text/csv"],
            on_result=lambda e: future.set_result(e),
            service=service
        )
        self.page.open(
            gp
        )
        await gp.load_path("root")
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
        self.set_team_data()
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
    
    def set_team_data(self):
        if not (self.reader and self.reader.is_specified):
            self.page.open(
                ft.SnackBar(
                    ft.Text("Please upload a file first", color=ft.Colors.BLACK),
                    bgcolor=ft.Colors.RED_100
                )
            )
            return
        LOGGER.info("Loading team data")
        # Turn comma-separated categories into lists
        for col in ["break_categories", "speaker_1_categories", "speaker_2_categories", "speaker_3_categories"]:
            if col not in self.reader.data.columns:
                continue
            self.reader.data[col].fillna("", inplace=True)
            self.reader.data[col] = self.reader.data[col].apply(
                lambda x: np.nan if pd.isna(x) else re.split(r"\s*,\s*", x) if x else []
            )
        # Set data table
        self.data_table.columns = [
            ft.DataColumn(
                ft.Text(col, weight=ft.FontWeight.BOLD if col in FIELD_NAMES else ft.FontWeight.NORMAL)
            ) for col in self.reader.data.columns
        ]
        self.data_table.rows = [
            TeamImporterRow(self.reader.data.iloc[i]) for i in range(len(self.reader.data.index))
        ]
        self.set_sheet_select()
        self.update()
    
    async def on_import(self, e):
        self.button_import.disabled = True
        self.update()
        institutions = set(self.reader.data["institution"].dropna().unique()) if "institution" in self.reader.data.columns else []
        break_categories = set(self.reader.data["break_categories"].explode().dropna().unique()) if "break_categories" in self.reader.data.columns else []
        speaker_categories = set()
        for i in range(1, 4):
            if f"speaker_{i}_categories" in self.reader.data.columns:
                speaker_categories.update(self.reader.data[f"speaker_{i}_categories"].explode().dropna().unique())
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
        # Missing break categories
        missing_break_categories = [cat for cat in break_categories if self.app.tournament._links.break_categories.find(name=cat) is None]
        if missing_break_categories:
            col.controls.append(
                ft.ExpansionTile(
                    title=ft.Text("Missing Break Categories"),
                    controls=[ft.Text(bc) for bc in missing_break_categories],
                    collapsed_text_color=ft.Colors.RED,
                    text_color=ft.Colors.RED,
                    subtitle=ft.Text(f"{len(missing_break_categories)} break categories will be created automatically")
                )
            )
        # Missing speaker categories
        missing_speaker_categories = [cat for cat in speaker_categories if self.app.tournament._links.speaker_categories.find(name=cat) is None]
        if missing_speaker_categories:
            col.controls.append(
                ft.ExpansionTile(
                    title=ft.Text("Missing Speaker Categories"),
                    controls=[ft.Text(value=sc) for sc in missing_speaker_categories],
                    collapsed_text_color=ft.Colors.RED,
                    text_color=ft.Colors.RED,
                    subtitle=ft.Text(f"{len(missing_speaker_categories)} speaker categories will be created automatically")
                )
            )
        # Teams to create
        col.controls.append(
            ft.ExpansionTile(
                title=ft.Text("Teams to Create"),
                controls=[ft.Text(f"{to_text(row.drow.get("reference", np.nan))}") for row in self.data_table.rows],
                subtitle=ft.Text(f"{len(self.data_table.rows)} teams will be created")
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
                    for bc in missing_break_categories:
                        tg.create_task(
                            self.app.tournament.create(
                                tc.models.BreakCategory(
                                    name=bc,
                                    slug=to_snake_case(bc),
                                    seq=max([x.seq for x in self.app.tournament._links.break_categories] + [-1]) + 1,
                                    break_size=2,
                                    is_general=False,
                                    priority=0
                                )
                            )
                        )
                    for sc in missing_speaker_categories:
                        tg.create_task(
                            self.app.tournament.create(
                                tc.models.SpeakerCategory(
                                    name=sc,
                                    slug=to_snake_case(sc),
                                    seq=max([x.seq for x in self.app.tournament._links.speaker_categories] + [-1]) + 1
                                )
                            )
                        )
                # Sync PaginatedInstitutions etc.
                await asyncio.gather(
                    self.app.update_institutions(),
                    self.app.update_break_categories(),
                    self.app.update_speaker_categories()
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
                        ft.Text("Teams created successfully", color=ft.Colors.BLACK),
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
            title=ft.Text("Import Teams?"),
            content=col,
            actions=[
                ft.TextButton("Confirm", on_click=on_confirm),
                ft.TextButton("Cancel", on_click=lambda _: on_close),
            ]
        )
        self.page.open(dlg)