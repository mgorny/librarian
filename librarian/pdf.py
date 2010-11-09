# -*- coding: utf-8 -*-
#
# This file is part of Librarian, licensed under GNU Affero GPLv3 or later.
# Copyright © Fundacja Nowoczesna Polska. See NOTICE for more information.
#
from __future__ import with_statement
import os
import os.path
import shutil
from StringIO import StringIO
from tempfile import mkdtemp
import re
from copy import deepcopy
from subprocess import call, PIPE

import sys

from Texml.processor import process
from lxml import etree
from lxml.etree import XMLSyntaxError, XSLTApplyError

from librarian.parser import WLDocument
from librarian import ParseError
from librarian import functions



functions.reg_substitute_entities()
functions.reg_person_name()
functions.reg_strip()
functions.reg_starts_white()
functions.reg_ends_white()

STYLESHEETS = {
    'wl2tex': 'xslt/wl2tex.xslt',
}


def insert_tags(doc, split_re, tagname):
    """ inserts <tagname> for every occurence of `split_re' in text nodes in the `doc' tree 

    >>> t = etree.fromstring('<a><b>A-B-C</b>X-Y-Z</a>');
    >>> insert_tags(t, re.compile('-'), 'd');
    >>> print etree.tostring(t)
    <a><b>A<d/>B<d/>C</b>X<d/>Y<d/>Z</a>
    """

    for elem in doc.iter():
        try:
            if elem.text:
                chunks = split_re.split(elem.text)
                while len(chunks) > 1:
                    ins = etree.Element(tagname)
                    ins.tail = chunks.pop()
                    elem.insert(0, ins)
                elem.text = chunks.pop(0)
            if elem.tail:
                chunks = split_re.split(elem.tail)
                parent = elem.getparent()
                ins_index = parent.index(elem) + 1
                while len(chunks) > 1:
                    ins = etree.Element(tagname)
                    ins.tail = chunks.pop()
                    parent.insert(ins_index, ins)
                elem.tail = chunks.pop(0)
        except TypeError, e:
            # element with no children, like comment
            pass


def substitute_hyphens(doc):
    insert_tags(doc, 
                re.compile("(?<=[^-\s])-(?=[^-\s])"),
                "dywiz")


def fix_hanging(doc):
    insert_tags(doc, 
                re.compile("(?<=\s\w)\s+"),
                "nbsp")


def move_motifs_inside(doc):
    """ moves motifs to be into block elements """
    for master in doc.xpath('//powiesc|//opowiadanie|//liryka_l|//liryka_lp|//dramat_wierszowany_l|//dramat_wierszowany_lp|//dramat_wspolczesny'):
        for motif in master.xpath('motyw'):
            print motif.text
            for sib in motif.itersiblings():
                if sib.tag not in ('sekcja_swiatlo', 'sekcja_asterysk', 'separator_linia', 'begin', 'end', 'motyw', 'extra', 'uwaga'):
                    # motif shouldn't have a tail - it would be untagged text
                    motif.tail = None
                    motif.getparent().remove(motif)
                    sib.insert(0, motif)
                    break


def hack_motifs(doc):
    """ dirty hack for the marginpar-creates-orphans LaTeX problem
    see http://www.latex-project.org/cgi-bin/ltxbugs2html?pr=latex/2304

    moves motifs in stanzas from first verse to second
    and from next to last to last, then inserts negative vspace before them
    """
    for motif in doc.findall('//strofa//motyw'):
        # find relevant verse-level tag
        verse, stanza = motif, motif.getparent()
        while stanza is not None and stanza.tag != 'strofa':
            verse, stanza = stanza, stanza.getparent()
        breaks_before = sum(1 for i in verse.itersiblings('br', preceding=True))
        breaks_after = sum(1 for i in verse.itersiblings('br'))
        if (breaks_before == 0 and breaks_after > 0) or breaks_after == 1:
            move_by = 1
            if breaks_after == 2:
                move_by += 1
            moved_motif = deepcopy(motif)
            motif.tag = 'span'
            motif.text = None
            moved_motif.tail = None
            moved_motif.set('moved', str(move_by))

            for br in verse.itersiblings('br'):
                if move_by > 1:
                    move_by -= 1
                    continue
                br.addnext(moved_motif)
                break


def get_resource(path):
    return os.path.join(os.path.dirname(__file__), path)

