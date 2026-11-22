# LINE Sticker Discord Bot
A Python Discord bot for browsing LINE sticker packs and sharing static PNG previews.

## Commands
| Command | Usage |
| --- | --- |
| `/stickers url folder_name [public]` | Downloads a sticker pack as a ZIP containing numbered PNG files. |
| `/panel url [public]` | Shows 10 sticker previews per page. Click a number to have the bot post that PNG to the channel. |
| `/search keyword [public]` | Searches for LINE sticker packs, showing five names and covers per page with previous/next buttons. Selecting a pack opens its panel. |
| `/help [public]` | Shows a guide to the bot and its commands. |

`url` must be a LINE STORE sticker product link, as `https://store.line.me/stickershop/product/[PRODUCT_ID]`. Replace `PRODUCT_ID` as it is in the actual link.

Downloads, search results and panels are private by default. To share a ZIP, search result, panel, or guide with the channel, add the optional `public` field at the end of the slash command and select the intended visibility choice from its choice menu. A panel opened from search inherits the same visibility, and the search message stays available. **Selected PNGs are always posted publicly** in the channel. If either the emoji or sticker version is not yet saved to the server, its message includes an **Add to Server** button. Members with the Create Expressions permission can save it as a server emoji or sticker.

Example: `/search keyword:貓咪 public:public`. Omit `public` to keep the results private.

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
4. Invite the application to your server with the `bot` and `applications.commands` scopes. Grant **View Channels**, **Send Messages**, **Attach Files**, and **Create Expressions** permissions for the bot. Members also need **Create Expressions** permissions to use Add to Server.

**Never commit `.env` or share your bot token.**

### Deploying from GitHub

Push `bot.py`, `requirements.txt`, and `README.md` to your GitHub repository. For Torchlite instructions, see https://torchlite.host/guides. In your hosting panel:

1. Choose the Discord bot (Python) runtime and set the main file to `bot.py`.
2. Connect your repository and install dependencies from `requirements.txt`.
3. Configure `DISCORD_BOT_TOKEN` or `DISCORD_TOKEN` as a private environment variable in the hosting panel.
4. Start the bot and check its console logs. After future commits, use your host's update/redeploy workflow.

Hosting availability and renewal requirements depend on your provider and plan.

## Add to Server

When the bot posts a PNG from `/panel`, click **Add to Server** and choose **Emoji** or **Sticker**. The image is resized for Discord automatically and saved under `gst_<LINE sticker ID>`. Stickers are cropped to remove transparent margins and proportionally scaled to fill the 320 × 320 canvas. The bot checks existing emoji and sticker names to avoid saving the same LINE sticker twice in each format. It does not remove server expressions or overwrite existing ones. If the server has no free slots, the upload fails with a message. 

## Limitations

- Sending a PNG does not create a Discord-native sticker. People can invoke the bot without Nitro, subject to channel permissions.
- Only static PNG previews are supported. Animations and sound are not included.
- LINE STORE searches use an unofficial, changeable interface. If `/search` fails, find the product URL on LINE STORE and use `/panel` directly.
- Panels expire after **10 minutes**.
- Opening a panel downloads **the first 10 PNGs** and displays the first page before background loading the remaining pages. Loaded pages and individual PNGs are kept in memory only for that panel.
- Preview sheets use compressed JPEG to reduce upload latency. So, switching to a page that is not ready may still take time. The shared stickers and ZIP files remain PNG. 
- Search results show up to **five packs per page**, with previous/next controls and one-page lookahead. If LINE search omits a cover, the bot loads it from the product page in the background and updates the result without delaying the first response.
- Maximum **120 stickers** per pack, **3 MB** per PNG, and **30 MB** of downloaded images per pack. Discord's attachment limit still applies. Page flips must still upload a new preview to Discord, so network latency remains possible.
- Only stickers saved with their `gst_` identifier are recognized as already added; identical images under other names may not be detected.
- Share artwork only where you have permission to do so. The bot does not grant rights to LINE stickers.
