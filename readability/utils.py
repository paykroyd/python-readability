import logging

from urlparse import urlparse

from lxml.etree import tostring

import re
from lxml.html import fragment_fromstring


REGEXES = {
    'unlikelyCandidatesRe': re.compile('combx|comment|community|disqus|extra|foot|header|menu|remark|rss|shoutbox|sidebar|sponsor|ad-break|agegate|pagination|pager|popup|tweet|twitter', re.I),
    'okMaybeItsACandidateRe': re.compile('and|article|body|column|main|shadow', re.I),
    'positiveRe': re.compile('article|body|content|entry|hentry|main|page|pagination|post|text|blog|story', re.I),
    'negativeRe': re.compile('combx|comment|com-|contact|foot|footer|footnote|masthead|media|meta|outbrain|promo|related|scroll|shoutbox|sidebar|sponsor|shopping|tags|tool|widget', re.I),
    'divToPElementsRe': re.compile('<(a|blockquote|dl|div|img|ol|p|pre|table|ul)', re.I),
    #'replaceBrsRe': re.compile('(<br[^>]*>[ \n\r\t]*){2,}',re.I),
    #'replaceFontsRe': re.compile('<(\/?)font[^>]*>',re.I),
    #'trimRe': re.compile('^\s+|\s+$/'),
    #'normalizeRe': re.compile('\s{2,}/'),
    #'killBreaksRe': re.compile('(<br\s*\/?>(\s|&nbsp;?)*){1,}/'),
    #'videoRe': re.compile('http:\/\/(www\.)?(youtube|vimeo)\.com', re.I),
    #skipFootnoteLink:      /^\s*(\[?[a-z0-9]{1,2}\]?|^|edit|citation needed)\s*$/i,
}


def tags(node, *tag_names):
    """
    Iterates through all descendants of node with any of the tag names.

    :param node: lxml element
    :param tag_names: strings
    """
    for tag_name in tag_names:
        for e in node.findall('.//%s' % tag_name):
            yield e


def reverse_tags(node, *tag_names):
    """
    Iterates in reverse order through all descendants of node with any of the tag names.

    :param node: lxml element
    :param tag_names: strings
    """
    for tag_name in tag_names:
        for e in reversed(node.findall('.//%s' % tag_name)):
            yield e


def clean(text):
    text = re.sub('\s*\n\s*', '\n', text)
    text = re.sub('[ \t]{2,}', ' ', text)
    return text.strip()


def class_weight(e):
    """
    Scores the node positively or negatively based on its class and id
    """
    weight = 0
    for feature in [e.get('class', None), e.get('id', None)]:
        if feature:
            if REGEXES['negativeRe'].search(feature):
                weight -= 25

            if REGEXES['positiveRe'].search(feature):
                weight += 25
    return weight


def score_node(elem, score_text_length=False):
    """
    Scores the element based on the type of HTML tag and its class.

    :returns: a dict containing 'content_score' and 'elem' keys.
    """
    content_score = class_weight(elem)
    name = elem.tag.lower()
    if name == "article":
        content_score += 25
    elif name == "div":
        content_score += 5
    elif name in ["pre", "td", "blockquote"]:
        content_score += 3
    elif name in ["address", "ol", "ul", "dl", "dd", "dt", "li", "form"]:
        content_score -= 3
    elif name in ["h1", "h2", "h3", "h4", "h5", "h6", "th"]:
        content_score -= 5

    if score_text_length:
        inner_text = clean(elem.text_content() or "")
        inner_text_len = len(inner_text)

        # If this section is less than 200 characters
        # don't even count it.
        if inner_text_len < 200:
            content_score = 0
        else:
            content_score += len(inner_text.split(','))
            content_score += min((inner_text_len / 100), 3)

    return {
        'content_score': content_score,
        'elem': elem
    }


def get_article_element(html):
    """
    Returns an article candidate if there is a definitive article.
    """
    articles = [art for art in [score_node(art, True) for art in tags(html, 'article')] if art['content_score'] > 0]
    if len(articles) == 1:
        return articles[0]
    else:
        return None


