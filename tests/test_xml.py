import collections
# import numbers
import io
import unittest
import unittest.mock

import lxml.sax

import xml.sax as sax
import xml.sax.handler as saxhandler

import asyncio_xmpp.xml as xml
import asyncio_xmpp.jid as jid
import asyncio_xmpp.errors as errors
import asyncio_xmpp.stanza_model as stanza_model

from asyncio_xmpp.utils import etree, namespaces

from .xmltestutils import XMLTestCase


# this tree is extracted from http://api.met.no, the API of the norwegian
# meterological institute. This data is under CC-BY-SA.
TEST_TREE = b"""<weatherdata xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:noNamespaceSchemaLocation="http://api.met.no/weatherapi/locationforecast/1.9/schema" created="2015-03-02T19:40:26Z">
   <meta>
      <model name="LOCAL" termin="2015-03-02T12:00:00Z" runended="2015-03-02T15:39:25Z" nextrun="2015-03-03T04:00:00Z" from="2015-03-02T20:00:00Z" to="2015-03-05T06:00:00Z" />
      <model name="EC.GEO.0.25" termin="2015-03-02T12:00:00Z" runended="2015-03-02T19:04:34Z" nextrun="2015-03-02T20:00:00Z" from="2015-03-05T09:00:00Z" to="2015-03-12T12:00:00Z" />
      </meta>
   <product class="pointData">
      <time datatype="forecast" from="2015-03-02T20:00:00Z" to="2015-03-02T20:00:00Z">
         <location altitude="288" latitude="51.0000" longitude="13.0000">
            <temperature id="TTT" unit="celsius" value="2.1"/>
            <windDirection id="dd" deg="232.7" name="SW"/>
            <windSpeed id="ff" mps="5.4" beaufort="3" name="Lett bris"/>
            <humidity value="72.7" unit="percent"/>
            <pressure id="pr" unit="hPa" value="1007.5"/>
            <cloudiness id="NN" percent="70.4"/>
            <fog id="FOG" percent="0.0"/>
            <lowClouds id="LOW" percent="0.6"/>
            <mediumClouds id="MEDIUM" percent="69.8"/>
            <highClouds id="HIGH" percent="0.0"/>
            <dewpointTemperature id="TD" unit="celsius" value="-2.5"/>
         </location>
      </time>
      <time datatype="forecast" from="2015-03-02T19:00:00Z" to="2015-03-02T20:00:00Z">
         <location altitude="288" latitude="51.0000" longitude="13.0000">
            <precipitation unit="mm" value="0.0" minvalue="0.0" maxvalue="0.0"/>
<symbol id="PartlyCloud" number="3"/>
         </location>
      </time>
</product></weatherdata>"""
# end of data extracted from http://api.met.no


class Cls(stanza_model.StanzaObject):
    TAG = ("uri:foo", "bar")


class TestxmlValidateNameValue_str(unittest.TestCase):
    def test_foo(self):
        self.assertTrue(xml.xmlValidateNameValue_str("foo"))

    def test_greater_than(self):
        self.assertFalse(xml.xmlValidateNameValue_str("foo>"))

    def test_less_than(self):
        self.assertFalse(xml.xmlValidateNameValue_str("foo<"))


