#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""scholarly.py"""

from __future__ import absolute_import, division, print_function, unicode_literals

from bs4 import BeautifulSoup

import arrow
import bibtexparser
import codecs
import hashlib
import pprint
import random
import re
import requests
import sys
import time
import collections

PYTHON2 = sys.version[0] == 2
if PYTHON2:
    text_type = unicode
    input = raw_input
    string_types = (str, unicode)
else:
    text_type = str
    string_types = (str,)

_GOOGLEID = hashlib.md5(text_type(random.random()).encode('utf-8')).hexdigest()[:16]
_COOKIES = {'GSP': 'ID={0}:CF=4'.format(_GOOGLEID)}

USER_AGENTS = [
    'Mozilla/5.0 (Windows; U; Windows NT 5.1; it; rv:1.8.1.11) Gecko/20071127 Firefox/2.0.0.11',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Ubuntu Chromium/41.0.2272.76 Chrome/41.0.2272.76 Safari/537.36',
]

_HEADERS = {
    'accept-language': 'en-US,en',
    'User-Agent': USER_AGENTS[1],
    'accept': 'text/html,application/xhtml+xml,application/xml'
}

_HOST = 'https://scholar.google.com'
_AUTHSEARCH = '/citations?view_op=search_authors&hl=en&mauthors={0}'
_CITATIONAUTH = '/citations?user={0}&hl=en'
_CITATIONPUB = '/citations?view_op=view_citation&citation_for_view={0}'
_KEYWORDSEARCH = '/citations?view_op=search_authors&hl=en&mauthors=label:{0}'
_PUBSEARCH = '/scholar?q={0}'
_SCHOLARPUB = '/scholar?oi=bibs&hl=en&cites={0}'
_ADVANCED_SEARCH = '/scholar?{0}'

_CITATIONAUTHRE = r'user=([\w-]*)'
_CITATIONPUBRE = r'citation_for_view=([\w-]*:[\w-]*)'
_SCHOLARCITERE = r'gs_ocit\(event,\'([\w-]*)\''
_SCHOLARPUBRE = r'cites=([\w-]*)'

_SESSION = requests.Session()
_PAGESIZE = 100

VERBOSE = False


def _handle_captcha(url):
    # TODO: PROBLEMS HERE! NEEDS ATTENTION
    # Get the captcha image
    raise NotImplementedError('Needs attention')
    g_id = None
    captcha_url = _HOST + '/sorry/image?id={0}'.format(g_id)
    captcha = _SESSION.get(captcha_url, headers=_HEADERS)
    # Upload to remote host and display to user for human verification
    img_upload = requests.post('http://postimage.org/',
                               files={'upload[]': ('scholarly_captcha.jpg',
                                                   captcha.text)})
    print(img_upload.text)
    img_url_soup = BeautifulSoup(img_upload.text, 'html.parser')
    img_url = img_url_soup.find_all(alt='scholarly_captcha')[0].get('src')
    print('CAPTCHA image URL: {0}'.format(img_url))
    # Need to check Python version for input
    g_response = input('Enter CAPTCHA: ')
    # Once we get a response, follow through and load the new page.
    url_response = _HOST + '/sorry/CaptchaRedirect?continue={0}&id={1}&captcha={2}&submit=Submit'.format(url, g_id, g_response)
    resp_captcha = _SESSION.get(url_response, headers=_HEADERS, cookies=_COOKIES)
    print('Forwarded to {0}'.format(resp_captcha.url))
    return resp_captcha.url