def describe(node, depth=1):
    if not hasattr(node, 'tag'):
        return "[%s]" % type(node)
    name = node.tag
    if node.get('id', ''):
        name += '#' + node.get('id')
    if node.get('class', ''):
        name += '.' + node.get('class').replace(' ', '.')
    if name[:4] in ['div#', 'div.']:
        name = name[3:]
    if depth and node.getparent() is not None:
        return name + ' - ' + describe(node.getparent(), depth - 1)
    return name


def score_paragraphs(html, min_len=25):
    """
    Scores each paragraph in the document except for those that are less than min length.

    :returns: a dict of candidate element to a dict containing 'content_score' and 'elem' keys.
    """
    # minimum length to be considered as a valid paragraph (in number of characters)
    candidates = {}  # dict mapping the candidate node to its score
    ordered = []
    for elem in tags(html, "p", "pre", "td"):
        parent_node = elem.getparent()
        if parent_node is None:
            continue
        grand_parent_node = parent_node.getparent()

        inner_text = clean(elem.text_content() or "")
        inner_text_len = len(inner_text)

        # If this paragraph is less than 25 characters
        # don't even count it.
        if inner_text_len < min_len:
            continue

        if parent_node not in candidates:
            candidates[parent_node] = score_node(parent_node)
            ordered.append(parent_node)

        if grand_parent_node is not None and grand_parent_node not in candidates:
            candidates[grand_parent_node] = score_node(grand_parent_node)
            ordered.append(grand_parent_node)

        content_score = 1
        content_score += len(inner_text.split(','))
        content_score += min((inner_text_len / 100), 3)
        #if elem not in candidates:
        #    candidates[elem] = self.score_node(elem)

        #WTF? candidates[elem]['content_score'] += content_score
        candidates[parent_node]['content_score'] += content_score
        if grand_parent_node is not None:
            candidates[grand_parent_node]['content_score'] += content_score / 2.0

    # Scale the final candidates score based on link density. Good content
    # should have a relatively small link density (5% or less) and be
    # mostly unaffected by this operation.
    for elem in ordered:
        candidate = candidates[elem]
        ld = get_link_density(elem)
        score = candidate['content_score']
        logging.debug("Candid: %6.3f %s link density %.3f -> %6.3f" % (
            score,
            describe(elem),
            ld,
            score * (1 - ld)))
        candidate['content_score'] *= (1 - ld)

    return candidates


def remove_unlikely_candidates(html):
    """
    Removes parts of the document that are unlikely to be part of the article.

    :param html: the html lxml document element
    """
    for elem in html.iter():
        s = "%s %s" % (elem.get('class', ''), elem.get('id', ''))
        if len(s) < 2:
            continue
        if REGEXES['unlikelyCandidatesRe'].search(s) and (not REGEXES['okMaybeItsACandidateRe'].search(s)) and elem.tag not in ['html', 'body']:
            logging.debug("Removing unlikely candidate - %s" % describe(elem))
            elem.drop_tree()
    return html


def transform_misused_divs_into_paragraphs(html):
    """
    Transform <div>s that do not contain other block elements into <p>'s.

    :param html: the lxml document element
    """
    for elem in tags(html, 'div'):
        #FIXME: The current implementation ignores all descendants that
        # are not direct children of elem
        # This results in incorrect results in case there is an <img>
        # buried within an <a> for example
        if not REGEXES['divToPElementsRe'].search(
                unicode(''.join(map(tostring, list(elem))))):
            #self.debug("Altering %s to p" % (describe(elem)))
            elem.tag = "p"
            #print "Fixed element "+describe(elem)

    for elem in tags(html, 'div'):
        if elem.text and elem.text.strip():
            p = fragment_fromstring('<p/>')
            p.text = elem.text
            elem.text = None
            elem.insert(0, p)
            #print "Appended "+tounicode(p)+" to "+describe(elem)

        for pos, child in reversed(list(enumerate(elem))):
            if child.tail and child.tail.strip():
                p = fragment_fromstring('<p/>')
                p.text = child.tail
                child.tail = None
                elem.insert(pos + 1, p)
                #print "Inserted "+tounicode(p)+" to "+describe(elem)
            if child.tag == 'br':
                #print 'Dropped <br> at '+describe(elem)
                child.drop_tree()
    return html


