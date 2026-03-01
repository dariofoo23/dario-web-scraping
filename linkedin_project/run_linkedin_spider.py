import os
from scrapy.crawler import CrawlerProcess
from scrapy.utils.project import get_project_settings

from linkedin_extraction_spider import LinkedinSeleniumSpider

from webdriver_manager.chrome import ChromeDriverManager


def main():
    settings = get_project_settings()

    # Persistent profile folder (change this!)
    profile_dir = r"C:\Users\Dario Martínez\Documents\selenium_profiles\linkedin"
    settings.set("SELENIUM_DRIVER_NAME", "chrome")
    settings.set("SELENIUM_DRIVER_EXECUTABLE_PATH", ChromeDriverManager().install())
    settings.set("FEEDS", {"01_linkedin_companies.csv": {"format": "csv", "overwrite": True}})
    settings.set("SELENIUM_DRIVER_ARGUMENTS", [
    f"--user-data-dir={profile_dir}",
    "--profile-directory=Default",
    "--start-maximized",
    "--disable-blink-features=AutomationControlled",
    ])

    process = CrawlerProcess(settings)
    process.crawl(LinkedinSeleniumSpider, max_pages=None)
    process.start()


if __name__ == "__main__":
    main()
