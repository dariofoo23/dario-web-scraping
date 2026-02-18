from urllib import response
from scrapy.item import Field, Item
from scrapy.spiders import CrawlSpider, Rule
from scrapy.selector import Selector
from itemloaders.processors import MapCompose
from scrapy.linkextractors import LinkExtractor
from scrapy.loader import ItemLoader


class Reviews(Item):
    starRating = Field()
    opinionTitle = Field()
    opinionText = Field()

class TrustPilotCrawler(CrawlSpider):
    # 1-Definir el nombre del spider
    name = 'TrustPilotCrawler'

    # 2- Definir el USER_AGENT
    custom_settings = {
        'USER_AGENT': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.7499.193 Safari/537.36',
        'ROBOTSTXT_OBEY': False,
        #'DEPTH_LIMIT': 2,
        #'CLOSESPIDER_PAGECOUNT': 2,
        #'CLOSESPIDER_ITEMCOUNT': 10,
        'FEED_EXPORT_ENCODING': 'utf-8-sig',
    }

    # 3- Definir las reglas de extracción (Rules)
    start_urls = ['https://es.trustpilot.com/review/www.telekom.de?languages=all']

    # 4- Definir dominios permitidos
    allowed_domains = ["trustpilot.com"]

    # Tiempo de espera entre requests
    download_delay = 2

    # 5- Definir reglas del orquestador

    rules = (
        Rule(
            LinkExtractor(
                allow=r"/review/www\.telekom\.de\?languages=all(&|$).*page=\d+"
            ),
            callback="parse_opinion",
            follow=True,
        ),
    )

    # make sure page 1 also gets parsed
    def parse_start_url(self, response):
        return self.parse_opinion(response)
    

    def parse_opinion(self, response):
        sel = Selector(response)
        
        review_objects = sel.xpath('//div[contains(@class,"styles_cardWrapper__g8amG styles_show__Z8n7u")]')

        for review in review_objects:

            item = ItemLoader(Reviews(),response)

            stars = review.xpath('.//section[contains(@class,"styles_reviewContentwrapper__K2aRu")]//div[contains(@class,"styles_reviewHeader__DzoAZ")]//img/@alt').get()
            item.add_value('starRating', stars)

            title = review.xpath('.//div[contains(@class,"styles_reviewContent__tuXiN")]//a[contains(@class,"CDS_Typography_appearance-inherit__68c681 CDS_Typography_prettyStyle__68c681 CDS_Link_link__0e2efd CDS_Link_noUnderline__0e2efd")]//h2/text()').get()
            item.add_value('opinionTitle', title)

            full_text = review.xpath('.//div[contains(@class,"styles_reviewContent__tuXiN")]//p[@data-service-review-text-typography="true"]/text()').getall()
            text = " ".join(full_text)
            item.add_value('opinionText', text)

            yield item.load_item()

"scrapy runspider 40_googleScholar.py -O 41_GS_data.json:json"