class TestXMPPXMLGenerator(XMLTestCase):
    def setUp(self):
        self.buf = io.BytesIO()

    def test_declaration(self):
        gen = xml.XMPPXMLGenerator(self.buf)
        gen.startDocument()
        gen.endDocument()

        self.assertEqual(
            b'<?xml version="1.0"?>',
            self.buf.getvalue()
        )

    def test_reject_namespaceless_stuff(self):
        gen = xml.XMPPXMLGenerator(self.buf)
        gen.startDocument()
        with self.assertRaises(NotImplementedError):
            gen.startElement(None, None)
        with self.assertRaises(NotImplementedError):
            gen.endElement(None)

    def test_reject_invalid_prefix(self):
        gen = xml.XMPPXMLGenerator(self.buf)
        gen.startDocument()
        with self.assertRaises(ValueError):
            gen.startPrefixMapping(">", "uri:foo")
        with self.assertRaises(ValueError):
            gen.startPrefixMapping(":", "uri:foo")

    def test_reject_invalid_attribute_name(self):
        gen = xml.XMPPXMLGenerator(self.buf)
        gen.startDocument()
        with self.assertRaises(ValueError):
            gen.startElementNS((None, "foo"), None, {(None, ">"): "bar"})

    def test_reject_invalid_element_name(self):
        gen = xml.XMPPXMLGenerator(self.buf)
        gen.startDocument()
        with self.assertRaises(ValueError):
            gen.startElementNS((None, ">"), None, None)

    def test_element_with_explicit_namespace_setup(self):
        gen = xml.XMPPXMLGenerator(self.buf, short_empty_elements=True)
        gen.startDocument()
        gen.startPrefixMapping("ns", "uri:foo")
        gen.startElementNS(("uri:foo", "foo"), None, None)
        gen.endElementNS(("uri:foo", "foo"), None)
        gen.endPrefixMapping("ns")
        gen.endDocument()

        self.assertEqual(
            b'<?xml version="1.0"?><ns:foo xmlns:ns="uri:foo"/>',
            self.buf.getvalue()
        )

    def test_element_without_explicit_namespace_setup(self):
        gen = xml.XMPPXMLGenerator(self.buf, short_empty_elements=True)
        gen.startDocument()
        gen.startElementNS(("uri:foo", "foo"), None, None)
        gen.endElementNS(("uri:foo", "foo"), None)
        gen.endDocument()

        self.assertEqual(
            b'<?xml version="1.0"?><ns0:foo xmlns:ns0="uri:foo"/>',
            self.buf.getvalue()
        )

    def test_detection_of_unclosed_namespace(self):
        gen = xml.XMPPXMLGenerator(self.buf)
        gen.startDocument()
        gen.startPrefixMapping("ns0", "uri:foo")
        gen.startElementNS(("uri:foo", "foo"), None, None)
        gen.startPrefixMapping("ns0", "uri:bar")
        gen.startElementNS(("uri:bar", "e1"), None, None)
        gen.endElementNS(("uri:bar", "e1"), None)
        with self.assertRaises(RuntimeError):
            gen.startElementNS(("uri:bar", "e2"), None, None)
        with self.assertRaises(RuntimeError):
            gen.startElementNS(("uri:foo", "e2"), None, None)
        with self.assertRaises(RuntimeError):
            gen.endElementNS(("uri:foo", "foo"), None)

    def test_no_need_to_close_auto_generated_prefix(self):
        gen = xml.XMPPXMLGenerator(self.buf)
        gen.startDocument()
        gen.startPrefixMapping("ns", "uri:foo")
        gen.startElementNS(("uri:foo", "foo"), None, None)
        gen.startElementNS(("uri:bar", "e1"), None, None)
        gen.endElementNS(("uri:bar", "e1"), None)
        gen.endElementNS(("uri:foo", "foo"), None)
        gen.endDocument()
        self.assertEqual(
            b'<?xml version="1.0"?>'
            b'<ns:foo xmlns:ns="uri:foo">'
            b'<ns0:e1 xmlns:ns0="uri:bar"/>'
            b'</ns:foo>',
            self.buf.getvalue()
        )

    def test_auto_namespacing_per_element(self):
        gen = xml.XMPPXMLGenerator(self.buf)
        gen.startDocument()
        gen.startPrefixMapping("ns", "uri:foo")
        gen.startElementNS(("uri:foo", "foo"), None, None)
        gen.startElementNS(("uri:bar", "e"), None, None)
        gen.endElementNS(("uri:bar", "e"), None)
        gen.startElementNS(("uri:baz", "e"), None, None)
        gen.endElementNS(("uri:baz", "e"), None)
        gen.endElementNS(("uri:foo", "foo"), None)
        gen.endDocument()
        self.assertEqual(
            b'<?xml version="1.0"?>'
            b'<ns:foo xmlns:ns="uri:foo">'
            b'<ns0:e xmlns:ns0="uri:bar"/>'
            b'<ns0:e xmlns:ns0="uri:baz"/>'
            b'</ns:foo>',
            self.buf.getvalue()
        )

    def test_namespaceless_root(self):
        gen = xml.XMPPXMLGenerator(self.buf)
        gen.startDocument()
        gen.startElementNS((None, "foo"), None, None)
        gen.endElementNS((None, "foo"), None)
        gen.endDocument()
        self.assertEqual(
            b'<?xml version="1.0"?>'
            b'<foo/>',
            self.buf.getvalue()
        )

    def test_attributes(self):
        gen = xml.XMPPXMLGenerator(self.buf, short_empty_elements=True)
        gen.startDocument()
        gen.startElementNS(
            (None, "foo"),
            None,
            {
                (None, "bar"): "1",
                (None, "fnord"): "2"
            }
        )
        gen.endElementNS((None, "foo"), None)
        gen.endDocument()
        self.assertIn(
            self.buf.getvalue(),
            {
                b'<?xml version="1.0"?><foo bar="1" fnord="2"/>',
                b'<?xml version="1.0"?><foo fnord="2" bar="1"/>',
            }
        )

    def test_attributes_sortedattrs(self):
        gen = xml.XMPPXMLGenerator(self.buf,
                                   short_empty_elements=True,
                                   sorted_attributes=True)
        gen.startDocument()
        gen.startElementNS(
            (None, "foo"),
            None,
            {
                (None, "bar"): "1",
                (None, "fnord"): "2",
                ("uri:foo", "baz"): "3"
            }
        )
        gen.endElementNS((None, "foo"), None)
        gen.endDocument()
        self.assertEqual(
            b'<?xml version="1.0"?><foo xmlns:ns0="uri:foo" bar="1" fnord="2" ns0:baz="3"/>',
            self.buf.getvalue()
        )

    def test_attribute_ns_autogeneration(self):
        gen = xml.XMPPXMLGenerator(self.buf)
        gen.startDocument()
        gen.startPrefixMapping("ns", "uri:foo")
        gen.startElementNS(
            (None, "foo"),
            None,
            collections.OrderedDict([
                ((None, "a"), "1"),
                (("uri:foo", "b"), "2"),
                (("uri:bar", "b"), "3"),
            ])
        )
        gen.endElementNS((None, "foo"), None)
        gen.endPrefixMapping("ns")
        gen.endDocument()

        self.assertEqual(
            b'<?xml version="1.0"?>'
            b'<foo xmlns:ns="uri:foo" xmlns:ns0="uri:bar"'
            b' a="1" ns:b="2" ns0:b="3"/>',
            self.buf.getvalue()
        )

    def test_text(self):
        gen = xml.XMPPXMLGenerator(self.buf)
        gen.startDocument()
        gen.startElementNS((None, "foo"), None, None)
        gen.characters("foobar")
        gen.endElementNS((None, "foo"), None)
        gen.endDocument()

        self.assertEqual(
            b'<?xml version="1.0"?>'
            b"<foo>foobar</foo>",
            self.buf.getvalue()
        )

    def test_text_escaping(self):
        gen = xml.XMPPXMLGenerator(self.buf)
        gen.startDocument()
        gen.startElementNS((None, "foo"), None, None)
        gen.characters("<fo&o>")
        gen.endElementNS((None, "foo"), None)
        gen.endDocument()

        self.assertEqual(
            b'<?xml version="1.0"?>'
            b"<foo>&lt;fo&amp;o&gt;</foo>",
            self.buf.getvalue()
        )

    def test_interleave_setup_and_teardown_of_namespaces(self):
        gen = xml.XMPPXMLGenerator(self.buf, short_empty_elements=True)
        gen.startDocument()
        gen.startPrefixMapping("ns0", "uri:foo")
        gen.startElementNS(("uri:foo", "foo"), None, None)
        gen.startPrefixMapping("ns1", "uri:bar")
        gen.startElementNS(("uri:bar", "e1"), None, None)
        gen.endElementNS(("uri:bar", "e1"), None)
        gen.startPrefixMapping("ns1", "uri:baz")
        gen.endPrefixMapping("ns1")
        gen.startElementNS(("uri:baz", "e2"), None, None)
        gen.endElementNS(("uri:baz", "e2"), None)
        gen.endPrefixMapping("ns1")
        gen.endElementNS(("uri:foo", "foo"), None)
        gen.endPrefixMapping("ns0")
        gen.endDocument()
        self.assertEqual(
            b'<?xml version="1.0"?>'
            b'<ns0:foo xmlns:ns0="uri:foo">'
            b'<ns1:e1 xmlns:ns1="uri:bar"/>'
            b'<ns1:e2 xmlns:ns1="uri:baz"/>'
            b'</ns0:foo>',
            self.buf.getvalue()
        )

    def test_complex_tree(self):
        tree = etree.fromstring(TEST_TREE)
        gen = xml.XMPPXMLGenerator(self.buf, short_empty_elements=True)
        lxml.sax.saxify(tree, gen)

        tree2 = etree.fromstring(self.buf.getvalue())

        self.assertSubtreeEqual(
            tree,
            tree2)

    def test_reject_processing_instruction(self):
        gen = xml.XMPPXMLGenerator(self.buf)
        gen.startDocument()
        gen.startElementNS((None, "foo"), None, None)
        with self.assertRaisesRegexp(ValueError,
                                     "restricted xml: processing instruction"):
            gen.processingInstruction("foo", "bar")

    def test_reject_multiple_assignments_for_prefix(self):
        gen = xml.XMPPXMLGenerator(self.buf)
        gen.startDocument()
        gen.startPrefixMapping("a", "uri:foo")
        with self.assertRaises(ValueError):
            gen.startPrefixMapping("a", "uri:bar")

    def test_no_duplicate_auto_assignments_of_prefixes(self):
        gen = xml.XMPPXMLGenerator(self.buf)
        gen.startDocument()
        gen.startPrefixMapping("ns0", "uri:foo")
        gen.startElementNS(("uri:bar", "foo"), None, None)
        gen.startElementNS(("uri:foo", "foo"), None, None)
        gen.endElementNS(("uri:foo", "foo"), None)
        gen.endElementNS(("uri:bar", "foo"), None)
        gen.endPrefixMapping("ns0")
        gen.endDocument()

        self.assertSubtreeEqual(
            etree.fromstring("<foo xmlns='uri:bar'><foo xmlns='uri:foo' /></foo>"),
            etree.fromstring(self.buf.getvalue())
        )

    def test_reject_control_characters_in_characters(self):
        gen = xml.XMPPXMLGenerator(self.buf)
        gen.startDocument()
        gen.startElementNS(("uri:bar", "foo"), None, None)
        for i in set(range(32)) - {9, 10, 13}:
            with self.assertRaises(ValueError):
                gen.characters(chr(i))

    def test_skippedEntity_not_implemented(self):
        gen = xml.XMPPXMLGenerator(self.buf)
        with self.assertRaises(NotImplementedError):
            gen.skippedEntity("foo")

    def test_setDocumentLocator_not_implemented(self):
        gen = xml.XMPPXMLGenerator(self.buf)
        with self.assertRaises(NotImplementedError):
            gen.setDocumentLocator("foo")

    def test_ignorableWhitespace_not_implemented(self):
        gen = xml.XMPPXMLGenerator(self.buf)
        with self.assertRaises(NotImplementedError):
            gen.ignorableWhitespace("foo")

    def test_reject_unnamespaced_element_if_default_namespace_is_set(self):
        gen = xml.XMPPXMLGenerator(self.buf)
        gen.startDocument()
        gen.startPrefixMapping(None, "uri:foo")
        with self.assertRaises(ValueError):
            gen.startElementNS((None, "foo"), None, None)

    def test_properly_handle_empty_root(self):
        gen = xml.XMPPXMLGenerator(self.buf, short_empty_elements=True)
        gen.startDocument()
        gen.startElementNS((None, "foo"), None, None)
        gen.endElementNS((None, "foo"), None)
        gen.endDocument()

        self.assertEqual(
            b'<?xml version="1.0"?>'
            b"<foo/>",
            self.buf.getvalue()
        )

    def test_finish_partially_opened_element_on_flush(self):
        gen = xml.XMPPXMLGenerator(self.buf, short_empty_elements=True)
        gen.startDocument()
        gen.startElementNS((None, "foo"), None, None)
        gen.flush()
        self.assertEqual(
            b'<?xml version="1.0"?>'
            b"<foo>",
            self.buf.getvalue()
        )
        gen.endElementNS((None, "foo"), None)
        gen.endDocument()
        self.assertEqual(
            b'<?xml version="1.0"?>'
            b"<foo></foo>",
            self.buf.getvalue()
        )

    def test_implicit_xml_prefix(self):
        gen = xml.XMPPXMLGenerator(self.buf, short_empty_elements=True)
        gen.startDocument()
        gen.startElementNS(
            ("http://www.w3.org/XML/1998/namespace", "foo"), None, None)
        gen.endElementNS(("http://www.w3.org/XML/1998/namespace", "foo"),
                         None)
        gen.endDocument()
        self.assertEqual(
            b'<?xml version="1.0"?>'
            b"<xml:foo/>",
            self.buf.getvalue()
        )

    def test_non_short_empty_elements(self):
        gen = xml.XMPPXMLGenerator(self.buf, short_empty_elements=False)
        gen.startDocument()
        gen.startElementNS((None, "foo"), None, None)
        gen.endElementNS((None, "foo"), None)
        gen.endDocument()
        self.assertEqual(
            b'<?xml version="1.0"?>'
            b"<foo></foo>",
            self.buf.getvalue()
        )

    def test_flush(self):
        buf = unittest.mock.MagicMock()

        gen = xml.XMPPXMLGenerator(buf, short_empty_elements=True)
        gen.flush()

        self.assertSequenceEqual(
            [
                unittest.mock.call.flush.__bool__(),
                unittest.mock.call.flush(),
            ],
            buf.mock_calls
        )

    def test_reject_colon_in_element_name(self):
        gen = xml.XMPPXMLGenerator(self.buf, short_empty_elements=True)
        gen.startDocument()
        with self.assertRaises(ValueError):
            gen.startElementNS((None, "foo:bar"), None, None)

    def test_reject_invalid_element_names(self):
        gen = xml.XMPPXMLGenerator(self.buf, short_empty_elements=True)
        gen.startDocument()
        with self.assertRaises(ValueError):
            gen.startElementNS((None, "foo*bar"), None, None)
        with self.assertRaises(ValueError):
            gen.startElementNS((None, "\u0002bar"), None, None)
        with self.assertRaises(ValueError):
            gen.startElementNS((None, "\u0000"), None, None)

    def test_reject_xmlns_attributes(self):
        gen = xml.XMPPXMLGenerator(self.buf, short_empty_elements=True)
        gen.startDocument()
        with self.assertRaises(ValueError):
            gen.startElementNS((None, "foo"), None, {
                (None, "xmlns"): "foobar"
            })
        with self.assertRaises(ValueError):
            gen.startElementNS((None, "foo"), None, {
                (None, "xmlns:foo"): "foobar"
            })

    def test_reject_reserved_prefixes(self):
        gen = xml.XMPPXMLGenerator(self.buf, short_empty_elements=True)
        gen.startDocument()
        with self.assertRaises(ValueError):
            gen.startPrefixMapping("xmlns", "uri:foo")
        with self.assertRaises(ValueError):
            gen.startPrefixMapping("xml", "uri:foo")

    def test_catch_non_tuple_attribute(self):
        gen = xml.XMPPXMLGenerator(self.buf, short_empty_elements=True)
        gen.startDocument()
        with self.assertRaises(ValueError):
            gen.startElementNS((None, "foo"), None, {
                "fo": "foobar"
            })

    def test_works_without_flush(self):
        class Backend:
            def write(self, data):
                pass

        gen = xml.XMPPXMLGenerator(Backend())
        gen.startDocument()
        gen.startElementNS((None, "foo"), None, {})
        gen.flush()
        gen.endElementNS((None, "foo"), None)
        gen.endDocument()
        gen.flush()

    def tearDown(self):
        del self.buf