def text_length(i):
    return len(clean(i.text_content() or ""))


def get_link_density(elem):
    link_length = 0
    for i in elem.findall(".//a"):
        link_length += text_length(i)
    #if len(elem.findall(".//div") or elem.findall(".//p")):
    #    link_length = link_length
    total_length = text_length(elem)
    return float(link_length) / max(total_length, 1)


def get_article(candidates, best_candidate):
    # Now that we have the top candidate, look through its siblings for
    # content that might also be related.
    # Things like preambles, content split by ads that we removed, etc.
    sibling_score_threshold = max([10, best_candidate['content_score'] * 0.2])
    # create a new html document with a html->body->div
    output = fragment_fromstring('<div/>')
    best_elem = best_candidate['elem']
    for sibling in best_elem.getparent().getchildren():
        # in lxml there no concept of simple text
        # if isinstance(sibling, NavigableString): continue
        append = False
        if sibling is best_elem:
            append = True
        sibling_key = sibling  # HashableElement(sibling)
        if sibling_key in candidates and candidates[sibling_key]['content_score'] >= sibling_score_threshold:
            append = True

        if sibling.tag == "p":
            link_density = get_link_density(sibling)
            node_content = sibling.text or ""
            node_length = len(node_content)

            if node_length > 80 and link_density < 0.25:
                append = True
            elif node_length <= 80 and link_density == 0 and re.search('\.( |$)', node_content):
                append = True

        if append:
            # We don't want to append directly to output, but the div
            # in html->body->div
            output.append(sibling)
    #if output is not None:
    #    output.append(best_elem)
    return output


def sanitize(node, candidates, min_len=25):
    for header in tags(node, "h1", "h2", "h3", "h4", "h5", "h6"):
        if class_weight(header) < 0 or get_link_density(header) > 0.33:
            header.drop_tree()

    for elem in tags(node, "form", "iframe", "textarea"):
        elem.drop_tree()
    allowed = {}
    # Conditionally clean <table>s, <ul>s, and <div>s
    for el in reverse_tags(node, "table", "ul", "div"):
        if el in allowed:
            continue
        weight = class_weight(el)
        if el in candidates:
            content_score = candidates[el]['content_score']
            #print '!',el, '-> %6.3f' % content_score
        else:
            content_score = 0
        tag = el.tag

        if weight + content_score < 0:
            logging.debug("Cleaned %s with score %6.3f and weight %-3s" % (describe(el), content_score, weight, ))
            el.drop_tree()
        elif el.text_content().count(",") < 10:
            counts = {}
            for kind in ['p', 'img', 'li', 'a', 'embed', 'input']:
                counts[kind] = len(el.findall('.//%s' % kind))
            counts["li"] -= 100

            # Count the text length excluding any surrounding whitespace
            content_length = text_length(el)
            link_density = get_link_density(el)
            parent_node = el.getparent()
            if parent_node is not None:
                if parent_node in candidates:
                    content_score = candidates[parent_node]['content_score']
                else:
                    content_score = 0
            #if parent_node is not None:
                #pweight = class_weight(parent_node) + content_score
                #pname = describe(parent_node)
            #else:
                #pweight = 0
                #pname = "no parent"
            to_remove = False
            reason = ""

            #if el.tag == 'div' and counts["img"] >= 1:
            #    continue
            if counts["p"] and counts["img"] > counts["p"]:
                reason = "too many images (%s)" % counts["img"]
                to_remove = True
            elif counts["li"] > counts["p"] and tag != "ul" and tag != "ol":
                reason = "more <li>s than <p>s"
                to_remove = True
            elif counts["input"] > (counts["p"] / 3):
                reason = "less than 3x <p>s than <input>s"
                to_remove = True
            elif content_length < min_len and (counts["img"] == 0 or counts["img"] > 2):
                reason = "too short content length %s without a single image" % content_length
                to_remove = True
            elif weight < 25 and link_density > 0.2:
                    reason = "too many links %.3f for its weight %s" % (
                        link_density, weight)
                    to_remove = True
            elif weight >= 25 and link_density > 0.5:
                reason = "too many links %.3f for its weight %s" % (
                    link_density, weight)
                to_remove = True
            elif (counts["embed"] == 1 and content_length < 75) or counts["embed"] > 1:
                reason = "<embed>s with too short content length, or too many <embed>s"
                to_remove = True
