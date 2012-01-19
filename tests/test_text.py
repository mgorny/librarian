# -*- coding: utf-8 -*-
#
# This file is part of Librarian, licensed under GNU Affero GPLv3 or later.
# Copyright © Fundacja Nowoczesna Polska. See NOTICE for more information.
#
from librarian import NoDublinCore
from librarian.parser import WLDocument
from nose.tools import *
from utils import get_fixture


def test_transform():
    expected_output_file_path = get_fixture('text', 'asnyk_miedzy_nami_expected.txt')

    text = WLDocument.from_file(
            get_fixture('text', 'miedzy-nami-nic-nie-bylo.xml')
        ).as_text().get_string()

    assert_equal(text, file(expected_output_file_path).read())


@raises(NoDublinCore)
def test_no_dublincore():
    WLDocument.from_file(
            get_fixture('text', 'asnyk_miedzy_nami_nodc.xml')
        ).as_text()


def test_passing_parse_dublincore_to_transform():
    """Passing parse_dublincore=False to the constructor omits DublinCore parsing."""
    WLDocument.from_file(
            get_fixture('text', 'asnyk_miedzy_nami_nodc.xml'),
            parse_dublincore=False,
        ).as_text()
