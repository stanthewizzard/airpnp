import unittest
import urllib2
from mock import patch
from airpnp.util import *
from airpnp.upnp import SoapMessage, SoapError
from cStringIO import StringIO
from airpnp.upnp import parse_duration as hms_to_sec
from airpnp.upnp import to_duration as sec_to_hms
from twisted.internet import defer
from twisted.python import failure
from twisted.web import error, http


class RaisingOpener:

    def __init__(self):
        self.calls = 0

    def open(self, req, data=None, timeout=0):
        self.calls += 1
        self.req = req
        raise urllib2.URLError('error')


class TestGetMaxAge(unittest.TestCase):

    def test_with_proper_header(self):
        headers = {'CACHE-CONTROL': 'max-age=10'}
        max_age = get_max_age(headers)

        self.assertEqual(max_age, 10)

    def test_with_spaces_around_eq(self):
        headers = {'CACHE-CONTROL': 'max-age = 10'}
        max_age = get_max_age(headers)

        self.assertEqual(max_age, 10)

    def test_with_missing_max_age(self):
        headers = {'CACHE-CONTROL': 'xyz=10'}
        max_age = get_max_age(headers)

        self.assertIsNone(max_age)

    def test_with_missing_header(self):
        headers = {'a': 'b'}
        max_age = get_max_age(headers)

        self.assertIsNone(max_age)

    def test_with_malformed_max_age(self):
        headers = {'CACHE-CONTROL': 'max-age='}
        max_age = get_max_age(headers)

        self.assertIsNone(max_age)


@patch('twisted.web.client.getPage')
class TestSendSoapMessageDeferred(unittest.TestCase):

    def test_request_headers(self, pageMock):
        # Given
        msg = SoapMessage('urn:schemas-upnp-org:service:ConnectionManager:1', 'GetCurrentConnectionIDs')

        # When
        send_soap_message_deferred('http://www.dummy.com', msg)

        # Then
        headers = pageMock.call_args[1]['headers']
        self.assertEqual(headers['Content-Type'], 'text/xml; charset="utf-8"')
        self.assertEqual(headers['Soapaction'],
                         '"urn:schemas-upnp-org:service:ConnectionManager:1#GetCurrentConnectionIDs"')

    def test_request_agent(self, pageMock):
        # Given
        msg = SoapMessage('urn:schemas-upnp-org:service:ConnectionManager:1', 'GetCurrentConnectionIDs')

        # When
        send_soap_message_deferred('http://www.dummy.com', msg)

        # Then
        agent = pageMock.call_args[1]['agent']
        self.assertEqual(agent, 'OS/1.0 UPnP/1.0 airpnp/1.0')

    def test_soap_response(self, pageMock):
        # Setup mock
        pageMock.return_value = defer.succeed(SoapMessage('urn:schemas-upnp-org:service:ConnectionManager:1',
                                                          'GetCurrentConnectionIDsResponse').tostring())

        # Given
        msg = SoapMessage('urn:schemas-upnp-org:service:ConnectionManager:1', 'GetCurrentConnectionIDs')

        # When
        d = send_soap_message_deferred('http://www.dummy.com', msg)

        # Then
        response = d.result
        self.assertEqual(response.__class__, SoapMessage)
        self.assertEqual(response.get_header(),
                         '"urn:schemas-upnp-org:service:ConnectionManager:1#GetCurrentConnectionIDsResponse"')

    def test_soap_error_on_500_response(self, pageMock):
        # Setup mock
        f = failure.Failure(error.Error(http.INTERNAL_SERVER_ERROR, 'Internal Error', 
                                        SoapError(501, 'Action Failed').tostring()))
        pageMock.return_value = defer.fail(f)

        # Given
        msg = SoapMessage('urn:schemas-upnp-org:service:ConnectionManager:1', 'GetCurrentConnectionIDs')

        # When
        d = send_soap_message_deferred('http://www.dummy.com', msg)

        # Then
        response = d.result
        self.assertEqual(response.__class__, SoapError)
        self.assertEqual(response.code, '501')

    def test_unrecognized_error_is_reraised(self, pageMock):
        # Setup mock
        f = failure.Failure(error.Error(http.NOT_FOUND, 'Not Found', 'Not Found'))
        pageMock.return_value = defer.fail(f)

        # Given
        msg = SoapMessage('urn:schemas-upnp-org:service:ConnectionManager:1', 'GetCurrentConnectionIDs')

        # When
        d = send_soap_message_deferred('http://www.dummy.com', msg)

        # Then
        f = d.result
        self.assertTrue(f.check(error.Error))

    def test_fallback_to_mpost(self, pageMock):
        # Setup mock
        def side_effect(*args, **kwargs):
            def second_call(*args, **kwargs):
                return defer.succeed(SoapMessage('urn:schemas-upnp-org:service:ConnectionManager:1',
                                                 'GetCurrentConnectionIDsResponse').tostring())
            pageMock.side_effect = second_call
            f = failure.Failure(error.Error(http.NOT_ALLOWED, 'Method Not Allowed',
                                            'Method Not Allowed'))
            return defer.fail(f)
        pageMock.side_effect = side_effect

        # Given
        msg = SoapMessage('urn:schemas-upnp-org:service:ConnectionManager:1', 'GetCurrentConnectionIDs')

        # When
        send_soap_message_deferred('http://www.dummy.com', msg)

        # Then
        headers = pageMock.call_args[1]['headers']
        self.assertEqual(headers['Man'],
                         '"http://schemas.xmlsoap.org/soap/envelope/"; ns=01')
        self.assertEqual(headers['01-Soapaction'],
                         '"urn:schemas-upnp-org:service:ConnectionManager:1#GetCurrentConnectionIDs"')


