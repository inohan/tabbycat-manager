import flet as ft
import tabbycat_api as tc
import logging
import asyncio
from datetime import datetime
from typing import Literal
from ..base import AppControl, try_string, wait_finish

LOGGER = logging.getLogger(__name__)
TeamFeedbackDirection = Literal["orallist", "all-adjs", "no-one"]
AdjFeedbackDirection = Literal["minimal", "with-p-on-c", "with-t-on-c", "all-adjs", "with-p-on-p", "no-adjs"]


class FeedbackTile(ft.ListTile, AppControl):
    """List Tile for a single feedback
    """
    feedback: tc.models.Feedback
    
    def __init__(self, feedback: tc.models.Feedback):
        self.feedback = feedback
        icon_color = ft.Colors.GREY_400
        icon = ft.Icons.REMOVE_CIRCLE
        if self.feedback.confirmed:
            if not self.feedback.ignored:
                icon_color = ft.Colors.GREEN_ACCENT_400
                icon = ft.Icons.CHECK_CIRCLE
            else:
                icon_color = ft.Colors.AMBER_ACCENT_400
                icon = ft.Icons.FLAG_CIRCLE
        super().__init__(
            ft.Text(f"To {try_string(lambda: feedback.adjudicator.name)} @ {try_string(lambda: datetime.fromisoformat(feedback.timestamp).strftime('%Y/%m/%d %H:%M'))}"),
            leading=ft.Icon(
                icon,
                color=icon_color,
                size=30,
                badge=ft.Badge(
                    text=try_string(lambda: feedback.score, "?"),
                    bgcolor=icon_color,
                    text_color=ft.Colors.BLACK
                )
            ),
            on_click=self.on_click_tile
        )
    
    def on_click_tile(self, e):
        texts = [
            ("From", try_string(lambda: self.feedback.participant_submitter.name)),
            ("To", try_string(lambda: self.feedback.adjudicator.name)),
            ("Timestamp", try_string(lambda: datetime.fromisoformat(self.feedback.timestamp).strftime('%Y/%m/%d %H:%M'))),
            ("Score", try_string(lambda: self.feedback.score, "?"))
        ]
        for q in self.feedback.answers:
            texts.append((try_string(lambda: q.question.text), try_string(lambda: q.answer)))
        self.page.open(
            ft.AlertDialog(
                title=ft.Text("Feedback Details"),
                content=ft.Column(
                    [
                        ft.ListTile(
                            ft.Text(title),
                            ft.Text(subtitle),
                        ) for title, subtitle in texts
                    ],
                    expand=True
                )
            )
        )

class AdjudicatorContainer(ft.Container, AppControl):
    """Container for a single adjudicator and their feedback
    """
    def __init__(
        self,
        adjudicator: tc.models.Adjudicator,
        position: Literal["chair", "panellist", "trainee"],
        feedbacks: list[tc.models.Feedback]
    ):
        col_feedbacks = ft.Column(
            []
        )
        if len(feedbacks):
            col_feedbacks.controls.append(
                ft.Text("Feedbacks")
            )
            for fb in feedbacks:
                col_feedbacks.controls.append(
                    FeedbackTile(fb)
                )
        super().__init__(
            ft.ListTile(
                ft.Text(f"[{position[0].upper()}] {try_string(lambda: adjudicator.name)}"),
                subtitle=col_feedbacks
            ),
            col=12,
            border=ft.border.all(1, ft.Colors.GREY_400)
        )