def _get_page(pagerequest):
    """Return the data for a page on scholar.google.com"""
    # Note that we include a sleep to avoid overloading the scholar server
    if VERBOSE:
        print('Making request: %s' % (pagerequest,))
    time.sleep(5 + random.uniform(0, 5))
    if PYTHON2:
        resp = _SESSION.get(pagerequest, headers=_HEADERS, cookies=_COOKIES, verify=False)
    else:
        resp = _SESSION.get(pagerequest, headers=_HEADERS, cookies=_COOKIES)
    if 'Please show you' in resp.text and 'not a robot' in resp.text and 'gs_captcha_c' in resp.text:
        raise Exception('Need to handle captcha')
    if resp.status_code == 200:
        return resp.text
    if resp.status_code == 503:
        # Inelegant way of dealing with the G captcha
        raise Exception('Error: {0} {1}'.format(resp.status_code, resp.reason))
        # TODO: Need to fix captcha handling
        # dest_url = requests.utils.quote(_SCHOLARHOST+pagerequest)
        # soup = BeautifulSoup(resp.text, 'html.parser')
        # captcha_url = soup.find('img').get('src')
        # resp = _handle_captcha(captcha_url)
        # return _get_page(re.findall(r'https:\/\/(?:.*?)(\/.*)', resp)[0])
    else:
        raise Exception('Error: {0} {1}'.format(resp.status_code, resp.reason))


def _get_soup(pagerequest):
    """Return the BeautifulSoup for a page on scholar.google.com"""
    html = _get_page(pagerequest)
    return BeautifulSoup(html, 'html.parser')


def _search_scholar_soup(soup):
    """Generator that returns Publication objects from the search page"""
    while True:
        for row in soup.find_all('div', 'gs_r'):
            yield Publication(row, 'scholar')
        if soup.find(class_='gs_ico gs_ico_nav_next'):
            url = soup.find(class_='gs_ico gs_ico_nav_next').parent['href']
            soup = _get_soup(_HOST + url)
        else:
            break


def _search_citation_soup(soup):
    """Generator that returns Author objects from the author search page"""
    while True:
        for row in soup.find_all('div', 'gsc_1usr'):
            yield Author(row)
        nextbutton = soup.find(class_='gs_btnPR gs_in_ib gs_btn_half gs_btn_srt')
        if nextbutton and 'disabled' not in nextbutton.attrs:
            url = nextbutton['onclick'][17:-1]
            url = codecs.getdecoder("unicode_escape")(url)[0]
            soup = _get_soup(_HOST + url)
        else:
            break


class Publication(object):
    """Returns an object for a single publication"""
    def __init__(self, __data, pubtype=None):
        self.bib = dict()
        self.source = pubtype
        if self.source == 'citations':
            self.bib['title'] = __data.find('a', class_='gsc_a_at').text
            self.id_citations = re.findall(_CITATIONPUBRE, __data.find('a', class_='gsc_a_at')['href'])[0]
            citedby = __data.find(class_='gsc_a_ac')
            if citedby and not citedby.text.isspace():
                self.citedby = int(citedby.text)
            year = __data.find(class_='gsc_a_h')
            if year and year.text and not year.text.isspace() and len(year.text) > 0:
                self.bib['year'] = int(year.text)
        elif self.source == 'scholar':
            databox = __data.find('div', class_='gs_ri')
            title = databox.find('h3', class_='gs_rt')
            if title.find('span', class_='gs_ctu'):  # A citation
                title.span.extract()
            elif title.find('span', class_='gs_ctc'):  # A book or PDF
                title.span.extract()
            self.bib['title'] = title.text.strip()
            if title.find('a'):
                self.bib['url'] = title.find('a')['href']
            authorinfo = databox.find('div', class_='gs_a')
            self.bib['author'] = ' and '.join([i.strip() for i in authorinfo.text.split(' - ')[0].split(',')])
            if databox.find('div', class_='gs_rs'):
                self.bib['abstract'] = databox.find('div', class_='gs_rs').text
                if self.bib['abstract'][0:8].lower() == 'abstract':
                    self.bib['abstract'] = self.bib['abstract'][9:].strip()
            lowerlinks = databox.find('div', class_='gs_fl').find_all('a')
            for link in lowerlinks:
                if 'Import into BibTeX' in link.text:
                    self.url_scholarbib = link['href']
                if 'Cited by' in link.text:
                    self.citedby = int(re.findall(r'\d+', link.text)[0])
                    self.id_scholarcitedby = re.findall(_SCHOLARPUBRE, link['href'])[0]
            if __data.find('div', class_='gs_ggs gs_fl'):
                self.bib['eprint'] = _HOST + __data.find('div', class_='gs_ggs gs_fl').a['href']
        self._filled = False

    def fill(self):
        """Populate the Publication with information from its profile"""
        if self.source == 'citations':
            url = _CITATIONPUB.format(self.id_citations)
            soup = _get_soup(_HOST + url)
            self.bib['title'] = soup.find('div', id='gsc_title').text
            if soup.find('a', class_='gsc_title_link'):
                self.bib['url'] = soup.find('a', class_='gsc_title_link')['href']
            for item in soup.find_all('div', class_='gs_scl'):
                key = item.find(class_='gsc_field').text
                val = item.find(class_='gsc_value')
                if key == 'Authors':
                    self.bib['author'] = ' and '.join([i.strip() for i in val.text.split(',')])
                elif key == 'Journal':
                    self.bib['journal'] = val.text
                elif key == 'Volume':
                    self.bib['volume'] = val.text
                elif key == 'Issue':
                    self.bib['number'] = val.text
                elif key == 'Pages':
                    self.bib['pages'] = val.text
                elif key == 'Publisher':
                    self.bib['publisher'] = val.text
                elif key == 'Publication date':
                    self.bib['year'] = arrow.get(val.text).year
                elif key == 'Description':
                    if val.text[0:8].lower() == 'abstract':
                        val = val.text[9:].strip()
                    self.bib['abstract'] = val
                elif key == 'Total citations':
                    self.id_scholarcitedby = re.findall(_SCHOLARPUBRE, val.a['href'])[0]
            if soup.find('div', class_='gsc_title_ggi'):
                self.bib['eprint'] = _HOST + soup.find('div', class_='gsc_title_ggi').a['href']
            self._filled = True
        elif self.source == 'scholar':
            bibtex = _get_page(self.url_scholarbib)
            self.bib.update(bibtexparser.loads(bibtex).entries[0])
            self._filled = True
        return self

    def get_citedby(self):
        """Searches GScholar for other articles that cite this Publication and
        returns a Publication generator.
        """
        if not hasattr(self, 'id_scholarcitedby'):
            self.fill()
        if hasattr(self, 'id_scholarcitedby'):
            url = _SCHOLARPUB.format(requests.utils.quote(self.id_scholarcitedby))
            soup = _get_soup(_HOST + url)
            return _search_scholar_soup(soup)
        else:
            return []

    def __str__(self):
        return pprint.pformat(self.__dict__)


