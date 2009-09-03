# -*- coding: utf-8 -*-
from librarian import ValidationError, NoDublinCore,  ParseError
from librarian import RDFNS, DCNS
from librarian import dcparser

from xml.parsers.expat import ExpatError
from lxml import etree
from lxml.etree import XMLSyntaxError, XSLTApplyError

import re
from StringIO import StringIO

class WLDocument(object):
    LINE_SWAP_EXPR = re.compile(r'/\s', re.MULTILINE | re.UNICODE);

    def __init__(self, edoc, parse_dublincore=True):
        self.edoc = edoc

        root_elem = edoc.getroot()
       
        dc_path = './/' + RDFNS('RDF')
        
        if root_elem.tag != 'utwor':
            raise ValidationError("Invalid root element. Found '%s', should be 'utwor'" % root_elem.tag)

        if parse_dublincore:
            self.rdf_elem = root_elem.find(dc_path)

            if self.rdf_elem is None:
                raise NoDublinCore('Document has no DublinCore - which is required.')
            
            self.book_info = dcparser.BookInfo.from_element(self.rdf_elem)
        else:
            self.book_info = None
    
    @classmethod
    def from_string(cls, xml, swap_endlines=False, parse_dublincore=True):
        return cls.from_file(StringIO(xml), swap_endlines, parse_dublincore=parse_dublincore)

    @classmethod
    def from_file(cls, xmlfile, swap_endlines=False, parse_dublincore=True):

        # first, prepare for parsing
        if isinstance(xmlfile, basestring):
            file = open(xmlfile, 'rb')
            try:
                data = file.read()
            finally:
                file.close()
        else:
            data = xmlfile.read()

        if not isinstance(data, unicode):
            data = data.decode('utf-8')

        if swap_endlines:
            data = cls.LINE_SWAP_EXPR.sub(u'<br />\n', data)
    
        try:
            parser = etree.XMLParser(remove_blank_text=True)
            return cls(etree.parse(StringIO(data), parser), parse_dublincore=parse_dublincore)
        except (ExpatError, XMLSyntaxError, XSLTApplyError), e:
            raise ParseError(e)                  

    def part_as_text(self, path):
        # convert the path to XPath        
        print "[L] Retrieving part:", path

        elems = self.edoc.xpath(self.path_to_xpath(path))
        print "[L] xpath", elems
        
        if len(elems) == 0:
            return None        

        return etree.tostring(elems[0], encoding=unicode, pretty_print=True)


    def path_to_xpath(self, path):
        parts = []

        for part in path.split('/'):
            match = re.match(r'([^\[]+)\[(\d+)\]', part)
            if not match:
                parts.append(part)
            else:
                tag, n = match.groups()
                parts.append("node()[position() = %d and name() = '%s']" % (int(n), tag) )

        if parts[0] == '.':
            parts[0] = ''

        return '/'.join(parts)

    def transform(self, stylesheet, **options):
        return self.edoc.xslt(stylesheet, **options)

    def update_dc(self):
        parent = self.rdf_elem.getparent()
        parent.replace( self.rdf_elem, self.book_info.to_etree(parent) )

    def serialize(self):
        self.update_dc()
        return etree.tostring(self.edoc, encoding=unicode, pretty_print=True)

    def merge_chunks(self, chunk_dict):
        unmerged = []

        for key, data in chunk_dict.iteritems():
            try:
                xpath = self.path_to_xpath(key)
                node = self.edoc.xpath(xpath)[0]                
                repl = etree.fromstring(data)
                node.getparent().replace(node, repl);
            except Exception, e:
                unmerged.append( repr( (key, xpath, e) ) )

        return unmerged