class Testwrite_objects(unittest.TestCase):
    def setUp(self):
        self.buf = io.BytesIO()

    def test_setup(self):
        gen = xml.write_objects(self.buf)
        next(gen)
        gen.close()

        self.assertEqual(
            b'<?xml version="1.0"?>'
            b'<stream:stream xmlns:stream="http://etherx.jabber.org/streams"></stream:stream>',
            self.buf.getvalue()
        )

    def test_reset(self):
        gen = xml.write_objects(self.buf)
        next(gen)
        with self.assertRaises(StopIteration):
            gen.throw(xml.AbortStream())

        self.assertEqual(
            b'<?xml version="1.0"?>'
            b'<stream:stream xmlns:stream="http://etherx.jabber.org/streams">',
            self.buf.getvalue()
        )

    def test_root_ns(self):
        gen = xml.write_objects(self.buf, nsmap={None: "jabber:client"})
        next(gen)
        gen.close()

        self.assertEqual(
            b'<?xml version="1.0"?>'
            b'<stream:stream xmlns="jabber:client" xmlns:stream="http://etherx.jabber.org/streams"></stream:stream>',
            self.buf.getvalue()
        )

    def test_send_object(self):
        obj = Cls()
        gen = xml.write_objects(self.buf)
        next(gen)
        gen.send(obj)
        gen.close()

        self.assertEqual(
            b'<?xml version="1.0"?>'
            b'<stream:stream xmlns:stream="http://etherx.jabber.org/streams">'
            b'<ns0:bar xmlns:ns0="uri:foo"/>'
            b'</stream:stream>',
            self.buf.getvalue())

    def test_send_object_inherits_namespaces(self):
        obj = Cls()
        gen = xml.write_objects(
            self.buf,
            nsmap={"jc": "uri:foo"})
        next(gen)
        gen.send(obj)
        gen.close()

        self.assertEqual(
            b'<?xml version="1.0"?>'
            b'<stream:stream xmlns:jc="uri:foo" xmlns:stream="http://etherx.jabber.org/streams">'
            b'<jc:bar/>'
            b'</stream:stream>',
            self.buf.getvalue())

    def tearDown(self):
        del self.buf


