"""xmltramp: Make XML documents easily accessible."""

import unittest
from io import BytesIO
from xml.sax.handler import EntityResolver, DTDHandler, ContentHandler, ErrorHandler
from xml.sax import make_parser
from xml.sax.handler import feature_namespaces

from beatbox.six import python_2_unicode_compatible, StringIO, text_type, xrange, urlopen

__version__ = "2.18"
__author__ = "Aaron Swartz"
__credits__ = "Many thanks to pjz, bitsko, and DanC."
__copyright__ = "(C) 2003-2006 Aaron Swartz. GNU GPL 2."


def isstr(f):
    return isinstance(f, str) or isinstance(f, text_type)


def islst(f):
    return isinstance(f, tuple) or isinstance(f, list)


empty = {'http://www.w3.org/1999/xhtml':
         ['img', 'br', 'hr', 'meta', 'link', 'base', 'param', 'input', 'col', 'area']}


def quote(x, elt=True):
    if elt and '<' in x and len(x) > 24 and x.find(']]>') == -1:
        return "<![CDATA[{}]]>".format(x)
    else:
        x = x.replace('&', '&amp;').replace('<', '&lt;').replace(']]>', ']]&gt;')
    if not elt:
        x = x.replace('"', '&quot;')
    return x


@python_2_unicode_compatible
class Element(object):
    def __init__(self, name, attrs=None, children=None, prefixes=None):
        if islst(name) and name[0] is None:
            name = name[1]
        if attrs:
            na = {}
            for k in attrs.keys():
                if islst(k) and k[0] is None:
                    na[k[1]] = attrs[k]
                else:
                    na[k] = attrs[k]
            attrs = na

        self._name = name
        self._attrs = attrs or {}
        self._dir = children or []

        prefixes = prefixes or {}
        self._prefixes = dict(zip(prefixes.values(), prefixes.keys()))

        if prefixes:
            self._dNS = prefixes.get(None, None)
        else:
            self._dNS = None

    def __repr__(self, recursive=0, multiline=0, inprefixes=None):
        def qname(name, inprefixes):
            if islst(name):
                if inprefixes[name[0]] is not None:
                    return inprefixes[name[0]] + ':' + name[1]
                else:
                    return name[1]
            else:
                return name

        def arep(a, inprefixes, addns=1):
            out = ''

            for p in sorted(self._prefixes.keys()):
                if p not in inprefixes.keys():
                    if addns:
                        out += ' xmlns'
                    if addns and self._prefixes[p]:
                        out += ':' + self._prefixes[p]
                    if addns:
                        out += '="{}"'.format(quote(p, False))
                    inprefixes[p] = self._prefixes[p]

            for k in sorted(a.keys()):
                out += ' ' + qname(k, inprefixes) + '="' + quote(a[k], False) + '"'

            return out

        inprefixes = inprefixes or {'http://www.w3.org/XML/1998/namespace': 'xml'}

        # need to call first to set inprefixes:
        attributes = arep(self._attrs, inprefixes, recursive)
        out = '<' + qname(self._name, inprefixes) + attributes

        if not self._dir and (self._name[0] in empty.keys() and
                              self._name[1] in empty[self._name[0]]):
            out += ' />'
            return out

        out += '>'

        if recursive:
            content = 0
            for x in self._dir:
                if isinstance(x, Element):
                    content = 1

            pad = '\n' + ('\t' * recursive)
            for x in self._dir:
                if multiline and content:
                    out += pad
                if isstr(x):
                    out += quote(x)
                elif isinstance(x, Element):
                    out += x.__repr__(recursive + 1, multiline, inprefixes.copy())
                else:
                    raise TypeError("I wasn't expecting {}.".format(repr(x)))
            if multiline and content:
                out += '\n' + ('\t' * (recursive - 1))
        else:
            if self._dir:
                out += '...'

        out += '</' + qname(self._name, inprefixes) + '>'

        return out

    def __str__(self):
        text = u''
        for x in self._dir:
            # "six.text_type" is unicode in Python 2 and str in Python 3.
            text += text_type(x)
        return ' '.join(text.split())

    def __getattr__(self, n):
        if n[0] == '_':
            raise AttributeError("Use foo['{}'] to access the child element.".format(n))
        if self._dNS:
            n = (self._dNS, n)
        for x in self._dir:
            if isinstance(x, Element) and x._name == n:
                return x
        raise AttributeError('No child element named {}'.format(repr(n)))

    def __hasattr__(self, n):
        for x in self._dir:
            if isinstance(x, Element) and x._name == n:
                return True
        return False

    def __setattr__(self, n, v):
        if n[0] == '_':
            self.__dict__[n] = v
        else:
            self[n] = v

    def __getitem__(self, n):
        if isinstance(n, int):  # d[1] == d._dir[1]
            return self._dir[n]
        elif isinstance(n, slice):
            # numerical slices
            if isinstance(n.start, int) or n == slice(None):
                return self._dir[n.start:n.stop]

            # d['foo':] == all <foo>s
            n = n.start
            if self._dNS and not islst(n):
                n = (self._dNS, n)
            out = []
            for x in self._dir:
                if isinstance(x, Element) and x._name == n:
                    out.append(x)
            return out
        else:  # d['foo'] == first <foo>
            if self._dNS and not islst(n):
                n = (self._dNS, n)
            for x in self._dir:
                if isinstance(x, Element) and x._name == n:
                    return x
            raise KeyError(n)

    def __setitem__(self, n, v):
        if isinstance(n, int):  # d[1]
            self._dir[n] = v
        elif isinstance(n, slice):
            # d['foo':] adds a new foo
            n = n.start
            if self._dNS and not islst(n):
                n = (self._dNS, n)

            nv = Element(n)
            self._dir.append(nv)

        else:  # d["foo"] replaces first <foo> and dels rest
            if self._dNS and not islst(n):
                n = (self._dNS, n)

            nv = Element(n)
            nv._dir.append(v)
            replaced = False

            todel = []
            for i in xrange(len(self)):
                if self[i]._name == n:
                    if replaced:
                        todel.append(i)
                    else:
                        self[i] = nv
                        replaced = True
            if not replaced:
                self._dir.append(nv)
            for i in sorted(todel, reverse=True):
                del self[i]

    def __delitem__(self, n):
        if isinstance(n, int):
            del self._dir[n]
        elif isinstance(n, slice):
            # delete all <foo>s
            n = n.start
            if self._dNS and not islst(n):
                n = (self._dNS, n)

            for i in reversed(range(len(self))):
                if self[i]._name == n:
                    del self[i]
        else:
            # delete first foo
            for i in range(len(self)):
                if self[i]._name == n:
                    del self[i]
                    break

    def __call__(self, *_pos, **_set):
        if _set:
            for k in _set.keys():
                self._attrs[k] = _set[k]
        if len(_pos) > 1:
            for i in range(0, len(_pos), 2):
                self._attrs[_pos[i]] = _pos[i + 1]
        if len(_pos) == 1:
            return self._attrs[_pos[0]]
        if len(_pos) == 0:
            return self._attrs

    def __len__(self):
        return len(self._dir)