def get_stylesheet(name):
    return get_resource(STYLESHEETS[name])


def package_available(package, args='', verbose=False):
    """ check if a verion of a latex package accepting given args is available """  
    tempdir = mkdtemp('-wl2pdf-test')
    fpath = os.path.join(tempdir, 'test.tex')
    f = open(fpath, 'w')
    f.write(r"""
        \documentclass{book}
        \usepackage[%s]{%s}
        \begin{document}
        \end{document}
        """ % (args, package))
    f.close()
    if verbose:
        p = call(['xelatex', '-output-directory', tempdir, fpath])
    else:
        p = call(['xelatex', '-interaction=batchmode', '-output-directory', tempdir, fpath], stdout=PIPE, stderr=PIPE)
    shutil.rmtree(tempdir)
    return p == 0


def transform(provider, slug, output_file=None, output_dir=None, make_dir=False, verbose=False, save_tex=None):
    """ produces a PDF file with XeLaTeX

    provider: a DocProvider
    slug: slug of file to process, available by provider
    output_file: file-like object or path to output file
    output_dir: path to directory to save output file to; either this or output_file must be present
    make_dir: writes output to <output_dir>/<author>/<slug>.pdf istead of <output_dir>/<slug>.pdf
    verbose: prints all output from LaTeX
    save_tex: path to save the intermediary LaTeX file to
    """

    # Parse XSLT
    try:
        document = load_including_children(provider, slug)

        # check for latex packages
        if not package_available('morefloats', 'maxfloats=19', verbose=verbose):
            document.edoc.getroot().set('old-morefloats', 'yes')
            print >> sys.stderr, """
==============================================================================
LaTeX `morefloats' package is older than v.1.0c or not available at all.
Some documents with many motifs in long stanzas or paragraphs may not compile.
=============================================================================="""

        # hack the tree
        move_motifs_inside(document.edoc)
        hack_motifs(document.edoc)
        substitute_hyphens(document.edoc)
        fix_hanging(document.edoc)

        # find output dir
        if make_dir and output_dir is not None:
            author = unicode(document.book_info.author)
            output_dir = os.path.join(output_dir, author)

        # wl -> TeXML
        style_filename = get_stylesheet("wl2tex")
        style = etree.parse(style_filename)
        texml = document.transform(style)
        del document # no longer needed large object :)

        # TeXML -> LaTeX
        temp = mkdtemp('-wl2pdf')
        tex_path = os.path.join(temp, 'doc.tex')
        fout = open(tex_path, 'w')
        process(StringIO(texml), fout, 'utf-8')
        fout.close()
        del texml

        if save_tex:
            shutil.copy(tex_path, save_tex)

        # LaTeX -> PDF
        shutil.copy(get_resource('pdf/wl.sty'), temp)
        shutil.copy(get_resource('pdf/wl-logo.png'), temp)

        cwd = os.getcwd()
        os.chdir(temp)

        if verbose:
            p = call(['xelatex', tex_path])
        else:
            p = call(['xelatex', '-interaction=batchmode', tex_path], stdout=PIPE, stderr=PIPE)
        if p:
            raise ParseError("Error parsing .tex file")

        os.chdir(cwd)

        # save the PDF
        pdf_path = os.path.join(temp, 'doc.pdf')
        if output_dir is not None:
            try:
                os.makedirs(output_dir)
            except OSError:
                pass
            output_path = os.path.join(output_dir, '%s.pdf' % slug)
            shutil.move(pdf_path, output_path)
        else:
            if hasattr(output_file, 'write'):
                # file-like object
                with open(pdf_path) as f:
                    output_file.write(f.read())
                output_file.close()
            else:
                # path to output file
                shutil.copy(pdf_path, output_file)
        shutil.rmtree(temp)

    except (XMLSyntaxError, XSLTApplyError), e:
        raise ParseError(e)


def load_including_children(provider, slug=None, uri=None):
    """ makes one big xml file with children inserted at end 
    either slug or uri must be provided
    """

    if uri:
        f = provider.by_uri(uri)
    elif slug:
        f = provider[slug]
    else:
        raise ValueError('Neither slug nor URI provided for a book.')

    document = WLDocument.from_file(f, True,
        parse_dublincore=True,
        preserve_lines=False)

    for child_uri in document.book_info.parts:
        child = load_including_children(provider, uri=child_uri)
        document.edoc.getroot().append(child.edoc.getroot())

    return document
