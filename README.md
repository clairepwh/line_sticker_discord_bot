# Line Sticker Fetch Bot
This discord bot fetches line stickers from the given product url and sends back a zip file with the images.
## Setup
1. Create an application and bot at https://discord.com/developers/applications.
2. In **Installation**, configure a guild-install link with the `bot` and `applications.commands` scopes. Give the bot permissions to **View Channels**, **Send Messages**, and **Attach Files** (Permissions integer: `35840`). Use the install link to add it to your server.
3. Install Python 3.10+ and dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Create file `.env`, with `DISCORD_BOT_TOKEN=` the bot token from Discord's developer portal. Never post or commit this token.
5. Start the bot:
   ```bash
   python bot.py
   ```
6. In Discord, run:
   ```text
   /stickers url:https://store.line.me/stickershop/product/[example] folder_name:[example]
   ```
   The reply contains `[example].zip`, with PNG images in the `[example]` folder.

## Notes
ver1
- Works with current (2026/11/20) LINE Store sticker product pages.
- Downloads static PNGs only. Animated stickers are not preserved as animations.
- The ZIP must fit the relevant Discord channel's file-size limit.
- Only download and redistribute sticker artwork when you have permission to do so.
