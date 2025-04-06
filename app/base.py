from __future__ import annotations
import flet as ft
from functools import wraps
import inspect
from typing import Callable, TYPE_CHECKING
import logging
if TYPE_CHECKING:
    from .app import TabbycatApp

LOGGER = logging.getLogger(__name__)

def try_string(fn: Callable, err: str = "Unknown") -> str:
    try:
        return str(fn())
    except Exception:
        return err

def wait_finish(fn):
    """
    Decorator to disable a button while the function is running.
    Supports sync and async functions, as well as instance methods.
    Also handles exceptions and shows them in a SnackBar.
    """
    def get_event_arg(args) -> ft.ControlEvent:
        """Extract the event argument, adjusting for bound methods."""
        return args[-1]
        #return args[1] if inspect.isfunction(fn) and "." in fn.__qualname__ else args[0]

    @wraps(fn)
    async def async_wrapper(*args, **kwargs):
        e = get_event_arg(args)
        if e:
            e.control.disabled = True
            e.control.update()
        try:
            return await fn(*args, **kwargs)
        except Exception as err:
            LOGGER.exception(err)
            e.page.open(
                ft.SnackBar(
                    ft.Text(f"{type(err).__name__}: {err}", color=ft.Colors.BLACK),
                    bgcolor=ft.Colors.RED_100,
                )
            )
        finally:
            if e:
                e.control.disabled = False
                e.control.update()

    @wraps(fn)
    def sync_wrapper(*args, **kwargs):
        e = get_event_arg(args)
        if e:
            e.control.disabled = True
            e.control.update()
        try:
            return fn(*args, **kwargs)
        except Exception as err:
            LOGGER.exception(err)
            e.page.open(
                ft.SnackBar(
                    ft.Text(f"{type(err).__name__}: {err}", color=ft.Colors.BLACK),
                    bgcolor=ft.Colors.RED_100,
                )
            )
        finally:
            if e:
                e.control.disabled = False
                e.control.update()

    return async_wrapper if inspect.iscoroutinefunction(fn) else sync_wrapper

class AppControl:
    @property
    def app(self) -> TabbycatApp:
        return self.page.data["app"]