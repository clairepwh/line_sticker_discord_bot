import asyncio
import io
import json
import os
import re
import zipfile
import time
from concurrent.futures import ThreadPoolExecutor
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
SEARCH_PER_PAGE = 5
PNG_HEADER = b"\x89PNG\r\n\x1a\n"
LEN_LIMIT = 120
Image.MAX_IMAGE_PIXELS = 4_000_000


def check_host(url, host):
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname != host
            or parsed.username or parsed.password or parsed.port not in (None, 443)):
        raise ValueError("網址錯誤。")


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
                raise ValueError(f"下載檔案超過大小限制（{limit}）。")
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
        raise ValueError("找不到貼圖。")
    if len(stickers) > LEN_LIMIT:
        raise ValueError(f"此貼圖包超過處理上限（{LEN_LIMIT} 張）。")
    return title[:100], stickers


def make_zip(url, folder):
    folder = folder.strip()
    if not re.fullmatch(r"[\w ()-]{1,60}", folder):
        raise ValueError("資料夾名稱限 1–60 字，可使用文字、數字、空格、底線、-、(、)。")
    _, stickers = stickers_from_url(url)
    output = io.BytesIO()
    total = 0
    with requests.Session() as session, zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for i, (sticker_id, image_url) in enumerate(stickers, 1):
            data = png(session, image_url)
            total += len(data)
            if total > TOTAL_LIMIT:
                raise ValueError(f"貼圖包超過處理上限（{TOTAL_LIMIT // (1024 * 1024)} MB）。")
            archive.writestr(f"{folder}/{i:03d}_{sticker_id}.png", data)
    output.seek(0)
    return output, len(stickers)