class TeamContainer(ft.Container, AppControl):
    """Container for a debate team and its feedback
    """
    def __init__(
        self,
        debate_team: tc.models.DebateTeam,
        result: tc.models.TeamResult|None,
        feedbacks: list[tc.models.Feedback],
        num_sides: int
    ):
        text_subtitle = "No record"
        icon_winloss = ft.Icons.QUESTION_MARK
        icon_color = ft.Colors.GREY_500
        text_color = ft.Colors.BLACK
        if result:
            if result.speeches:
                # If a valid ballot exists, display the speaker info
                str_speakers: list[str] = []
                for sp in result.speeches:
                    line = f"{try_string(lambda: sp.speaker.name)}: {try_string(lambda: sp.score)}"
                    if sp.ghost:
                        line += " (duplicate)"
                    str_speakers.append(line)
                text_subtitle = "\n".join(str_speakers)
            if isinstance(result.points, int):
                # Get the win/points info
                if num_sides == 2:
                    icon_winloss = ft.Icons.EXPOSURE_PLUS_1 if result.win else ft.Icons.EXPOSURE_NEG_1
                    icon_color = ft.Colors.GREEN_ACCENT_400 if result.win else ft.Colors.RED_ACCENT_400
                    text_color = ft.Colors.BLACK if result.win else ft.Colors.WHITE
                elif num_sides == 4:
                    icon_winloss = [ft.Icons.EXPOSURE_MINUS_2, ft.Icons.EXPOSURE_MINUS_1, ft.Icons.EXPOSURE_PLUS_1, ft.Icons.EXPOSURE_PLUS_2][result.points]
                    icon_color = [ft.Colors.RED_ACCENT_400, ft.Colors.RED_ACCENT_100, ft.Colors.GREEN_ACCENT_100, ft.Colors.GREEN_ACCENT_400][result.points]
                    text_color = ft.Colors.BLACK if result.points >= 1 else ft.Colors.WHITE
        col_feedbacks = ft.Column(
            []
        )
        if len(feedbacks):
            col_feedbacks.controls.append(
                ft.Text("Feedbacks")
            )
            for fb in feedbacks:
                col_feedbacks.controls.append(
                    FeedbackTile(fb)
                )
        super().__init__(
            ft.ListTile(
                ft.Text(f"[{try_string(lambda: debate_team.side)}] {try_string(lambda: debate_team.team.long_name)}"),
                ft.Column(
                    [
                        ft.Text(text_subtitle),
                        col_feedbacks
                    ]
                ),
                leading=ft.Icon(
                    icon_winloss,
                    size=40,
                    color=icon_color,
                    badge=ft.Badge(
                        try_string(lambda: result.score, "?"),
                        bgcolor=icon_color,
                        text_color=text_color
                    )
                ),
                horizontal_spacing=40
            ),
            col=6,
            border=ft.border.all(1, ft.Colors.GREY_400)
        )

