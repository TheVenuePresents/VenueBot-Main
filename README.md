# HostBot

HostBot is a Discord bot that automates assigning co-hosts in a Zoom meeting.
The bot sends commands to TriggerCMD. Configuration is provided through
environment variables and a local JSON file.

## Requirements
- Python 3.8+
- See `requirements.txt` for Python package dependencies

## Installation
1. Install Python.
2. Install the required Python packages:
   ```bash
   pip install -r requirements.txt
   ```
3. Copy the provided `.env.example` file to `.env` (or edit the existing
   `.env` file) and fill in your Discord details. HostBot uses `python-dotenv`
   to load the file automatically when it starts.

### Environment Variables
HostBot loads the following variables from a `.env` file if present. Some have
defaults while others must be provided:

```bash
DISCORD_BOT_TOKEN=your-token-id
DISCORD_CHANNEL_ID=YOUR-CHANNEL-ID
DISCORD_BOT_LOG=YOUR-LOG-CHANNEL-ID
DISCORD_COHOST_ROLE=YOUR-ROLE-ID
DISCORD_OPS_ROLE=YOUR-ROLE-ID
EMBED_THUMBNAIL_URL=https://example.com/thumbnail.png
EMBED_REFRESH_INTERVAL=3600
TRIGGERCMD_TOKEN=your-triggercmd-token
LOG_LEVEL=INFO
# A valid TriggerCMD token is required for commands like `revoke`. If the token
# is missing or incorrect, TriggerCMD will respond with HTTP 401 Unauthorized.
# Path to your Firebase service account JSON stored outside this repository
FIREBASE_CREDENTIALS="C:\Users\BotGhost\Documents\GitHub\TheCoolestBot\ServiceAccount.json"
FIREBASE_PROJECT_ID=venuehost-bot
# Root URL of your Firebase Realtime Database
FIREBASE_DATABASE_URL=https://venuehost-bot-default-rtdb.firebaseio.com/
FIREBASE_COLLECTION=hostbot
```

`FIREBASE_DATABASE_URL` should point to the base URL of your Realtime Database
(for example `https://your-project-id-default-rtdb.firebaseio.com`) rather than
the Firebase console link.

`DISCORD_COHOST_ROLE` should contain the role ID for members allowed to use the
host command. It is used when the **Disable Host Command** button hides the
channel from this role.

`DISCORD_OPS_ROLE` can be set to a role ID that should also have access to the
admin panel in addition to users with the Administrator permission.

HostBot stores data in Firebase. Set `FIREBASE_CREDENTIALS` to the path of your
service account JSON. Keep this file outside the repository for security. You
may also set `FIREBASE_PROJECT_ID`. If these are not configured, the bot falls
back to the JSON file specified by `HOSTBOT_DATA_FILE`.

## Usage
Run `hostbot.py`:
```bash
python hostbot.py
```
HostBot reads the bot token and channel IDs from environment variables (e.g. a `.env` file).
If any required value is missing, the bot will exit with an error message.

> **Note**: This bot requires the **Message Content Intent** to be enabled for your Discord application. Enable it in the Discord Developer Portal under **Bot → Privileged Gateway Intents**.

When the bot starts, it serves a basic web dashboard on port `8000` showing the current
co-host queue and a button to refresh the host command embed. The embed is also refreshed
automatically every `EMBED_REFRESH_INTERVAL` seconds to keep its interactions active.

### Commands
- `/embed-host-command` – displays the control widget with buttons to update your
  Zoom name or self-assign co-host.
- Sending a base64 encoded name in the designated channel causes the bot to
  attempt to make that participant a co-host in the active Zoom meeting.
 - Users with the **Administrator** permission, or members with the role specified by
   `DISCORD_OPS_ROLE`, can access extra tools by clicking the **Admin** button in the
   widget.
- The admin tools include a **Disable Host Command** button that renames the channel
    to `〔🔴〕hostbot-disabled` and hides it from the role specified by
    `DISCORD_COHOST_ROLE`.
- The **Unmute** button provides a quick way to unmute Zoom. Pressing it asks for
  confirmation and starts an eight-second countdown while the unmute command is
  sent to TriggerCMD.
- The **Revoke Co-Host** button in the admin panel opens a modal to specify a Zoom name. Submitting that modal triggers the `revoke` command through TriggerCMD to remove the selected user's co-host role in Zoom.

## Data Storage

User information is stored in the Firebase Realtime Database under the
collection name `FIREBASE_COLLECTION`. Each user's data is stored at the path
`/hostbot/<DISCORD_ID>` with the following fields:

- `zoomName` – the Zoom display name.
- `base64` – the base64-encoded `zoomName` sent to TriggerCMD.
- `lastUsed` – timestamp of the most recent interaction.
- `telegramId` – an optional Telegram identifier.

If Firebase is unavailable, data is written to a JSON file at
`HOSTBOT_DATA_FILE`. The same file also stores the bot token and
channel IDs when configured with `save_config_to_file()`.

Set `FIREBASE_CREDENTIALS` to the path of your service account JSON stored
outside this repository. Provide `FIREBASE_PROJECT_ID` and
`FIREBASE_DATABASE_URL` for your project. If Firebase cannot be reached,
HostBot will fall back to the local JSON file.

## Docker Usage

This repository contains a `Dockerfile` and simple PowerShell scripts for running
HostBot in a container on Windows 11 with Docker Desktop.

```powershell
./build.ps1    # build the hostbot image
./run.ps1      # run the container using your .env file
./rebuild.ps1  # remove the container and rebuild the image
```

The container loads configuration from the `.env` file and runs `hostbot.py`
inside the image.


## Development
Format the code using `black` with a line length of 100:
```bash
black --line-length 100 hostbot/*.py hostbot.py
```
After any code changes, verify that the script compiles:
```bash
python -m py_compile hostbot.py
```

