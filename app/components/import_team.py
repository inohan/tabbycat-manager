import asyncio
import flet as ft
from googleapiclient.discovery import build
from io import BytesIO
import logging
import numpy as np
import os
import pandas as pd
import re
from typing import Any, Optional

import tabbycat_api as tc
from ..sheet_reader import SheetReader, ExcelReader, CSVReader, to_text, to_snake_case, to_bool
from ..base import AppControl, wait_finish, try_string
from ..exceptions import ExpectedError
from .google_picker import GoogleFilePicker, GoogleFilePickerResultEvent

FIELD_NAMES = ["institution", "break_categories", "reference", "short_reference", "use_institution_prefix", "speaker_1_name", "speaker_1_email", "speaker_1_categories", "speaker_2_name", "speaker_2_email", "speaker_2_categories", "speaker_3_name", "speaker_3_email", "speaker_3_categories"]
LOGGER = logging.getLogger(__name__)

def notna(value: Any) -> bool:
    return value is not None and value is not pd.NA and value is not np.nan
class TeamImporterRow(ft.DataRow, AppControl):
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
                case _:
                    return ft.Text(to_text(self.drow[index]))
        self.cells = [
            ft.DataCell(_get_content(col)) for col in self.drow.index
        ]
    
    def build(self):
        super().build()
        if notna(self.drow.get("reference")) and notna(self.drow.get("institution")) and self.app.tournament._links.teams.find(
            lambda team: team.reference == self.drow.get("reference") and team.institution and team.institution.code == self.drow.get("institution")
        ):
            self.selected = False
    
    def get_object(self) -> Optional[tc.models.Team]:
        if not self.selected:
            return None
        def _value(col: Any) -> Any:
            value = self.drow.get(col, tc.NULL)
            return value if notna(value) else tc.NULL
        speakers: list[tc.models.Speaker] = []
        for i in range(1, 10):
            if any(
                (
                    notna(self.drow.get(col, None))
                    for col in {f"speaker_{i}_name", f"speaker_{i}_email", f"speaker_{i}_categories"}
                )
            ) and _value(f"speaker_{i}_name"):
                speakers.append(
                    tc.models.Speaker(
                        name=_value(f"speaker_{i}_name"),
                        email=_value(f"speaker_{i}_email"),
                        categories=[self.app.tournament._links.speaker_categories.find(slug=to_snake_case(cat)) for cat in cats] if (cats:=_value(f"speaker_{i}_categories")) is not tc.NULL else [],
                    )
                )
        return tc.models.Team(
            institution=self.app.institutions.find(code=inst) if (inst:=_value("institution")) is not tc.NULL else tc.NULL,
            break_categories=[self.app.tournament._links.break_categories.find(slug=to_snake_case(cat)) for cat in _value("break_categories")] if (cats:=_value("break_categories")) is not tc.NULL else [],
            reference=_value("reference"),
            short_reference=_value("short_reference") or ref[:35] if (ref:=_value("reference")) is not tc.NULL else tc.NULL,
            use_institution_prefix=to_bool(value) if (value := _value("use_institution_prefix")) is not tc.NULL else tc.NULL,
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
            self.set_team_data()
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
            self.set_team_data()
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
            self.data_table.columns = [
                ft.DataColumn(ft.Text("No data"))
            ]
            self.data_table.rows.clear()
            return
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
    
    @wait_finish
    async def on_import(self, e):
        selected_rows: list[TeamImporterRow] = [row for row in self.data_table.rows if isinstance(row, TeamImporterRow) and row.selected]
        def get_name(data: pd.Series):
            if to_bool(data.get("use_institution_prefix", False)) and data.get("institution"):
                return f"{data.get('institution')} {data.get('reference')}"
            return data.get("reference")
        institutions_table: set[str] = {inst for row in selected_rows if pd.notna((inst := row.drow.get("institution")))}
        break_categories_table: set[str] = {bc for row in selected_rows if row.drow.get("break_categories", None) for bc in row.drow.get("break_categories")}
        speaker_categories_table: set[str] = {sc for row in selected_rows for i in range(1, 4) if (ls_scs := row.drow.get(f"speaker_{i}_categories")) for sc in ls_scs}
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
        # Missing break categories
        missing_break_categories = [cat for cat in break_categories_table if self.app.tournament._links.break_categories.find(slug=to_snake_case(cat)) is None]
        if missing_break_categories:
            col.controls.append(
                ft.ExpansionTile(
                    title=ft.Text("Missing Break Categories"),
                    controls=[ft.ListTile(ft.Text(bc)) for bc in missing_break_categories],
                    collapsed_text_color=ft.Colors.RED,
                    text_color=ft.Colors.RED,
                    subtitle=ft.Text(f"{len(missing_break_categories)} break categories will be created automatically")
                )
            )
        # Missing speaker categories
        missing_speaker_categories = [cat for cat in speaker_categories_table if self.app.tournament._links.speaker_categories.find(slug=to_snake_case(cat)) is None]
        if missing_speaker_categories:
            col.controls.append(
                ft.ExpansionTile(
                    title=ft.Text("Missing Speaker Categories"),
                    controls=[ft.ListTile(ft.Text(value=sc)) for sc in missing_speaker_categories],
                    collapsed_text_color=ft.Colors.RED,
                    text_color=ft.Colors.RED,
                    subtitle=ft.Text(f"{len(missing_speaker_categories)} speaker categories will be created automatically")
                )
            )
        # Teams to create
        col.controls.append(
            ft.ExpansionTile(
                title=ft.Text("Teams to Create"),
                controls=[ft.ListTile(ft.Text(f"{try_string(lambda: get_name(row.drow), "No name")}")) for row in selected_rows],
                subtitle=ft.Text(f"{len(selected_rows)} teams will be created")
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
            title=ft.Text("Import Teams?"),
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
        bc_seq = generate_seq(max(bc.seq for bc in self.app.tournament._links.break_categories) if len(self.app.tournament._links.break_categories) else 0)
        sc_seq = generate_seq(max(sc.seq for sc in self.app.tournament._links.speaker_categories) if len(self.app.tournament._links.speaker_categories) else 0)
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
            },
            **{
                f"break category \"{bc}\"": asyncio.create_task(
                    self.app.tournament.create(
                        tc.models.BreakCategory(
                            name=bc,
                            slug=to_snake_case(bc),
                            seq=next(bc_seq),
                            break_size=4,
                            is_general=False,
                            priority=1
                        )
                    )
                ) for bc in missing_break_categories
            },
            **{
                f"speaker category \"{sc}\"": asyncio.create_task(
                    self.app.tournament.create(
                        tc.models.SpeakerCategory(
                            name=sc,
                            slug=to_snake_case(sc),
                            seq=next(sc_seq)
                        )
                    )
                ) for sc in missing_speaker_categories
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
            get_name(row.drow): asyncio.create_task(self.app.tournament.create(obj)) for row in selected_rows
            if (obj := row.get_object()) is not None
        }
        await asyncio.gather(*tasks.values(), return_exceptions=True)
        has_exceptions: bool = False
        results: list[str] = []
        for name, task in tasks.items():
            if task.exception():
                LOGGER.error("Failed to create %s", name, exc_info=task.exception())
                results.append(f"Failed to create team \"{name}\": {task.exception()}")
                has_exceptions = True
            else:
                results.append(f"Created team \"{name}\" successfully")
        await asyncio.gather(
            self.app.update_teams(),
            self.app.update_speakers()
        )
        self.page.open(
            ft.SnackBar(
                ft.Text("\n".join(results), color=ft.Colors.BLACK),
                bgcolor=ft.Colors.RED_100 if has_exceptions else ft.Colors.GREEN_100
            )
        )