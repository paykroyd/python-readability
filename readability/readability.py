#!/usr/bin/env python
# -*- coding: utf-8 -*-
import logging
import sys
from copy import deepcopy

from lxml.etree import tounicode

import requests
import utils
from cleaners import clean_attributes
from cleaners import html_cleaner
from htmls import build_doc
from htmls import get_title
from htmls import shorten_title


logging.basicConfig(level=logging.INFO)
log = logging.getLogger()


class Unparseable(ValueError):
    pass


class NotArticle(ValueError):
    pass


class Document:
    """
    Represents a single page of content.
    """
    TEXT_LENGTH_THRESHOLD = 25
    RETRY_LENGTH = 250

    def __init__(self, url, text=None, page=1, min_article_length=250, min_article_percentage=0.075):
        """
        :param url: the url of the document
        :param text: optionally the string value of the page may be passed in
        :param page: if this is one in a series of documents in an article this should be set
        :param min_article_length: if an article is less than this number of characters it's not an article
        :param min_article_percentage: an article must be this % of the text on the page
        """
        self.url = url
        self.page = page
        self._article = None
        self.min_article_length = min_article_length
        self.min_article_percentage = min_article_percentage

        if text:
            self.text = text
        else:
            self.text = requests.get(url).text

        # parses the HTML and cleans it up removing elements this doesn't want to deal with (e.g., head, script, form)
        doc, self.encoding = build_doc(self.text)
        doc = html_cleaner.clean_html(doc)
        doc.make_links_absolute(self.url, resolve_base_href=True)
        self.html = doc

    def title(self):
        return get_title(self.html)

    def short_title(self):
        return shorten_title(self.html)

    def get_clean_article(self):
        """
        Returns a string version of the html with attributes removed.
        """
        return clean_attributes(tounicode(self.article))

    @property
    def is_article(self):
        """
        Returns True if this is an article.

        Start off by determining this via the length of the article.
        """
        if not self.article:
            return False
        article_len = utils.text_length(self.article)
        if article_len < self.min_article_length:
            return False
        percent = float(article_len) / utils.text_length(self.html)
        logging.info('Article is %f %% of the documemnt' % percent)
        return percent >= self.min_article_percentage

    @property
    def article(self):
        if self._article is None:
            self._article = self.parse()
        return self._article

    def get_next_page_url(self):
        """
        Searches the page for a next page URL if it can find one.
        """
        # if this is a media wiki page, skip it

        LinkCandidateXPathQuery = "descendant-or-self::*[(not(@id) or (@id!='disqus_thread' and @id!='comments')) and (not(@class) or @class!='userComments')]/a"
        candidates = self.html.xpath(LinkCandidateXPathQuery)

        best = None
        best_score = 0
        next_page = self.page + 1
        for candidate in candidates:
            score = utils.score_possible_paging_url(self.url, candidate, next_page)
            if score > best_score:
                best = candidate
                best_score = score

        if best is not None:
            return best.attrib.get('href')
        else:
            return None

    def parse(self):
        """
        Attempts to create an cleaned article version of this document.
        """
        def select_best_candidate(candidates):
            """
            Returns the candidate with the highest content score.
            """
            sorted_candidates = sorted(candidates.values(), key=lambda x: x['content_score'], reverse=True)
            for candidate in sorted_candidates[:5]:
                elem = candidate['elem']
                self.debug("Top 5 : %6.3f %s" % (candidate['content_score'], utils.describe(elem)))
            if len(sorted_candidates) == 0:
                return None
            return sorted_candidates[0]

        def do_parse(ruthless):
            try:
                html = deepcopy(self.html)
                for i in utils.tags(html, 'script', 'style'):
                    i.drop_tree()
                for i in utils.tags(html, 'body'):
                    i.set('id', 'readabilityBody')
                if ruthless:
                    html = utils.remove_unlikely_candidates(html)
                html = utils.transform_misused_divs_into_paragraphs(html)

                candidates = utils.score_paragraphs(html)

                # first try to get an article
                article_node = utils.get_article_element(html)
                if article_node:
                    best_candidate = article_node
                else:
                    best_candidate = select_best_candidate(candidates)

                if best_candidate:
                    # TODO: there was some logic here about retrying if the article wasn't long enough
                    return utils.sanitize(utils.get_article(candidates, best_candidate), candidates)
                else:
                    return None
            except StandardError, e:
                log.exception('error getting summary: ')
                raise Unparseable(str(e)), None, sys.exc_info()[2]

        # Make 2 attempts to parse an article. First, try ruthlessly: aggressively removing things that are likely
        # not part of the article. If that fails to find a valid article, try in a more conservative way
        article = None
        try:
            article = do_parse(True)
        except Unparseable:
            pass
        if article is None:
            log.info('ruthless parsing didn\'t work')
            article = do_parse(False)
        return article

    def debug(self, *a):
        log.debug(*a)


def get_article(url, text=None):
    """
    Given a URL this loads the page and parses the article, attempting to page it as well.

    :param url: url to find an article on
    """
    doc = Document(url, text)
    if not doc.is_article:
        raise NotArticle()

    pages = []
    used_urls = set(url)
    current = doc
    # if we find an article see if we can find more pages
    nexturl = current.get_next_page_url()
    while nexturl and nexturl not in used_urls:
        log.info('fetching page %d at url: %s' % (current.page + 1, nexturl))
        nextdoc = Document(nexturl, page=current.page + 1)
        if nextdoc.article is not None:
            used_urls.add(nexturl)
            pages.append(nextdoc.article)
            nexturl = nextdoc.get_next_page_url()
            current = nextdoc
    log.info('found %d more pages' % len(pages))
    # append any additional pages to the first one's content
    for page in pages:
        doc.article.append(page)
    # now clean it up, removing any boilerplate that may be on each page of the article
    utils.remove_boilerplate(doc.article, len(pages) + 1)
    return doc.get_clean_article()


def main():
    from optparse import OptionParser
    parser = OptionParser(usage="%prog: [options] [file]")
    parser.add_option('-v', '--verbose', action='store_true')
    parser.add_option('-u', '--url', default=None, help="use URL instead of a local file")
    parser.add_option('-p', '--positive-keywords', default=None, help="positive keywords (separated with comma)", action='store')
    parser.add_option('-n', '--negative-keywords', default=None, help="negative keywords (separated with comma)", action='store')
    (options, args) = parser.parse_args()

    if not (len(args) == 1 or options.url):
        parser.print_help()
        sys.exit(1)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.DEBUG)
    log.addHandler(handler)
    log.setLevel(logging.DEBUG)

    if options.url:
        import requests
        resp = requests.get(options.url)
        resp.raise_for_status()
        content = resp.text
    else:
        with open(args[0], 'rt') as f:
            content = f.read()

    enc = sys.__stdout__.encoding or 'utf-8' # XXX: this hack could not always work, better to set PYTHONIOENCODING
    print Document(options.url, content).get_clean_article().encode(enc, 'replace')


if __name__ == '__main__':
    main()
