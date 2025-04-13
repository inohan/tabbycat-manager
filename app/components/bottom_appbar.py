import flet as ft
import logging
from ..base import AppControl
from ..utils import get_version

LOGGER = logging.getLogger(__name__)

class MyBottomAppBar(ft.BottomAppBar, AppControl):
    def __init__(self):
        super().__init__(
            ft.Row(
                [
                    ft.Text(f"Tabbycat Manager v.{get_version()}")
                ],
                alignment=ft.MainAxisAlignment.CENTER
            ),
            padding=ft.padding.symmetric(5, 0),
            height=30
        )