class Author(object):
    """Returns an object for a single author"""
    def __init__(self, __data):
        if isinstance(__data, string_types):
            self.id = __data
        else:
            self.id = re.findall(_CITATIONAUTHRE, __data('a')[0]['href'])[0]
            self.url_picture = __data('img')[0]['src']
            self.name = __data.find('h3', class_='gsc_1usr_name').text
            affiliation = __data.find('div', class_='gsc_1usr_aff')
            if affiliation:
                self.affiliation = affiliation.text
            email = __data.find('div', class_='gsc_1usr_emlb')
            if email:
                self.email = email.text
            self.interests = [i.text.strip() for i in
                              __data.find_all('a', class_='gsc_co_int')]
            citedby = __data.find('div', class_='gsc_1usr_cby')
            if citedby:
                self.citedby = int(citedby.text[9:])
        self._filled = False

    def fill(self):
        """Populate the Author with information from their profile"""
        url_citations = _CITATIONAUTH.format(self.id)
        url = '{0}&pagesize={1}'.format(url_citations, _PAGESIZE)
        soup = _get_soup(_HOST + url)
        self.name = soup.find('div', id='gsc_prf_in').text
        self.affiliation = soup.find('div', class_='gsc_prf_il').text
        self.interests = [i.text.strip() for i in soup.find_all('a', class_='gsc_prf_ila')]
        self.url_picture = soup.find('img')['src']

        # h-index, i10-index and h-index, i10-index in the last 5 years
        index = soup.find_all('td', class_='gsc_rsb_std')
        self.hindex = int(index[2].text)
        self.hindex5y = int(index[3].text)
        self.i10index = int(index[4].text)
        self.i10index5y = int(index[5].text)

        self.publications = list()
        pubstart = 0
        while True:
            for row in soup.find_all('tr', class_='gsc_a_tr'):
                new_pub = Publication(row, 'citations')
                self.publications.append(new_pub)
            if 'disabled' not in soup.find('button', id='gsc_bpf_next').attrs:
                pubstart += _PAGESIZE
                url = '{0}&cstart={1}&pagesize={2}'.format(url_citations, pubstart, _PAGESIZE)
                soup = _get_soup(_HOST + url)
            else:
                break
        self._filled = True
        return self

    def __str__(self):
        return pprint.pformat(self.__dict__)