class TestXMPPXMLProcessor(unittest.TestCase):
    VALID_STREAM_HEADER = "".join((
        "<stream:stream xmlns:stream='{}'".format(namespaces.xmlstream),
        " version='1.0' from='example.test' ",
        "to='foo@example.test' id='foobarbaz'>"
    ))

    STREAM_HEADER_TAG = (namespaces.xmlstream, "stream")

    STREAM_HEADER_ATTRS = {
        (None, "from"): "example.test",
        (None, "to"): "foo@example.test",
        (None, "id"): "foobarbaz",
        (None, "version"): "1.0"
    }

    def setUp(self):
        self.proc = xml.XMPPXMLProcessor()
        self.parser = xml.make_parser()
        self.parser.setContentHandler(self.proc)

    def test_reject_processing_instruction(self):
        with self.assertRaises(errors.StreamError) as cm:
            self.proc.processingInstruction("foo", "bar")
        self.assertEqual(
            (namespaces.streams, "restricted-xml"),
            cm.exception.error_tag
        )

    def test_reject_start_element_without_ns(self):
        with self.assertRaises(RuntimeError):
            self.proc.startElement("foo", {})

    def test_reject_end_element_without_ns(self):
        with self.assertRaises(RuntimeError):
            self.proc.endElement("foo")

    def test_errors_propagate(self):
        self.parser.feed(self.VALID_STREAM_HEADER)
        with self.assertRaises(errors.StreamError):
            self.parser.feed("<!-- foo -->")

    def test_capture_stream_header(self):
        self.proc.startDocument()
        self.proc.startElementNS(
            self.STREAM_HEADER_TAG,
            None,
            self.STREAM_HEADER_ATTRS
        )

        self.assertEqual(
            (1, 0),
            self.proc.remote_version
        )
        self.assertEqual(
            jid.JID.fromstr("example.test"),
            self.proc.remote_from
        )
        self.assertEqual(
            jid.JID.fromstr("foo@example.test"),
            self.proc.remote_to
        )
        self.assertEqual(
            "foobarbaz",
            self.proc.remote_id
        )

    def test_require_stream_header(self):
        self.proc.startDocument()

        with self.assertRaises(errors.StreamError) as cm:
            self.proc.startElementNS((None, "foo"), None, {})
        self.assertEqual(
            (namespaces.streams, "invalid-namespace"),
            cm.exception.error_tag
        )

        with self.assertRaises(errors.StreamError) as cm:
            self.proc.startElementNS((namespaces.xmlstream, "bar"), None, {})
        self.assertEqual(
            (namespaces.streams, "invalid-namespace"),
            cm.exception.error_tag
        )

    def test_require_stream_header_from(self):
        attrs = self.STREAM_HEADER_ATTRS.copy()
        del attrs[(None, "from")]

        self.proc.startDocument()
        with self.assertRaises(errors.StreamError) as cm:
            self.proc.startElementNS(self.STREAM_HEADER_TAG, None, attrs)
        self.assertEqual(
            (namespaces.streams, "undefined-condition"),
            cm.exception.error_tag
        )

    def test_do_not_require_stream_header_to(self):
        attrs = self.STREAM_HEADER_ATTRS.copy()
        del attrs[(None, "to")]

        self.proc.startDocument()
        self.proc.startElementNS(self.STREAM_HEADER_TAG, None, attrs)
        self.assertIsNone(
            None,
            self.proc.remote_to)

    def test_require_stream_header_id(self):
        attrs = self.STREAM_HEADER_ATTRS.copy()
        del attrs[(None, "id")]

        self.proc.startDocument()
        with self.assertRaises(errors.StreamError) as cm:
            self.proc.startElementNS(self.STREAM_HEADER_TAG, None, attrs)
        self.assertEqual(
            (namespaces.streams, "undefined-condition"),
            cm.exception.error_tag
        )

    def test_check_stream_header_version(self):
        attrs = self.STREAM_HEADER_ATTRS.copy()
        attrs[None, "version"] = "2.0"

        self.proc.startDocument()
        with self.assertRaises(errors.StreamError) as cm:
            self.proc.startElementNS(self.STREAM_HEADER_TAG, None, attrs)
        self.assertEqual(
            (namespaces.streams, "unsupported-version"),
            cm.exception.error_tag
        )
        self.assertEqual(
            "2.0",
            cm.exception.text
        )

    def test_interpret_missing_version_as_0_point_9(self):
        attrs = self.STREAM_HEADER_ATTRS.copy()
        del attrs[None, "version"]

        self.proc.startDocument()
        with self.assertRaises(errors.StreamError) as cm:
            self.proc.startElementNS(self.STREAM_HEADER_TAG, None, attrs)
        self.assertEqual(
            (namespaces.streams, "unsupported-version"),
            cm.exception.error_tag
        )
        self.assertEqual(
            "0.9",
            cm.exception.text
        )

    def test_interpret_parsing_error_as_unsupported_version(self):
        attrs = self.STREAM_HEADER_ATTRS.copy()
        attrs[None, "version"] = "foobar"

        self.proc.startDocument()
        with self.assertRaises(errors.StreamError) as cm:
            self.proc.startElementNS(self.STREAM_HEADER_TAG, None, attrs)
        self.assertEqual(
            (namespaces.streams, "unsupported-version"),
            cm.exception.error_tag
        )

    def test_forward_to_parser(self):
        results = []

        def recv(obj):
            nonlocal results
            results.append(obj)

        self.proc.stanza_parser = stanza_model.StanzaParser()
        self.proc.stanza_parser.add_class(Cls, recv)

        self.proc.startDocument()
        self.proc.startElementNS(self.STREAM_HEADER_TAG, None,
                                 self.STREAM_HEADER_ATTRS)
        self.proc.startElementNS(Cls.TAG, None, {})
        self.proc.endElementNS(Cls.TAG, None)

        self.assertEqual(1, len(results))

        self.assertIsInstance(
            results[0],
            Cls)

    def test_end_element_of_stream_header_is_not_forwarded_to_parser(self):
        self.proc.startDocument()
        self.proc._driver = unittest.mock.MagicMock()

        self.proc.startElementNS(self.STREAM_HEADER_TAG, None,
                                 self.STREAM_HEADER_ATTRS)
        self.proc.endElementNS(self.STREAM_HEADER_TAG, None)

        self.assertSequenceEqual(
            [],
            self.proc._driver.mock_calls)

    def test_require_start_document(self):
        with self.assertRaises(RuntimeError):
            self.proc.startElementNS((None, "foo"), None, {})
        with self.assertRaises(RuntimeError):
            self.proc.endElementNS((None, "foo"), None)
        with self.assertRaises(RuntimeError):
            self.proc.characters("foo")

    def test_parse_complex_class(self):
        results = []

        def recv(obj):
            nonlocal results
            results.append(obj)

        class Bar(stanza_model.StanzaObject):
            TAG = ("uri:foo", "bar")

            text = stanza_model.Text()

            def __init__(self, text=None):
                super().__init__()
                self.text = text

        class Baz(stanza_model.StanzaObject):
            TAG = ("uri:foo", "baz")

            children = stanza_model.ChildList([Bar])

        class Foo(stanza_model.StanzaObject):
            TAG = ("uri:foo", "foo")

            attr = stanza_model.Attr((None, "attr"))
            bar = stanza_model.Child([Bar])
            baz = stanza_model.Child([Baz])

        self.proc.stanza_parser = stanza_model.StanzaParser()
        self.proc.stanza_parser.add_class(Foo, recv)

        self.proc.startDocument()
        self.proc.startElementNS(self.STREAM_HEADER_TAG, None,
                                 self.STREAM_HEADER_ATTRS)

        f = Foo()
        f.attr = "fnord"
        f.bar = Bar()
        f.bar.text = "some text"
        f.baz = Baz()
        f.baz.children.append(Bar("child a"))
        f.baz.children.append(Bar("child b"))

        f.unparse_to_sax(self.proc)

        self.assertEqual(1, len(results))

        f2 = results.pop()
        self.assertEqual(
            f.attr,
            f2.attr
        )
        self.assertEqual(
            f.bar.text,
            f2.bar.text
        )
        self.assertEqual(
            len(f.baz.children),
            len(f2.baz.children)
        )
        for c1, c2 in zip(f.baz.children, f2.baz.children):
            self.assertEqual(c1.text, c2.text)

        self.proc.endElementNS(self.STREAM_HEADER_TAG, None)
        self.proc.endDocument()

    def test_require_end_document_before_restarting(self):
        self.proc.startDocument()
        self.proc.startElementNS(self.STREAM_HEADER_TAG, None,
                                 self.STREAM_HEADER_ATTRS)
        with self.assertRaises(RuntimeError):
            self.proc.startDocument()
        self.proc.endElementNS(self.STREAM_HEADER_TAG, None)
        with self.assertRaises(RuntimeError):
            self.proc.startDocument()
        self.proc.endDocument()
        self.proc.startDocument()

    def test_allow_end_document_only_after_stream_has_finished(self):
        with self.assertRaises(RuntimeError):
            self.proc.endDocument()
        self.proc.startDocument()
        with self.assertRaises(RuntimeError):
            self.proc.endDocument()
        self.proc.startElementNS(self.STREAM_HEADER_TAG, None,
                                 self.STREAM_HEADER_ATTRS)
        with self.assertRaises(RuntimeError):
            self.proc.endDocument()
        self.proc.endElementNS(self.STREAM_HEADER_TAG, None)
        self.proc.endDocument()

    def test_disallow_changing_stanza_parser_during_processing(self):
        self.proc.stanza_parser = unittest.mock.MagicMock()
        self.proc.startDocument()
        with self.assertRaises(RuntimeError):
            self.proc.stanza_parser = unittest.mock.MagicMock()

    # def test_depth_limit(self):
    #     def dummy_parser():
    #         while True:
    #             yield

    #     self.assertEqual(
    #         1024,
    #         self.proc.depth_limit)

    #     self.proc.stanza_parser = dummy_parser
    #     self.proc.startDocument()
    #     self.proc.depth_limit = 100

    #     self.proc.startElementNS(self.STREAM_HEADER_TAG,
    #                              None,
    #                              self.STREAM_HEADER_ATTRS)
    #     for i in range(99):
    #         self.proc.startElementNS((None, "foo"), None, {})

    #     with self.assertRaises(errors.StreamError) as cm:
    #         self.proc.startElementNS((None, "foo"), None, {})
    #     self.assertEqual(
    #         (namespaces.streams, "policy-violation"),
    #         cm.exception.error_tag
    #     )

    def tearDown(self):
        del self.proc
        del self.parser


