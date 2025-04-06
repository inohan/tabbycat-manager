import flet as ft
import tabbycat_api as tc
import logging
import uuid
from ..base import AppControl, wait_finish

LOGGER = logging.getLogger(__name__)

class LoginCard(ft.Card, AppControl):
    def __init__(self):
        self.dropdown_history = ft.Dropdown(
            options=[],
            label="History",
            value="null",
            expand=True,
            width=500
        )
        self.input_url = ft.TextField(
            label="URL",
            hint_text="https://xyz.calicotab.com/",
        )
        self.input_token = ft.TextField(
            label="Token",
            hint_text="API Token",
        )
        self.button_load = ft.ElevatedButton(
            text="Load",
            on_click=self.on_load,
        )
        self.dropdown_slug = ft.Dropdown(
            options=[],
            label="Select Tournament"
        )
        self.button_slug = ft.ElevatedButton(
            text="Login"
        )
        self.col_select_tournament = ft.Column(
            [
                ft.Divider(),
                ft.Text("Select Tournament", theme_style=ft.TextThemeStyle.TITLE_MEDIUM),
                self.dropdown_slug,
                self.button_slug
            ],
            visible=False
        )
        super().__init__(
            content=ft.Container(
                ft.Column(
                [
                        ft.Text("Login to Tabbycat", theme_style=ft.TextThemeStyle.TITLE_LARGE),
                        ft.Text("Login from history", theme_style=ft.TextThemeStyle.TITLE_MEDIUM),
                        ft.Row(
                            [self.dropdown_history],
                        ),
                        ft.Divider(),
                        ft.Text("Login with URL and Token", theme_style=ft.TextThemeStyle.TITLE_MEDIUM),
                        self.input_url,
                        self.input_token,
                        self.button_load,
                        self.col_select_tournament
                    ],
                ),
                margin=40
            ),
        )
    
    def did_mount(self):
        super().did_mount()
        self.update_history()
    
    @wait_finish
    async def on_load(self, e):
        key: str = self.dropdown_history.value if self.dropdown_history.value != "null" else None
        cache: dict|None = key and await self.page.client_storage.get_async(key)
        base_url: str = ""
        token: str = ""
        slug: str|None = None
        if cache is not None: # Login from history
            base_url = cache["base_url"]
            slug = cache["slug"]
            token = cache["token"]
        else: # Login with URL and Token
            base_url = self.input_url.value
            token = self.input_token.value
        client = tc.Client(
            tc.ClientConfig(
                base_url=base_url,
                api_token=token,
                editable=True,
                httpx_timeout=20
            )
        )
        tournaments = await client.get_tournaments()
        if not len(tournaments):
            raise ValueError("No tournaments found")
        if slug is None:
            self.dropdown_slug.options = [
                ft.DropdownOption(
                    key=t.slug,
                    text=f"{t.name} ({t.short_name})"
                ) for t in tournaments
            ]
            self.dropdown_slug.value = self.dropdown_slug.options[0].key
            self.col_select_tournament.visible = True
            async def on_login(e):
                tournament = tournaments.find(slug=self.dropdown_slug.value)
                # Cache entry
                saved_caches: dict[str, dict] = {key: await self.page.client_storage.get_async(key) for key in await self.page.client_storage.get_keys_async("tabbycat_login.")}
                value = {
                    "base_url": client._config.base_url,
                    "name": f"{tournament.name} ({tournament.short_name})",
                    "slug": tournament.slug,
                    "token": token,
                }
                hit_key = next((k for k, v in saved_caches.items() if v == value), None)
                if hit_key is None:
                    hit_key = f"tabbycat_login.{uuid.uuid4().hex}"
                    await self.page.client_storage.set_async(hit_key, value)
                await self.login(client, tournament, hit_key)
            self.button_slug.on_click = on_login
            self.update()
        elif (target_tournament := tournaments.find(slug=slug)) is not None:
            await self.login(client, target_tournament, key)
        else:
            raise ValueError(f"Tournament {slug} not found")
    
    async def login(self, client: tc.Client, tournament: tc.models.Tournament, storage_key: str):
        await self.app.set_tabbycat(client, tournament, storage_key)
        self.page.open(
            ft.SnackBar(
                content=ft.Text(f"Logged in to {tournament.name}", color=ft.Colors.BLACK),
                bgcolor=ft.Colors.GREEN_100
            )
        )
    
    def update_history(self):
        saved_caches = {key: self.page.client_storage.get(key) for key in self.page.client_storage.get_keys("tabbycat_login.")}
        self.dropdown_history.options.clear()
        self.dropdown_history.options.append(ft.DropdownOption(key="null", text="-- Load from URL and token --"))
        self.dropdown_history.options.extend(
            [
                ft.DropdownOption(
                    key=key,
                    text=f"{cache['name']} ({cache['base_url']})"
                ) for key, cache in saved_caches.items()
            ]
        )
        self.dropdown_history.value = "null"
        self.dropdown_history.update()

class TabbycatAuthPagelet(ft.Pagelet):
    
    def __init__(self):
        super().__init__(
            ft.Container(
                LoginCard(),
                alignment=ft.alignment.center
            )
        )