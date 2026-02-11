import asyncio

from playwright.async_api import async_playwright, ViewportSize


async def fast_login():
    """快速恢复登录状态"""
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-images",  # 禁用所有图片加载
            ],
        )

        context = await browser.new_context(
            storage_state=r"E:\Program\Python\mhzx\Download\temp\storage_state.json",
            viewport=ViewportSize(width=1280, height=720),
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        )
        page=await context.new_page()
        url = r"https://www.mhh1.com/901389.html"
        await page.goto(url,timeout=100000)
        temp_expwd_xpath=r"xpath=//article/div/div[2]/div[3]/div/div/div/div/h3"
        await page.wait_for_selector(temp_expwd_xpath)
        result = await page.locator(temp_expwd_xpath).text_content()
        expwd=result.split(":")[1]
        print(expwd)

asyncio.run(fast_login())