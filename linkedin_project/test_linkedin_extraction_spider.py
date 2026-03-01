import random,time
from urllib.parse import urljoin, urlparse, parse_qs

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

    """<a id="ember4921" class="ember-view link--mercado" data-anonymize="company-name" 
    data-control-name="view_company_via_result_name" data-control-id="êbúÄ¾M¾ls#¢" 
    href="/sales/company/555307?_ntb=3bKHzZl4TCe8mO7DPzD3og%3D%3D" data-sales-action="">
          Talgo
        </a>"""


    industry = Field()
    employees = Field()
    revenue = Field()
    url = Field() # Extract id from href="/sales/company/555307
    # Build the linkedin_company_page = f"https://www.linkedin.com/company/{id}/" using href="/sales/company/555307

"""<div id="ember4923" class="artdeco-entity-lockup__subtitle ember-view t-14">
      <span data-anonymize="industry">
        Railroad Equipment Manufacturing
      </span>

      <span aria-hidden="true" class="separator--middot"></span>

          <span>
            <a id="ember4924" class="ember-view _link_1derdc _view-all-employees_1derdc link-without-visited-state" aria-label="View all 2K+ employees at Talgo on LinkedIn" data-anonymize="company-size" href="/sales/search/people?query=(filters%3AList((type%3ACURRENT_COMPANY%2Cvalues%3AList((id%3A555307%2CselectionType%3AINCLUDED)))))">
              2K+ employees
            </a>
            on LinkedIn
          </span>

            <span>
          <span aria-hidden="true" class="separator--middot"></span>

        <span data-anonymize="revenue">$500M - $1B</span> in revenue
              <!---->

  
          <span data-test="account-revenue" class="vertical-align-sub">
            <svg aria-hidden="false" role="button" aria-label="More info about range of annual revenue" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" data-supported-dps="16x16" fill="currentColor" aria-describedby="hue-web-tooltip-content-account-revenue-legal-tooltip" tabindex="0">
  <path d="M12 2H4a2 2 0 00-2 2v8a2 2 0 002 2h8a2 2 0 002-2V4a2 2 0 00-2-2zm-3 8v2H7.5A1.5 1.5 0 016 10.5a1.56 1.56 0 01.1-.5l1.08-3h2.13l-1.09 3zm0-3.75A1.25 1.25 0 1110.25 5 1.25 1.25 0 019 6.25z"></path>
</svg>
          </span>
        

  </span>

    </div>"""

