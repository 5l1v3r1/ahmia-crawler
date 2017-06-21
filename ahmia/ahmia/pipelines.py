# -*- coding: utf-8 -*-
"""
In this module, you can find pipelines.
AnchorTextPipeline is responsible to index an anchor text with the target
document.
AuthorityPipeline stores links until the spider is closed. Then it creates a
graph and compute the pagerank algorithm on it.
"""
from datetime import datetime
import hashlib
from urlparse import urlparse

from scrapyelasticsearch.scrapyelasticsearch import ElasticSearchPipeline

from .items import DocumentItem, LinkItem, AuthorityItem
from simhash import Simhash
import requests

def simhash(s):
        width = 3
        sim = s.strip()
        sim = sim.lower()
        sim.replace(",","")
        sim.replace("\n","")
        sim = re.sub('http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+', '', sim, flags=re.MULTILINE)
        sim = re.sub('mailto://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+', '', sim, flags=re.MULTILINE)
        sim = re.sub(r'[^\w]+', '', sim)
        sim = re.sub('^[13][a-km-zA-HJ-NP-Z1-9]{25,34}$', '',sim, flags = re.MULTILINE)
        features =  [sim[i:i + width] for i in range(max(len(sim) - width + 1, 1))]
        shash = Simhash(features)
        return shash


class HistoricalElasticSearchPipeline(ElasticSearchPipeline):
    """
    HistoricalElasticSearchPipeline indexes new DocumentItems to ES, if they do 
    not already exist. It also indexes a crawl record
    """
    def index_item(self, item):
        index_name = self.settings['ELASTICSEARCH_RESEARCH_INDEX']
        index_suffix_format = self.settings.get(
            'ELASTICSEARCH_INDEX_DATE_FORMAT', None)

        if index_suffix_format:
            index_name += "-" + datetime.strftime(datetime.now(),
                                                  index_suffix_format)

        if isinstance(item, DocumentItem):
            content_index_action = {
                '_index': index_name,
                '_type': self.settings['ELASTICSEARCH_CONTENT_TYPE'],
                '_id': simhash(item['content']),
                'title': item['title'],
                'content': item['content']
            }
            self.items_buffer.append(content_index_action)
            crawl_index_action = {
                '_index': index_name,
                '_type': self.settings['ELASTICSEARCH_CRAWL_TYPE'],
                'crawl_time': datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                'content_id': simhash(item['content'])
             }
             self.items_buffer.append(crawl_index_action)              

        else:
            return


        if len(self.items_buffer) >= \
          self.settings.get('ELASTICSEARCH_BUFFER_LENGTH', 500):
            self.send_items()
            self.items_buffer = []


#import json #### For research
#from scrapy.conf import settings #### For research

#### For research

"""
class ResearchElasticSearchPipeline(object):
    #Take a copy of item and save it to different index for research purposes.

    def process_item(self, item, spider):
        # Do not mofify original item
        ITEM_TYPE_WEBSITES = "websites"
        research_item = item # Research item is a copy of item

        # Now add fields you need for your research_item

        # Clever way to detect duplicates under a domain
        # Allows same text content from different domains but not under same domain
        sha256_text = hashlib.sha256( research_item["raw_text"] ).hexdigest()
        domain_and_hashtext = research_item['domain'] + sha256_text
        research_item["sha256"] = hashlib.sha256( domain_and_hashtext ).hexdigest()

        # Add timestamp
        timestamp = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        research_item["timestamp"] = timestamp

        # Add what ever fields you need
        # research_item["category"] = neuralNetworkGuessCategory(research_item)

        # Drop duplicate content and index non-duplicate items
        # Check is there already this item in the index
        es_connection = settings.get('RESEARCH_INDEX') + ITEM_TYPE_WEBSITES + "/"
        search_url = es_connection + "_search?size=0&q=sha256:" + research_item["sha256"]
        r = requests.get(search_url)
        # Test if this data is already there
        if r.status_code == 200: # If HTTP OK
            responsejson = r.json()
            try:
                total = int(responsejson["hits"]["total"]) # Number of search results
            except KeyError:
                total = 1
            if total == 0: # No items with this sha256 checksum
                # Finally index this research_item
                # NOT SURE IS THIS RIGHT, please test!
                response = requests.post( es_connection, json=research_item)

        return item # Does not change this item!
"""

class CustomElasticSearchPipeline(ElasticSearchPipeline):
    """
    CustomElasticSearchPipeline is responsible to index items to ES.
    In this version, the index_item method is different because to it needs to
    handle different type of items.
    """
    items_buffer = []

    def index_item(self, item):
        """
        Item are indexed here.
        This method receives an item which can be of type DocumentItem,
        LinkItem or AuthorityItem.
        Note: You should add the following line to your elasticsearch.yml file
        script.engine.groovy.inline.update: on
        """
        index_name = self.settings['ELASTICSEARCH_INDEX']
        index_suffix_format = self.settings.get(
            'ELASTICSEARCH_INDEX_DATE_FORMAT', None)

        if index_suffix_format:
            index_name += "-" + datetime.strftime(datetime.now(),
                                                  index_suffix_format)

        if isinstance(item, DocumentItem):
            index_action = {
                '_index': index_name,
                '_type': self.settings['ELASTICSEARCH_TYPE'],
                '_id': hashlib.sha1(item['url']).hexdigest(),
                '_source': dict(item)
            }
        elif isinstance(item, LinkItem):
            search_url = "%s/%s/%s/"  % ( self.settings['ELASTICSEARCH_SERVER'], self.settings['ELASTICSEARCH_INDEX'], self.settings['ELASTICSEARCH_TYPE'] )
            item_id = hashlib.sha1(item['target']).hexdigest()
            search_url = search_url + item_id
            r = requests.get(search_url)
            if r.status_code == 200:
                responsejson = r.json()
                anchors = responsejson.get("_source",{}).get("anchors", [])
                anchors.append(item["anchor"])
                anchors = list(set(anchors))
                index_action = {
                    "_op_type": "update",
                    "_index": index_name,
                    "_type": self.settings['ELASTICSEARCH_TYPE'],
                    "_id": item_id,
                    "doc": {
                        "anchors": anchors,
                        "url": item['target'],
                        "domain": urlparse(item['target']).hostname,
                        "updated_on": datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
                    }
                }
            else:
                index_action = {
                    '_index': index_name,
                    '_type': self.settings['ELASTICSEARCH_TYPE'],
                    '_id': item_id,
                    '_source': dict(item)
                }
        elif isinstance(item, AuthorityItem):
            index_action = {
                "_op_type": "update",
                "_index": index_name,
                "_type": self.settings['ELASTICSEARCH_TYPE'],
                "_id": item['url'],
                "doc": {
                    "authority": item['score']
                }
            }
        else:
            return

        self.items_buffer.append(index_action)

        if len(self.items_buffer) >= \
          self.settings.get('ELASTICSEARCH_BUFFER_LENGTH', 500):
            self.send_items()
            self.items_buffer = []