class TestSendSoapMessage(unittest.TestCase):

    def setUp(self):
        self.old_opener = urllib2._opener

    def tearDown(self):
        urllib2.install_opener(self.old_opener)

    def test_request_headers(self):
        o = RaisingOpener()
        urllib2.install_opener(o)

        msg = SoapMessage('urn:schemas-upnp-org:service:ConnectionManager:1', 'GetCurrentConnectionIDs')
        try:
            send_soap_message('http://www.dummy.com', msg)
        except:
            pass

        req = o.req
        self.assertEqual(req.get_header('Content-type'), 'text/xml; charset="utf-8"')
        self.assertEqual(req.get_header('User-agent'), 'OS/1.0 UPnP/1.0 airpnp/1.0')
        self.assertEqual(req.get_header('Soapaction'),
                         '"urn:schemas-upnp-org:service:ConnectionManager:1#GetCurrentConnectionIDs"')

    def test_soap_response(self):
        class Opener:
            def open(self, req, data=None, timeout=0):
                response = SoapMessage('urn:schemas-upnp-org:service:ConnectionManager:1',
                                       'GetCurrentConnectionIDsResponse')
                return StringIO(response.tostring())

        o = Opener()
        urllib2.install_opener(o)

        msg = SoapMessage('urn:schemas-upnp-org:service:ConnectionManager:1', 'GetCurrentConnectionIDs')
        response = send_soap_message('http://www.dummy.com', msg)

        self.assertEqual(response.__class__, SoapMessage)
        self.assertEqual(response.get_header(),
                         '"urn:schemas-upnp-org:service:ConnectionManager:1#GetCurrentConnectionIDsResponse"')

    def test_soap_error_on_500_response(self):
        class Opener:
            def open(self, req, data=None, timeout=0):
                response = SoapError(501, 'Action Failed')
                raise urllib2.HTTPError('http://www.dummy.com', 500, 
                                        'Internal Error', None, 
                                        StringIO(response.tostring()))

        o = Opener()
        urllib2.install_opener(o)

        msg = SoapMessage('urn:schemas-upnp-org:service:ConnectionManager:1', 'GetCurrentConnectionIDs')
        response = send_soap_message('http://www.dummy.com', msg)

        self.assertEqual(response.__class__, SoapError)
        self.assertEqual(response.code, '501')

    def test_url_error_is_reraised(self):
        class Opener:
            def open(self, req, data=None, timeout=0):
                raise urllib2.URLError('error')

        o = Opener()
        urllib2.install_opener(o)

        msg = SoapMessage('urn:schemas-upnp-org:service:ConnectionManager:1', 'GetCurrentConnectionIDs')
        self.assertRaises(urllib2.URLError, send_soap_message,
                          'http://www.dummy.com', msg)

    def test_http_error_is_reraised_if_not_405_or_500(self):
        class Opener:
            def open(self, req, data=None, timeout=0):
                raise urllib2.HTTPError('http://www.dummy.com', 404, 
                                        'Not Found', None, 
                                        StringIO('Not Found'))

        o = Opener()
        urllib2.install_opener(o)

        msg = SoapMessage('urn:schemas-upnp-org:service:ConnectionManager:1', 'GetCurrentConnectionIDs')
        self.assertRaises(urllib2.HTTPError, send_soap_message,
                          'http://www.dummy.com', msg)

    def test_fallback_to_mpost(self):
        class Opener:
            def open(self, req, data=None, timeout=0):
                if req.get_method() == 'POST':
                    raise urllib2.HTTPError('http://www.dummy.com', 405, 
                                            'Method Not Allowed', None, 
                                            StringIO('Method Not Allowed'))
                else:
                    e = urllib2.URLError('')
                    e.headers = req.headers
                    raise e

        o = Opener()
        urllib2.install_opener(o)

        msg = SoapMessage('urn:schemas-upnp-org:service:ConnectionManager:1', 'GetCurrentConnectionIDs')
        try:
            send_soap_message('http://www.dummy.com', msg)
        except urllib2.URLError, e:
            self.assertEqual(e.headers['Man'],
                             '"http://schemas.xmlsoap.org/soap/envelope/"; ns=01')
            self.assertEqual(e.headers['01-soapaction'],
                             '"urn:schemas-upnp-org:service:ConnectionManager:1#GetCurrentConnectionIDs"')


