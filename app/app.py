import asyncio
import base64
from collections import defaultdict
from dataclasses import dataclass, fields
from datetime import datetime
import flet as ft
from flet.auth import OAuthProvider
from flet.security import encrypt, decrypt
from functools import cache
from google.oauth2.credentials import Credentials
import httpx
import logging
import os
from typing import Literal, Optional, Awaitable, Callable

import tabbycat_api as tc
from .components import TabbycatAuthPagelet, MyAppBar, MyNavDrawer, TeamImporterPagelet, AdjudicatorImporterPagelet, RoundStatusPagelet, LogoManagerPagelet, SlideGeneratorPagelet
from .utils import MyGoogleOAuthProvider, LogoData

LOGGER = logging.getLogger(__name__)
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
GOOGLE_REDIRECT_URL = os.getenv("GOOGLE_REDIRECT_URL")
SECRET_KEY = os.getenv("SECRET_KEY")
# assert GOOGLE_CLIENT_ID, "GOOGLE_CLIENT_ID is not set"
# assert GOOGLE_CLIENT_SECRET, "GOOGLE_CLIENT_SECRET is not set"
# assert SECRET_KEY, "SECRET_KEY is not set"

@dataclass
class AppPagelets:
    pg_tabbycat_auth: TabbycatAuthPagelet = None
    pg_team_importer: TeamImporterPagelet = None
    pg_adjudicator_importer: AdjudicatorImporterPagelet = None
    pg_round_status: RoundStatusPagelet = None
    pg_logo_manager: LogoManagerPagelet = None
    pg_generate_slides: SlideGeneratorPagelet = None
    
    def get_all_pagelets(self) -> list[ft.Pagelet]:
        return [getattr(self, field.name) for field in fields(self) if field.name.startswith("pg_")]
    
    def switch_visibility(self, pagelet: Literal["tabbycat_auth", "team_importer", "adjudicator_importer", "round_status", "logo_manager", "generate_slides"]):
        for k, v in {field.name: getattr(self, field.name) for field in fields(self)}.items():
            if not k.startswith("pg_"):
                pass
            if not isinstance(v, ft.Pagelet):
                pass
            if k == f"pg_{pagelet}":
                v.visible = True
            else:
                v.visible = False
    
    def set_page(self, page: ft.Page, pagelet: Literal["tabbycat_auth", "team_importer", "adjudicator_importer", "round_status", "logo_manager"]):
        for k, v in {field.name: getattr(self, field.name) for field in fields(self)}.items():
            if k == f"pg_{pagelet}":
                page.controls = [v]

