from typing import TYPE_CHECKING
import flet as ft
import logging
from ..base import AppControl

LOGGER = logging.getLogger(__name__)

class MyNavDrawer(ft.NavigationDrawer, AppControl):
    def __init__(self):
        super().__init__(
            [
                ft.NavigationDrawerDestination(
                    label="Home",
                    icon=ft.Icons.HOME_OUTLINED,
                    selected_icon=ft.Icons.HOME
                ),
                ft.NavigationDrawerDestination(
                    label="Import Teams",
                    icon=ft.Icons.GROUPS_OUTLINED,
                    selected_icon=ft.Icons.GROUPS,
                    disabled=True
                ),
                ft.NavigationDrawerDestination(
                    label="Import Adjudicators",
                    icon=ft.Icons.BALANCE_OUTLINED,
                    selected_icon=ft.Icons.BALANCE,
                    disabled=True
                ),
                ft.NavigationDrawerDestination(
                    label="Round Status",
                    icon=ft.Icons.TIMER_OUTLINED,
                    selected_icon=ft.Icons.TIMER,
                    disabled=True
                ),
                ft.NavigationDrawerDestination(
                    label="Manage Logos",
                    icon=ft.Icons.IMAGE_OUTLINED,
                    selected_icon=ft.Icons.IMAGE,
                    disabled=True
                ),
                ft.NavigationDrawerDestination(
                    label="Generate Slides",
                    icon=ft.Icons.AUTO_AWESOME_MOTION_OUTLINED,
                    selected_icon=ft.Icons.AUTO_AWESOME_MOTION,
                    disabled=True
                ),
            ],
            on_change=self.on_change_item
        )
    
    def set_tabbycat(self):
        for ctrl in self.controls[1:]:
            ctrl.disabled = self.app.client is None
    
    def on_change_item(self, e):
        match e.control.selected_index:
            case 0:
                self.page.go("/")
            case 1:
                self.page.go("/teams")
            case 2:
                self.page.go("/adjudicators")
            case 3:
                self.page.go("/rounds")
            case 4:
                self.page.go("/logos")
            case 5:
                self.page.go("/slides")