def search_pubs_query(query):
    """Search by scholar query and return a generator of Publication objects"""
    url = _PUBSEARCH.format(requests.utils.quote(query))
    soup = _get_soup(_HOST + url)
    return _search_scholar_soup(soup)


def search_author(name):
    """Search by author name and return a generator of Author objects"""
    url = _AUTHSEARCH.format(requests.utils.quote(name))
    soup = _get_soup(_HOST + url)
    return _search_citation_soup(soup)


def search_keyword(keyword):
    """Search by keyword and return a generator of Author objects"""
    url = _KEYWORDSEARCH.format(requests.utils.quote(keyword))
    soup = _get_soup(_HOST + url)
    return _search_citation_soup(soup)


def search_pubs_custom_url(url):
    """Search by custom URL and return a generator of Publication objects
    URL should be of the form '/scholar?q=...'"""
    soup = _get_soup(_HOST + url)
    return _search_scholar_soup(soup)


def search_author_custom_url(url):
    """Search by custom URL and return a generator of Publication objects
    URL should be of the form '/citation?q=...'"""
    soup = _get_soup(_HOST + url)
    return _search_citation_soup(soup)


class _ScholarSoupIter(object):
    """
    Generator that returns Publication objects from the search page.
    Contains information about current progress
    """
    def __init__(soup_iter, pagerequest):
        soup_iter.pagerequest = pagerequest
        soup_iter.history = [pagerequest]
        soup_iter.soup = _get_soup(pagerequest)

    def page_progress(soup_iter):
        import parse
        fmt1 = 'About {total} results ({time})'
        fmt2 = 'Page {index} of about {total} results ({time})'
        prog_text = soup_iter.soup.find('div', id='gs_ab_md').text
        parse_result = parse.parse(fmt1, prog_text)
        if parse_result is None:
            parse_result = parse.parse(fmt2, prog_text)
        try:
            index = int(parse_result['index']) - 1
        except KeyError:
            index = 0
        total = int(parse_result['total'])
        return index, total

    def goto_next_page(soup_iter):
        if soup_iter.soup.find(class_='gs_ico gs_ico_nav_next'):
            url = soup_iter.soup.find(class_='gs_ico gs_ico_nav_next').parent['href']
            soup_iter.pagerequest = _HOST + url
            soup_iter.history.append(soup_iter.pagerequest)
            # pagerequest = soup_iter.pagerequest
            # html = _get_page(pagerequest)
            # soup = BeautifulSoup(html, 'html.parser')
            soup_iter.soup = _get_soup(soup_iter.pagerequest)
        else:
            raise StopIteration('no more pages')

    def page_publications(soup_iter):
        """
        Yields all publications on the current page
        """
        for row in soup_iter.soup.find_all('div', 'gs_r'):
            yield Publication(row, 'scholar')

    def iter_pubs(soup_iter, max_pages=None, verbose=True):
        """
        Yields publications until the number of pages visited is `max_pages`.
        """
        import itertools as it
        for index in it.count(0):
            if verbose:
                print('Parsing page %r/%r' % soup_iter.page_progress())
            for pub in soup_iter.page_publications():
                yield pub
            if max_pages is not None and index >= max_pages:
                raise StopIteration()
            soup_iter.goto_next_page()

    def __iter__(soup_iter):
        for pub in soup_iter.iter_pubs():
            yield pub