class Namespace(object):
    def __init__(self, uri):
        self.__uri = uri

    def __getattr__(self, n):
        return (self.__uri, n)

    def __getitem__(self, n):
        return (self.__uri, n)


class Seeder(EntityResolver, DTDHandler, ContentHandler, ErrorHandler):
    def __init__(self):
        self.stack = []
        self.ch = ''
        self.prefixes = {}
        ContentHandler.__init__(self)

    def startPrefixMapping(self, prefix, uri):
        if prefix not in self.prefixes:
            self.prefixes[prefix] = []
        self.prefixes[prefix].append(uri)

    def endPrefixMapping(self, prefix):
        self.prefixes[prefix].pop()
        # szf: 5/15/5
        if len(self.prefixes[prefix]) == 0:
            del self.prefixes[prefix]

    def startElementNS(self, name, qname, attrs):
        ch = self.ch
        self.ch = ''
        if ch and not ch.isspace():
            self.stack[-1]._dir.append(ch)

        attrs = dict(attrs)
        newprefixes = {}
        for k in self.prefixes.keys():
            newprefixes[k] = self.prefixes[k][-1]

        self.stack.append(Element(name, attrs, prefixes=newprefixes.copy()))

    def characters(self, ch):
        # This is called only by sax (never directly) and the string ch is
        # everytimes converted to text_type (unicode) by sax.
        self.ch += ch

    def endElementNS(self, name, qname):
        ch = self.ch
        self.ch = ''
        if ch and not ch.isspace():
            self.stack[-1]._dir.append(ch)

        element = self.stack.pop()
        if self.stack:
            self.stack[-1]._dir.append(element)
        else:
            self.result = element


