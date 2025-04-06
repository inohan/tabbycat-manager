import flet as ft
import inspect
from typing import Callable, Optional, Any
import re
from googleapiclient.discovery import build
import logging
import asyncio
from ..base import AppControl, wait_finish

LOGGER = logging.getLogger(__name__)

class GoogleFilePickerResultEvent(ft.ControlEvent):
    def __init__(self, e: Optional[ft.ControlEvent], data: Optional[dict], control: "GoogleFilePicker"):
        if e is not None:
            super().__init__(e.target, e.name, data, control=control, page=e.page)
        else:
            super().__init__(None, "error", data, control, control.page)

class GoogleFilePicker(ft.AlertDialog, AppControl):
    __service: Any = None
    __current_directory: Optional[str] = None
    __cache: dict[str, dict]
    mime_types: Optional[list[str]] = None
    __on_result: ft.OptionalEventCallable = None
    __exit_func: ft.OptionalEventCallable = None
    
    def __init__(
        self,
        title: Optional[ft.Control] = None,
        mime_type: Optional[list[str]] = None,
        service: Any = None,
        on_result: Optional[Callable] = None,
        data: Any = None
    ):
        self.__service = service
        self.__cache = {}
        self.mime_types = mime_type
        self.text_search = ft.TextField(
            label="Search",
            hint_text="Keyword or URL",
            on_submit=self._on_search,
            expand=True
        )
        self.row_path = ft.Row(
            [],
            spacing=0,
            wrap=True,
            )
        self.list_view = ft.ResponsiveRow(
            [],
            expand=True
        )
        async def on_confirm(e: ft.ControlEvent):
            selected = next((lt for lt in self.list_view.controls if hasattr(lt, "selected") and lt.selected), None)
            # Check if a selected file content exists and is a supported mime type
            if not (selected and self.verify_mime(selected.data)):
                return
            self.page.close(self)
            event = GoogleFilePickerResultEvent(
                e,
                selected.data,
                self
            )
            if self.on_result is None:
                return
            if inspect.iscoroutinefunction(self.on_result):
                return await self.on_result(event)
            return self.on_result(event)
        async def on_cancel(e: ft.ControlEvent):
            self.page.close(self)
            event = GoogleFilePickerResultEvent(
                e,
                None,
                self
            )
            if self.on_result is None:
                return
            if inspect.iscoroutinefunction(self.on_result):
                return await self.on_result(event)
            self.on_result(event)
        async def on_home(e: ft.ControlEvent):
            await self.load_path("root")
        super().__init__(
            modal=True,
            title=title,
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.IconButton(
                                ft.Icons.HOME_FILLED,
                                on_click=on_home,
                                tooltip="My Drive",
                            ),
                            self.text_search
                        ]
                    ),
                    self.row_path,
                    ft.Column(
                        [self.list_view],
                        expand=True,
                        scroll=ft.ScrollMode.AUTO,
                    )
                ],
                expand=True,
                width=1600
            ),
            actions=[
                ft.TextButton(
                    "Confirm",
                    #on_click=on_confirm
                ),
                ft.TextButton(
                    "Cancel",
                    #on_click=on_cancel
                )
            ],
            data=data
        )
        self.on_result = on_result
    
    @property
    def on_result(self) -> ft.OptionalEventCallable:
        return self.__on_result
    
    @on_result.setter
    def on_result(self, value: ft.OptionalEventCallable):
        self.__on_result = value
        if not callable(value):
            on_confirm = value
            on_cancel = value
        elif inspect.iscoroutinefunction(value):
            @wait_finish
            async def on_confirm(e: ft.ControlEvent):
                selected = next((lt for lt in self.list_view.controls if hasattr(lt, "selected") and lt.selected), None)
                # Check if a selected file content exists and is a supported mime type
                if not (selected and self.verify_mime(selected.data)):
                    return
                self.page.close(self)
                event = GoogleFilePickerResultEvent(e, selected.data, self)
                await value(event)
            @wait_finish
            async def on_cancel(e: ft.ControlEvent):
                self.page.close(self)
                event = GoogleFilePickerResultEvent(e, None, self)
                await value(event)
        else:
            def on_confirm(e: ft.ControlEvent):
                selected = next((lt for lt in self.list_view.controls if hasattr(lt, "selected") and lt.selected), None)
                # Check if a selected file content exists and is a supported mime type
                if not (selected and self.verify_mime(selected.data)):
                    return
                self.page.close(self)
                event = GoogleFilePickerResultEvent(e, selected.data, self)
                value(event)
            def on_cancel(e: ft.ControlEvent):
                self.page.close(self)
                event = GoogleFilePickerResultEvent(e, None, self)
                value(event)
        self.actions[0].on_click = on_confirm
        self.actions[1].on_click = on_cancel
        self.__exit_func = on_cancel
    
    def did_mount(self):
        super().did_mount()
        if self.__service is None:
            self.set_credentials()
        if self.__service is None:
            if inspect.iscoroutinefunction(self.__exit_func):
                self.page.run_task(self.__exit_func, None)
            elif callable(self.__exit_func):
                self.__exit_func(None)
            return
        root = self.__service.files().get(
            fileId="root",
            fields="id, name, iconLink, mimeType, parents"
        ).execute()
        self.to_cache(root)
        self.__cache["root"] = root
        self.page.run_task(self.load_path, "root")
    
    def verify_mime(self, file: dict) -> bool:
        selected_mime = file.get("mimeType")
        return not (self.mime_types and not any(mt in selected_mime for mt in self.mime_types))
    
    def to_cache(self, file: dict):
        if file.get("id") is None:
            raise ValueError("File ID is None.")
        self.__cache[file.get("id")] = file
    
    def set_credentials(self):
        if self.app.oauth_credentials:
            self.__service = build(
                "drive",
                "v3",
                credentials=self.app.oauth_credentials
            )
    
    async def load_path(self, file_id: str):
        if not self.__service:
            if inspect.iscoroutinefunction(self.__exit_func):
                await self.__exit_func(None)
            elif callable(self.__exit_func):
                self.__exit_func(None)
            raise Exception("Google Drive service not available.")
        # If parent is undiscovered, get it
        if file_id not in self.__cache:
            result = self.__service.files().get(
                fileId=file_id,
                fields="id, name, iconLink, mimeType, parents"
            ).execute()
            self.to_cache(result)
        self.__current_directory = file_id
        q = f"'{file_id}' in parents and trashed = false"
        if self.mime_types:
            q_mime = " or ".join(
                ["mimeType = 'application/vnd.google-apps.folder'"] + [f"mimeType contains '{mime_type}'" for mime_type in self.mime_types]
            )
            q = f"{q} and ({q_mime})"
        result = self.__service.files().list(
            q=q,
            fields="nextPageToken, files(id, name, iconLink, mimeType, parents)",
            orderBy="folder,name_natural"
        ).execute()
        items = result.get("files", [])
        # Set to flet controls
        await self.update_files(items, self.__current_directory)
    
    async def update_files(self, files: list[dict], cd: str = None):
        """Updates the list view with the given files

        Args:
            files (list[dict]): list of Files object to display
            cd (str, optional): Current directory to display in path bar. Defaults to None.
        """
        async def gather_and_control(file: dict) -> ft.ListTile:
            self.to_cache(file)
            base64 = await self.app.cache_image_async(src=file.get("iconLink", None))
            return ft.ListTile(
                title=ft.Text(file.get("name", "Unknown")),
                leading=ft.Image(
                    src_base64=base64
                ),
                data=file,
                on_long_press=self._on_select,
                on_click=self._on_single_select,
                col=3
            )
        self.list_view.controls.clear()
        if len(files):
            self.list_view.controls.extend(
                await asyncio.gather(
                    *[
                        gather_and_control(file) for file in files
                    ]
                )
            )
        else:
            self.list_view.controls.append(
                ft.Text("No files found.", col=12)
            )
        await self.set_path_display(cd)
        self.update()
    
    async def set_path_display(self, id: Optional[str]):
        async def get_path_button(item: dict) -> ft.TextButton:
            controls = []
            if "iconLink" in item:
                controls.append(ft.Image(
                    src_base64=await self.app.cache_image_async(src=item.get("iconLink", None)),
                ))
            controls.append(ft.Text(item.get("name", "Unknown")))
            return ft.TextButton(
                content=ft.Row(
                    controls,
                    tight=True
                ),
                data=item,
                on_click=self._on_select,
            )
        # In case no current directory, set to root
        if id is None:
            self.row_path.controls = [await get_path_button(self.__cache.get("root", None))]
            return
        self.row_path.controls.clear()
        path = []
        current = self.__cache.get(id, None)
        while current:
            path.append(current)
            current = self.__cache.get(parent_ids[0], {"id": parent_ids[0], "mimeType": "application/vnd.google-apps.folder"}) if (parent_ids := current.get("parents", None)) else None
        for i, item in enumerate(reversed(path)):
            # Create a ">" icon
            if i:
                self.row_path.controls.append(ft.Icon(ft.Icons.KEYBOARD_ARROW_RIGHT))
            # Create a clickable button with the icon and name
            self.row_path.controls.append(await get_path_button(item))
    
    async def _on_search(self, e: ft.ControlEvent):
        value = e.control.value
        if not value:
            return await self.load_path(self.__current_directory)
        match_id = re.search(r"(?:\/d\/|\/folders\/|id=)([a-zA-Z0-9_-]+)", value)
        # fileId is directly input
        if match_id:
            result = self.__service.files().get(
                fileId=match_id.group(1),
                fields="id, name, iconLink, mimeType, parents"
            ).execute()
            self.__current_directory = None
            if not self.verify_mime(result):
                return await self.update_files([], None)
            self.to_cache(result)
            return await self.update_files([result], None)
        # Keyword search
        else:
            q = "trashed = false"
            if self.mime_types:
                q_mime = " or ".join(
                    ["mimeType = 'application/vnd.google-apps.folder'"] + [f"mimeType contains '{mime_type}'" for mime_type in self.mime_types]
                )
                q = f"{q} and ({q_mime})"
            # Search
            q_search = " or ".join(
                [f"name contains '{word}'" for word in value.split()]
            )
            q = f"{q} and ({q_search})"
            # If not in root, add parent condition
            if self.__current_directory and self.__current_directory != "root" and self.__current_directory != self.__cache.get("root", {}).get("id", None):
                q = f"{q} and '{self.__current_directory}' in parents"
            result = self.__service.files().list(
                q=q,
                fields="nextPageToken, files(id, name, iconLink, mimeType, parents)",
                orderBy="folder,name_natural"
            ).execute()
            items = result.get("files", [])
            await self.update_files(items, self.__current_directory)
    
    async def _on_select(self, e: ft.ControlEvent):
        if e.control.data.get("mimeType") == "application/vnd.google-apps.folder":
            await self.load_path(e.control.data.get("id"))
    
    def _on_single_select(self, e: ft.ControlEvent):
        """Selects a ListTile object and deselects all others"""
        for lt in self.list_view.controls:
            lt.selected = False
        e.control.selected = True
        self.update()