class AdvancedSearch(object):
    """
    Searches for publications using advanced search options.
    See `AdvancedSearch.formkw_defaults` for the accepted keyword arguments.

    Example Advanced Search Form:
        with all of the words: one two three
        with the exact phrase: four tell me that
        with at least one of the words: you love me
        without the words: more five

        where my words occur: [X] anywhere in the article
                              [ ] in the title of the article

        Return articles authored by: six seven eight
        Return articles published in: who are we
        Return articles dated between: 1900 — 2099

    Results in:
        https://scholar.google.com/scholar?
        as_q=one+two+three&
        as_epq=four+tell+me+that&
        as_oq=you+love+me+&
        as_eq=more+five+&
        as_occt=any&
        as_sauthors=six+seven+eight&
        as_publication=who+are+we+&
        as_ylo=1900&
        as_yhi=2099&
        btnG=&
        hl=en&
        as_sdt=0%2C33

    Example:
        >>> # DISABLE_DOCTEST
        >>> from scholarly import *  # NOQA
        >>> self = AdvancedSearch(published_in='nature methods', min_year=2016)
        >>> soup_iter = self.soup_iterator()
        >>> publications = []
        >>> publications += list(soup_iter.iter_pubs(max_pages=2, verbose=True))
    """
    formkw_defaults = {
        'with_all'          : '',
        'with_exact'        : '',
        'with_any'          : '',
        'without'           : '',
        'where_words_occur' : 'anywhere',
        'authored_by'       : '',
        'published_in'      : '',
        'min_year'          : '',
        'max_year'          : '',
        'include_pattents'  : True,
        'include_citations' : True,
        'sortby'            : 'relevance',
        'search_abstracts'  : False
    }

    _url_keys = collections.OrderedDict([
        ('with_all'          , 'as_q'),
        ('with_exact'        , 'as_epq'),
        ('with_any'          , 'as_oq'),
        ('without'           , 'as_eq'),
        ('where_words_occur' , 'as_occt'),
        ('authored_by'       , 'as_sauthors'),
        ('published_in'      , 'as_publication'),
        ('min_year'          , 'as_ylo'),
        ('max_year'          , 'as_yhi'),
        ('include_pattents'  , 'as_std'),
        ('include_citations' , 'as_vis'),
    ])

    def __init__(self, **kwargs):
        self.formkw = self.formkw_defaults.copy()
        self._url_vals = None
        unknown_keys = set(kwargs.keys()) - set(self.formkw.keys())
        if unknown_keys:
            raise ValueError('Unknown keys=%r. Valid keys are: %r' %
                             (unknown_keys, list(self.formkw.keys())))
        self.formkw.update(**kwargs)
        self._fix_formkw()
        self._check_formkw()

    def soup_iterator(self):
        url = self._make_url()
        pagerequest = _HOST + url
        soup_iter = _ScholarSoupIter(pagerequest)
        return soup_iter

    def execute(self):
        soup_iter = self.soup_iterator()
        return iter(soup_iter)

    def _check_formkw(self):
        _valid_values = {
            'sortby': ['relevance', 'date'],
            'where_words_occur': ['any', 'title', 'anywhere'],
        }
        for key, valid in _valid_values.items():
            value = self.formkw[key]
            if value not in valid:
                raise ValueError(
                    'Invalid item %r: %r. Valid values are %r' % (
                        key, value, valid))
        if self.formkw['search_abstracts'] and self.formkw['sortby'] != 'date':
            raise ValueError(
                'must have sortby="date" when search_abstracts=True')

    def _fix_formkw(self):
        if self.formkw['where_words_occur'] == 'anywhere':
            self.formkw['where_words_occur'] = 'any'
        self.formkw['include_pattents'] = '{0},33'.format(int(bool(self.formkw['include_pattents'])))
        self.formkw['include_citations'] = '{0}'.format(1 - int(bool(self.formkw['include_citations'])))
        for key in self.formkw.keys():
            if key in {'search_abstracts'}:
                continue

    def _make_url(self):
        self._url_vals = {key: '+'.join(str(self.formkw[key]).split(' '))
                          for key in self._url_keys.keys()}
        query_parts = ['{0}={1}'.format(self._url_keys[key], self._url_vals[key])
                       for key in self._url_vals.keys()]
        if self.formkw['sortby'] == 'date':
            if self.formkw['search_abstracts']:
                query_parts.apend('scisbd=2')
            else:
                query_parts.apend('scisbd=1')
        url = _ADVANCED_SEARCH.format('&'.join(query_parts))
        return url


if __name__ == "__main__":
    author = next(search_author('Steven A. Cholewiak')).fill()
    print(author)
