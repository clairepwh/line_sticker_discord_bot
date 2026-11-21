"""Discord bot for browsing and sharing LINE sticker previews."""

import asyncio
import io
import json
import os
import re
import zipfile
from urllib.parse import quote, urljoin, urlsplit

import discord
import requests
from bs4 import BeautifulSoup
from discord import app_commands
from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFont

HEADERS = {"User-Agent": "Mozilla/5.0"}
PAGE_LIMIT = 4 * 1024 * 1024
IMAGE_LIMIT = 3 * 1024 * 1024
TOTAL_LIMIT = 30 * 1024 * 1024
PER_PAGE = 10
PNG_HEADER = b"\x89PNG\r\n\x1a\n"
Image.MAX_IMAGE_PIXELS = 4_000_000


def check_host(url, host):
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname != host
            or parsed.username or parsed.password or parsed.port not in (None, 443)):
        raise ValueError("不支援的網址。")


def check_product(url):
    check_host(url, "store.line.me")
    if not re.fullmatch(r"/stickershop/product/\d+(?:/[A-Za-z-]+)?/?", urlsplit(url).path):
        raise ValueError("請提供 LINE STORE 的貼圖商品網址。")


def check_image(url):
    check_host(url, "stickershop.line-scdn.net")
    if not urlsplit(url).path.lower().endswith(".png"):
        raise ValueError("圖片網址不是 PNG。")


def fetch(session, url, limit):
    with session.get(url, headers=HEADERS, stream=True, allow_redirects=False,
                     timeout=(10, 20)) as response:
        if response.is_redirect:
            raise ValueError("LINE 回傳了非預期的轉址。")
        response.raise_for_status()
        data = bytearray()
        for chunk in response.iter_content(64 * 1024):
            data.extend(chunk)
            if len(data) > limit:
                raise ValueError("下載檔案超過大小限制。")
        return bytes(data)


def png(session, url):
    check_image(url)
    data = fetch(session, url, IMAGE_LIMIT)
    if not data.startswith(PNG_HEADER):
        raise ValueError("LINE 回傳的檔案不是 PNG。")
    return data


def stickers_from_url(url):
    check_product(url)
    with requests.Session() as session:
        soup = BeautifulSoup(fetch(session, url, PAGE_LIMIT), "html.parser")
    title_tag = soup.select_one('meta[property="og:title"]')
    title = (title_tag.get("content", "") if title_tag else "") or "LINE 貼圖"
    stickers = []
    for node in soup.select("li.FnStickerPreviewItem[data-preview]"):
        try:
            item = json.loads(node["data-preview"])
            image_url = item["staticUrl"]
            check_image(image_url)
            sticker_id = str(item.get("id", len(stickers) + 1))
            stickers.append((sticker_id if re.fullmatch(r"\d{1,20}", sticker_id)
                             else str(len(stickers) + 1), image_url))
        except (KeyError, ValueError, TypeError):
            continue
    if not stickers:
        raise ValueError("找不到貼圖，LINE STORE 的網頁格式可能已改變。")
    if len(stickers) > 120:
        raise ValueError("此貼圖包超過 120 張的處理上限。")
    return title[:100], stickers


def make_zip(url, folder):
    folder = folder.strip()
    if not re.fullmatch(r"[\w ()-]{1,60}", folder):
        raise ValueError("資料夾名稱限 1–60 字，可使用文字、數字、空格、底線、-、()。")
    _, stickers = stickers_from_url(url)
    output = io.BytesIO()
    total = 0
    with requests.Session() as session, zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for i, (sticker_id, image_url) in enumerate(stickers, 1):
            data = png(session, image_url)
            total += len(data)
            if total > TOTAL_LIMIT:
                raise ValueError("貼圖包超過 30 MB 的處理上限。")
            archive.writestr(f"{folder}/{i:03d}_{sticker_id}.png", data)
    output.seek(0)
    return output, len(stickers)


