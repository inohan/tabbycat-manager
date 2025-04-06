import flet as ft
import os
import sys
import tabbycat_api as tc
from dotenv import load_dotenv
import logging
import coloredlogs
load_dotenv()
tc.config.set_tabbycat_config(null_exception=False, lazy_load=False)
from app import TabbycatApp

def main(page: ft.Page):
    #page.client_storage.clear()
    app = TabbycatApp(page)

# Set up logging to stdout
handler = logging.StreamHandler(sys.stdout)
handler.setLevel(logging.INFO)  # Adjust the logging level as needed

formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)

logger = logging.getLogger()
logger.setLevel(logging.INFO)  # Adjust the logging level as needed
logger.addHandler(handler)

print(f"Starting Tabbycat Flet app, port {os.getenv('PORT')}")
logging.getLogger(__name__).info("Starting Tabbycat Flet app, port %s", os.getenv("PORT"))
ft.app(
    main,
    port=os.getenv("PORT", 8550),
    #view=ft.WEB_BROWSER,
    assets_dir="assets",
    upload_dir="assets/uploads",
)