class LinkedinSeleniumSpider(scrapy.Spider):
    name = "LinkedinSeleniumSpider"
    start_urls = ["https://www.linkedin.com/sales/search/company?savedSearchId=1980479034&sessionId=FUTibHswSPW8UMM4eB2KFQ%3D%3D"]

    # Estructure of following pages for pagination:
    # https://www.linkedin.com/sales/search/company?page=2&savedSearchId=1980479034&sessionId=3bKHzZl4TCe8mO7DPzD3og%3D%3D
    # and page=3, page=4, etc.

    linkedin_company_page = "https://www.linkedin.com/company/{id}/"

    custom_settings = {
        "FEED_EXPORT_ENCODING": "utf-8-sig",
        "DOWNLOADER_MIDDLEWARES": {"scrapy_selenium.SeleniumMiddleware": 800},
        "DUPEFILTER_CLASS": "scrapy.dupefilters.BaseDupeFilter",
        # Optional: reduce noisy selenium logs
        "LOG_LEVEL": "INFO",
    }


    def start_requests(self):
        yield SeleniumRequest(
            url=self.start_urls[0],
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
        self.logger.warning("LOGIN REQUIRED. Please log in in the opened Chrome window.")
        self.logger.warning("After login, come back here and press ENTER.")
        input("Press ENTER to continue after you finish logging in...")

    def parse_with_selenium(self, response):
        driver = response.meta["driver"]

        # Give the browser more time to load pages
        driver.set_page_load_timeout(60)

        wait = WebDriverWait(driver, 30)

        # Always start at page 1
        driver.get(self.start_urls[0])

        visited = set()

        while True:
            current_url = driver.current_url

            # We don't have a users/connect login wall here
            # We need to login manually before starting the spider, and we will just get blocked if we get logged out during the crawl

            if current_url in visited:
                self._manual_login_pause(driver)
                # return to the same page after login
                driver.get(current_url)
                time.sleep(2)

            if current_url in visited:
                self.logger.info("Repeated URL, stopping: %s", current_url)
                break
            visited.add(current_url)

            try:
                # Wait reviews cards
                wait.until(
                    EC.presence_of_all_elements_located(
                        (By.XPATH, '//ol[contains(@class,"artdeco-list background-color-white _border-search-results_1igybl")]')
                    )
                )
            except TimeoutException:
                # Instead of crashing the spider, handle it:
                self.logger.warning("Timeout waiting reviews on %s", current_url)

                # If timeout happened because we were pushed to login
                if current_url in visited:
                    self._manual_login_pause(driver)
                    # return to the same page after login
                    driver.get(current_url)
                    time.sleep(2)
                    continue

                # Otherwise: try refresh once
                driver.refresh()
                time.sleep(2)
                continue

            sel = scrapy.Selector(text=driver.page_source)
            review_objects = sel.xpath('//ol[contains(@class,"artdeco-list background-color-white _border-search-results_1igybl")]')
            page_num = self._get_page_num(current_url)

            self.logger.info("PAGE=%s URL=%s reviews=%d", page_num, current_url, len(review_objects))

            for review in review_objects:
                item = ItemLoader(Reviews(), selector=review)
                item.add_value("url", current_url)
                item.add_value("page", page_num)

                # Company Name
                company_name = review.xpath('.//div[contains(@class,"artdeco-entity-lockup__title ember-view")]/text()').get()
                item.add_value("companyName", company_name)
                # Industry
                industry = review.xpath('.//div[contains(@class,"artdeco-entity-lockup__subtitle ember-view")]/span[1]/text()').get()
                item.add_value("industry", industry)
                # Employees
                employees = review.xpath('.//div[contains(@class,"artdeco-entity-lockup__subtitle ember-view")]/span[2]/span/a/text()').get()
                item.add_value("employees", employees)  
                # Revenue
                revenue = review.xpath('.//div[contains(@class,"artdeco-entity-lockup__subtitle ember-view")]/span[3]/span/text()').get()
                item.add_value("revenue", revenue)

                #url
                url = review.xpath('.//div[contains(@class,"artdeco-entity-lockup__title ember-view")]/a/@href').get()
                id = url.split("/")[-2] # Extract id from href="/sales/company/555307
                item.add_value("url", self.linkedin_company_page.format(id=id)) # Build the linkedin_company_page = f"https://www.linkedin.com/company/{id}/" using href="/sales/company/555307

                yield item.load_item()

            # Find next button
            #Element that contains the next button:
            """<button aria-label="Next" id="ember4914" class="artdeco-button artdeco-button--muted artdeco-button--icon-right artdeco-button--1 artdeco-button--tertiary ember-view artdeco-pagination__button artdeco-pagination__button--next" type="button">  <li-icon aria-hidden="true" type="chevron-right-icon" class="artdeco-button__icon" size="small"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" data-supported-dps="16x16" fill="currentColor" width="16" height="16" focusable="false">
            <path d="M9 8L5 2.07 6.54 1l4.2 6.15a1.5 1.5 0 010 1.69L6.54 15 5 13.93z"></path>
            </svg></li-icon>

                <span class="artdeco-button__text">
                Next
                </span></button>"""


            next_href = sel.xpath('//button[@class="artdeco-pagination__button--next"]').get()
            if not next_href:
                self.logger.info("No next button. Finished.")
                break

            next_url = urljoin(driver.current_url, next_href)
            next_page = self._get_page_num(next_url)

            # Go next and wait URL updates (but don't crash if it doesn't)
            driver.get(next_url)
            try:
                wait.until(lambda d: f"page={next_page}" in d.current_url or "/users/connect" in d.current_url)
            except TimeoutException:
                self.logger.warning("Timeout waiting URL change to page=%s. Continuing anyway.", next_page)

            human_sleep(page_num)
