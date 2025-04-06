from typing import Any, Optional, Literal
import flet as ft
import tabbycat_api as tc
import logging

from .teams import TeamTab, TeamMetrics
from .speakers import SpeakerTab, SpeakerMetrics
from .adjudicators import AdjudicatorTab
from ...base import AppControl, wait_finish, try_string

LOGGER = logging.getLogger(__name__)

DESCRIPTION_TEAM_METRICS: dict[TeamMetrics, str] = {
    "speaks_ind_avg": "Average individual speaker score",
    "margin_avg": "Average margin",
    "speaks_avg": "Average total speaker score",
    "draw_strength_speaks": "Draw strength by total speaker score",
    "draw_strength": "Draw strength by wins",
    "firsts": "Number of firsts",
    "npullups": "Number of pullups",
    "seconds": "Number of seconds",
    "thirds": "Number of thirds",
    "pullup_debates": "Number of times in pullup debates",
    "num_iron": "Number of times ironed",
    "points": "Points",
    "speaks_stddev": "Speaker score standard deviation",
    "margin_sum": "Sum of margins",
    "speaks_sum": "Total speaker score",
    "num_adjs": "Votes/ballots carried",
    "wbw": "Who-beat-whom",
    "wins": "Wins"
}
DESCRIPTION_SPEAKER_METRICS: dict[SpeakerMetrics, str] = {
    "total": "Total",
    "average": "Average",
    "trimmed_mean": "Trimmed mean (high-low drop)",
    "team_points": "Team points",
    "stdev": "Standard deviation",
    "count": "Number of speeches given",
    "replies_sum": "Total (reply)",
    "replies_avg": "Average (reply)",
    "replies_stddev": "Standard deviation (reply)",
    "replies_count": "Number of speeches given (reply)",
    "srank": "Speech ranks"
}

