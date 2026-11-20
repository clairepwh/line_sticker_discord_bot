# LINE sticker PNG ZIP Discord bot
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
   /stickers url:https://store.line.me/stickershop/product/28908433/en folder_name:cute_stickers
   ```
   The reply contains `cute_stickers.zip`, with PNG images in the `cute_stickers/` folder.

## Notes

- Works with LINE Store sticker product pages that expose `li.FnStickerPreviewItem[data-preview]` and `staticUrl` (the same structure as the notebook).
- Downloads **static PNGs** only; animated stickers are not preserved as animations.
- Creates the ZIP in memory; no files remain on disk.
- Restricts input URLs to LINE Store and image downloads to LINE's sticker CDN, blocks redirects, and checks download sizes.
- The ZIP must fit the relevant Discord channel's file-size limit.
- If LINE changes the page structure, the CSS selector or metadata extraction may need updating.
- Only download and redistribute sticker artwork when you have permission to do so.