class RoundStatusPanel(ft.ExpansionPanel, AppControl):
    """Expansion Panel for a single debate pairing and its result
    """
    pairing: tc.models.RoundPairing
    ballots: list[tc.models.Ballot]
    feedbacks: list[tc.models.Feedback]
    round: tc.models.Round
    
    def __init__(self, pairing: tc.models.RoundPairing, round: tc.models.Round):
        self.pairing = pairing
        self.round = round
        self.dropdown_ballot = ft.Dropdown(
            on_change=self.on_select_ballot,
            expand=True
        )
        self.grid_teams = ft.ResponsiveRow(
            [],
            columns=12,
        )
        self.grid_adjudicators = ft.ResponsiveRow(
            [],
            columns=12,
        )
        panel_subheader_text = " vs. ".join([try_string(lambda: dt.team.short_name) for dt in self.pairing.teams])
        panel_subheader_text += "\n"
        panels_name = []
        if self.pairing.adjudicators.chair:
            panels_name.append("🄫" + try_string(lambda: self.pairing.adjudicators.chair.name))
        if self.pairing.adjudicators.panellists:
            panels_name.extend([try_string(lambda: panellist.name) for panellist in self.pairing.adjudicators.panellists])
        if self.pairing.adjudicators.trainees:
            panels_name.extend([try_string(lambda: trainee.name) for trainee in self.pairing.adjudicators.trainees])
        panel_subheader_text += ", ".join(panels_name)
        
        self.panel_header = ft.ListTile(
            title=ft.Text(try_string(lambda: self.pairing.venue.display_name)),
            subtitle=ft.Text(panel_subheader_text),
        )
        super().__init__(
            header=self.panel_header,
            content=ft.Container(
                ft.Column(
                    [
                        self.dropdown_ballot,
                        self.grid_teams,
                        ft.Divider(color=ft.Colors.BLACK),
                        self.grid_adjudicators,
                    ],
                    tight=True,
                ),
                bgcolor=ft.Colors.GREY_200
            ),
            can_tap_header=True,
            expanded=False,
            bgcolor=ft.Colors.GREY_200
        )
    
    def build(self):
        super().build()
        self.sync_data()
        self.set_ballot(int(self.dropdown_ballot.value))
        self.set_panel()
        self.set_verify_status()
    
    def on_select_ballot(self, e):
        self.set_ballot(int(self.dropdown_ballot.value))
        self.update()
    
    def set_ballot(self, i: int = -1):
        num_sides: int = self.app.tournament._links.preferences.find(identifier="debate_rules__teams_in_debate").value
        # Get the selected ballot, -1 if none
        i = int(self.dropdown_ballot.value)
        # Render team grids
        ballot = self.ballots[i] if i != -1 else None
        self.grid_teams.controls.clear()
        for dt in self.pairing.teams:
            team = next((result for result in ballot.result.sheets[0].teams if result.side == dt.side), None) if ballot else None
            feedbacks = [fb for fb in self.feedbacks if fb.source == dt.team]
            self.grid_teams.controls.append(
                TeamContainer(
                    dt,
                    team,
                    feedbacks,
                    num_sides
                )
            )
    
    def set_panel(self):
        adj = self.pairing.adjudicators
        # Chair
        if adj.chair:
            self.grid_adjudicators.controls.append(
                AdjudicatorContainer(
                    adj.chair,
                    "chair",
                    [fb for fb in self.feedbacks if fb.source == adj.chair]
                )
            )
        # Panellists
        for panellist in adj.panellists:
            self.grid_adjudicators.controls.append(
                AdjudicatorContainer(
                    panellist,
                    "panellist",
                    [fb for fb in self.feedbacks if fb.source == panellist]
                )
            )
        # Trainees
        for trainee in adj.trainees:
            self.grid_adjudicators.controls.append(
                AdjudicatorContainer(
                    trainee,
                    "trainee",
                    [fb for fb in self.feedbacks if fb.source == trainee]
                )
            )
    
    def set_verify_status(self):
        status, msg = self.get_verify_status()
        if status == 0:
            self.bgcolor = ft.Colors.RED_100
            self.panel_header.leading = ft.Icon(
                ft.Icons.ERROR,
                color=ft.Colors.RED_ACCENT_400,
                size=40,
                tooltip=msg
            )
        elif status == 1:
            self.bgcolor = ft.Colors.AMBER_100
            self.panel_header.leading = ft.Icon(
                ft.Icons.FLAG_CIRCLE,
                color=ft.Colors.AMBER_ACCENT_400,
                size=40,
                tooltip=msg
            )
        else:
            self.bgcolor = ft.Colors.GREEN_100
            self.panel_header.leading = ft.Icon(
                ft.Icons.CHECK_CIRCLE,
                color=ft.Colors.GREEN_ACCENT_400,
                size=40,
                tooltip="All feedbacks are correct"
            )
    
    def get_verify_status(self) -> tuple[int, str]:
        """Get the round status

        Returns:
            tuple[int, str]: 0 = unconfirmed, 1 = error, 2 = all correct and error message
        """
        round_confirmed = (self.pairing.result_status == "C")
        missing_feedbacks_team, extra_feedbacks_team, orallists = self.verify_status_team("no-one" if self.round.silent or self.round.stage == "E" else None)
        missing_feedbacks_adj, extra_feedbacks_adj = self.verify_status_adj("no-adjs" if self.round.stage == "E" else None)
        is_err = False
        text_error = ""
        text_missing = [f"{try_string(lambda: src.name)}→{try_string(lambda: dest.name)}" for src, dest in missing_feedbacks_adj]
        text_missing.extend([f"{try_string(lambda: team.short_name)}→{try_string(lambda: adj.name) if adj!='orallist' else 'orallist'}" for team, adj in missing_feedbacks_team])
        if text_missing:
            is_err = True
            text_error += "Missing feedbacks: " + ", ".join(text_missing) + "\n"
        text_extra = [f"{try_string(lambda: fb.source.name)}→{try_string(lambda: fb.adjudicator.name)}" for fb in extra_feedbacks_adj+extra_feedbacks_team]
        if text_extra:
            is_err = True
            text_error += "Extra feedbacks: " + ", ".join(text_extra) + "\n"
        if orallists is not None and len(orallists) != 1:
            is_err = True
            text_error += "Multiple orallists: " + ", ".join([try_string(lambda: adj.name) for adj in orallists]) + "\n"
        if not round_confirmed:
            return 0, "Round unconfirmed"
        if is_err:
            return 1, text_error[:-1]
        return 2, "All feedbacks are correct"
    
    def verify_status_team(self, fb_team: TeamFeedbackDirection|None = None) -> tuple[list[tuple[tc.models.Team, tc.models.Adjudicator|Literal["orallist"]]], list[tc.models.Feedback], list[tc.models.Adjudicator]|None]:
        if fb_team is None:
            fb_team = self.app.tournament._links.preferences.find(identifier="feedback__feedback_from_teams").value
        adjs: list[tuple[Literal["c", "p", "t"], tc.models.Adjudicator]] = []
        if self.pairing.adjudicators.chair:
            adjs.append(("c", self.pairing.adjudicators.chair))
        if self.pairing.adjudicators.panellists:
            for panellist in self.pairing.adjudicators.panellists:
                adjs.append(("p", panellist))
        if self.pairing.adjudicators.trainees:
            for trainee in self.pairing.adjudicators.trainees:
                adjs.append(("t", trainee))
        match fb_team:
            case "orallist":
                orallists = {
                    fb.adjudicator.url for fb in self.feedbacks if fb.confirmed and isinstance(fb.source, tc.models.Team)
                }
                missing_feedbacks = [
                    (dt.team, "orallist")
                    for dt in self.pairing.teams
                    if not any(fb.source == dt.team and fb.confirmed for fb in self.feedbacks)
                ]
                return missing_feedbacks, [], [self.app.tournament._links.adjudicators.find(url=url) for url in orallists]
            case "all-adjs":
                missing_feedbacks = [
                    (dt.team, adj)
                    for dt in self.pairing.teams
                    for _, adj in adjs
                    if not any(fb.source == dt.team and fb.adjudicator == adj and fb.confirmed for fb in self.feedbacks)
                ]
                return missing_feedbacks, [], None
            case "no-one":
                return [], [fb for fb in self.feedbacks if isinstance(fb.source, tc.models.Team)], None
    
    def verify_status_adj(self, fb_adj: AdjFeedbackDirection|None = None) -> tuple[list[tuple[tc.models.Adjudicator, tc.models.Adjudicator]], list[tc.models.Feedback]]:
        if fb_adj is None:
            fb_adj = self.app.tournament._links.preferences.find(identifier="feedback__feedback_paths").value
        # Check adjudicators
        adjs: list[tuple[Literal["c", "p", "t"], tc.models.Adjudicator]] = []
        if self.pairing.adjudicators.chair:
            adjs.append(("c", self.pairing.adjudicators.chair))
        if self.pairing.adjudicators.panellists:
            for panellist in self.pairing.adjudicators.panellists:
                adjs.append(("p", panellist))
        if self.pairing.adjudicators.trainees:
            for trainee in self.pairing.adjudicators.trainees:
                adjs.append(("t", trainee))
        is_necessary: tuple[tuple[bool, bool, bool], tuple[bool, bool, bool], tuple[bool, bool, bool]] = None
        match fb_adj:
            case "minimal":
                is_necessary = ((True, True, True), (False, False, False), (False, False, False))
            case "with-p-on-c":
                is_necessary = ((True, True, True), (True, False, False), (False, False, False))
            case "with-t-on-c":
                is_necessary = ((True, True, True), (True, False, False), (True, False, False))
            case "all-adjs":
                is_necessary = ((True, True, True), (True, True, True), (True, True, True))
            case "with-p-on-p":
                is_necessary = ((True, True, True), (True, True, False), (True, False, False))
            case "no-adjs":
                is_necessary = ((False, False, False), (False, False, False), (False, False, False))
            case _:
                raise ValueError(f"Invalid feedback path: {fb_adj}")
        dict_pos: dict[Literal["c", "p", "t"], int] = {"c": 0, "p": 1, "t": 2}
        necessity_matrix = {
            adj_src.url: {
                adj_dest.url: is_necessary[dict_pos[p_src]][dict_pos[p_dest]] if adj_src != adj_dest else False
                for p_dest, adj_dest in adjs
            }
            for p_src, adj_src in adjs
        }
        
        extra_feedbacks: list[tc.models.Feedback] = []
        for fb in self.feedbacks:
            if not fb.confirmed or isinstance(fb.source, tc.models.Team):
                continue
            necessity = necessity_matrix[fb.source.url][fb.adjudicator.url]
            if not necessity:
                extra_feedbacks.append(fb)
            necessity_matrix[fb.source.url][fb.adjudicator.url] = False
        missing_feedbacks: list[tuple[tc.models.Adjudicator, tc.models.Adjudicator]] = [
            (self.app.tournament._links.adjudicators.find(url=url_src), self.app.tournament._links.adjudicators.find(url=url_dest))
            for url_src, m in necessity_matrix.items()
            for url_dest, b in m.items()
            if b
        ]
        return missing_feedbacks, extra_feedbacks
    
    def sync_data(self):
        self.ballots = list(self.pairing._links.ballots)
        self.feedbacks = [fb for fb in self.app.tournament._links.feedback if fb.debate == self.pairing]
        def get_ballot_text(ballot: tc.models.Ballot):
            res = ""
            if ballot.confirmed:
                res += "✅ "
            if ballot.discarded:
                res += "❌ "
            res += f"Ver. {try_string(lambda: ballot.version, "?")} from {try_string(lambda: ballot.participant_submitter.name)} @ {try_string(lambda: datetime.fromisoformat(ballot.timestamp).strftime("%Y/%m/%d %H:%M"))}"
            return res
        self.dropdown_ballot.options = [
            ft.DropdownOption(
                key="-1",
                text="None"
            )
        ]
        self.dropdown_ballot.options.extend(
            [
                ft.DropdownOption(
                    key=str(i),
                    text=get_ballot_text(ballot)
                ) for i, ballot in enumerate(self.ballots)
            ]
        )
        self.dropdown_ballot.value = next((str(i) for i, ballot in enumerate(self.ballots) if ballot.confirmed), len(self.ballots) - 1)

