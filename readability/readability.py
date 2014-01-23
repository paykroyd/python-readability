#!/usr/bin/env python
# -*- coding: utf-8 -*-
import logging
import sys
from copy import deepcopy

from lxml.etree import tounicode

import re
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


def to_int(x):
    if not x:
        return None
    x = x.strip()
    if x.endswith('px'):
        return int(x[:-2])
    if x.endswith('em'):
        return int(x[:-2]) * 12
    return int(x)

regexp_type = type(re.compile('hello, world'))


def compile_pattern(elements):
    if not elements:
        return None
    if isinstance(elements, regexp_type):
        return elements
    if isinstance(elements, basestring):
        elements = elements.split(',')
    return re.compile(u'|'.join([re.escape(x.lower()) for x in elements]), re.U)


class Document:
    """
    Represents a single page of content.
    """
    TEXT_LENGTH_THRESHOLD = 25
    RETRY_LENGTH = 250

    def __init__(self, url, text=None, page=1):
        """
        :param url: the url of the document
        :param text: optionally the string value of the page may be passed in
        :param page: if this is one in a series of documents in an article this should be set
        """
        self.url = url
        self.page = page
        self._article = None

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
    def article(self):
        if not self._article:
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
        for candidate in candidates:
            text = (candidate.text_content() or '').lower().strip()
            if text == 'next':
                best = candidate
                break
            elif text == str(self.page + 1):
                best = candidate

        if best != None:
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
        if not article:
            log.info('ruthless parsing didn\'t work')
            article = do_parse(False)
        return article

    def debug(self, *a):
        log.debug(*a)



# def handle_paging():
#     if page:
#         url = self.get_next_page_url()
#         if url:
#             import requests
#             try:
#                 log.info('fetching page %d at url: %s' % (self.page + 1, url))
#                 nextdoc = Document(requests.get(url).text, url=url, page=self.page + 1)
#                 rest = nextdoc.summary(True, True)
#                 self.max_page = nextdoc.max_page
#
#                 if rest:
#                     self.html.append(nextdoc.html)
#                     # if this is page 1, try to remove any repeating boilerplate
#                     # which is anything that we find exactly identical in every page
#                     if self.page == 1:
#                         els = {}
#
#                         for el in utils.tags(self.html, 'div', 'header', 'section'):
#                             els[el] = len(el.text_content())
#
#                         to_remove = []
#                         for el in els:
#                             length = els[el]
#                             identicals = [el]
#                             for e, l in els.iteritems():
#                                 if e != el and l == length and e.text_content() == el.text_content():
#                                     identicals.append(e)
#                             # if there was one of these identical items per page, then we should probably
#                             # remove it
#                             if len(identicals) == self.max_page:
#                                 to_remove.extend(identicals)
#
#                         log.info('removing %d elements from the document' % len(to_remove))
#                         for el in to_remove:
#                             try:
#                                 el.drop_tree()
#                             except:
#                                 # TODO: need to not try to remove things that are in a tree that has already been removed
#                                 log.exception('could not remove this')
#
#
#                     cleaned_article = self.get_clean_html()
#             except BaseException:
#                 log.exception('error trying to fetch the next page of article from: %s' % url)
#                 pass
#
#


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
