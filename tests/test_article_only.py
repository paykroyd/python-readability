import os
import unittest

from readability import Document


SAMPLES = os.path.join(os.path.dirname(__file__), 'samples')


def load_sample(filename):
    """Helper to get the content out of the sample files"""
    return open(os.path.join(SAMPLES, filename)).read()


class TestArticleOnly(unittest.TestCase):
    """The option to not get back a full html doc should work

    Given a full html document, the call can request just divs of processed
    content. In this way the developer can then wrap the article however they
    want in their own view or application.

    """

    def test_si_sample_html_partial(self):
        """Using the si sample, make sure we can get the article alone."""
        sample = load_sample('si-game.sample.html')
        doc = Document('http://sportsillustrated.cnn.com/baseball/mlb/gameflash/2012/04/16/40630_preview.html',
                       sample)
        res = doc.get_clean_article()
        self.assertEqual('<div><div class="', res[0:17])


class TestArticleParsing(unittest.TestCase):
    """
    Tests that we handle different aspects of articles correctly.
    """

    def test_lazy_images(self):
        """
        Some sites use <img> elements with data-lazy-src elements pointing to the actual image.
        """
        sample = load_sample('wired.sample.html')
        doc = Document('http://www.wired.com/design/2014/01/will-influential-ui-design-minority-report/', sample)
        article = doc.get_clean_article()
        self.assertIn('<img src="http://www.wired.com/images_blogs/design/2014/01/her-joaquin-phoenix-41-660x371.jpg"', article)

