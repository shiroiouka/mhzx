from mhzx_downloader import MhzxDownloader, MhzxSpider

if __name__ == "__main__":
    # 创建下载器
    downloader = MhzxDownloader(
        # headless=False,
        # max_concurrent=5,
        # articles_path=r"地址",
    )
    # 创建爬取器
    spider = MhzxSpider(
        # headless=False,
        keyword="game", # '关键字'|game|3D|默认(2D)
        pages_count=2,
    )

    # 运行
    # spider.run()
    downloader.run()