#                if el.tag == 'div' and counts['img'] >= 1 and to_remove:
#                    imgs = el.findall('.//img')
#                    valid_img = False
#                    logging.debug(tounicode(el))
#                    for img in imgs:
#
#                        height = img.get('height')
#                        text_length = img.get('text_length')
#                        debug ("height %s text_length %s" %(repr(height), repr(text_length)))
#                        if to_int(height) >= 100 or to_int(text_length) >= 100:
#                            valid_img = True
#                            logging.debug("valid image" + tounicode(img))
#                            break
#                    if valid_img:
#                        to_remove = False
#                        logging.debug("Allowing %s" %el.text_content())
#                        for desnode in tags(el, "table", "ul", "div"):
#                            allowed[desnode] = True

                #find x non empty preceding and succeeding siblings
                i, j = 0, 0
                x = 1
                siblings = []
                for sib in el.itersiblings():
                    #logging.debug(sib.text_content())
                    sib_content_length = text_length(sib)
                    if sib_content_length:
                        i =+ 1
                        siblings.append(sib_content_length)
                        if i == x:
                            break
                for sib in el.itersiblings(preceding=True):
                    #logging.debug(sib.text_content())
                    sib_content_length = text_length(sib)
                    if sib_content_length:
                        j =+ 1
                        siblings.append(sib_content_length)
                        if j == x:
                            break
                #logging.debug(str(siblings))
                if siblings and sum(siblings) > 1000:
                    to_remove = False
                    logging.debug("Allowing %s" % describe(el))
                    for desnode in tags(el, "table", "ul", "div"):
                        allowed[desnode] = True

            if to_remove:
                logging.debug("Cleaned %6.3f %s with weight %s cause it has %s." % (content_score, describe(el), weight, reason))
                #print tounicode(el)
                #logging.debug("pname %s pweight %.3f" %(pname, pweight))
                el.drop_tree()

    # TODO: there was some code here to remove specific attributes from nodes

    return node


def remove_boilerplate(article, page_count):
    """
    Removes any content that shows up as many times as there are pages (e.g. boilerplate).

    :param article: lxml element
    :param page_count: number of pages
    """
    if page_count <= 1:
        return

    # get the text size of each element
    els = {}
    for el in tags(article, 'div', 'header', 'section'):
        els[el] = len(el.text_content())

    # now look at pairs that are exactly the same length, if they are the same text exactly and appear
    # page_count number of times, then they should be removed
    to_remove = []
    for el in els:
        if el in to_remove:
            continue
        length = els[el]
        identicals = [el]
        for e, l in els.iteritems():
            if e != el and l == length and e.text_content() == el.text_content():
                identicals.append(e)
        # if there was one of these identical items per page, then we should probably
        # remove it
        if len(identicals) == page_count:
            to_remove.extend(identicals)

    logging.info('removing %d elements from the document' % len(to_remove))

    for el in to_remove:
        try:
            el.drop_tree()
        except StandardError:
            # TODO: need to not try to remove things that are in a tree that has already been removed
            logging.exception('could not remove this node')


def is_possible_paging_url(baseurl, candidateurl):
    """
    Returns true if the candidate url could plausibly be a next page url.

    For example, if it's not for the same domain then it's probably not a valid paging url.

    :param baseurl: current page's url
    :param candidateurl: the url being evaluated for next-pagey-ness
    :returns: boolean
    """
    if candidateurl is None:
        return False
    base = urlparse(baseurl)
    candidate = urlparse(candidateurl)
    # for now insist that protocol and domain are the same
    return base[0] == candidate[0] and base[1] == candidate[1]