# LINE Sticker Discord Bot
A Python Discord bot for browsing LINE sticker packs and sharing static PNG previews.

## Commands

| Command | Usage |
| --- | --- |
| `/stickers url folder_name` | Downloads a pack as a ZIP containing numbered PNG files. |
| `/panel url` | Shows 10 sticker previews per page. Click a number to have the bot post that PNG to the channel. |
| `/search keyword` | Searches for LINE sticker packs, shows up to five sticker names and their covers, and lets you open a pack's panel. |

`url` must be a LINE STORE sticker product link, such as `https://store.line.me/stickershop/product/PRODUCT_ID/zh-Hant` (replace `PRODUCT_ID` with the actual number).

The ZIP, search results, and browsing panel are **private** to the command user. Selected PNGs are posted **publicly** in the channel.

## Setup

Requires Python 3.10+.

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Set your Discord bot token in a private environment variable named `DISCORD_BOT_TOKEN` or `DISCORD_TOKEN`. For local development, you can create a `.env` file:
   ```env
   DISCORD_BOT_TOKEN=your_bot_token_here
   ```
3. Start the bot:
   ```bash
   python bot.py
   ```
4. Invite the application to your server with the `bot` and `applications.commands` scopes. Grant **View Channels**, **Send Messages**, and **Attach Files** permissions.

**Never commit `.env` or share your bot token.**

### Deploying from GitHub

Follow these steps if you are willing to deploy to Torchlite, so your bot can run 24/7. Look for more detailed guides at https://torchlite.host/guides.
Push `bot.py`, `requirements.txt`, and `README.md` to your Github repository. In your hosting panel on Torchlite:

1. Choose the Discord bot (Python) runtime and set the main file to `bot.py`.
2. Connect your repository and install dependencies from `requirements.txt`.
3. Configure `DISCORD_BOT_TOKEN` as a private environment variable in `.env`.
4. Start the bot and check its console logs. After future commits, use your host's update/redeploy workflow.

## Limitations

- Sending a PNG **does not create a Discord-native sticker. People can invoke the bot without Nitro, subject to channel permissions.
- Only static PNG previews are supported. Animations and sound are not included.
- LINE STORE searches use an unofficial, changeable interface. If `/search` fails, find the product URL on LINE STORE and use `/panel` directly.
- Panels expire after **10 minutes**. Images are fetched on demand and not permanently stored.
- Maximum **120 stickers** per pack, **3 MB** per PNG, and **30 MB** of images per ZIP. Discord's attachment limit still applies.
- Share artwork only where you have permission to do so. The bot does not grant rights to LINE stickers.