class TabbycatApp:
    page: ft.Page
    client: tc.Client = None
    institutions: tc.models.PaginatedInstitutions = None
    tournament: tc.models.Tournament = None
    storage_key: str = None
    provider: MyGoogleOAuthProvider = None
    pagelets: AppPagelets = None
    __httpx: httpx.AsyncClient = None
    __futures: dict[str, asyncio.Future]
    __tasks: dict[str, asyncio.Task]
    __oauth_credentials: Optional[Credentials] = None
    __cached_images: dict[str, asyncio.Task]
    logos: Optional[LogoData]
    
    def __init__(self, page: ft.Page):
        self.page = page
        self.provider = MyGoogleOAuthProvider(
            GOOGLE_CLIENT_ID,
            GOOGLE_CLIENT_SECRET,
            GOOGLE_REDIRECT_URL
        )
        self.pagelets = AppPagelets(
            TabbycatAuthPagelet(),
            TeamImporterPagelet(),
            AdjudicatorImporterPagelet(),
            RoundStatusPagelet(),
            LogoManagerPagelet(),
            SlideGeneratorPagelet()
        )
        self.__tasks = {}
        self.__futures = {}
        self.__cached_images = {}
        self.__httpx = httpx.AsyncClient()
        self.page.data = {"app": self}
        self.page.appbar = MyAppBar(self.on_click_login, on_click_logout=self.on_click_logout)
        self.page.drawer = MyNavDrawer()
        #self.page.on_error = self.on_error
        self.page.on_login = self.on_login
        self.page.on_logout = self.on_logout
        self.page.on_route_change = self.on_route_change
        self.page.controls = self.pagelets.get_all_pagelets()
        self.page.go("/")
    
    def on_click_login(self, e):
        ejt = self.page.client_storage.get("auth_token")
        jt = None
        if ejt:
            jt = decrypt(ejt, SECRET_KEY)
        try:
            self.page.login(
                provider=self.provider,
                saved_token=jt,
                on_open_authorization_url=lambda url: self.page.launch_url(url, web_window_name="_blank"),
                scope=[
                    "https://www.googleapis.com/auth/userinfo.email",
                    "https://www.googleapis.com/auth/userinfo.profile",
                    "https://www.googleapis.com/auth/drive"
                ]
            )
        except Exception:
            LOGGER.warning("An error occurred while logging in, deleting auth token")
            self.page.client_storage.remove("auth_token")
    
    def on_click_logout(self, e):
        self.page.client_storage.remove("auth_token")
        self.page.logout()
    
    async def on_login(self, e: ft.LoginEvent):
        if not e.error:
            LOGGER.info(f"Logged in as {self.page.auth.user['name']}, expires at {datetime.fromtimestamp(self.page.auth.token.expires_at)}")
            def refresh_handler(*args, **kwargs) -> tuple[str, str]:
                token, expires_at = self.page.auth.token.access_token, datetime.fromtimestamp(self.page.auth.token.expires_at)
                LOGGER.info("Refreshing token: token=%s, expires_at=%s", token, expires_at)
                return token, expires_at
            self.__oauth_credentials = Credentials(
                token=self.page.auth.token.access_token,
                refresh_handler=refresh_handler
            )
            jt = self.page.auth.token.to_json()
            ejt = encrypt(jt, SECRET_KEY)
            try:
                await self.page.client_storage.set_async("auth_token", ejt)
            except Exception as e:
                LOGGER.warning(f"Failed to save auth token: {e}")
            self.page.open(
                ft.SnackBar(
                    content=ft.Text("Logged in", color=ft.Colors.BLACK),
                    bgcolor=ft.Colors.GREEN_100
                )
            )
            self.page.appbar.set_loginout()
            self.page.appbar.update()
        else:
            LOGGER.error(f"Login error: {e.error}")
            self.page.open(
                ft.SnackBar(
                    content=ft.Text("Failed to log in", color=ft.Colors.BLACK),
                    bgcolor=ft.Colors.RED_100
                )
            )
    
    def on_logout(self, e):
        self.__oauth_credentials = None
        LOGGER.info("Logged out")
        self.page.open(
            ft.SnackBar(
                content=ft.Text("Logged out", color=ft.Colors.BLACK),
                bgcolor=ft.Colors.GREEN_100
            )
        )
        self.page.appbar.set_loginout()
        self.page.appbar.update()
    
    def on_route_change(self, e: ft.RouteChangeEvent):
        LOGGER.info(f"Route change: {e.route}")
        if self.client is None:
            self.page.go("/")
        else:
            if e.route == "/":
                self.pagelets.switch_visibility("tabbycat_auth")
            elif e.route == "/teams":
                self.pagelets.switch_visibility("team_importer")
            elif e.route == "/adjudicators":
                self.pagelets.switch_visibility("adjudicator_importer")
            elif e.route == "/rounds":
                self.pagelets.switch_visibility("round_status")
            elif e.route == "/logos":
                self.pagelets.switch_visibility("logo_manager")
            elif e.route == "/slides":
                self.pagelets.switch_visibility("generate_slides")
        self.page.update()
    
    async def on_error(self, e):
        LOGGER.exception(e.data)
        self.page.open(
            ft.SnackBar(
                content=ft.Text(f"Error: {e}", color=ft.Colors.BLACK),
                bgcolor=ft.Colors.RED_100
            )
        )
    
    def load_logos(self, storage_key: str):
        key = f"logos.{storage_key}"
        try:
            if not self.page.client_storage.contains_key(key):
                raise KeyError(f"Storage key {storage_key} not found")
            self.logos = LogoData.from_dict(self.page.client_storage.get(key))
        except Exception:
            self.logos = LogoData.default()
    
    async def load_logos_async(self, storage_key: str):
        key = f"logos.{storage_key}"
        try:
            if not await self.page.client_storage.contains_key_async(key):
                raise KeyError(f"Storage key {storage_key} not found")
            self.logos = LogoData.from_dict(await self.page.client_storage.get_async(key))
        except Exception:
            self.logos = LogoData.default()
    
    def save_logos(self, storage_key: str):
        key = f"logos.{storage_key}"
        self.page.client_storage.set(key, self.logos.to_dict())
    
    async def save_logos_async(self, storage_key: str):
        key = f"logos.{storage_key}"
        await self.page.client_storage.set_async(key, self.logos.to_dict())
    
    def clear_logos(self, storage_key: str):
        key = f"logos.{storage_key}"
        if self.page.client_storage.contains_key(key):
            self.page.client_storage.remove(key)
        self.logos = LogoData.default()
    
    async def clear_logos_async(self, storage_key: str):
        key = f"logos.{storage_key}"
        if await self.page.client_storage.contains_key_async(key):
            await self.page.client_storage.remove_async(key)
        self.logos = LogoData.default()
    
    @property
    def oauth_credentials(self) -> Optional[Credentials]:
        return self.__oauth_credentials
    
    async def cache_image_async(self, *, src: Optional[str]=None, file_id: Optional[str]=None) -> str|None:
        try:
            if not src and not file_id:
                raise ValueError("Either src or file_id must be provided.")
            if src and file_id:
                raise ValueError("Either src or file_id must be provided, not both.")
            headers = None
            if file_id: # Google Drive
                if self.page.auth is None:
                    raise Exception("Not authenticated")
                src = f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media"
                headers = {"Authorization": f"Bearer {self.page.auth.token.access_token}"}
            async def wrapper():
                response = await self.__httpx.get(src, headers=headers)
                response.raise_for_status()
                base64_image = base64.b64encode(response.content).decode("utf-8")
                return base64_image
            # Check if the image is already cached
            if src not in self.__cached_images:
                self.__cached_images[src] = asyncio.create_task(wrapper())
            elif self.__cached_images[src].done() and self.__cached_images[src].exception():
                # If the task failed, create a new one
                self.__cached_images[src] = asyncio.create_task(wrapper())
            # Wait for the task to complete
            return await self.__cached_images[src]
        except Exception as e:
            return None
    
    @cache
    def cache_image(self, src: str) -> str:
        response = httpx.get(src)
        response.raise_for_status()
        base64_image = base64.b64encode(response.content).decode("utf-8")
        return base64_image
    
    async def set_tabbycat(self, client: tc.Client, tournament: tc.models.Tournament, storage_key: str):
        self.client = client
        self.tournament = tournament
        self.institutions = await self.client.get_institutions()
        await asyncio.gather(
            self.update_teams(),
            self.update_break_categories(),
            self.update_speakers(),
            self.update_speaker_categories(),
            self.update_adjudicators(),
            self.update_rounds(),
            self.update_motions(),
            self.update_venues(),
            self.update_venue_categories(),
            self.update_feedback_questions(),
            self.update_feedback(),
            self.update_preferences(),
        )
        self.storage_key = storage_key.split(".")[-1]
        LOGGER.info(f"Set Tabbycat {tournament.name} (storage_key = {self.storage_key})")
        await self.load_logos_async(self.storage_key)
        self.page.drawer.set_tabbycat()
        self.pagelets.pg_logo_manager.set_tabbycat()
        self.pagelets.pg_generate_slides.set_tabbycat()
        self.page.drawer.update()
    
    async def run_task[T](self, key: str, coro: Awaitable, rerun: bool = True, *, args = None, kwargs = None) -> T:
        """Runs a task and returns the result. Prevents multiple tasks from running at the same time.
        """
        future = self.__futures.get(key, None)
        if future and not rerun:
            LOGGER.debug(f"Task {key} has already run. Returning...")
            return await future
        if future is None or future.done():
            future = asyncio.Future()
            self.__futures[key] = future
        if key in self.__tasks:
            task = self.__tasks.get(key)
            if task and not task.done():
                # Cancel existing running tasks and wait until halted
                LOGGER.debug(f"Task {key} is running. Cancelling...")
                # Cancel existing running tasks and wait until halted
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        async def _task():
            try:
                result = await coro
                future.set_result(result)
            except Exception as e:
                future.set_exception(e)
        task = asyncio.create_task(_task())
        self.__tasks[key] = task
        return await future
    
    async def update_institutions(self):
        await self.run_task("update_institutions", self.institutions.load(force=True))
    
    async def update_teams(self):
        await self.run_task("update_teams", self.tournament._links.teams.load(force=True))
    
    async def update_break_categories(self):
        await self.run_task("update_break_categories", self.tournament._links.break_categories.load(force=True))
    
    async def update_speakers(self):
        await self.run_task("update_speakers", self.tournament._links.speakers.load(force=True))
    
    async def update_speaker_categories(self):
        await self.run_task("update_speaker_categories", self.tournament._links.speaker_categories.load(force=True))
    
    async def update_adjudicators(self):
        await self.run_task("update_adjudicators", self.tournament._links.adjudicators.load(force=True))
    
    async def update_rounds(self):
        await self.run_task("update_rounds", self.tournament._links.rounds.load(force=True))
    
    async def update_motions(self):
        await self.run_task("update_motions", self.tournament._links.motions.load(force=True))
    
    async def update_venues(self):
        await self.run_task("update_venues", self.tournament._links.venues.load(force=True))
    
    async def update_venue_categories(self):
        await self.run_task("update_venue_categories", self.tournament._links.venue_categories.load(force=True))
    
    async def update_feedback_questions(self):
        await self.run_task("update_feedback_questions", self.tournament._links.feedback_questions.load(force=True))
    
    async def update_feedback(self):
        await self.run_task("update_feedback_responses", self.tournament._links.feedback.load(force=True))
    
    async def update_preferences(self):
        await self.run_task("update_preferences", self.tournament._links.preferences.load(force=True))