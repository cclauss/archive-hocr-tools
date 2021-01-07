import xml.parsers.expat

from .util import open_if_required
from .parse import hocr_page_to_word_data, hocr_page_to_word_data_fast, \
        hocr_page_iterator, hocr_page_get_dimensions

MIN_WORD_CONF = 75


def hocr_page_text(page):
    """
    Extract text from a hOCR XML page element.

    Args:

    * page: hOCR XML page element

    Returns: page contents (`str`)
    """
    text = ''
    word_data = hocr_page_to_word_data(page)

    for paragraph in word_data:
        block_data = False
        for line in paragraph['lines']:
            line_words = ''
            for word in line['words']:
                if word['confidence'] < MIN_WORD_CONF:
                    continue
                line_words += word['text'] + ' '
                block_data = True

            # Encode
            line_words = line_words.strip().encode('utf-8')

            # Write out
            if line_words:
                text += ' '+line_words.decode('utf-8')

        if block_data:
            text += '\n'	

    return text


def hocr_paragraphs(hocr_iter):
    """
    Takes a hocr page iterator (from hocr.parse.hocr_page_iterator) and emits
    paragraphs from the page exactly as they are found in the FTS document. This
    requires parsing and interpreting the text up front, potentially merging
    paragraphs into a single one.

    Function also returns the reconstructed hocr text that should match the FTS
    paragraph text.

    Function also keeps track of the page number, width and heights for usage
    later on in the code.

    Args:

    * hocr_iter: iterator as returned by hocr_page_iterator
    """
    text = ''
    ps = []

    page_no = 0
    for hocr_page in hocr_iter:
        page_width, page_height = hocr_page_get_dimensions(hocr_page)

        #paragraphs = hocr_page_to_word_data(hocr_page)  # XXX
        paragraphs = hocr_page_to_word_data_fast(hocr_page)
        for paragraph in paragraphs:
            ptext, ok = hocr_paragraph_text(paragraph)
            if not ok:
                text += ptext
                ps.append(paragraph)
                continue

            if len(ps):
                # Create unified paragraph data from multiple hocr paragraphs
                ps.append(paragraph)
                new_paragraph = {}
                new_paragraph['lines'] = []
                for p in ps:
                    new_paragraph['lines'].extend(p['lines'])

                paragraph = new_paragraph

            yield (paragraph, ptext, page_no, page_width, page_height)
            text = ''
            ps = []

        page_no += 1


def hocr_paragraph_text(paragraph):
    """
    Reconstruct text that matches the FTS text from a hOCR paragraph.
    Returns a tuple, first item in the tuple is the text, the second is a
    boolean, indicating if this paragraph is to be merged into the next one, see
    hocr_paragraphs for more information.

    Args:

    * paragraph: hOCR paragraph as returned by hocr_paragraphs

    Returns:

    * Tuple of (`str`, `bool`), where the `str` is the paragraph data, and the
      boolean if this text continues is to be merged with the next paragraph.
    """
    data = ''
    block_data = False
    for line in paragraph['lines']:
        line_words = ''
        for word in line['words']:
            if word['confidence'] < MIN_WORD_CONF:
                continue
            line_words += word['text'] + ' '
            block_data = True

        data += line_words

    return data, block_data


def get_hocr_words(paragraph):
    """
    Find all the words in a hOCR paragraph.

    Args:

    * hOCR paragraph as returned by hocr_paragraphs.

    Returns a `list` of hocr words in a hocr paragraph.
    For this to be usable for matching purposes, only run this on merged hocr
    paragraphs as returned by hocr_paragraphs.
    """
    words = []
    for line in paragraph['lines']:
        for word in line['words']:
            if word['confidence'] < MIN_WORD_CONF:
                continue
            words.append(word)

    return words


# Finds bytes where pages start, and the final body segment to denote the end of
# the last page.
class PageFinder:
    def __init__(self, current_parser):
        self.parser = current_parser
        self.parser.StartElementHandler = self.start_element
        self.parser.EndElementHandler = self.end_element

        self.page_bytes = []

    def start_element(self, name, attrs):
        if name == 'div' and 'class' in attrs and attrs['class'] == 'ocr_page':
            self.page_bytes.append(self.parser.CurrentByteIndex)

    def end_element(self, name):
        if name == 'body':
            self.page_bytes.append(self.parser.CurrentByteIndex)


def hocr_get_xml_page_offsets(fd_or_path):
    """
    Builds a list of start and end bytes for each ocr_page element in the XML
    file.  This can be used to construct a "lookup" table, together with
    hocr_get_plaintext_page_offsets.

    Args:

    * fd_or_path: hOCR file to operate on, or a path (str).

    Return a list of tuples (start_byte, end_byte) for each ocr_page element in
    a hOCR file. The start and ends bytes point to the position of the page
    element in the XML file.
    """
    xml_file = open_if_required(fd_or_path)
    xml_file.seek(0)

    p = xml.parsers.expat.ParserCreate()
    h = PageFinder(p)
    p.ParseFile(xml_file)

    page_boundaries = list(zip(h.page_bytes[:-1], h.page_bytes[1:]))

    return page_boundaries


def hocr_get_plaintext_page_offsets(fd_or_path):
    """
    Builds a list of start and end bytes for each ocr_page in the plain text
    file. That is, if the plain text were generated from a hOCR XML file, which
    plaintext is part of which ocr_page element, and where does that text start
    and end. This can be used to construct a "lookup" table, together with
    hocr_get_xml_page_offsets.

    Args:

    * fd_or_path: hOCR file to operate on, or a path (str).

    Return a list of tuples (start_byte, end_byte) for each ocr_page element in
    a hOCR file. The start and ends bytes point to the position of the text as
    extracted from the page in the XML file.
    """
    page_it = hocr_page_iterator(fd_or_path)

    page_bytes = []
    cursor = 0

    page_bytes.append(0)

    for page in page_it:
        page_text = hocr_page_text(page)
        cursor += len(page_text)
        page_bytes.append(cursor)

    page_bytes = list(zip(page_bytes[:-1], page_bytes[1:]))

    return page_bytes