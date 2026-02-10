from mhzx_downloader import MhzxDownloader, MhzxSpider

if __name__ == "__main__":
    # 创建下载器实例
    downloader = MhzxDownloader(
        # headless=False,
        # max_concurrent=5,
        articles_path=r"/Python/mhzx_2D/articles.json",
    )
    spider = MhzxSpider(
        # headless=False,
        articles_path=r"articles.json",
        article_url="https://www.mhh1.com/search/-#eyJrdyI6Iuimi%2BOBmuawtOeFriIsInRhZ3MiOltdLCJjYXQiOltdLCJwYWdlZCI6MSwiY2F0cyI6W119"
    )

    # 运行下载器
    # downloader.run()
    spider.run()
