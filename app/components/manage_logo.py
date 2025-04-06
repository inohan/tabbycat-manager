import asyncio
import flet as ft
from googleapiclient.discovery import build
import logging
import tabbycat_api as tc
from typing import Optional, override, Sequence

from ..utils import Logo, LogoData
from ..base import AppControl, try_string, wait_finish
from .google_picker import GoogleFilePicker, GoogleFilePickerResultEvent

LOGGER = logging.getLogger(__name__)

class LogoImageContainer(ft.Container, AppControl):
    logo: Logo
    
    def __init__(
        self,
        logo: Logo,
        actions: Optional[Sequence[ft.Control]] = None,
        disabled: Optional[bool] = None,
        width: Optional[int] = None,
        height: Optional[int] = None,
    ):
        self.logo = logo
        # self.image_logo = ft.Image(
        #     visible=False,
        #     expand=True,
        # )
        self.image_logo = ft.Container(
            None,
            visible=False
        )
        self.text_alias = ft.Text(
            "",
            visible=False,
            expand=True,
            size=24,
            weight=ft.FontWeight.BOLD
        )
        self.row_actions = ft.Row(
            actions,
            visible=False,
            alignment=ft.MainAxisAlignment.END,
        )
        super().__init__(
            ft.Stack(
                [
                    self.image_logo,
                    self.text_alias,
                    ft.Container(
                        self.row_actions,
                        alignment=ft.alignment.top_right
                    )
                ],
                alignment=ft.alignment.center,
                expand=True
            ),
            width=width,
            height=height,
            border=ft.border.all(1),
            border_radius=10,
            on_hover=self._on_hover,
            disabled=disabled
        )
    
    @property
    def actions(self) -> Optional[Sequence[ft.Control]]:
        return self.row_actions.controls
    
    @actions.setter
    def actions(self, actions: Optional[Sequence[ft.Control]]):
        self.row_actions.controls = actions
    
    def did_mount(self):
        super().did_mount()
        self.page.run_task(self.load_component)
    
    def _on_hover(self, e: ft.ControlEvent):
        self.row_actions.visible = e.data == "true" and not self.disabled
        self.row_actions.update()
    
    async def load_component(self):
        image = None
        alias_name = None
        try:
            if self.logo["type"] == "alias":
                alias_name = self.logo["value"]
                aliased = self.app.logos.aliases.get(self.logo["value"], None)
                if aliased:
                    image = {aliased["type"]: aliased["value"]}
            else:
                image = {self.logo["type"]: self.logo["value"]}
        except Exception:
            pass
        src_base64 = await self.app.cache_image_async(**image) if image else None
        if src_base64:
            #self.image_logo.src_base64 = src_base64
            self.image_logo.image = ft.DecorationImage(
                src_base64=src_base64,
                opacity=0.3
            )
            self.image_logo.visible = True
        else:
            self.image_logo.visible = False
        if alias_name:
            self.text_alias.value = alias_name
            self.text_alias.visible = True
        else:
            self.text_alias.visible = False
        self.update()