def contact_sheet(images, page):
    canvas = Image.new("RGB", (700, 300), "#f5f5f5")
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default(size=17)
    for i, (_, data) in enumerate(images):
        x, y = (i % 5) * 140, (i // 5) * 150
        try:
            with Image.open(io.BytesIO(data)) as source:
                image = source.convert("RGBA")
                image.thumbnail((128, 115), Image.Resampling.LANCZOS)
        except (OSError, Image.DecompressionBombError) as exc:
            raise ValueError("無法讀取貼圖圖片。") from exc
        canvas.paste(image, (x + (140 - image.width) // 2, y + 3), image)
        draw.text((x + 60, y + 123), str(page * PER_PAGE + i + 1),
                  fill="#222222", font=font)
    output = io.BytesIO()
    canvas.save(output, "JPEG", quality=82)
    return output.getvalue()


def expression_image(data, size):
    try:
        with Image.open(io.BytesIO(data)) as source:
            image = source.convert("RGBA")
            image.thumbnail((size, size), Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA", (size, size))
        canvas.paste(image, ((size - image.width) // 2, (size - image.height) // 2))
    except (OSError, Image.DecompressionBombError) as exc:
        raise ValueError("無法處理貼圖圖片。") from exc
    output = io.BytesIO()
    canvas.save(output, "PNG", optimize=True)
    return output.getvalue()


def download_sticker(sticker):
    sticker_id, url = sticker
    with requests.Session() as session:
        return sticker_id, png(session, url)


def load_page(stickers, page):
    with ThreadPoolExecutor(max_workers=3) as pool:
        images = list(pool.map(download_sticker, stickers[page * PER_PAGE:(page + 1) * PER_PAGE]))
    return images, contact_sheet(images, page)


def load_first_page(url):
    title, stickers = stickers_from_url(url)
    return title, stickers, load_page(stickers, 0)


def search_packs(keyword, page=0):
    keyword = keyword.strip()
    if not 1 <= len(keyword) <= 60:
        raise ValueError("搜尋字詞須為 1–60 個字。")
    packs = []
    seen = set()
    with requests.Session() as session:
        try:
            api = (f"https://store.line.me/api/search/sticker?query={quote(keyword)}"
                   f"&offset={page * SEARCH_PER_PAGE}&limit=10&type=ALL&includeFacets=false")
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
                if len(packs) > SEARCH_PER_PAGE:
                    break
        except (requests.RequestException, ValueError, TypeError, AttributeError):
            pass

        if not packs:
            try:
                url = f"https://store.line.me/search/sticker/zh-Hant?q={quote(keyword)}&page={page + 1}"
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
                    if len(packs) > SEARCH_PER_PAGE:
                        break
            except (requests.RequestException, ValueError):
                pass

        has_next = len(packs) > SEARCH_PER_PAGE
        results = []
        for title, url, cover in packs[:SEARCH_PER_PAGE]:
            try:
                host = urlsplit(cover).hostname
                if host not in ("store.line.me", "stickershop.line-scdn.net"):
                    cover = ""
                else:
                    check_host(cover, host)
            except (ValueError, TypeError):
                cover = ""
            results.append((title, url, cover))
    return results, has_next

def product_cover(url):
    check_product(url)
    with requests.Session() as session:
        soup = BeautifulSoup(fetch(session, url, PAGE_LIMIT), "html.parser")
    tag = soup.select_one('meta[property="og:image"]')
    cover = urljoin(url, tag.get("content", "")) if tag else ""
    host = urlsplit(cover).hostname
    if host not in ("store.line.me", "stickershop.line-scdn.net"):
        return ""
    check_host(cover, host)
    return cover


def error_message(exc):
    return str(exc) if isinstance(exc, ValueError) else "連線或圖片處理失敗，請稍後再試。"


def add_permission_error(interaction):
    guild = interaction.guild
    if not guild or not interaction.user.guild_permissions.create_expressions:
        return "你沒有新增伺服器表情的權限。"
    if not guild.me or not guild.me.guild_permissions.create_expressions:
        return "Bot 沒有新增伺服器表情的權限。"
    return ""


class AddOptions(discord.ui.View):
    def __init__(self, name, data, guild):
        super().__init__(timeout=120)
        self.name, self.data = name, data
        self.emoji.disabled = any(item.name == name for item in guild.emojis)
        self.sticker.disabled = any(item.name == name for item in guild.stickers)

    async def create(self, interaction, kind):
        error = add_permission_error(interaction)
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return
        guild = interaction.guild

        await interaction.response.defer(thinking=True, ephemeral=True)
        try:
            if kind == "Emoji":
                if any(item.name == self.name for item in await guild.fetch_emojis()):
                    raise ValueError("伺服器已經有這個 Emoji。")
                image = await asyncio.to_thread(expression_image, self.data, 128)
                if len(image) > 256 * 1024:
                    raise ValueError("Emoji 圖片超過大小限制。")
                await guild.create_custom_emoji(name=self.name, image=image)
            else:
                if any(item.name == self.name for item in await guild.fetch_stickers()):
                    raise ValueError("伺服器已經有這個 Sticker。")
                image = await asyncio.to_thread(expression_image, self.data, 320)
                if len(image) > 512 * 1024:
                    raise ValueError("Sticker 圖片超過大小限制。")
                await guild.create_sticker(name=self.name, emoji="🙂", description="LINE 貼圖",
                                           file=discord.File(io.BytesIO(image), filename="sticker.png"))
            await interaction.followup.send(f"已新增至伺服器 {kind}：`{self.name}`", ephemeral=True)
        except ValueError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send("Bot 沒有新增伺服器表情的權限。", ephemeral=True)
        except discord.HTTPException as exc:
            print(f"新增 {kind} 失敗：{exc}")
            await interaction.followup.send("新增失敗，請確認伺服器容量及圖片限制。", ephemeral=True)

    @discord.ui.button(label="Emoji", style=discord.ButtonStyle.primary)
    async def emoji(self, interaction, button):
        await self.create(interaction, "Emoji")

    @discord.ui.button(label="Sticker", style=discord.ButtonStyle.primary)
    async def sticker(self, interaction, button):
        await self.create(interaction, "Sticker")


class AddToServer(discord.ui.View):
    def __init__(self, name, data):
        super().__init__(timeout=600)
        self.name, self.data = name, data

    @discord.ui.button(label="Add to Server", style=discord.ButtonStyle.secondary)
    async def add(self, interaction, button):
        error = add_permission_error(interaction)
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return
        guild = interaction.guild
        view = AddOptions(self.name, self.data, guild)
        if view.emoji.disabled and view.sticker.disabled:
            await interaction.response.send_message("伺服器已收藏這張貼圖。", ephemeral=True)
        else:
            await interaction.response.send_message("要新增為 Emoji 還是 Sticker？", view=view, ephemeral=True)


class Panel(discord.ui.View):
    def __init__(self, title, url, stickers, first_page):
        super().__init__(timeout=600)
        self.title, self.url, self.stickers = title, url, stickers
        self.pages = (len(stickers) + PER_PAGE - 1) // PER_PAGE
        self.cache = {0: first_page}
        self.tasks = {}
        self.limit = asyncio.Semaphore(1)
        self.total = sum(len(data) for _, data in first_page[0])
        self.page = 0
        self.buttons()

    def preload(self):
        for page in range(1, self.pages):
            self.tasks[page] = asyncio.create_task(self.load(page))

    async def load(self, page):
        async with self.limit:
            data = await asyncio.to_thread(load_page, self.stickers, page)
            self.total += sum(len(image) for _, image in data[0])
            if self.total > TOTAL_LIMIT:
                raise ValueError("此貼圖包超過處理大小限制。")
            self.cache[page] = data

    def embed(self):
        embed = discord.Embed(title=self.title, url=self.url,
                              description=f"依照編號傳送圖片 · 第 {self.page + 1}/{self.pages} 頁")
        embed.set_image(url="attachment://preview.jpg")
        return embed

    def preview_file(self):
        return discord.File(io.BytesIO(self.cache[self.page][1]), filename="preview.jpg")

    def buttons(self):
        self.clear_items()
        for offset, (sticker_id, data) in enumerate(self.cache[self.page][0]):
            number = self.page * PER_PAGE + offset + 1
            button = discord.ui.Button(label=str(number), row=offset // 5)

            async def send(interaction, selected_data=data, selected_id=sticker_id):
                await interaction.response.defer()
                if len(selected_data) > interaction.filesize_limit:
                    await interaction.followup.send("圖片超過 Discord 附件大小限制。", ephemeral=True)
                    return
                view = None
                if interaction.guild:
                    name = f"gst_{selected_id}"
                    guild = interaction.guild
                    if not (any(item.name == name for item in guild.emojis) and
                            any(item.name == name for item in guild.stickers)):
                        view = AddToServer(name, selected_data)
                await interaction.followup.send(
                    file=discord.File(io.BytesIO(selected_data), filename=f"sticker_{selected_id}.png"),
                    view=view)

            button.callback = send
            self.add_item(button)

        for step, label in ((-1, "上一頁"), (1, "下一頁")):
            button = discord.ui.Button(label=label, style=discord.ButtonStyle.primary,
                                       disabled=not 0 <= self.page + step < self.pages, row=2)

            async def change(interaction, direction=step):
                await interaction.response.defer()
                next_page = self.page + direction
                start = time.perf_counter()
                try:
                    if next_page not in self.cache:
                        await self.tasks[next_page]
                    loaded = time.perf_counter()
                    self.page = next_page
                    self.buttons()
                    await interaction.edit_original_response(
                        embed=self.embed(), attachments=[self.preview_file()], view=self)
                    print(f"面板翻頁：載入等待 {loaded-start:.2f}s，Discord 更新 {time.perf_counter()-loaded:.2f}s")
                except (requests.RequestException, ValueError, OSError, discord.HTTPException) as exc:
                    await interaction.followup.send(f"無法切換頁面：{error_message(exc)}", ephemeral=True)

            button.callback = change
            self.add_item(button)


async def show_panel(interaction, url, private=True):
    title, stickers, first_page = await asyncio.to_thread(load_first_page, url)
    view = Panel(title, url, stickers, first_page)
    await interaction.followup.send(embed=view.embed(), file=view.preview_file(),
                                    view=view, ephemeral=private)
    view.preload()


class Results(discord.ui.View):
    def __init__(self, keyword, packs, has_next, private=True):
        super().__init__(timeout=600)
        self.keyword, self.page, self.private = keyword, 0, private
        self.cache = {0: (packs, has_next)}
        self.tasks = {}
        self.cover_tasks = {}
        self.lock = asyncio.Lock()
        self.refresh(packs, has_next)

    def preload(self):
        next_page = self.page + 1
        if self.more and next_page not in self.cache and next_page not in self.tasks:
            self.tasks[next_page] = asyncio.create_task(
                asyncio.to_thread(search_packs, self.keyword, next_page))

    def preload_covers(self, page):
        if page not in self.cover_tasks:
            self.cover_tasks[page] = asyncio.create_task(self.fill_covers(page))

    async def fill_covers(self, page):
        packs, more = self.cache[page]
        missing = [(i, url) for i, (_, url, cover) in enumerate(packs) if not cover]
        if not missing:
            return

        async def load(i, url):
            try:
                return i, await asyncio.to_thread(product_cover, url)
            except (requests.RequestException, ValueError, TypeError):
                return i, ""

        results = await asyncio.gather(*(load(i, url) for i, url in missing))
        packs = list(packs)
        for i, cover in results:
            if cover:
                title, url, _ = packs[i]
                packs[i] = (title, url, cover)
        self.cache[page] = (packs, more)
        async with self.lock:
            if self.page == page:
                self.packs = packs
                try:
                    await self.message.edit(embeds=self.embeds())
                except discord.HTTPException:
                    pass

    def embeds(self):
        embeds = []
        for i, (title, url, cover) in enumerate(self.packs, 1):
            embed = discord.Embed(title=f"{self.page * SEARCH_PER_PAGE + i}. {title}", url=url)
            if cover:
                embed.set_thumbnail(url=cover)
            embeds.append(embed)
        return embeds

    def caption(self):
        return f"「{discord.utils.escape_markdown(self.keyword)}」的搜尋結果 · 第 {self.page + 1} 頁"

    def refresh(self, packs, has_next):
        self.packs, self.more = packs, has_next
        self.clear_items()
        selector = discord.ui.Select(placeholder="選擇貼圖包", row=0, options=[
            discord.SelectOption(label=title, value=str(i)) for i, (title, _, _) in enumerate(packs)])

        async def selected(interaction):
            await interaction.response.defer(thinking=True, ephemeral=self.private)
            try:
                await show_panel(interaction, self.packs[int(selector.values[0])][1], self.private)
            except (requests.RequestException, ValueError, OSError) as exc:
                await interaction.followup.send(f"無法開啟貼圖包：{error_message(exc)}", ephemeral=True)

        selector.callback = selected
        self.add_item(selector)
        for step, label in ((-1, "上一頁"), (1, "下一頁")):
            button = discord.ui.Button(label=label, style=discord.ButtonStyle.primary,
                                       disabled=(self.page == 0 if step == -1 else not has_next), row=1)

            async def change(interaction, direction=step):
                await interaction.response.defer()
                next_page = self.page + direction
                try:
                    if next_page not in self.cache:
                        if next_page in self.tasks:
                            self.cache[next_page] = await self.tasks.pop(next_page)
                        else:
                            self.cache[next_page] = await asyncio.to_thread(search_packs, self.keyword, next_page)
                    packs, more = self.cache[next_page]
                    if not packs:
                        await interaction.followup.send("沒有更多搜尋結果了。", ephemeral=True)
                        return
                    async with self.lock:
                        self.page = next_page
                        self.refresh(packs, more)
                        await interaction.edit_original_response(
                            content=self.caption(), embeds=self.embeds(), view=self)
                    self.preload()
                    self.preload_covers(next_page)
                except (requests.RequestException, ValueError, discord.HTTPException) as exc:
                    await interaction.followup.send(f"無法切換搜尋結果：{error_message(exc)}", ephemeral=True)

            button.callback = change
            self.add_item(button)


class StickerBot(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        await self.tree.sync()


bot = StickerBot()
PUBLIC = [app_commands.Choice(name="Public", value="yes")]


@bot.tree.command(name="stickers", description="下載 LINE 貼圖並打包成 ZIP")
@app_commands.describe(url="LINE STORE 貼圖網址", folder_name="自訂資料夾名稱",
                       public="選擇「Public」讓其他人也能看到 ZIP（預設私人）")
@app_commands.choices(public=PUBLIC)
async def stickers(interaction: discord.Interaction, url: str, folder_name: str, public: str = None):
    private = public is None
    await interaction.response.defer(thinking=True, ephemeral=private)
    try:
        archive, count = await asyncio.to_thread(make_zip, url, folder_name)
        if archive.getbuffer().nbytes > interaction.filesize_limit:
            raise ValueError("ZIP 超過 Discord 附件大小限制。")
        await interaction.followup.send(f"已下載 {count} 張 PNG。",
                                        file=discord.File(archive, filename=f"{folder_name.strip()}.zip"),
                                        ephemeral=private)
    except (requests.RequestException, ValueError) as exc:
        await interaction.followup.send(f"下載失敗：{error_message(exc)}", ephemeral=private)


@bot.tree.command(name="panel", description="預覽 LINE 貼圖並選擇要發送的圖片")
@app_commands.describe(url="LINE STORE 貼圖網址", public="選擇「Public」讓其他人也能使用面板（預設私人）")
@app_commands.choices(public=PUBLIC)
async def panel(interaction: discord.Interaction, url: str, public: str = None):
    private = public is None
    await interaction.response.defer(thinking=True, ephemeral=private)
    try:
        await show_panel(interaction, url, private)
    except (requests.RequestException, ValueError, OSError) as exc:
        await interaction.followup.send(f"開啟面板失敗：{error_message(exc)}", ephemeral=private)


@bot.tree.command(name="search", description="搜尋 LINE 貼圖包")
@app_commands.describe(keyword="貼圖名稱或關鍵字", public="選擇「Public」分享搜尋結果（預設私人）")
@app_commands.choices(public=PUBLIC)
async def search(interaction: discord.Interaction, keyword: str, public: str = None):
    private = public is None
    await interaction.response.defer(thinking=True, ephemeral=private)
    try:
        packs, has_next = await asyncio.to_thread(search_packs, keyword)
        if not packs:
            await interaction.followup.send(
                "目前無法取得 LINE 搜尋結果，可先在 LINE STORE 找到網址，再使用 `/panel`。",
                ephemeral=private)
            return
        view = Results(keyword, packs, has_next, private)
        view.message = await interaction.followup.send(content=view.caption(), embeds=view.embeds(),
                                                       view=view, ephemeral=private, wait=True)
        view.preload()
        view.preload_covers(0)
    except (requests.RequestException, ValueError) as exc:
        await interaction.followup.send(f"搜尋失敗：{error_message(exc)}", ephemeral=private)


@bot.tree.command(name="help", description="查看貼圖機器人使用說明")
@app_commands.describe(public="選擇「公開」讓其他人也能看到說明（預設私人）")
@app_commands.choices(public=PUBLIC)
async def help(interaction: discord.Interaction, public: str = None):
    embed = discord.Embed(title="LINE 貼圖機器人使用說明", description=(
        "`/search keyword`：搜尋 LINE 貼圖包，每頁 5 個結果，可翻頁或開啟貼圖面板。\n\n"
        "`/panel url`：輸入 LINE STORE 貼圖網址，預覽貼圖並點擊對應編號發送圖片。\n\n"
        "`/stickers url folder_name`：將整包貼圖下載為 PNG，並打包成 ZIP。\n\n"
        "`/help`：查看這份說明。\n\n"
        "私人／公開：預設使用動作只有自己看得到。若想分享給聊天室，在指令最後加入 `public`，並從選單選擇「公開」。\n"
        "從公開搜尋結果開啟的貼圖面板也會公開。無論面板是否公開，點擊編號發出的 PNG 都會公開在頻道。\n\n"
        "Add to server：若貼圖尚未加入伺服器，可使用圖片下方的 Add to Server 新增為 Emoji 或 Sticker（需要建立表情權限）。\n\n"
        "貼圖面板每頁 10 張，約 10 分鐘後按鈕會失效。"
    ))
    await interaction.response.send_message(embed=embed, ephemeral=public is None)


if __name__ == "__main__":
    load_dotenv()
    token = os.getenv("DISCORD_BOT_TOKEN") or os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("請設定 DISCORD_BOT_TOKEN 或 DISCORD_TOKEN。")
    bot.run(token)
