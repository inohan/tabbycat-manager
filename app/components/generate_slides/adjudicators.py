import asyncio
import flet as ft
from googleapiclient.discovery import build
import logging
import re
from typing import Literal, Optional
import tabbycat_api as tc
from dataclasses import dataclass, field
from ..google_picker import GoogleFilePicker, GoogleFilePickerResultEvent
from ...utils import reversor, ordinal, rank_with_ties, SlideData, create_slides
from ...base import AppControl, wait_finish, try_string
from ..editable_data_cell import EditableDataCell

LOGGER = logging.getLogger(__name__)

@dataclass
class AdjudicatorData:
    adjudicator: tc.models.Adjudicator
    feedbacks: list[tc.models.Feedback] = field(default_factory=list)
    weighted_score: float = 0.0
    title: str = field(default="", init=False)

class AdjudicatorDataRow(ft.DataRow, AppControl):
    adjudicator_data: AdjudicatorData
    def __init__(self, adjudicator_data: AdjudicatorData):
        self.adjudicator_data = adjudicator_data
        super().__init__(
            [
                ft.DataCell(ft.Text("")),
                ft.DataCell(ft.Text("")),
                ft.DataCell(ft.Text("")),
                ft.DataCell(ft.Text("")),
                ft.DataCell(ft.Icon()),
                ft.DataCell(ft.Icon()),
                ft.DataCell(ft.Icon()),
                EditableDataCell("", on_change=lambda _: setattr(self.adjudicator_data, "title", self.cells[7].value))
            ]
        )
    
    def build(self):
        super().build()
        self.reset_cells()
    
    def reset_cells(self):
        valid_feedbacks = [feedback for feedback in self.adjudicator_data.feedbacks if feedback.confirmed and not feedback.ignored]
        self.cells[0].content.value = try_string(lambda: self.adjudicator_data.adjudicator.name)
        self.cells[1].content.value = try_string(lambda: self.adjudicator_data.adjudicator.base_score)
        self.cells[2].content.value = f"{sum([fb.score for fb in valid_feedbacks])/len(valid_feedbacks):.3f}" if len(valid_feedbacks) else "0.000"
        self.cells[2].content.tooltip = f"Total {sum([fb.score for fb in valid_feedbacks])} points for {len(valid_feedbacks)} valid feedback(s)"
        self.cells[3].content.value = self.app.pagelets.pg_generate_slides.format_adjudicator_score(self.adjudicator_data.weighted_score)
        self.cells[4].content.name = ft.Icons.CHECK if self.adjudicator_data.adjudicator.adj_core else None
        self.cells[5].content.name = ft.Icons.CHECK if self.adjudicator_data.adjudicator.independent else None
        self.cells[6].content.name = ft.Icons.CHECK if self.adjudicator_data.adjudicator.breaking else None
        self.cells[7].value = self.adjudicator_data.title

