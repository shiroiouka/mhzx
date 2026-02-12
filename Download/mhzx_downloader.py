import asyncio
import json
import logging
import os
from functools import wraps

import cv2
from numpy import frombuffer, uint8, random
from playwright.async_api import async_playwright, ViewportSize

temp_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temp")
if not os.path.exists(temp_dir):
    os.makedirs(temp_dir, exist_ok=True)


def async_retry(
    max_retries=3,
    base_delay=1.0,
    max_delay=10.0,
    exceptions=(asyncio.TimeoutError, Exception),
):
    """异步重试装饰器"""

    def decorator(func):

        @wraps(func)
        async def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_retries - 1:
                        delay = min(base_delay * (2**attempt), max_delay)
                        jitter = delay * 0.1
                        actual_delay = delay + random.uniform(-jitter, jitter)

                        await asyncio.sleep(actual_delay)
                    else:
                        raise last_exception
            raise last_exception

        return wrapper

    return decorator


class Log:
    def __init__(self, name="logger", is_log=False):

        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.DEBUG)

        if not self.logger.handlers:
            formatter = logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            )
            if is_log:
                file_handler = logging.FileHandler(name + ".log")
                file_handler.setLevel(logging.DEBUG)
                file_handler.setFormatter(formatter)
                self.logger.addHandler(file_handler)

            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.INFO)
            console_handler.setFormatter(formatter)
            self.logger.addHandler(console_handler)

    def cleanup(self):
        """关闭所有handler"""
        for handler in self.logger.handlers[:]:
            handler.close()
            self.logger.removeHandler(handler)

    def log(self):
        return self.logger


class DownloaderAsync:
    _logger = Log("DownloaderAsync").log()

    def __init__(
        self,
        headless=True,
        storage_state_path=os.path.join(temp_dir, "storage_state.json"),
    ):
        self.headless = headless
        self.storage_state_path = storage_state_path

        self.playwright = None
        self.browser = None
        self.context = None

        self.image_extensions = {
            ".jpg",
            ".jpeg",
            ".png",
            ".gif",
            ".bmp",
            ".tiff",
            ".webp",
            ".svg",
        }
        self.links_lock = asyncio.Lock()

    async def login_and_save(self, url):
        """首次登录并保存状态"""
        self._logger.info("第一次登录并保存状态...")

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(
                headless=False,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                ],
            )

            context = await browser.new_context(
                viewport=ViewportSize(width=1280, height=720),
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            )

            page = await context.new_page()

            self._logger.info("请手动登录")
            await page.goto(url, wait_until="domcontentloaded")
            self._logger.info("登录完成后按回车保存状态...")
            input()

            await context.storage_state(path=self.storage_state_path)

            await page.close()
            await context.close()
            await browser.close()

    async def fast_login(self):
        """快速恢复登录状态"""
        self.browser = await self.playwright.chromium.launch(
            headless=self.headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-images",  # 禁用所有图片加载
            ],
        )

        self.context = await self.browser.new_context(
            storage_state=self.storage_state_path,
            viewport=ViewportSize(width=1280, height=720),
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        )

    async def safe_close_page(self, page):
        """安全关闭页面"""
        if page and not page.is_closed():
            try:
                await page.close()
            except Exception as e:
                self._logger.info(f"关闭页面时出错: {e}", exc_info=True)

    def load_existing_names(self, file_path):
        """读取已有文件,避免重复"""
        try:
            name_set = set()
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            for item in data:
                if name := item.get("name"):
                    # 去掉 "_部分X" 后缀
                    import re

                    cleaned_name = re.sub(r"_部分\d+$", "", name)

                    name_set.add(cleaned_name)
            return name_set
        except:
            return name_set

    def is_image_url(self, url: str) -> bool:
        """检查URL是否是图片链接"""
        if url:
            url_lower = url.lower()
            for ext in self.image_extensions:
                if ext in url_lower:
                    return True
        return False

    async def decode_qr_async(self, image_url: str):
        """异步二维码解码"""

        def _process_qr_image(img_data: bytes):
            """处理二维码图像"""
            try:
                # 解码图片
                img = cv2.imdecode(frombuffer(img_data, uint8), -1)

                if img is None:
                    self._logger.warning(f"无法解码图片: {image_url}")
                    return None

                # 使用一行式多策略解码
                img_gray = (
                    cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                    if len(img.shape) == 3
                    else img
                )
                detector = cv2.QRCodeDetector()

                # 尝试所有预处理组合
                methods = [
                    img_gray,
                    cv2.medianBlur(img_gray, 5),
                    cv2.adaptiveThreshold(img_gray, 255, 0, 1, 11, 2),
                    cv2.threshold(
                        cv2.GaussianBlur(img_gray, (5, 5), 0), 0, 255, 0 + 16
                    )[1],
                    cv2.morphologyEx(img_gray, 2, cv2.getStructuringElement(0, (5, 5))),
                ]

                for i, proc in enumerate(methods):
                    try:
                        data, bbox, _ = detector.detectAndDecode(proc)
                        if data:
                            return data
                    except Exception as e:
                        self._logger.warning(f"解码方法{i + 1}失败: {e}", exc_info=True)
                        continue

                self._logger.warning(f"所有解码方法均失败: {image_url}")
                return None

            except Exception as e:
                self._logger.warning(f"图像处理异常 {image_url}: {e}", exc_info=True)
                return None

        try:
            # 修复：使用 context.request.get 获取响应，然后使用 body() 而不是 read()
            response = await self.context.request.get(image_url)
            if response.status != 200:
                self._logger.warning(f"图片下载失败，状态码: {response.status} - {image_url}")
                return None

            # 修复：APIResponse 使用 body() 方法获取内容
            img_data = await response.body()

            # 在同步代码中处理图像（避免阻塞事件循环）
            loop = asyncio.get_event_loop()
            decoded_result = await loop.run_in_executor(
                None, _process_qr_image, img_data
            )

            return decoded_result

        except Exception as e:
            self._logger.warning(f"二维码解码异常 {image_url}: {e}", exc_info=True)
            return None

    async def produce(self):
        pass

    async def async_run(self):
        """主运行函数"""
        self._logger.info("开始运行...")
        if not os.path.exists(self.storage_state_path):
            await self.login_and_save("https://www.mhh1.com")

        async with async_playwright() as playwright:
            self.playwright = playwright
            await self.fast_login()

            # 执行逻辑
            await self.produce()

            if self.context:
                await self.context.close()
            if self.browser:
                await self.browser.close()

        self._logger.info("运行结束!")

    # 外部接口
    def run(self):
        try:
            asyncio.run(self.async_run())
        except KeyboardInterrupt:
            self._logger.error("用户中断运行!")
        except Exception as e:
            self._logger.error(f"运行失败: {e}", exc_info=True)


