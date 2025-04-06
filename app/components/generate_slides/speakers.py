import asyncio
from typing import Literal, Optional
import flet as ft
from googleapiclient.discovery import build
import logging
import re
import tabbycat_api as tc
from dataclasses import dataclass, field
from ..google_picker import GoogleFilePicker, GoogleFilePickerResultEvent
from ...base import AppControl, wait_finish, try_string
from ...utils import ordinal, SlideData, create_slides, reversor
from ..editable_data_cell import EditableDataCell

LOGGER = logging.getLogger(__name__)

SpeakerMetrics = Literal["total", "average", "trimmed_mean", "team_points", "stdev", "count", "replies_sum", "replies_avg", "replies_stddev", "replies_count", "srank"]

@dataclass
class SpeakerData:
    standings: tc.models.SpeakerStanding
    num_metrics_include: int = field(default=0, init=False)
    title: str = field(default="", init=False)
    
    @property
    def speaker(self) -> tc.models.Speaker:
        return self.standings.speaker

class SpeakerDataRow(ft.DataRow, AppControl):
    speaker_data: SpeakerData
    def __init__(self, speaker_data: SpeakerData):
        self.speaker_data = speaker_data
        super().__init__(
            [
                ft.DataCell(ft.Text("")),
                ft.DataCell(ft.Text("")),
                ft.DataCell(ft.Text("")),
                ft.DataCell(ft.Text("")),
                EditableDataCell("", on_change=lambda _: setattr(self.speaker_data, "title", self.cells[4].value))
            ]
        )

    def build(self):
        super().build()
        self.reset_cells()
    
    def reset_cells(self):
        self.cells[0].content.value = try_string(lambda: self.speaker_data.speaker.name)
        self.cells[1].content.value = try_string(lambda: self.speaker_data.speaker.team.long_name, "")
        self.cells[2].content.value = try_string(lambda: self.speaker_data.standings.rank)
        self.cells[3].content.value = self.app.pagelets.pg_generate_slides.format_speaker_metrics(self.speaker_data.num_metrics_include, self.speaker_data.standings)
        self.cells[4].value = self.speaker_data.title