class AdjudicatorTab(ft.Tab, AppControl):
    __data: dict[str, AdjudicatorData]
    feedback_weight: float = 1.0
    use_rounded: bool = True
    
    def __init__(self):
        self.__data = {}
        self.data_table = ft.DataTable(
            columns=[
                ft.DataColumn(ft.Text("Name"), tooltip="Replaces text {{name}}"),
                ft.DataColumn(ft.Text("BS"), tooltip="Base Score"),
                ft.DataColumn(ft.Text("FS"), tooltip="Feedback Score"),
                ft.DataColumn(ft.Text("Metrics"), tooltip="Weighted Score, replaces text {{score}}"),
                ft.DataColumn(ft.Text("AdjCore")),
                ft.DataColumn(ft.Text("IA")),
                ft.DataColumn(ft.Text("Breaking")),
                ft.DataColumn(ft.Text("Title"), tooltip="Replaces text {{title}}"),
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
                                text="Change Calculation",
                                icon=ft.Icons.CALCULATE,
                                on_click=self.on_change_calculation
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
            text="Adjudicators",
            icon=ft.Icons.BALANCE
        )
    
    def did_mount(self):
        super().did_mount()
        self.page.run_task(self.on_mount)
    
    async def on_mount(self):
        self.calculate()
        self.calculate_title()
        self.update_table()
    
    @wait_finish
    async def on_reload(self, e: ft.ControlEvent):
        await self.app.update_feedback()
        self.calculate()
        self.calculate_title()
        self.update_table()
    
    @wait_finish
    def on_change_title(self, e: ft.ControlEvent):
        text_title = ft.TextField(
            value="{} Best Adjudicator",
            label="Format for title"
        )
        text_max_award = ft.TextField(
            value="5",
            label="Max number of awards",
            keyboard_type=ft.KeyboardType.NUMBER,
        )
        @wait_finish
        def on_save(e: ft.ControlEvent):
            self.calculate_title(format=text_title.value, max_award=int(text_max_award.value))
            self.update_table_display()
            self.page.close(dlg)
        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("Change Title"),
            content=ft.Column(
                [text_title, text_max_award],
                tight=True
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
    def on_change_calculation(self, e: ft.ControlEvent):
        text_weight = ft.TextField(
            value=str(self.feedback_weight),
            label="Weight for feedback score (0.0=base score, 1.0=feedback score)",
            keyboard_type=ft.KeyboardType.NUMBER
        )
        check_round = ft.Checkbox(
            label="Round score",
            value=self.use_rounded
        )
        @wait_finish
        def on_save(e: ft.ControlEvent):
            self.feedback_weight = float(text_weight.value)
            self.use_rounded = check_round.value
            self.calculate_score()
            self.calculate_title()
            self.update_table_display()
            self.page.close(dlg)
        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("Change Calculation"),
            content=ft.Column(
                [text_weight, check_round],
                tight=True
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
        num_institutions: set[int] = {0}.union({len(self.app.logos.get_object_logo_urls(row.adjudicator_data.adjudicator)) for row in self.data_table.rows})
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
                            "{{metrics}}": self.app.pagelets.pg_generate_slides.format_adjudicator_score(data.weighted_score),
                        },
                        "images": set()
                    }
                )
            slides.append(
                {
                    "texts": {
                        "{{title}}": data.title + duplicate_title,
                        "{{name}}": try_string(lambda: data.adjudicator.name, "Redacted"),
                        "{{metrics}}": self.app.pagelets.pg_generate_slides.format_adjudicator_score(data.weighted_score),
                    },
                    "images": self.app.logos.get_object_logo_urls(data.adjudicator)
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
                ft.Text(f"Created {len(slides)} slides", color=ft.Colors.BLACK),
                bgcolor=ft.Colors.GREEN_100
            )
        )
    
    def update_table(self):
        data_sorted = sorted(
            self.__data.values(),
            key=lambda x: (reversor(x.weighted_score), x.adjudicator.name)
        )
        self.data_table.rows = [
            AdjudicatorDataRow(adj_data)
            for adj_data in data_sorted
        ]
        self.data_table.update()
    
    def update_table_display(self):
        for row in self.data_table.rows:
            row.reset_cells()
        self.data_table.update()
    
    def calculate(self):
        adjudicators = self.app.tournament._links.adjudicators
        dict_data: dict[str, AdjudicatorData] = {adj._href: AdjudicatorData(adj) for adj in adjudicators}
        for feedback in self.app.tournament._links.feedback:
            if not feedback.adjudicator:
                continue
            data = dict_data.get(feedback.adjudicator._href)
            data.feedbacks.append(feedback)
        self.__data.clear()
        self.__data.update(dict_data)
        self.calculate_score()
    
    def calculate_score(self) -> float:
        for adjudicator_data in self.__data.values():
            num_valid_feedback = 0
            sum_feedback = 0.0
            for feedback in adjudicator_data.feedbacks:
                if feedback.confirmed and not feedback.ignored:
                    num_valid_feedback += 1
                    sum_feedback += feedback.score
            if num_valid_feedback: # If there are valid feedbacks
                weighted_score = self.feedback_weight * (sum_feedback/num_valid_feedback) + (1-self.feedback_weight) * adjudicator_data.adjudicator.base_score
            else:
                weighted_score = adjudicator_data.adjudicator.base_score
            if self.use_rounded:
                weighted_score = round(weighted_score, 1)
            adjudicator_data.weighted_score = weighted_score

    def calculate_title(self, format: str = "{} Best Adjudicator", max_award: int = 5):
        # Get the top adjudicators
        eligible_adjs = list(adj_data for adj_data in self.__data.values() if not adj_data.adjudicator.adj_core)
        rankings = rank_with_ties(eligible_adjs, key=lambda x: x.weighted_score)
        for data in self.__data.values():
            data.title = ""
        for ranking, data in zip(rankings, eligible_adjs):
            if ranking > max_award:
                continue
            data.title = re.sub(r"\b1st\s(?=[bB]est\b)", "", format.format(ordinal(ranking)))

    def get_data(self, ascending: bool = True) -> list[AdjudicatorData]:
        return sorted(
            self.__data.values(),
            key=lambda x: (reversor(x.weighted_score) if ascending else x.weighted_score, x.adjudicator.name)
        )