class RoundStatusTab(ft.Tab, AppControl):
    round: tc.models.Round
    
    def __init__(self, round: tc.models.Round):
        self.round = round
        self.expansion_panels = ft.ExpansionPanelList(
            [],
            divider_color=ft.Colors.BLACK,
            expanded_header_padding=ft.padding.symmetric(vertical=24)
            
        )
        self.col_content = ft.Column(
            [
                self.expansion_panels
            ],
            expand=True,
            scroll=ft.ScrollMode.AUTO
        )
        self.icon_tab = ft.Icon(
            None
        )
        super().__init__(
            text=f"{round.name} ({round.abbreviation})",
            content=self.col_content,
            tab_content=ft.Row(
                [
                    self.icon_tab,
                    ft.Text(f"{try_string(lambda: round.name)} ({try_string(lambda: round.abbreviation)})"),
                    ft.IconButton(
                        ft.Icons.REFRESH,
                        on_click=self.on_refresh
                    )
                ]
            )
        )
    
    def set_debates(self):
        LOGGER.info(f"Loading debates for round {self.round.name}")
        panels = [
            RoundStatusPanel(pairing, self.round) for pairing in self.round._links.pairing
        ]
        self.expansion_panels.controls = panels
        self.update()
        all_ok = all(p.get_verify_status()[0] == 2 for p in panels)
        self.icon_tab.name = ft.Icons.CHECK_CIRCLE if all_ok else ft.Icons.ERROR
        self.icon_tab.color = ft.Colors.GREEN_ACCENT_400 if all_ok else ft.Colors.RED_ACCENT_400
        self.icon_tab.update()
    
    @wait_finish
    async def on_refresh(self, e):
        # Load all pairings
        await asyncio.gather(self.round._links.pairing.load(force=True), self.app.tournament._links.feedback.load(force=True))
        # Load all ballots
        await asyncio.gather(
            *[pairing._links.ballots.load(force=True) for pairing in self.round._links.pairing]
        )
        self.set_debates()
        self.page.open(
            ft.SnackBar(
                content=ft.Text(f"Updated {try_string(lambda: self.round.name)} successfully", color=ft.Colors.BLACK),
                bgcolor=ft.Colors.GREEN_100,
            )
        )

class RoundStatusPagelet(ft.Pagelet, AppControl):
    tab_round: dict[int, RoundStatusTab]
    
    def __init__(self):
        self.tabs_round = ft.Tabs(
            [],
            expand=True,
            scrollable=True
        )
        super().__init__(
            ft.Column(
                [
                    ft.ElevatedButton(
                        "Update",
                        icon=ft.Icons.SYNC,
                        on_click=self.on_btn_update
                    ),
                    self.tabs_round
                ],
                expand=True,
            ),
            expand=True
        )
    
    async def set_tabs(self):
        # Load all pairings
        await asyncio.gather(
            *[round._links.pairing.load() for round in self.app.tournament._links.rounds]
        )
        # Load all ballots
        await asyncio.gather(
            *[pairing._links.ballots.load() for round in self.app.tournament._links.rounds for pairing in round._links.pairing]
        )
        tabs = [
            RoundStatusTab(round) for round in self.app.tournament._links.rounds
        ]
        self.tabs_round.tabs = tabs
        self.update()
        for tab in tabs:
            tab.set_debates()
    
    @wait_finish
    async def on_btn_update(self, e):
        await self.set_tabs()
