import logging.config
import flet as ft
import json
import os
import sys
import tabbycat_api as tc
from dotenv import load_dotenv
import logging
load_dotenv()
tc.config.set_tabbycat_config(null_exception=False, lazy_load=False)
from app import TabbycatApp

def main(page: ft.Page):
    TabbycatApp(page)

def set_logging(default_level=logging.INFO):
    if os.path.exists(os.getenv("LOGGING_CONFIG", "logging.json")):
        with open(os.getenv("LOGGING_CONFIG", "logging.json")) as f:
            logging.config.dictConfig(
                json.load(f)
            )
    else:
        logging.basicConfig(level=default_level)

if __name__ == "__main__":
    set_logging()
    logging.getLogger(__name__).info("Starting Tabbycat Flet app, port %s", os.getenv("PORT"))
    ft.app(
        main,
        port=int(os.getenv("PORT", 8550)),
        view=ft.WEB_BROWSER,
        assets_dir="assets",
        upload_dir="assets/uploads",
    )
    