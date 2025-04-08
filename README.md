# Tabbycat Manager

A web application extension for [Tabbycat](https://github.com/TabbycatDebate/tabbycat) made to make organizing easier, using [Flet](https://flet.dev/).

-   [GitHub](https://github.com/inohan/tabbycat-manager)
-   [Web App](https://tabbycat-manager-a5a33890fcfc.herokuapp.com/)

## Features

-   **Team & Adjudicator importer**: you can import data to tabbycat from CSV, Excel, or Google Spreadsheet.
-   **Round Status viewer**: you can see the submission of feedbacks AND ballots per debate and check for wrong ballot submissions.
-   **Slide Generator**: you can create break announcements & closing ceremony slides relatively easily, with support for inserting institutional logos

## Getting started

### Online

An online version is available [here](https://tabbycat-manager-a5a33890fcfc.herokuapp.com/).

### Running locally

You also have the option to run the app locally on your computer.

**Requirements**

-   Python 3.13
-   Git

1. Install `uv` using the methods in the [official documentation](https://docs.astral.sh/uv/getting-started/installation/#standalone-installer).

2. Clone this repository (do not include the `$` in the beginning).

    ```sh
    $ git clone https://github.com/inohan/tabbycat-manager.git
    ```

3. Navigate to the cloned repository and activate virtual environment.

    ```sh
    $ cd tabbycat-manager
    $ uv venv
    ```

4. (First time only) Go to [Google Cloud Platform](https://console.cloud.google.com/) and create a project and an OAuth client.

    - Go to **Enabled APIs & services** page under **APIs & Services** section, activate **Google Drive API**, **Google Sheets API**, and **Google Slides API** in the .
    - Go to **Credentials** page under **APIs & Services** section, click **+ Create credentials** and select **OAuth clientID**. Once navigated, select **Web application** as Application type, type in `http://localhost:8550` for **Authorized JavaScript origins** and `http://localhost:8550/oauth_callback` for **Authorized redirect URIs**. Then click **Create**. Copy the Google Client ID and secret.
    - If you need to set up **OAuth consent screen**, set it up.
    - In the **Audience** page under **Google Auth Platform**, if the **Publishing status** is in testing, you must add yourself as authorized testing user.

5. (First time only) Create a `.env` file containing all the environment variables necessary for connection. In the file, add the following environment variables.

    ```
    GOOGLE_CLIENT_ID="(Google Client ID for your OAuth Client)"
    GOOGLE_CLIENT_SECRET="(Google Client secret for your OAuth Client)"
    GOOGLE_REDIRECT_URL="http://localhost:8550/oauth_callback"
    SECRET_KEY="(A random secret key for encoding confidential data)"
    FLET_SECRET_KEY="(A secret key, such as abcdef)"
    PORT=8550
    ```

6. Run the program. You can customize the startup method (web app / standalone executable) according to the settings for [Flet](https://flet.dev/docs/reference/cli/run), but the following setting is recommended.
    ```
    $ uv run flet run -wnd -p 8550
    ```

## Usage

1. Enter the URL (e.g. `https://xyz.calicotab.com`) and API Token (can be found in the **Get API Token / Change Password** page on Tabbycat) and click **Load**. Next, select the tournament to load. Alternatively, tournaments that have been loaded in the past can be loaded from the **Login from history** dropdown.

2. (Optional, but required for most functions including selecting files and generating slides) Log in to Google from the top-right circle.

3. From the menu icon on the top left, go to whichever page you want to use.

### Import Teams / Adjudicators

1. Enter data you want to import to CSV / Excel / Spreadsheet file. Make sure that the header (= first row) of the sheet is named according to the supported columns (supports `snake_case`, `camelCase`, and `PascalCase` of headers).

    - For example, for teams, you should have the headers named "institution", "break_categories", "speaker_1_email", etc.
    - For example, for adjudicators, you should have the headers named "name", "institution", etc.
    - Separate speaker / break categories with comma (`,`).
    - Institutions, break categories and speaker categories not recognized in the tab will be automatically created.

2. Select the CSV / Excel / Google Spreadsheet file you want to load by clicking **Upload** (for local files) or **Select from Google Spreadsheets** (for files on Google Drive; you must be logged in to google).

3. Click **Import** to import.

### Round Status

1. Click **Update**

2. Tabs will be displayed for each round. If everything in the round is confirmed, a green checkmark will appear on the tab label. Otherwise, a red circle will appear.

3. You can check the details for each debate room, including the ballot, result, and feedback submission.

### Manage Logos

This page is used to set institutional logos for each speaker, team or adjudicator. When creating break announcement slides or closing ceremony slides, the data input here will be used.

-   Click on **Manage Icons** on the top left to bulk import icons from Google Drive. This is recommended for cases where you import logos used for multiple teams, such as institutional logos.
-   Click on each speaker / team / adjudicator tile to edit the logos. The institution will be loaded automatically from tab if team or adjudicator's institution is set; otherwise, you will have to add it manually.
-   By default, the logo for teams is set to the combination of all logos of the teammates. However, in certain cases where you need to set the logo differently (e.g. a "team logo"), you can set the team logo by checking off **Use logos of speakers**.
-   Save the modifications, otherwise they will not persist.

### Generate Slides

This will generate slides based on the institutional logo set in the **Manage Logos** page and the standings data.

-   To change the format of the metrics (e.g. display points as "xx points" instead of "xx pts."), change from **Edit displayed metrics**. The braces `{}` will be replaced by the value, and you can customize the digits displayed according to the [formatting rules of python](https://www.w3schools.com/python/ref_string_format.asp).
-   To bulk change the title of the metrics, click **Change Title** under each tab and set the format.
-   For adjudicators, you can set the ratio of base score and feedback score, and whether to round scores from **Change Calculation**.
-   To generate the slides, click Generate and select the target file.
    -   Select the template slide for each number of logos.
    -   Select whether the slides should be in ascending order (usually for breaks) or descending order (usually for closing ceremony).
    -   Select whether you want danger prevention slides inserted before every slide.

## Issues

Please submit issues via [GitHub](https://github.com/inohan/tabbycat-manager).
