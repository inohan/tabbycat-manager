import flet as ft
from typing import Optional, Any
import inspect

class EditableDataCell(ft.DataCell):
    __on_change: ft.OptionalEventCallable
    
    def __init__(
        self,
        value: Optional[str],
        placeholder: Optional[bool] = None,
        on_change: ft.OptionalEventCallable = None,
        ref: Optional[Any] = None,
        visible: Optional[bool] = None,
        disabled: Optional[bool] = None,
        data: Any = None
    ):
        self._text_value = ft.Text(value)
        self._text_field = ft.TextField(
            value=value,
            on_blur=self._on_cancel,
            expand=True
        )
        super().__init__(
            self._text_value,
            placeholder,
            True,
            on_tap=self._on_tap,
            on_tap_cancel=self._on_cancel,
            ref=ref,
            visible=visible,
            disabled=disabled,
            data=data
        )
        self.value = value
        self.on_change = on_change
    
    @property
    def value(self) -> str:
        return self._text_value.value
    
    @value.setter
    def value(self, value: str):
        self._text_value.value = value
    
    @property
    def on_change(self) -> ft.OptionalEventCallable:
        return self.__on_change
    
    @on_change.setter
    def on_change(self, value: ft.OptionalEventCallable):
        self.__on_change = value
        if inspect.iscoroutinefunction(value):
            async def on_submit(e: ft.ControlEvent):
                self.value = self._text_field.value
                self._on_cancel(e)
                await value(ft.ControlEvent(self._id, "change", None, self, self.page))
        elif callable(value):
            def on_submit(e: ft.ControlEvent):
                self.value = self._text_field.value
                self._on_cancel(e)
                value(ft.ControlEvent(self._id, "change", None, self, self.page))
        else:
            def on_submit(e: ft.ControlEvent):
                self.value = self._text_field.value
                self._on_cancel(e)
        self._text_field.on_submit = on_submit
    
    def _on_tap(self, e: ft.ControlEvent):
        self.content = self._text_field
        self._text_field.value = self.value
        self.show_edit_icon = False
        self.on_tap = None
        self.update()
        self._text_field.focus()
    
    def _on_cancel(self, e: ft.ControlEvent):
        self.content = self._text_value
        self.show_edit_icon = True
        self.on_tap = self._on_tap
        self.update()