def contact_sheet(stickers, page):
    canvas = Image.new("RGB", (700, 300), "#f5f5f5")
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default(size=17)
    with requests.Session() as session:
        for i, (_, url) in enumerate(stickers[page * PER_PAGE:(page + 1) * PER_PAGE]):
            x, y = (i % 5) * 140, (i // 5) * 150
            try:
                with Image.open(io.BytesIO(png(session, url))) as source:
                    image = source.convert("RGBA")
                    image.thumbnail((128, 115), Image.Resampling.LANCZOS)
            except (OSError, Image.DecompressionBombError) as exc:
                raise ValueError("無法讀取貼圖圖片。") from exc
            canvas.paste(image, (x + (140 - image.width) // 2, y + 3), image)
            draw.text((x + 60, y + 123), str(page * PER_PAGE + i + 1),
                      fill="#222222", font=font)
    output = io.BytesIO()
    canvas.save(output, "PNG")
    output.seek(0)
    return output


def search_packs(keyword):
    keyword = keyword.strip()
    if not 1 <= len(keyword) <= 60:
        raise ValueError("搜尋字詞須為 1–60 個字。")
    packs = []
    seen = set()
    with requests.Session() as session:
        # LINE has no stable public search API; try its current endpoint first.
        try:
            api = (f"https://store.line.me/api/search/sticker?query={quote(keyword)}"
                   "&offset=0&limit=10&type=ALL&includeFacets=false")
            items = json.loads(fetch(session, api, PAGE_LIMIT)).get("items", [])
            for item in items:
                pack_id = str(item.get("id", ""))
                if not re.fullmatch(r"\d{1,20}", pack_id) or pack_id in seen:
                    continue
                seen.add(pack_id)
                title = str(item.get("title") or f"貼圖 {pack_id}")[:100]
                cover = item.get("mainImageUrl") or item.get("imageUrl") or ""
                packs.append((title, f"https://store.line.me/stickershop/product/{pack_id}/zh-Hant",
                              cover if isinstance(cover, str) and cover.startswith("https://") else ""))
                if len(packs) == 5:
                    break
        except (requests.RequestException, ValueError, TypeError, AttributeError):
            pass

        if not packs:
            # Fallback for search pages whose results are present in HTML.
            try:
                url = f"https://store.line.me/search/sticker/zh-Hant?q={quote(keyword)}"
                soup = BeautifulSoup(fetch(session, url, PAGE_LIMIT), "html.parser")
                for link in soup.select('a[href*="/stickershop/product/"]'):
                    href = urljoin("https://store.line.me", link.get("href", ""))
                    try:
                        check_product(href)
                    except ValueError:
                        continue
                    pack_id = re.search(r"/product/(\d+)", href).group(1)
                    if pack_id in seen:
                        continue
                    seen.add(pack_id)
                    img = link.select_one("img")
                    title = link.get_text(" ", strip=True) or (img.get("alt", "") if img else "")
                    cover = urljoin("https://store.line.me", (img.get("data-src") or img.get("src") or "")) if img else ""
                    packs.append(((title or f"貼圖 {pack_id}")[:100], href, cover))
                    if len(packs) == 5:
                        break
            except (requests.RequestException, ValueError):
                pass

        # If search results lack a cover, read the product page's Open Graph image.
        results = []
        for title, url, cover in packs:
            try:
                host = urlsplit(cover).hostname
                if host not in ("store.line.me", "stickershop.line-scdn.net"):
                    cover = ""
                else:
                    check_host(cover, host)
            except (ValueError, TypeError):
                cover = ""
            if not cover:
                try:
                    page = BeautifulSoup(fetch(session, url, PAGE_LIMIT), "html.parser")
                    tag = page.select_one('meta[property="og:image"]')
                    cover = tag.get("content", "") if tag else ""
                except (requests.RequestException, ValueError):
                    cover = ""
            results.append((title, url, cover))
    return results


class Panel(discord.ui.View):
    def __init__(self, title, url, stickers):
        super().__init__(timeout=600)
        self.title, self.url, self.stickers = title, url, stickers
        self.page = 0
        self.buttons()

    def embed(self):
        pages = (len(self.stickers) + PER_PAGE - 1) // PER_PAGE
        embed = discord.Embed(title=self.title, url=self.url,
                              description=f"按編號傳送圖片 · 第 {self.page + 1}/{pages} 頁")
        embed.set_image(url="attachment://preview.png")
        return embed

    def buttons(self):
        self.clear_items()
        for offset, (sticker_id, url) in enumerate(
                self.stickers[self.page * PER_PAGE:(self.page + 1) * PER_PAGE]):
            number = self.page * PER_PAGE + offset + 1
            button = discord.ui.Button(label=str(number), row=offset // 5)

            async def send(interaction, selected_url=url, selected_id=sticker_id):
                await interaction.response.defer(thinking=True)
                try:
                    with requests.Session() as session:
                        data = await asyncio.to_thread(png, session, selected_url)
                    if len(data) > interaction.filesize_limit:
                        raise ValueError("圖片超過 Discord 附件大小限制。")
                    await interaction.followup.send(
                        file=discord.File(io.BytesIO(data), filename=f"sticker_{selected_id}.png"))
                except (requests.RequestException, ValueError) as exc:
                    await interaction.followup.send(f"無法傳送圖片：{exc}", ephemeral=True)

            button.callback = send
            self.add_item(button)
        for offset, label in ((-1, "上一頁"), (1, "下一頁")):
            button = discord.ui.Button(label=label, style=discord.ButtonStyle.primary,
                                       disabled=not 0 <= self.page + offset <
                                       (len(self.stickers) + PER_PAGE - 1) // PER_PAGE, row=2)

            async def change(interaction, step=offset):
                await interaction.response.defer()
                try:
                    new_page = self.page + step
                    image = await asyncio.to_thread(contact_sheet, self.stickers, new_page)
                    self.page = new_page
                    self.buttons()
                    await interaction.edit_original_response(
                        embed=self.embed(), attachments=[discord.File(image, filename="preview.png")], view=self)
                except (requests.RequestException, ValueError, OSError) as exc:
                    await interaction.followup.send(f"無法切換頁面：{exc}", ephemeral=True)

            button.callback = change
            self.add_item(button)


async def show_panel(interaction, url, replace=False):
    title, stickers = await asyncio.to_thread(stickers_from_url, url)
    view = Panel(title, url, stickers)
    image = await asyncio.to_thread(contact_sheet, stickers, 0)
    file = discord.File(image, filename="preview.png")
    if replace:
        await interaction.edit_original_response(content=None, embed=view.embed(),
                                                 attachments=[file], view=view)
    else:
        await interaction.followup.send(embed=view.embed(), file=file, view=view, ephemeral=True)


class Results(discord.ui.View):
    def __init__(self, packs):
        super().__init__(timeout=600)
        selector = discord.ui.Select(placeholder="選擇貼圖包", options=[
            discord.SelectOption(label=title, value=str(i)) for i, (title, _, _) in enumerate(packs)])

        async def selected(interaction):
            await interaction.response.defer()
            try:
                await show_panel(interaction, packs[int(selector.values[0])][1], replace=True)
            except (requests.RequestException, ValueError, OSError) as exc:
                await interaction.followup.send(f"無法開啟貼圖包：{exc}", ephemeral=True)

        selector.callback = selected
        self.add_item(selector)


class StickerBot(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        await self.tree.sync()


bot = StickerBot()


@bot.tree.command(name="stickers", description="Download LINE sticker PNGs as a ZIP")
@app_commands.describe(url="LINE STORE 貼圖網址", folder_name="ZIP 內的資料夾名稱")
async def stickers(interaction: discord.Interaction, url: str, folder_name: str):
    await interaction.response.defer(thinking=True, ephemeral=True)
    try:
        archive, count = await asyncio.to_thread(make_zip, url, folder_name)
        if archive.getbuffer().nbytes > interaction.filesize_limit:
            raise ValueError("ZIP 超過 Discord 附件大小限制。")
        await interaction.followup.send(f"已下載 {count} 張 PNG。",
                                        file=discord.File(archive, filename=f"{folder_name.strip()}.zip"),
                                        ephemeral=True)
    except (requests.RequestException, ValueError) as exc:
        await interaction.followup.send(f"下載失敗：{exc}", ephemeral=True)


@bot.tree.command(name="panel", description="Preview LINE stickers and choose one to send")
@app_commands.describe(url="LINE STORE 貼圖網址")
async def panel(interaction: discord.Interaction, url: str):
    await interaction.response.defer(thinking=True, ephemeral=True)
    try:
        await show_panel(interaction, url)
    except (requests.RequestException, ValueError, OSError) as exc:
        await interaction.followup.send(f"開啟面板失敗：{exc}", ephemeral=True)


@bot.tree.command(name="search", description="Search LINE sticker packs")
@app_commands.describe(keyword="貼圖名稱或關鍵字")
async def search(interaction: discord.Interaction, keyword: str):
    await interaction.response.defer(thinking=True, ephemeral=True)
    try:
        packs = await asyncio.to_thread(search_packs, keyword)
        if not packs:
            await interaction.followup.send(
                "目前無法取得 LINE 搜尋結果，可先在 LINE STORE 找到網址，再使用 `/panel`。",
                ephemeral=True)
            return
        embeds = []
        for i, (title, url, cover) in enumerate(packs, 1):
            embed = discord.Embed(title=f"{i}. {title}", url=url)
            if cover:
                embed.set_thumbnail(url=cover)
            embeds.append(embed)
        await interaction.followup.send(content=f"「{discord.utils.escape_markdown(keyword)}」的搜尋結果",
                                        embeds=embeds, view=Results(packs), ephemeral=True)
    except (requests.RequestException, ValueError) as exc:
        await interaction.followup.send(f"搜尋失敗：{exc}", ephemeral=True)


if __name__ == "__main__":
    load_dotenv()
    token = os.getenv("DISCORD_BOT_TOKEN") or os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("請設定 DISCORD_BOT_TOKEN 或 DISCORD_TOKEN。")
    bot.run(token)