class ParticipantLogoTile[T: tc.models.Team|tc.models.Adjudicator|tc.models.Speaker](ft.ListTile, AppControl):
    participant: T
    
    def __init__(self, participant: T, col: Optional[ft.ResponsiveRow] = None):
        self.participant = participant
        self.row_logos = ft.Row(
            [],
            expand=True,
            scroll=ft.ScrollMode.AUTO,
        )
        super().__init__(
            title=ft.Text(try_string(lambda: (participant.long_name if isinstance(participant, tc.models.Team) else participant.name))),
            subtitle=self.row_logos,
            col=col,
            on_click=self.on_tile_click,
        )
    
    def build(self):
        super().build()
        self.set_display()
    
    def set_display(self):
        if self.logos is None:
            self.row_logos.controls = [
                ft.Text(
                    "No logos, likely error",
                    col=12
                )
            ]
        else:
            self.row_logos.controls = [
                LogoImageContainer(logo, width=100, height=100) for logo in self.logos
            ]
    
    @property
    def logos(self) -> list[Logo]|None:
        return self.app.logos.get_object_logo(self.participant)

    @logos.setter
    def logos(self, logos: list[Logo]|None):
        self.app.logos.mappings[self.participant._href] = logos
    
    async def on_tile_click(self, e: ft.ControlEvent):
        def get_image_container(logo: Logo) -> LogoImageContainer:
            def on_remove(e: ft.ControlEvent):
                row_logos_dlg.controls.remove(img)
                row_logos_dlg.update()
            img = LogoImageContainer(
                logo,
                actions=[
                    ft.IconButton(
                        ft.Icons.DELETE,
                        on_click = on_remove
                    )
                ],
                width=100,
                height=100
            )
            return img
        row_logos_dlg = ft.Row(
            [get_image_container(logo) for logo in self.logos],
            expand=True,
            scroll=ft.ScrollMode.AUTO,
        )
        def get_row_logos() -> list[Logo]:
            """Gets the logos in the row_logos_dlg content, in the current state"""
            return [logo.logo for logo in row_logos_dlg.controls]
        
        dropdown_aliases = ft.Dropdown(
            label="Add Alias",
            options=[
                ft.DropdownOption(
                    key=alias,
                    text=alias
                ) for alias in sorted(self.app.logos.gather_aliases())
            ],
            enable_filter=True,
        )
        
        def on_add_alias(e: ft.ControlEvent):
            alias = dropdown_aliases.value
            if alias:
                logo_new: Logo = {"type": "alias", "value": alias}
                if logo_new not in get_row_logos():
                    row_logos_dlg.controls.append(get_image_container(logo_new))
                    row_logos_dlg.update()
                else:
                    self.page.open(
                        ft.SnackBar(
                            ft.Text("Logo already exists", color=ft.Colors.BLACK),
                            bgcolor=ft.Colors.RED_100,
                        )
                    )
        
        def on_file_picked(e: GoogleFilePickerResultEvent):
            if e.data:
                logo_new: Logo = {"type": "file_id", "value": e.data.get("id")}
                if logo_new not in get_row_logos():
                    row_logos_dlg.controls.append(get_image_container(logo_new))
                    row_logos_dlg.update()
            self.page.open(dlg)
        
        @wait_finish
        def on_open_google_drive(e: ft.ControlEvent):
            if not self.app.oauth_credentials:
                raise Exception("Not logged in to Google Drive")
            self.page.open(GoogleFilePicker(mime_type=["image/"], on_result=on_file_picked))
        
        def on_save(e: ft.ControlEvent):
            self.logos = get_row_logos()
            self.page.close(dlg)
            self.set_display()
            self.update()
        
        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text(f"Edit Logos for {try_string(lambda: self.participant.long_name if isinstance(self.participant, tc.models.Team) else self.participant.name)}"),
            content=ft.Column(
                [
                    row_logos_dlg,
                    ft.Divider(),
                    ft.Row(
                        [
                            dropdown_aliases,
                            ft.IconButton(
                                ft.Icons.ADD,
                                on_click=on_add_alias
                            )
                        ]
                    ),
                    ft.ElevatedButton(
                        "Add from Google Drive",
                        icon=ft.Icons.ADD_TO_DRIVE,
                        on_click = on_open_google_drive
                    )
                ],
                tight=True,
                expand=True
            ),
            actions=[
                ft.TextButton(
                    "Save",
                    on_click=on_save
                ),
                ft.TextButton(
                    "Cancel",
                    on_click=lambda _: self.page.close(dlg)
                )
            ]
        )
        self.page.open(dlg)