def seed(fileobj):
    seeder = Seeder()
    parser = make_parser()
    parser.setFeature(feature_namespaces, 1)
    parser.setContentHandler(seeder)
    parser.parse(fileobj)
    return seeder.result


def parse(text):
    """Parse XML to tree of Element.

    text: XML in unicode or byte string
    """
    return seed(StringIO(text) if isinstance(text, text_type) else BytesIO(text))


def load(url):
    """Load XML from a public url  (unused)

    >>> print(beatbox.xmltramp.load("http://www.w3schools.com/xml/note.xml").__repr__(1, 1))
    """
    return seed(urlopen(url))


class XmlTrampTests(unittest.TestCase):
    def test_str(self):
        self.assertEqual(str(parse("<doc />")), "")
        self.assertEqual(str(parse("<doc>I <b>love</b> you.</doc>")), "I love you.")
        self.assertEqual(parse("<doc>\nmom\nwow\n</doc>")[0].strip(), "mom\nwow")
        self.assertEqual(str(parse('<bing>  <bang> <bong>center</bong> </bang>  </bing>')), "center")
        self.assertEqual(str(parse('<doc>\xcf\x80</doc>')), '\xcf\x80')

    def test_attr(self):
        d = Element('foo',
                    attrs={'foo': 'bar'},
                    children=['hit with a', Element('bar'), Element('bar')])

        try:
            d._doesnotexist
            raise RuntimeError("Expected Error but found success. Damn.")
        except AttributeError:
            pass
        self.assertEqual(d.bar._name, 'bar')
        try:
            d.doesnotexist
            raise RuntimeError("Expected Error but found success. Damn.")
        except AttributeError:
            pass

        self.assertTrue(hasattr(d, 'bar'))

        self.assertEqual(d('foo'), 'bar')
        d(silly='yes')
        self.assertEqual(d('silly'), 'yes')
        self.assertEqual(d(), d._attrs)

        self.assertEqual(d[0], 'hit with a')
        d[0] = 'ice cream'
        self.assertEqual(d[0], 'ice cream')
        del d[0]
        self.assertEqual(d[0]._name, "bar")
        self.assertEqual(len(d[:]), len(d._dir))
        self.assertEqual(len(d[1:]), len(d._dir) - 1)
        self.assertEqual(len(d['bar':]), 2)
        d['bar':] = 'baz'
        self.assertEqual(len(d['bar':]), 3)
        self.assertEqual(d['bar']._name, 'bar')

    def test_ns(self):
        d = Element('foo')

        doc = Namespace("http://example.org/bar")
        bbc = Namespace("http://example.org/bbc")
        dc = Namespace("http://purl.org/dc/elements/1.1/")
        d = parse("""
        <doc version="2.7182818284590451"
          xmlns="http://example.org/bar"
          xmlns:dc="http://purl.org/dc/elements/1.1/"
          xmlns:bbc="http://example.org/bbc">
            <author>John Polk and John Palfrey</author>
            <dc:creator>John Polk</dc:creator>
            <dc:creator>John Palfrey</dc:creator>
            <bbc:show bbc:station="4">Buffy</bbc:show>
        </doc>""")

        self.assertEqual(repr(d), '<doc version="2.7182818284590451">...</doc>')
        # the order of xmlns attributes is not garanteed invariant
        self.assertEqual(
                d.__repr__(1),
                '<doc xmlns="http://example.org/bar" xmlns:bbc="http://example.org/bbc"'
                ' xmlns:dc="http://purl.org/dc/elements/1.1/"'
                ' version="2.7182818284590451">'
                '<author>John Polk and John Palfrey</author>'
                '<dc:creator>John Polk</dc:creator>'
                '<dc:creator>John Palfrey</dc:creator>'
                '<bbc:show bbc:station="4">Buffy</bbc:show>'
                '</doc>'
                )
        self.assertEqual(
                d.__repr__(1, 1),
                '<doc xmlns="http://example.org/bar"'
                ' xmlns:bbc="http://example.org/bbc" xmlns:dc="http://purl.org/dc/elements/1.1/"'
                ' version="2.7182818284590451">\n'
                '\t<author>John Polk and John Palfrey</author>\n'
                '\t<dc:creator>John Polk</dc:creator>\n'
                '\t<dc:creator>John Palfrey</dc:creator>\n'
                '\t<bbc:show bbc:station="4">Buffy</bbc:show>\n'
                '</doc>',
                )

        self.assertEqual(
                parse('<doc>a<baz>f<b>o</b>ob<b>a</b>r</baz>a</doc>').__repr__(1, 1),
                '<doc>\n'
                '\ta\n'
                '\t<baz>\n'
                '\t\tf\n'
                '\t\t<b>o</b>\n'
                '\t\tob\n'
                '\t\t<b>a</b>\n'
                '\t\tr\n'
                '\t</baz>\n'
                '\ta\n'
                '</doc>')

        self.assertEqual(repr(parse("<doc xml:lang='en' />")), '<doc xml:lang="en"></doc>')

        self.assertEqual(str(d.author), str(d['author']))
        self.assertEqual(str(d.author), "John Polk and John Palfrey")
        self.assertEqual(d.author._name, doc.author)
        self.assertEqual(str(d[dc.creator]), "John Polk")
        self.assertEqual(d[dc.creator]._name, dc.creator)
        self.assertEqual(str(d[dc.creator:][1]), "John Palfrey")
        d[dc.creator] = "Me!!!"
        self.assertEqual(str(d[dc.creator]), "Me!!!")
        self.assertEqual(len(d[dc.creator:]), 1)
        d[dc.creator:] = "You!!!"
        self.assertEqual(len(d[dc.creator:]), 2)

        self.assertEqual(d[bbc.show](bbc.station), "4")
        d[bbc.show](bbc.station, "5")
        self.assertEqual(d[bbc.show](bbc.station), "5")

    def test_text(self):
        e = Element('e')
        e.c = '<img src="foo">'
        self.assertEqual(e.__repr__(1), '<e><c>&lt;img src="foo"></c></e>')
        e.c = '2 > 4'
        self.assertEqual(e.__repr__(1), '<e><c>2 > 4</c></e>')
        e.c = 'CDATA sections are <em>closed</em> with ]]>.'
        self.assertEqual(e.__repr__(1), '<e><c>CDATA sections are &lt;em>closed&lt;/em> with ]]&gt;.</c></e>')
        e.c = parse('<div xmlns="http://www.w3.org/1999/xhtml">i<br /><span></span>love<br />you</div>')
        self.assertEqual(e.__repr__(1), (
                '<e><c><div xmlns="http://www.w3.org/1999/xhtml">i<br /><span></span>love<br />you'
                '</div></c></e>'))

        e = Element('e')
        e('c', 'that "sucks"')
        self.assertEqual(e.__repr__(1), '<e c="that &quot;sucks&quot;"></e>')

        self.assertEqual(quote("]]>"), "]]&gt;")
        self.assertEqual(quote('< dkdkdsd dkd sksdksdfsd fsdfdsf]]> kfdfkg >'),
                         '&lt; dkdkdsd dkd sksdksdfsd fsdfdsf]]&gt; kfdfkg >')

        self.assertEqual(parse('<x a="&lt;"></x>').__repr__(1), '<x a="&lt;"></x>')
        self.assertEqual(parse('<a xmlns="http://a"><b xmlns="http://b"/></a>').__repr__(1),
                         '<a xmlns="http://a"><b xmlns="http://b"></b></a>')

if __name__ == '__main__':
    unittest.main()