class SpeakerTab(ft.Tab, AppControl):
    is_reply: bool = False
    speaker_category: tc.models.SpeakerCategory
    __standings: tc.models.PaginatedSpeakerStandings
    __data: dict[str, SpeakerData]
    
    def __init__(self, speaker_category: tc.models.SpeakerCategory, is_reply: bool = False):
        self.speaker_category = speaker_category
        self.is_reply = is_reply
        self.__data = {}
        self.data_table = ft.DataTable(
            columns=[
                ft.DataColumn(ft.Text("Speaker"), tooltip="Replaces text {{name}}"),
                ft.DataColumn(ft.Text("Team"), tooltip="Replaces text {{team}}"),
                ft.DataColumn(ft.Text("Standings")),
                ft.DataColumn(ft.Text("Metrics"), tooltip="Replaces text {{metrics}}"),
                ft.DataColumn(ft.Text("Title"), tooltip="Replaces text {{title}}")
            ],
            expand=True
        )
        super().__init__(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.ElevatedButton(
                                text="Reload",
                                icon=ft.Icons.REFRESH,
                                on_click=self.on_reload
                            ),
                            ft.ElevatedButton(
                                text="Change Title",
                                icon=ft.Icons.ABC,
                                on_click=self.on_change_title
                            ),
                            ft.ElevatedButton(
                                text="Generate",
                                icon=ft.Icons.AUTO_AWESOME_MOTION,
                                on_click=self.on_generate
                            )
                        ]
                    ),
                    ft.Row(
                        [
                            ft.Column(
                                [
                                    self.data_table
                                ],
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
            text=("Reply" if self.is_reply else try_string(lambda: self.speaker_category.name) if self.speaker_category else "All") + " Speakers",
            icon=ft.Icons.PERSON
        )
    
    @property
    def num_necessary_metrics(self) -> int:
        return self.app.pagelets.pg_generate_slides.num_team_metrics_include
    
    def did_mount(self):
        super().did_mount()
        self.page.run_task(self.on_mount)
    
    async def on_mount(self):
        if not self.is_reply:
            self.__standings = await self.app.tournament.get_speaker_standings(self.speaker_category)
        else:
            self.__standings = await self.app.tournament.get_reply_standings(self.speaker_category)
        self.calculate()
        self.calculate_title("{} Best Reply Speaker" if self.is_reply else f"{try_string(lambda: self.speaker_category.name)} {{}} Best Speaker" if self.speaker_category else  "{} Best Speaker")
        self.update_table()
    
    @wait_finish
    async def on_reload(self, e: ft.ControlEvent):
        await self.__standings.load(force=True)
        self.calculate()
        self.update_table()
    
    @wait_finish
    def on_change_title(self, e: ft.ControlEvent):
        text_title = ft.TextField(
            value="{} Best Reply Speaker" if self.is_reply else f"{try_string(lambda: self.speaker_category.name)} {{}} Best Speaker" if self.speaker_category else  "{} Best Speaker",
            label="Format for title"
        )
        text_max_award = ft.TextField(
            value="10",
            label="Max number of awards",
            keyboard_type=ft.KeyboardType.NUMBER,
            visible=False
        )
        def on_save(e: ft.ControlEvent):
            self.calculate_title(format=text_title.value, max_award=int(text_max_award.value))
            self.update_table_display()
            self.page.close(dlg)
        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("Change Title"),
            content=ft.Column(
                [text_title, text_max_award],
                tight=True,
            ),
            actions=[
                ft.TextButton(
                    "Update",
                    on_click=on_save
                ),
                ft.TextButton(
                    "Cancel",
                    on_click=lambda _: self.page.close(dlg)
                )
            ]
        )
        self.page.open(dlg)
    
    @wait_finish
    async def on_generate(self, e: ft.ControlEvent):
        # Prompt the presentation file
        future_file = asyncio.Future()
        dlg_file = GoogleFilePicker(
            ft.Text("Select a file to edit"),
            mime_type=["application/vnd.google-apps.presentation"],
            on_result=future_file.set_result,
        )
        if not self.app.oauth_credentials:
            raise Exception("Not logged into Google.")
        self.page.open(dlg_file)
        result: GoogleFilePickerResultEvent = await future_file
        if not result.data:
            return
        # Get further information
        future_slide_prompt = asyncio.Future()
        service = build("slides", "v1", credentials=self.app.oauth_credentials)
        presentation = service.presentations().get(presentationId=result.data.get("id")).execute()
        num_institutions: set[int] = {0}.union({len(self.app.logos.get_object_logo_urls(row.speaker_data.speaker)) for row in self.data_table.rows})
        fields_slide_inst = {
            num_inst: ft.TextField(
                label=f"Slide for {num_inst} institutions",
                value="1",
                keyboard_type=ft.KeyboardType.NUMBER,
                prefix_text="Slide #"
            ) for num_inst in sorted(num_institutions)
        }
        field_slide_insert = ft.TextField(
            label="Slide to insert after",
            value=str(len(presentation.get("slides"))),
            keyboard_type=ft.KeyboardType.NUMBER,
        )
        check_ascending = ft.Checkbox(
            label="Ascending order (1st, 2nd, ...)",
            value=True,
        )
        check_danger = ft.Checkbox(
            label="Insert danger prevention slides",
            value=True
        )
        @wait_finish
        def on_confirm_create(e: ft.ControlEvent):
            slides_institution: dict[int, str] = {}
            for num_inst, field in fields_slide_inst.items():
                if 1 <= int(field.value) <= len(presentation.get("slides")):
                    slides_institution[num_inst] = presentation.get("slides")[int(field.value)-1].get("objectId")
                else:
                    raise ValueError(f"Invalid slide number for {num_inst} institutions: {field.value}")
            if not (0 <= int(field_slide_insert.value) <= len(presentation.get("slides"))):
                raise ValueError(f"Invalid slide number to insert after: {field_slide_insert.value}")
            self.page.close(dlg_settings)
            future_slide_prompt.set_result({
                "institutions": slides_institution,
                "insert_position": int(field_slide_insert.value),
                "ascending": check_ascending.value,
                "danger": check_danger.value
            })
        dlg_settings = ft.AlertDialog(
            modal=True,
            title=ft.Text("Select slides"),
            content=ft.Column(
                [
                    ft.Text("After which slide should the slides be inserted? (0=before first)"),
                    field_slide_insert,
                    ft.Divider(),
                    ft.Text("Select the slide template for each number of institution"),
                    *fields_slide_inst.values(),
                    ft.Divider(),
                    check_ascending,
                    check_danger
                ],
                tight=True
            ),
            actions=[
                ft.TextButton(
                    "Create",
                    on_click=on_confirm_create
                ),
                ft.TextButton(
                    "Cancel",
                    on_click=lambda _: (future_slide_prompt.set_result(None), self.page.close(dlg_settings))
                )
            ]
        )
        self.page.open(dlg_settings)
        result_settings = await future_slide_prompt
        if result_settings is None:
            return
        # Create the slides
        datas = list(data for data in self.get_data(ascending=result_settings["ascending"]) if data.title)
        slides: list[SlideData] = []
        for data in datas:
            duplicates = [d for d in datas if d.title == data.title]
            duplicate_title = f" ({duplicates.index(data)+1}/{len(duplicates)})" if len(duplicates) > 1 else ""
            if result_settings["danger"]:
                slides.append(
                    {
                        "texts": {
                            "{{title}}": data.title + duplicate_title,
                            "{{name}}": "",
                            "{{team}}": "",
                            "{{metrics}}": self.app.pagelets.pg_generate_slides.format_speaker_metrics(data.num_metrics_include, data.standings),
                        },
                        "images": set()
                    }
                )
            slides.append(
                {
                    "texts": {
                        "{{title}}": data.title + duplicate_title,
                        "{{name}}": try_string(lambda: data.speaker.name, "Redacted"),
                        "{{team}}": data.speaker.team.long_name if data.speaker and data.speaker.team else "",
                        "{{metrics}}": self.app.pagelets.pg_generate_slides.format_speaker_metrics(data.num_metrics_include, data.standings),
                    },
                    "images": self.app.logos.get_object_logo_urls(data.speaker) if data.speaker else set()
                }
            )
        LOGGER.info(f"Creating {len(slides)} speaker slides")
        create_slides(
            service,
            presentation.get("presentationId"),
            result_settings["institutions"],
            slides,
            result_settings["insert_position"],
            len(presentation.get("slides")),
        )
        LOGGER.info(f"Created {len(slides)} speaker slides")
        self.page.open(
            ft.SnackBar(
                ft.Text(f"Created {len(slides)} speaker slides", color=ft.Colors.BLACK),
                bgcolor=ft.Colors.GREEN_100
            )
        )
    
    def update_table(self):
        data_sorted = sorted(
            self.__data.values(),
            key=lambda x: (x.standings.rank, x.speaker.name if x.speaker else "Redacted")
        )
        self.data_table.rows = [
            SpeakerDataRow(speaker_data)
            for speaker_data in data_sorted
        ]
        self.data_table.update()
    
    def update_table_display(self):
        for row in self.data_table.rows:
            row.reset_cells()
        self.data_table.update()
    
    def calculate(self):
        dict_data: dict[str, SpeakerData] = {standing.speaker._href if standing.speaker else f"Redacted {i+1}": SpeakerData(standing) for i, standing in enumerate(self.__standings)}
        metrics_preference: list[SpeakerMetrics] = self.app.tournament._links.preferences.find(identifier="standings__speaker_standings_precedence").value
        # Calculate the metrics necessary for display
        for data in dict_data.values():
            filtered: list[SpeakerData] = list(dict_data.values())
            for i in range(len(metrics_preference)):
                filtered = [team_data for team_data in filtered if team_data.standings.metrics[i].value == data.standings.metrics[i].value]
                if len(filtered) == 1 and i+1 >= self.num_necessary_metrics:
                    data.num_metrics_include = i+1
                    break
            else:
                data.num_metrics_include = len(metrics_preference)
        self.__data.clear()
        self.__data.update(dict_data)
    
    def calculate_title(self, format: str = "{} Best Speaker", max_award: int = 10):
        for data in self.__data.values():
            data.title = re.sub(r"\b1st\s(?=[bB]est\b)", "", format.format(ordinal(data.standings.rank))) if data.standings.rank <= max_award else ""

    def get_data(self, ascending: bool = True) -> list[SpeakerData]:
        return sorted(
            self.__data.values(),
            key=lambda x: (x.standings.rank if ascending else reversor(x.standings.rank), try_string(lambda: x.speaker.name, "Redacted"))
        )