class TeamLogoTile(ParticipantLogoTile[tc.models.Team]):
    @override
    def set_display(self):
        if self.logos is None:
            self.row_logos.controls = [
                ft.Text(
                    "Use logos of speakers",
                    col=12
                )
            ]
        else:
            self.row_logos.controls = [
                LogoImageContainer(logo, width=100, height=100) for logo in self.logos
            ]
    
    @override
    async def on_tile_click(self, e: ft.ControlEvent):
        def get_image_container(logo: Logo) -> LogoImageContainer:
            def on_remove(e: ft.ControlEvent):
                row_logos_dlg.controls.remove(img)
                row_logos_dlg.update()
            img = LogoImageContainer(
                logo,
                actions=[
                    ft.IconButton(
                        ft.Icons.DELETE,
                        on_click = on_remove
                    )
                ],
                width=100,
                height=100
            )
            return img
        def on_sw_change(e: ft.ControlEvent):
            for control in dlg.content.controls[1:]:
                control.visible = not e.control.value
            dlg.update()
        sw_use_speakers = ft.Switch(
            label="Use logos of speakers",
            on_change=on_sw_change,
            value=self.logos is None
        )
        row_logos_dlg = ft.Row(
            [get_image_container(logo) for logo in self.logos] if self.logos else [],
            expand=True,
            scroll=ft.ScrollMode.AUTO,
            visible=self.logos is not None
        )
        def get_row_logos() -> list[Logo]:
            """Gets the logos in the row_logos_dlg content, in the current state"""
            return [logo.logo for logo in row_logos_dlg.controls]
        
        dropdown_aliases = ft.Dropdown(
            label="Add Alias",
            options=[
                ft.DropdownOption(
                    key=alias,
                    text=alias
                ) for alias in sorted(self.app.logos.gather_aliases())
            ],
            enable_filter=True,
        )
        
        def on_add_alias(e: ft.ControlEvent):
            alias = dropdown_aliases.value
            if alias:
                logo_new: Logo = {"type": "alias", "value": alias}
                if logo_new not in get_row_logos():
                    row_logos_dlg.controls.append(get_image_container(logo_new))
                    row_logos_dlg.update()
                else:
                    self.page.open(
                        ft.SnackBar(
                            ft.Text("Logo already exists", color=ft.Colors.BLACK),
                            bgcolor=ft.Colors.RED_100,
                        )
                    )
        
        def on_file_picked(e: GoogleFilePickerResultEvent):
            if e.data:
                logo_new: Logo = {"type": "file_id", "value": e.data.get("id")}
                if logo_new not in get_row_logos():
                    row_logos_dlg.controls.append(get_image_container(logo_new))
                    row_logos_dlg.update()
            self.page.open(dlg)
        
        @wait_finish
        def on_open_google_drive(e: ft.ControlEvent):
            if not self.app.oauth_credentials:
                raise Exception("Not logged in to Google Drive")
            self.page.open(GoogleFilePicker(mime_type=["image/"], on_result=on_file_picked))
        
        def on_save(e: ft.ControlEvent):
            self.logos = get_row_logos() if not sw_use_speakers.value else None
            self.page.close(dlg)
            self.set_display()
            self.update()
        
        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text(f"Edit Logos for {try_string(lambda: self.participant.long_name if isinstance(self.participant, tc.models.Team) else self.participant.name)}"),
            content=ft.Column(
                [
                    sw_use_speakers,
                    row_logos_dlg,
                    ft.Divider(visible=self.logos is not None),
                    ft.Row(
                        [
                            dropdown_aliases,
                            ft.IconButton(
                                ft.Icons.ADD,
                                on_click=on_add_alias
                            )
                        ],
                        visible=self.logos is not None
                    ),
                    ft.ElevatedButton(
                        "Add from Google Drive",
                        icon=ft.Icons.ADD_TO_DRIVE,
                        on_click = on_open_google_drive,
                        visible=self.logos is not None
                    )
                ],
                tight=True
            ),
            actions=[
                ft.TextButton(
                    "Save",
                    on_click=on_save
                ),
                ft.TextButton(
                    "Cancel",
                    on_click=lambda _: self.page.close(dlg)
                )
            ]
        )
        self.page.open(dlg)

