from mhzx_downloader import MhzxDownloader, MhzxSpider

if __name__ == "__main__":
    # 创建下载器
    downloader = MhzxDownloader(
        # headless=False,
        max_concurrent=5,
        # articles_path=r"地址",
    )
    # 创建爬取器
    spider = MhzxSpider(
        # headless=False,
        keyword="2D",
    )

    # 运行
    # downloader.run()
    spider.run()