class TestHmsToSec(unittest.TestCase):

    def test_hour_conversion(self):
        sec = hms_to_sec('1:00:00')
        self.assertEqual(sec, 3600.0)

    def test_minute_conversion(self):
        sec = hms_to_sec('0:10:00')
        self.assertEqual(sec, 600.0)

    def test_second_conversion(self):
        sec = hms_to_sec('0:00:05')
        self.assertEqual(sec, 5.0)

    def test_with_fraction(self):
        sec = hms_to_sec('0:00:05.5')
        self.assertEqual(sec, 5.5)

    def test_with_div_fraction(self):
        sec = hms_to_sec('0:00:05.1/2')
        self.assertEqual(sec, 5.5)

    def test_with_plus_sign(self):
        sec = hms_to_sec('+1:01:01')
        self.assertEqual(sec, 3661.0)

    def test_with_minus_sign(self):
        sec = hms_to_sec('-1:01:01')
        self.assertEqual(sec, -3661.0)

    def test_without_hour_part(self):
        self.assertRaises(ValueError, hms_to_sec, '00:00')

    def test_with_empty_hour_part(self):
        self.assertRaises(ValueError, hms_to_sec, ':00:00')

    def test_with_too_short_minute_part(self):
        self.assertRaises(ValueError, hms_to_sec, '0:0:00')

    def test_with_too_short_second_part(self):
        self.assertRaises(ValueError, hms_to_sec, '0:00:0')

    def test_with_negative_minute(self):
        self.assertRaises(ValueError, hms_to_sec, '0:-1:00')

    def test_with_too_large_minute(self):
        self.assertRaises(ValueError, hms_to_sec, '0:60:00')

    def test_with_negative_second(self):
        self.assertRaises(ValueError, hms_to_sec, '0:00:-1')

    def test_with_too_large_second(self):
        self.assertRaises(ValueError, hms_to_sec, '0:00:60')

    def test_with_div_fraction_unsatisfied_inequality(self):
        self.assertRaises(ValueError, hms_to_sec, '0:00:05.5/5')


class TestSecToHms(unittest.TestCase):

    def test_seconds_only_without_fraction(self):
        hms = sec_to_hms(5)
        self.assertEqual(hms, '0:00:05.000')

    def test_seconds_with_fraction(self):
        hms = sec_to_hms(5.5)
        self.assertEqual(hms, '0:00:05.500')

    def test_minute_conversion(self):
        hms = sec_to_hms(65)
        self.assertEqual(hms, '0:01:05.000')

    def test_hour_conversion(self):
        hms = sec_to_hms(3600)
        self.assertEqual(hms, '1:00:00.000')

    def test_negative_seconds_conversion(self):
        hms = sec_to_hms(-3661.0)
        self.assertEqual(hms, '-1:01:01.000')


