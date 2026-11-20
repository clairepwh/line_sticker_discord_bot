"""Discord slash command: LINE sticker page -> PNG ZIP attachment."""

import asyncio
import io
import json
import os
import re
import zipfile
from urllib.parse import urlsplit

import discord
from discord import app_commands
from bs4 import BeautifulSoup
from dotenv import load_dotenv
import requests

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/157.0.0.0 Safari/537.36"
    )
}
MAX_PAGE_BYTES = 4 * 1024 * 1024
MAX_IMAGE_BYTES = 3 * 1024 * 1024
MAX_TOTAL_IMAGE_BYTES = 30 * 1024 * 1024
MAX_STICKERS = 120
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def check_url(url: str, hostname: str) -> None:
    """Only connect to exact known LINE hosts over HTTPS."""
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname != hostname
            or parsed.username is not None or parsed.password is not None
            or parsed.port not in (None, 443)):
        raise ValueError(f"Only HTTPS links from {hostname} are supported.")


def check_inputs(url: str, folder_name: str) -> str:
    check_url(url, "store.line.me")
    path = urlsplit(url).path
    if not re.fullmatch(r"/stickershop/product/\d+(?:/[A-Za-z-]+)?/?", path):
        raise ValueError("Please use a LINE sticker product URL (not a search page).")

    folder_name = folder_name.strip()
    if not re.fullmatch(r"[\w ()-]{1,60}", folder_name, flags=re.UNICODE):
        raise ValueError("Folder names must be 1–60 characters: letters, digits, spaces, _, - or ().")
    return folder_name


def download_limited(session: requests.Session, url: str, max_bytes: int) -> bytes:
    # No redirects: redirecting to another host would bypass our allowlist.
    with session.get(url, headers=HEADERS, timeout=(10, 20),
                     allow_redirects=False, stream=True) as response:
        response.raise_for_status()
        if 300 <= response.status_code < 400:
            raise ValueError("LINE returned an unexpected redirect.")
        chunks = []
        size = 0
        for chunk in response.iter_content(chunk_size=64 * 1024):
            size += len(chunk)
            if size > max_bytes:
                raise ValueError("An image or webpage exceeded the size limit.")
            chunks.append(chunk)
        return b"".join(chunks)


def make_sticker_zip(url: str, folder_name: str) -> tuple[io.BytesIO, int]:
    """Return (ZIP file in memory, number of PNGs). Runs in a worker thread."""
    folder_name = check_inputs(url, folder_name)
    output = io.BytesIO()
    total_size = 0
    downloaded = 0

    with requests.Session() as session:
        html = download_limited(session, url, MAX_PAGE_BYTES)
        soup = BeautifulSoup(html, "html.parser")
        stickers = soup.select("li.FnStickerPreviewItem[data-preview]")
        if not stickers:
            raise ValueError("No stickers found. LINE may have changed its page layout.")
        if len(stickers) > MAX_STICKERS:
            raise ValueError("This sticker pack has more images than the bot's limit.")

        with zipfile.ZipFile(output, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            for index, element in enumerate(stickers, start=1):
                try:
                    info = json.loads(element["data-preview"])
                except (json.JSONDecodeError, TypeError):
                    continue

                image_url = info.get("staticUrl")
                if not image_url:
                    continue
                check_url(image_url, "stickershop.line-scdn.net")
                if not urlsplit(image_url).path.lower().endswith(".png"):
                    raise ValueError("LINE returned an unexpected image URL.")

                data = download_limited(session, image_url, MAX_IMAGE_BYTES)
                if not data.startswith(PNG_SIGNATURE):
                    raise ValueError("LINE returned a file that is not a PNG.")
                total_size += len(data)
                if total_size > MAX_TOTAL_IMAGE_BYTES:
                    raise ValueError("This sticker pack is too large to process.")

                sticker_id = str(info.get("id", index))
                if not re.fullmatch(r"\d{1,20}", sticker_id):
                    sticker_id = str(index)
                filename = f"{folder_name}/{index:03d}_{sticker_id}.png"
                zf.writestr(filename, data)
                downloaded += 1

    if downloaded == 0:
        raise ValueError("No downloadable PNGs were found on this page.")
    output.seek(0)
    return output, downloaded


class StickerBot(discord.Client):
    def __init__(self) -> None:
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self) -> None:
        # Global slash commands may take some time to appear in Discord.
        await self.tree.sync()


bot = StickerBot()


@bot.tree.command(name="stickers", description="Download LINE stickers as a ZIP of PNGs")
@app_commands.describe(url="LINE Store sticker product URL", folder_name="Folder inside the ZIP")
async def stickers(interaction: discord.Interaction, url: str, folder_name: str) -> None:
    await interaction.response.defer(thinking=True)
    try:
        # requests is synchronous, so run downloads off the Discord event loop.
        archive, count = await asyncio.to_thread(make_sticker_zip, url, folder_name)
        safe_name = folder_name.strip()
        if archive.getbuffer().nbytes > interaction.filesize_limit:
            await interaction.followup.send(
                "The ZIP is larger than Discord allows for this upload."
            )
            return
        with archive:
            await interaction.followup.send(
                content=f"Downloaded {count} PNGs.",
                file=discord.File(archive, filename=f"{safe_name}.zip"),
            )
    except (ValueError, requests.RequestException) as exc:
        await interaction.followup.send(f"Could not download stickers: {exc}")


if __name__ == "__main__":
    load_dotenv()
    token = os.getenv("DISCORD_BOT_TOKEN")
    if not token:
        raise RuntimeError("Set DISCORD_BOT_TOKEN in your .env file first.")
    bot.run(token)
