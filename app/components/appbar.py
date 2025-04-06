import flet as ft

class MyAppBar(ft.AppBar):
    _on_login: ft.OptionalEventCallable
    _on_logout: ft.OptionalEventCallable
    
    def __init__(self, on_click_login: ft.OptionalEventCallable = None, on_click_logout: ft.OptionalEventCallable = None):
        self._on_login = on_click_login
        self._on_logout = on_click_logout
        self.avatar = ft.CircleAvatar(
            ft.Icon(ft.Icons.WARNING_ROUNDED),
        )
        self.btn_loginout = ft.PopupMenuItem(
            text="Log In",
            on_click=on_click_login
        )
        super().__init__(
            leading=ft.IconButton(
                icon=ft.Icons.MENU,
                on_click=lambda e: self.page.open(self.page.drawer)
            ),
            title=ft.Text("Tabbycat Manager"),
            actions=[
                ft.PopupMenuButton(
                    content=self.avatar,
                    items=[
                        self.btn_loginout
                    ]
                )
            ]
        )
    
    def build(self):
        super().build()
        self.set_loginout()
    
    def set_loginout(self):
        if self.page.auth is not None: #Logged in
            self.avatar.foreground_image_src = self.page.auth.user["picture"]
            self.btn_loginout.text = "Log Out"
            self.btn_loginout.on_click = self._on_logout
        else:
            self.avatar.foreground_image_src = None
            self.btn_loginout.text = "Log In"
            self.btn_loginout.on_click = self._on_login
        #self.update()