class TestSplitUsn(unittest.TestCase):

    def test_split_two_parts(self):
        usn = 'uuid:x::type'
        p1, p2 = split_usn(usn)

        self.assertEqual(p1, 'uuid:x')
        self.assertEqual(p2, 'type')

    def test_split_only_udn(self):
        usn = 'uuid:x'
        p1, p2 = split_usn(usn)

        self.assertEqual(p1, 'uuid:x')
        self.assertEqual(p2, '')
        

class TestGetImageType(unittest.TestCase):
    
    def test_with_jpeg_data(self):
        data = "\xff\xd8\x01\x02\x03\x04"
        actual = get_image_type(data)
        self.assertEqual(("image/jpeg", ".jpg"), actual)

    def test_with_unrecognized_data(self):
        data = "\x01\x02\x03\x04"
        actual = get_image_type(data)
        self.assertEqual(("image/unknown", ".bin"), actual)


class TestFormatSoapMessage(unittest.TestCase):

    def test_format_message_without_args(self):
        msg = SoapMessage('urn:schemas-upnp-org:service:ConnectionManager:1', 'AnOperation')
        self.assertEqual('AnOperation()', format_soap_message(msg))

    def test_format_message_with_one_arg(self):
        msg = SoapMessage('urn:schemas-upnp-org:service:ConnectionManager:1', 'AnOperation')
        msg.set_arg("Arg1", "0")
        self.assertEqual('AnOperation(Arg1=0)', format_soap_message(msg))

    def test_format_message_with_two_args(self):
        msg = SoapMessage('urn:schemas-upnp-org:service:ConnectionManager:1', 'AnOperation')
        msg.set_arg("Arg1", "0")
        msg.set_arg("Arg2", "0")
        self.assertEqual('AnOperation(Arg1=0, Arg2=0)', format_soap_message(msg))


class TestCreateDeviceId(unittest.TestCase):

    def test_create_id_from_uuid(self):
        id = "uuid:f8ecf350-8691-4639-a735-c10ee6ad15c1"
        did = create_device_id(id)
        self.assertEqual(17, len(did))
        self.assertEqual(6, len(did.split(":")))

    def test_create_id_from_non_uuid(self):
        id = "uuid:media_renderer_xyz"
        did = create_device_id(id)
        self.assertEqual(17, len(did))
        self.assertEqual(6, len(did.split(":")))

    def test_that_create_id_is_not_random(self):
        id = "uuid:f8ecf350-8691-4639-a735-c10ee6ad15c1"
        did1 = create_device_id(id)
        did2 = create_device_id(id)
        self.assertEqual(did1, did2)


def test_service_compatibility(): # generator function
    # different types
    yield (check_compatibility, 'urn:upnp-org:service:ConnectionManager:1', 
           'urn:upnp-org:service:AVTransport:1', False)
    # same type and version
    yield (check_compatibility, 'urn:upnp-org:service:ConnectionManager:1', 
           'urn:upnp-org:service:ConnectionManager:1', True)
    # actual has lower version
    yield (check_compatibility, 'urn:upnp-org:service:ConnectionManager:2', 
           'urn:upnp-org:service:ConnectionManager:1', False)
    # actual has higher version
    yield (check_compatibility, 'urn:upnp-org:service:ConnectionManager:1', 
           'urn:upnp-org:service:ConnectionManager:2', True)
    # malformed actual
    yield (check_compatibility, 'urn:upnp-org:service:ConnectionManager:1', 
           'ConnectionManager', False)
    # malformed required
    yield (check_compatibility, 'ConnectionManager', 
           'urn:upnp-org:service:ConnectionManager:1', False)
    # same type, no version
    yield (check_compatibility, 'upnp:rootdevice', 'upnp:rootdevice', True)
    # different types, no version
    yield (check_compatibility, 'upnp:rootdevice', 'upnp:smthelse', False)


def check_compatibility(req, act, exp_outcome):
    compat = are_service_types_compatible(req, act)
    assert exp_outcome == compat