class LogoManagerPagelet(ft.Pagelet, AppControl):
    def __init__(self):
        self.row_teams = ft.ResponsiveRow(
            [],
            expand=True
        )
        self.row_speakers = ft.ResponsiveRow(
            [],
            expand=True
        )
        self.row_adjudicators = ft.ResponsiveRow(
            [],
            expand=True
        )
        super().__init__(
            ft.Column(
                [
                    ft.Row(
                        [
                            ft.ElevatedButton(
                                "Load",
                                ft.Icons.REFRESH,
                                on_click=self.load_logos
                            ),
                            ft.ElevatedButton(
                                "Save",
                                ft.Icons.SAVE,
                                on_click=self.save_logos
                            ),
                            ft.ElevatedButton(
                                "Reset",
                                ft.Icons.DELETE,
                                on_click=self.reset_logos
                            ),
                            ft.ElevatedButton(
                                "Manage Icons",
                                ft.Icons.IMAGE,
                                on_click=self.show_icon_manager
                            )
                        ]
                    ),
                    ft.Column(
                        [
                            ft.Text("Speakers"),
                            self.row_speakers,
                            ft.Text("Adjudicators"),
                            self.row_adjudicators,
                            ft.Text("Teams"),
                            self.row_teams,
                        ],
                        expand=True,
                        scroll=ft.ScrollMode.AUTO,
                    )
                ],
                expand=True
            ),
            expand=True
        )
    
    def set_tabbycat(self):
        self.set_list_participants()
        self.update()
    
    def set_list_participants(self):
        self.row_teams.controls = [TeamLogoTile(team, col=3) for team in self.app.tournament._links.teams]
        self.row_speakers.controls = [ParticipantLogoTile(speaker, col=3) for speaker in self.app.tournament._links.speakers]
        self.row_adjudicators.controls = [ParticipantLogoTile(adjudicator, col=3) for adjudicator in self.app.tournament._links.adjudicators]
    
    @wait_finish
    async def load_logos(self, e: ft.ControlEvent):
        if self.app.logos is None:
            self.app.load_logos(self.app.storage_key)
        else:
            future = asyncio.Future()
            @wait_finish
            async def on_click(e):
                self.page.close(dlg)
                LOGGER.debug("Closed dialog")
                if not future.done():
                    future.set_result(e.control.data)
            dlg = ft.AlertDialog(
                modal=True,
                title=ft.Text("Reload Logos?"),
                content=ft.Text("Logos are already loaded. Do you want to reload them?"),
                actions=[
                    ft.TextButton(
                        "Yes",
                        on_click=on_click,
                        data=True
                    ),
                    ft.TextButton(
                        "No",
                        on_click=on_click,
                        data=False
                    )
                ],
            )
            self.page.open(dlg)
            res: bool = await future
            if res:
                await self.app.load_logos_async(self.app.storage_key)
                self.set_list_participants()
                self.update()
    
    @wait_finish
    async def save_logos(self, e):
        await self.app.save_logos_async(self.app.storage_key)
    
    @wait_finish
    async def reset_logos(self, e: ft.ControlEvent):
        await self.app.clear_logos_async(self.app.storage_key)
        self.set_list_participants()
        self.update()
    
    @wait_finish
    async def show_icon_manager(self, e: ft.ControlEvent):
        aliases = {
            alias: self.app.logos.aliases.get(alias, None) for alias in self.app.logos.gather_aliases()
        }
        def update_row_logos():
            row_logos_dlg.controls = [
                get_image_container(alias) for alias in aliases.keys()
            ]
            row_logos_dlg.update()
        
        def get_image_container(alias: str) -> LogoImageContainer:
            def on_remove(e: ft.ControlEvent):
                del aliases[alias]
                update_row_logos()
            def on_rename(e: ft.ControlEvent):
                def on_save_rename(e: ft.ControlEvent):
                    new_alias = dlg_rename.content.value
                    if new_alias:
                        aliases[new_alias] = aliases.pop(alias)
                        update_row_logos()
                    self.page.open(dlg)
                dlg_rename = ft.AlertDialog(
                    modal=True,
                    title=ft.Text(f"Rename alias {alias}"),
                    content=ft.TextField(
                        label="New name",
                        value=alias
                    ),
                    actions=[
                        ft.TextButton(
                            "Save",
                            on_click=on_save_rename
                        ),
                        ft.TextButton(
                            "Cancel",
                            on_click=lambda _: self.page.open(dlg)
                        )
                    ]
                )
                self.page.open(dlg_rename)
            
            @wait_finish
            def on_change_logo(e: ft.ControlEvent):
                def on_file_picked(e: GoogleFilePickerResultEvent):
                    if e.data:
                        aliases[alias] = {"type": "file_id", "value": e.data.get("id")}
                        update_row_logos()
                    self.page.open(dlg)
                if not self.app.oauth_credentials:
                    raise Exception("Not logged in to Google Drive")
                self.page.open(GoogleFilePicker(mime_type=["image/"], on_result=on_file_picked))
            img = LogoImageContainer(
                {"type": "alias", "value": alias},
                actions=[
                    ft.IconButton(
                        ft.Icons.DELETE,
                        on_click = on_remove,
                        tooltip="Remove alias"
                    ),
                    ft.IconButton(
                        ft.Icons.DRIVE_FILE_RENAME_OUTLINE_ROUNDED,
                        on_click=on_rename,
                        tooltip="Rename alias",
                    ),
                    ft.IconButton(
                        ft.Icons.IMAGE,
                        on_click=on_change_logo,
                        tooltip="Change logo",
                    )
                ],
                width=150,
                height=150
            )
            return img

        @wait_finish
        def add_alias(e: ft.ControlEvent):
            if not self.app.oauth_credentials:
                raise Exception("Not logged in to Google Drive")
            service = build("drive", "v3", credentials=self.app.oauth_credentials)
            def on_file_picked(e: GoogleFilePickerResultEvent):
                if e.data:
                    if e.data["mimeType"] == "application/vnd.google-apps.folder":
                        images = service.files().list(
                            q=f"'{e.data['id']}' in parents and mimeType contains 'image/' and trashed = false",
                            fields="files(id, name, mimeType)"
                        ).execute().get("files", [])
                        aliases.update({image.get("name").split(".")[0]: {"type": "file_id", "value": image.get("id")} for image in images})
                    else:
                        aliases[e.data["name"].split(".")[0]] = {"type": "file_id", "value": e.data.get("id")}
                    update_row_logos()
                self.page.open(dlg)
            self.page.open(GoogleFilePicker(mime_type=["image/", "application/vnd.google-apps.folder"], on_result=on_file_picked, service=service))
        
        row_logos_dlg = ft.Row(
            [],
            wrap=True,
            expand=True
        )
        
        def on_save_dlg(e: ft.ControlEvent):
            self.app.logos.aliases = aliases
            self.set_list_participants()
            self.update()
            self.page.close(control=dlg)
        
        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("Manage Icons"),
            content=ft.Column(
                [
                    ft.ElevatedButton(
                        "Add from Google Drive",
                        icon=ft.Icons.ADD_TO_DRIVE,
                        on_click=add_alias
                    ),
                    ft.Column(
                        [row_logos_dlg],
                        expand=True,
                        scroll=ft.ScrollMode.AUTO,
                    )
                ],
                expand=True
            ),
            actions=[
                ft.TextButton(
                    "Save",
                    on_click=on_save_dlg
                ),
                ft.TextButton(
                    "Cancel",
                    on_click=lambda _: self.page.close(dlg)
                )
            ]
        )
        self.page.open(dlg)
        update_row_logos()