class SlideGeneratorPagelet(ft.Pagelet, AppControl):
    dict_team_format: dict[TeamMetrics, str]
    num_team_metrics_include: int = 2
    dict_speaker_format: dict[SpeakerMetrics, str]
    num_speaker_metrics_include: int = 2
    adjudicator_format: str
    
    def __init__(self):
        self.tabs = ft.Tabs(
            expand=True
        )
        self.dict_team_format = {
            "speaks_ind_avg": "ind. avg. {:.2f} spks.",
            "margin_avg": "avg. margin {:.2f} spks.",
            "speaks_avg": "avg. {:.2f} spks.",
            "draw_strength_speaks": "DS {:.2f} spks.",
            "draw_strength": "DS {:d} pts.",
            "firsts": "{:d} firsts",
            "npullups": "{:d} pullups",
            "seconds": "{:d} seconds",
            "thirds": "{:d} thirds",
            "pullup_debates": "{:d} pullup debates",
            "num_iron": "{:d} irons",
            "points": "{:d} pts.",
            "speaks_stddev": "stdev. {:.2f} spks.",
            "margin_sum": "margin {:.2f} spks.",
            "speaks_sum": "{:.2f} spks.",
            "num_adjs": "{:d} adjs.",
            "wbw": "beat {:d} times",
            "wins": "{:d} wins"
        }
        self.dict_speaker_format = {
            "total": "{:.1f} spks.",
            "average": "avg. {:.2f} spks.",
            "trimmed_mean": "trimmed avg. {:.2f} spks.",
            "team_points": "{:d} pts.",
            "stdev": "stdev. {:.2f} spks.",
            "count": "{:d} speeches",
            "replies_sum": "{:.1f} spks.",
            "replies_avg": "avg. {:.2f} spks.",
            "replies_stddev": "stdev. {:.2f} spks.",
            "replies_count": "{:d} replies",
            "srank": "{:d} speech ranks"
        }
        self.adjudicator_format = "{:.1f} pts."
        super().__init__(
            ft.Column(
                [
                    ft.ElevatedButton(
                        "Edit displayed metrics",
                        icon=ft.Icons.DRIVE_FILE_RENAME_OUTLINE_ROUNDED,
                        on_click=self.on_change_metric,
                    ),
                    self.tabs
                ],
                expand=True
            ),
            expand=True
        )
    
    def set_tabbycat(self):
        has_reply: bool = self.app.tournament._links.preferences.find(identifier="debate_rules__reply_scores_enabled").value
        tabs = [
            TeamTab(break_category)
            for break_category in self.app.tournament._links.break_categories
        ]
        tabs.append(SpeakerTab(None))
        tabs.extend(SpeakerTab(speaker_category) for speaker_category in self.app.tournament._links.speaker_categories)
        if has_reply:
            tabs.append(SpeakerTab(None, is_reply=True))
        tabs.append(AdjudicatorTab())
        self.tabs.tabs = tabs
        self.update()
    
    def format_team_metrics(self, num_metrics: int, standing: tc.models.TeamStanding) -> str:
        def format_metric(metric: tc.models.TeamStandingMetric) -> Optional[str]:
            if metric.value is None or metric.value is tc.NULL:
                return None
            if "wbw" in metric.metric: # Metric for whom-beat-whom has a integer at the end (e.g. "wbw1"), so using __eq__ is inappropriate
                if metric.value == "n/a":
                    return None
                else:
                    return self.dict_team_format.get("wbw", "").format(metric.value)
            return self.dict_team_format.get(metric.metric, "").format(metric.value)
        return ", ".join(
            str_metric
            for i in range(num_metrics)
            if (str_metric := format_metric(standing.metrics[i])) is not None
        )
        
    def format_speaker_metrics(self, num_metrics: int, standing: tc.models.SpeakerStanding) -> str:
        def format_metric(metric: tc.models.SpeakerStandingMetric) -> Optional[str]:
            if metric.value is None or metric.value is tc.NULL:
                return None
            return self.dict_speaker_format.get(metric.metric, "").format(metric.value)
        return ", ".join(
            str_metric
            for i in range(num_metrics)
            if (str_metric := format_metric(standing.metrics[i])) is not None
        )
    
    def format_adjudicator_score(self, score: float) -> str:
        return self.adjudicator_format.format(score)
    
    @wait_finish
    def on_change_metric(self, e: ft.ControlEvent):
        team_metrics: list[TeamMetrics] = self.app.tournament._links.preferences.find(identifier="standings__team_standings_precedence").value
        speaker_metrics: list[SpeakerMetrics] = self.app.tournament._links.preferences.find(identifier="standings__speaker_standings_precedence").value
        dropdown_team = ft.Dropdown(
            value=str(min(self.num_team_metrics_include, len(team_metrics))-1),
            options=[
                ft.DropdownOption(
                    key=i,
                    text=DESCRIPTION_TEAM_METRICS.get(m, m),
                ) for i, m in enumerate(team_metrics)
            ],
            label="The last team metric to always display",
        )
        format_teams = {
            m: ft.TextField(
                value=self.dict_team_format.get(m, ""),
                label=f"Format for {DESCRIPTION_TEAM_METRICS.get(m, m)}",
            )
            for m in team_metrics
        }
        dropdown_speaker = ft.Dropdown(
            value=str(min(self.num_speaker_metrics_include, len(speaker_metrics))-1),
            options=[
                ft.DropdownOption(
                    key=i,
                    text=DESCRIPTION_SPEAKER_METRICS.get(m, m),
                ) for i, m in enumerate(speaker_metrics)
            ],
            label="The last speaker metric to always display",
        )
        format_speakers = {
            m: ft.TextField(
                value=self.dict_speaker_format.get(m, ""),
                label=f"Format for {DESCRIPTION_SPEAKER_METRICS.get(m, m)}",
            )
            for m in speaker_metrics
        }
        format_adj = ft.TextField(
            value=self.adjudicator_format,
            label="Format for Adjudicator score",
        )
        def on_confirm(e: ft.ControlEvent):
            self.num_team_metrics_include = int(dropdown_team.value) + 1
            self.num_speaker_metrics_include = int(dropdown_speaker.value) + 1
            self.adjudicator_format = format_adj.value
            self.dict_team_format.update(
                {key: text_field.value for key, text_field in format_teams.items()}
            )
            self.dict_speaker_format.update(
                {key: text_field.value for key, text_field in format_speakers.items()}
            )
            for tab in self.tabs.tabs:
                tab.update_table_display()
            self.page.close(dlg)
        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("Edit displayed metrics"),
            content=ft.Column(
                [
                    ft.Text("Team metrics"),
                    dropdown_team,
                    *format_teams.values(),
                    ft.Divider(),
                    ft.Text("Speaker metrics"),
                    dropdown_speaker,
                    *format_speakers.values(),
                    ft.Divider(),
                    ft.Text("Adjudicator metrics"),
                    format_adj
                ],
                expand=True,
                scroll=ft.ScrollMode.AUTO,
            ),
            actions=[
                ft.TextButton(
                    "Save",
                    on_click=on_confirm
                ),
                ft.TextButton(
                    "Cancel",
                    on_click=lambda _: self.page.close(dlg)
                )
            ]
        )
        self.page.open(dlg)