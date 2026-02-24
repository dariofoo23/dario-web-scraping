import random, time, re
from urllib.parse import urlparse, parse_qs

import scrapy
from scrapy.item import Item, Field
from scrapy.loader import ItemLoader
from scrapy_selenium import SeleniumRequest

from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


def human_sleep(page_num: int, short=(3.5, 7.5), long_every=25, long=(25, 55)):
    """Sleep a bit between pages, and take a longer break every N pages."""
    time.sleep(random.uniform(*short))
    if page_num % long_every == 0:
        time.sleep(random.uniform(*long))


class Reviews(Item):
    companyName = Field()
    industry = Field()
    employees = Field()
    revenue = Field()
    url = Field()     # linkedin company page built from sales/company/<id>
    page = Field()
    source_url = Field()  # the current sales nav search page url


class LinkedinSeleniumSpider(scrapy.Spider):
    name = "LinkedinSeleniumSpider"

    start_urls = [
        "https://www.linkedin.com/sales/search/company?savedSearchId=1980479034&sessionId=FUTibHswSPW8UMM4eB2KFQ%3D%3D"
    ]

    linkedin_company_page = "https://www.linkedin.com/company/{id}/"

    custom_settings = {
        "FEED_EXPORT_ENCODING": "utf-8-sig",
        "DOWNLOADER_MIDDLEWARES": {"scrapy_selenium.SeleniumMiddleware": 800},
        "DUPEFILTER_CLASS": "scrapy.dupefilters.BaseDupeFilter",
        "LOG_LEVEL": "INFO",
    }

    # ---- small knobs you can pass with -a ----
    # login_only=1 -> just open browser, login, press enter, exit (cookies saved in profile)
    login_only: bool = False
    # max_pages=2 -> only process page 1 and 2 for testing
    max_pages: int | None = None
    # start_page=1 -> start from specific page
    start_page: int = 1

    def __init__(self, login_only="0", max_pages=None, start_page="1", *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.login_only = str(login_only) == "1"
        self.max_pages = int(max_pages) if max_pages is not None else None
        self.start_page = int(start_page)

    def start_requests(self):
        base = self.start_urls[0]

        # If start_page is 1, use the start_url exactly as-is
        if self.start_page <= 1:
            url = base
        else:
            joiner = "&" if "?" in base else "?"
            url = f"{base}{joiner}page={self.start_page}"

        yield SeleniumRequest(
            url=url,
            callback=self.parse_with_selenium,
            wait_time=10,
            dont_filter=True,
        )

    def _get_page_num(self, url: str) -> int:
        try:
            qs = parse_qs(urlparse(url).query)
            return int(qs.get("page", ["1"])[0])
        except Exception:
            return 1

    def _manual_login_pause(self, driver):
        self.logger.warning("LOGIN REQUIRED. Please log in in the opened Chrome window (Sales Navigator).")
        self.logger.warning("After login, come back here and press ENTER.")
        input("Press ENTER to continue after you finish logging in...")

    def _needs_login(self, driver) -> bool:
        u = driver.current_url.lower()
        if "login" in u or "checkpoint" in u:
            return True
        html = driver.page_source.lower()
        # lightweight heuristics
        return ("sign in" in html and "linkedin" in html) or ("join linkedin" in html)
    
    def _is_logged_in(self, driver) -> bool:
    # If we can see the results list container, we're logged in.
        html = driver.page_source
        sel = scrapy.Selector(text=html)
        return bool(sel.xpath('//ol[contains(@class,"_border-search-results")]').get())

    def _extract_sales_company_id(self, href: str) -> str | None:
        # href example: /sales/company/555307?_ntb=...
        m = re.search(r"/sales/company/(\d+)", href)
        return m.group(1) if m else None

    def _scroll_until_cards_stable(self, driver, wait, max_rounds=20, pause=(0.7, 1.2), stable_rounds=3):
        """
        Scrolls down repeatedly until the number of /sales/company/ links stops increasing.
        """
        stable = 0
        last_count = -1

        for _ in range(max_rounds):
            # Count company links currently loaded
            html = driver.page_source
            sel = scrapy.Selector(text=html)
            count = len(sel.xpath('//a[contains(@href,"/sales/company/")]/@href').getall())

            if count == last_count:
                stable += 1
            else:
                stable = 0
                last_count = count

            # If it didn't grow for a few rounds, we're done
            if stable >= stable_rounds:
                return count

            # Scroll down to trigger lazy load
            driver.execute_script("window.scrollBy(0, 900);")
            time.sleep(random.uniform(*pause))

        return last_count

    def parse_with_selenium(self, response):
        driver = response.meta["driver"]
        driver.set_page_load_timeout(60)
        wait = WebDriverWait(driver, 30)

        # Go to starting page (important when resuming)
        driver.get(response.url)

        # First-run login capture
        if self._needs_login(driver):
            self._manual_login_pause(driver)
            driver.get(response.url)
            time.sleep(2)

        # If user asked for login-only mode: stop after successful login
        if self.login_only:
            # Force a pause unless we can confirm the Sales Nav results are visible
            if not self._is_logged_in(driver):
                self.logger.warning("Not confirmed logged in yet. Please log in in the opened browser.")
                self._manual_login_pause(driver)
                driver.get(response.url)
                time.sleep(2)

            if self._is_logged_in(driver):
                self.logger.info("Login confirmed. Session is stored in the Chrome profile.")
            else:
                self.logger.warning("Login still not confirmed. Try again (maybe LinkedIn showed a checkpoint).")
            return

        visited = set()

        while True:
            current_url = driver.current_url
            page_num = self._get_page_num(current_url)

            if self.max_pages is not None and page_num > self.max_pages:
                self.logger.info("Reached max_pages=%s, stopping at %s", self.max_pages, current_url)
                break

            # if logged out mid-run, pause
            if self._needs_login(driver):
                self._manual_login_pause(driver)
                driver.get(current_url)
                time.sleep(2)
                continue

            if current_url in visited:
                self.logger.info("Repeated URL, stopping: %s", current_url)
                break
            visited.add(current_url)

            try:
                # Wait for the results list (container)
                wait.until(
                    EC.presence_of_all_elements_located(
                        (By.XPATH, './/li[contains(@class,"artdeco-list__item pl3 pv3 ")]')
                    )
                )
            except TimeoutException:
                self.logger.warning("Timeout waiting results on %s", current_url)
                driver.refresh()
                time.sleep(2)
                continue
            
            # Load all cards on the current page by scrolling
            loaded = self._scroll_until_cards_stable(driver, wait)
            self.logger.info("Loaded company links on page: %s", loaded)

            sel = scrapy.Selector(text=driver.page_source)

            self.logger.info("Title=%r", sel.xpath("//title/text()").get())
            self.logger.info("Has /sales/company links: %d", len(sel.xpath('//a[contains(@href,"/sales/company/")]/@href').getall()))
            # IMPORTANT: select each result item (li), not the ol
            company_cards = sel.xpath(
            './/li[contains(@class,"artdeco-list__item pl3 pv3 ")]'
            )

            self.logger.info("PAGE=%s URL=%s cards=%d", page_num, current_url, len(company_cards))
            self.logger.info("First card has company link? %s", bool(company_cards[0].xpath('.//a[contains(@href,"/sales/company/")]').get()) if company_cards else False)

            for card in company_cards:
                item = ItemLoader(Reviews(), selector=card)
                item.add_value("source_url", current_url)
                item.add_value("page", page_num)

                # Company Name (Sales Nav uses data-anonymize="company-name" in many layouts)
                company_name = card.xpath('normalize-space(.//a[@data-anonymize="company-name"])').get()
                if company_name:
                    company_name = company_name.strip()
                item.add_value("companyName", company_name)

                industry = card.xpath('normalize-space(.//span[@data-anonymize="industry"]/text())').get()
                if industry:
                    industry = industry.strip()
                item.add_value("industry", industry)

                employees = card.xpath('normalize-space(.//a[@data-anonymize="company-size"]/text())').get()
                if employees:
                    employees = employees.strip()
                item.add_value("employees", employees)

                revenue = card.xpath('normalize-space(.//span[@data-anonymize="revenue"]/text())').get()
                if revenue:
                    revenue = revenue.strip()
                item.add_value("revenue", revenue)

                sales_href = card.xpath('.//a[contains(@href,"/sales/company/")]/@href').get()
                cid = self._extract_sales_company_id(sales_href or "")
                if cid:
                    item.add_value("url", self.linkedin_company_page.format(id=cid))
                else:
                    item.add_value("url", None)

                yield item.load_item()

            # ---- Pagination: click Next button ----
            # Scroll to bottom so pagination appears/enables
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2.0)

            try:
                next_btn = driver.find_element(By.XPATH, '//button[contains(@class,"artdeco-pagination__button--next")]')
            except Exception:
                self.logger.info("No next button found. Finished.")
                break

            # If disabled, stop
            aria_disabled = (next_btn.get_attribute("aria-disabled") or "").lower()
            disabled_attr = next_btn.get_attribute("disabled")
            if aria_disabled == "true" or disabled_attr is not None:
                self.logger.info("Next button disabled. Finished.")
                break

            next_page = page_num + 1

            # Click next and wait for page param to update OR list to refresh
            next_btn.click()
            try:
                wait.until(lambda d: f"page={next_page}" in d.current_url or self._needs_login(d))
            except TimeoutException:
                # Sometimes URL doesn't change but content does; continue anyway
                self.logger.warning("Timeout waiting URL change to page=%s, continuing.", next_page)

            human_sleep(page_num)