class MhzxDownloader(DownloaderAsync):
    _logger = Log("MhzxDownloader").log()

    def __init__(
        self,
        headless=True,
        max_concurrent=3,
        articles_path="articles.json",
        pan_baidu_path=os.path.join(temp_dir, "pan_baidu.json"),
        no_pan_baidu_path=os.path.join(temp_dir, "no_pan_baidu.json"),
    ):
        super().__init__(
            headless=headless,
        )
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.articles_path = articles_path
        self.pan_baidu_path = pan_baidu_path
        self.no_pan_baidu_path = no_pan_baidu_path

        self.links = []

    def save(self):
        """保存链接到文件"""
        self._logger.info("正在保存链接到文件...")

        def _load_existing_json(file_path):
            if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
                with open(file_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            return []

        def _save_file(file_path, data):
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

        if self.links:
            links_pan_baidu = []
            links_no_pan_baidu = []

            for link in self.links:
                if "pan.baidu.com" in link.get("download_url"):
                    links_pan_baidu.append(link)
                else:
                    links_no_pan_baidu.append(link)

            pan_baidu_json = _load_existing_json(self.pan_baidu_path)
            no_pan_baidu_json = _load_existing_json(self.no_pan_baidu_path)

            pan_baidu_links = pan_baidu_json + links_pan_baidu
            no_pan_baidu_links = no_pan_baidu_json + links_no_pan_baidu

            _save_file(self.pan_baidu_path, pan_baidu_links)
            _save_file(self.no_pan_baidu_path, no_pan_baidu_links)

            self._logger.info(
                f"{self.pan_baidu_path} 新增 {len(links_pan_baidu)} 条,总计 {len(pan_baidu_links)} 条"
            )
            self._logger.info(
                f"{self.no_pan_baidu_path} 新增 {len(links_no_pan_baidu)} 条,总计 {len(no_pan_baidu_links)} 条"
            )
        else:
            self._logger.warning("没有新的链接保存")

    async def produce(self):
        with open(self.articles_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        total = len(data)

        self._logger.info(f"共发现 {total} 个链接")

        pan_baidu_names = self.load_existing_names(self.pan_baidu_path)
        no_pan_baidu_names = self.load_existing_names(self.no_pan_baidu_path)

        items_to_process = []
        count = 0
        for item in data:
            name = item.get("name", "")
            url = item.get("url", "")
            if name in pan_baidu_names or name in no_pan_baidu_names:
                continue
            count += 1
            items_to_process.append((count, name, url))

        if items_to_process:
            total = len(items_to_process)

            self._logger.info(f"需要处理 {total} 个新链接")

            async def process_with_semaphore(count, name, url):
                """带超时和信号量的处理"""
                try:
                    async with asyncio.timeout(None):
                        async with self.semaphore:
                            await self.process_single(
                                count, total, name, url, retry_count=0
                            )
                except asyncio.TimeoutError:
                    self._logger.error(f"任务总超时(300s): {name}")
                except Exception as e:
                    self._logger.error(f"任务异常: {name}: {e}", exc_info=True)

            tasks = [
                process_with_semaphore(count, name, url)
                for count, name, url in items_to_process
            ]

            # 使用 gather 替代 as_completed，更好的错误处理
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # 检查是否有未捕获的异常
            for idx, result in enumerate(results):
                if isinstance(result, Exception):
                    self._logger.error(f"任务 {idx} 发生未捕获异常: {result}")

            self._logger.info(
                f"处理完成,共处理 {len(tasks)} 个文章 {len(self.links)} 个下载链接"
            )
        else:
            self._logger.info("所有链接都已处理过,无需处理新链接")
        self.save()
        save_as_txt(self.pan_baidu_path)

    async def process_single(
        self, count, total, name, article_url, retry_count=0, max_retries=3
    ):
        """处理单个链接（改进版本，确保资源清理）"""
        all_download_urls = []
        download_pwd = None
        extract_pwd = None

        try:
            page = await self.context.new_page()
            page.set_default_timeout(60000)
            await page.goto(article_url, wait_until="domcontentloaded")

            # 第一次点击
            try:
                async with page.expect_popup(timeout=40000) as popup_info:
                    download_selector = "span.poi-icon__text:has-text('下载')"
                    await page.click(download_selector)
                new_page = await popup_info.value
                await new_page.wait_for_load_state("domcontentloaded")
            except:
                # 确保清理所有已创建的页面
                await self.safe_close_page(page)
                await self.safe_close_page(new_page)

                if retry_count < max_retries:
                    # 递归重试前等待一下
                    await asyncio.sleep(2)
                    return await self.process_single(
                        count, total, name, article_url, retry_count + 1, max_retries
                    )
                else:
                    raise

            # 切换到新页面
            await self.safe_close_page(page)
            page = new_page

            # 获取密码信息
            download_pwd_selector = "div.inn-download-page__content__item__download-pwd > div > div.poi-g_lg-9-10.poi-g_7-10 > div > input"
            extract_pwd_selector = "div.inn-download-page__content__item__extract-pwd > div > div.poi-g_lg-9-10.poi-g_7-10 > div > input"

            try:
                download_pwd_input = await page.wait_for_selector(
                    download_pwd_selector, state="attached", timeout=3000
                )
                if download_pwd_input:
                    download_pwd = await download_pwd_input.get_attribute("value")
            except:
                pass

            try:
                extract_pwd_input = await page.wait_for_selector(
                    extract_pwd_selector, state="attached", timeout=3000
                )
                if extract_pwd_input:
                    extract_pwd = await extract_pwd_input.get_attribute("value")
            except:
                pass

            # 查找所有下载按钮
            download_buttons_selector = "span.poi-icon__text:has-text('下载')"
            download_buttons = await page.locator(download_buttons_selector).all()

            # 遍历并点击所有下载按钮
            for btn_index, button in enumerate(download_buttons):
                try:
                    # 等待新页面弹出
                    async with page.expect_popup(timeout=40000) as popup_info:
                        await button.click()

                    new_popup_page = await popup_info.value
                    await new_popup_page.wait_for_load_state("domcontentloaded")

                    # 获取新页面的URL
                    popup_url = new_popup_page.url

                    # 处理二维码（如果需要）
                    if self.is_image_url(popup_url):
                        try:
                            decoded_url = await self.decode_qr_async(popup_url)
                            if decoded_url:
                                popup_url = decoded_url
                        except Exception as e:
                            self._logger.warning(
                                f"[{count}/{total}] {name}: 第 {btn_index + 1} 个按钮二维码解码失败: {e}",
                                exc_info=True,
                            )

                    all_download_urls.append(popup_url)

                    # 关闭弹出页面
                    await self.safe_close_page(new_popup_page)

                except Exception as e:
                    self._logger.warning(
                        f"[{count}/{total}] {name}: 第 {btn_index + 1} 个按钮点击失败: {e}",
                        exc_info=True,
                    )
                    continue

            # 关闭主页面
            await self.safe_close_page(page)
            page = None

            # 保存结果
            async with self.links_lock:
                if all_download_urls:
                    # 对于每个获取到的URL，创建单独的记录
                    for url_index, download_url in enumerate(all_download_urls):
                        # 为每个URL创建唯一名称
                        url_name = name
                        if len(all_download_urls) > 1:
                            url_name = f"{name}_部分{url_index + 1}"

                        # 如果是百度网盘链接，添加密码
                        if (
                            "pan.baidu.com" in download_url
                            and "?pwd=" not in download_url
                            and download_pwd
                        ):
                            download_url = f"{download_url}?pwd={download_pwd}"

                        self.links.append(
                            {
                                "name": url_name,
                                "article_url": article_url,
                                "download_url": download_url,
                                "download_pwd": download_pwd,
                                "extract_pwd": extract_pwd,
                            }
                        )
                    self._logger.info(
                        f"[{count}/{total}] {name}: 处理完成, 共获取 {len(all_download_urls)} 个下载链接"
                    )
                else:
                    self._logger.info(f"[{count}/{total}] {name}: 没有获取到任何URL")

        except asyncio.TimeoutError:
            self._logger.info(f"[{count}/{total}] {name}: 超时")
        except Exception as e:
            self._logger.info(f"[{count}/{total}] {name}: 处理失败: {e}", exc_info=True)
        finally:
            # 确保所有页面都被关闭
            await self.safe_close_page(page)


class MhzxSpider(DownloaderAsync):
    _logger = Log("MhzxSpider").log()

    def __init__(
        self,
        headless=True,
        articles_path="articles.json",
        keyword=None,
        pages_count=5,
    ):
        super().__init__(
            headless=headless,
        )
        self.articles_path = articles_path
        self.keyword = keyword
        self.pages_count = pages_count
        self.list = []

    async def produce(self):
        page = await self.context.new_page()
        page.set_default_timeout(60000)

        page_num = 0
        article_selector = "article > div > h3 > a"
        next_page_selector = "a[title*='下一页']"

        if self.keyword == "game":
            url = r"https://www.mhh1.com/bbs/game"
        elif self.keyword == "3D":
            url = r"https://www.mhh1.com/bbs/sex/2-5d3d-tv"
        elif not self.keyword:
            url = r"https://www.mhh1.com/bbs/sex/2dr18-trdh"
        else:
            url = r"https://www.mhh1.com/"
            search_selector = "a[title*='经典搜索']"
            await page.click(search_selector)
            input_xpath = r"xpath=//html/body/div[14]/div/div[2]/div/form/input[1]"
            await page.fill(input_xpath, self.keyword)
            await page.press(input_xpath, "Enter")
            article_selector = f'a[title*="{self.keyword}"]'
        await page.goto(url, wait_until="domcontentloaded")
        try:
            while page_num < self.pages_count:
                page_num += 1
                # 等待当前页文章加载
                await page.wait_for_selector(article_selector, timeout=10000)

                # 获取当前页文章
                articles = await page.locator(article_selector).all()
                art_list = []
                for article in articles:
                    name = (await article.text_content() or "").strip()
                    url = await article.get_attribute("href")
                    art_list.append({"name": name, "url": url})

                self._logger.info(f"第 {page_num} 页: 收集 {len(art_list)} 个文章")
                self.list += art_list

                # 检查是否有下一页
                next_exists = await page.locator(next_page_selector).count()
                if next_exists == 0:
                    break

                # 检查下一页是否可用
                next_button = page.locator(next_page_selector)
                is_disabled = await next_button.get_attribute("disabled")
                if is_disabled:
                    break

                # 点击下一页
                await next_button.click()

                # 等待新内容加载
                await page.wait_for_timeout(2000)  # 简单等待

            self._logger.info(f"翻页完成，共 {page_num} 页，{len(self.list)} 个文章")

            with open(self.articles_path, "w", encoding="utf-8") as f:
                json.dump(self.list, f, ensure_ascii=False, indent=2)

            await self.safe_close_page(page)
        except Exception as e:
            self._logger.warning("发生未知错误: {e}", exc_info=True)


def save_as_txt(path):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    url_list = []
    extract_pwd = set()
    url_path = os.path.join(temp_dir, "pan_baidu.txt")
    pwd_path = r"E:\BaiduNetdiskDownload\password.txt"

    for i in data:
        url_list.append(i["download_url"])
        extract_pwd.add(i["extract_pwd"])
    if url_list:
        with open(url_path, "w", encoding="utf-8") as f:
            for url in url_list:
                f.write(url + "\n")
    if extract_pwd:
        with open(pwd_path, "w", encoding="utf-8") as f:
            for pwd in extract_pwd:
                if pwd:
                    f.write(pwd + "\n")