class Testmake_parser(unittest.TestCase):
    def setUp(self):
        self.p = xml.make_parser()

    def test_is_incremental(self):
        self.assertTrue(
            hasattr(self.p, "feed")
        )

    def test_namespace_feature_enabled(self):
        self.assertTrue(
            self.p.getFeature(saxhandler.feature_namespaces)
        )

    def test_validation_feature_disabled(self):
        self.assertFalse(
            self.p.getFeature(saxhandler.feature_validation)
        )

    def test_external_ges_feature_disabled(self):
        self.assertFalse(
            self.p.getFeature(saxhandler.feature_external_ges)
        )

    def test_external_pes_feature_disabled(self):
        self.assertFalse(
            self.p.getFeature(saxhandler.feature_external_pes)
        )

    def test_uses_XMPPLexicalHandler(self):
        self.assertIs(
            xml.XMPPLexicalHandler,
            self.p.getProperty(saxhandler.property_lexical_handler)
        )


class TestXMPPLexicalHandler(unittest.TestCase):
    def setUp(self):
        self.proc = xml.XMPPLexicalHandler()

    def test_reject_comments(self):
        with self.assertRaises(errors.StreamError) as cm:
            self.proc.comment("foobar")
        self.assertEqual(
            (namespaces.streams, "restricted-xml"),
            cm.exception.error_tag
        )
        self.proc.endCDATA()

    def test_reject_dtd(self):
        with self.assertRaises(errors.StreamError) as cm:
            self.proc.startDTD("foo", "bar", "baz")
        self.assertEqual(
            (namespaces.streams, "restricted-xml"),
            cm.exception.error_tag
        )
        self.proc.endDTD()

    def test_reject_non_predefined_entity(self):
        with self.assertRaises(errors.StreamError) as cm:
            self.proc.startEntity("foo")
        self.assertEqual(
            (namespaces.streams, "restricted-xml"),
            cm.exception.error_tag
        )
        self.proc.endEntity("foo")

    def test_accept_predefined_entity(self):
        for entity in ["amp", "lt", "gt", "apos", "quot"]:
            self.proc.startEntity(entity)
            self.proc.endEntity(entity)

    def test_ignore_cdata(self):
        self.proc.startCDATA()
        self.proc.endCDATA()

    def tearDown(self):
        del self.proc
