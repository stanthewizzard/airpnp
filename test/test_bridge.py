import unittest
import mock
from airpnp.bridge import AVControlPoint
from airpnp.airplayserver import SessionRejectedError


class TestAVControlPoint(unittest.TestCase):

    def setUp(self):
        self.avtransport = mock.Mock()
        self.connmgr = mock.Mock()
        def gsbyid(id):
            if id == 'urn:upnp-org:serviceId:AVTransport':
                return self.avtransport
            elif id == 'urn:upnp-org:serviceId:ConnectionManager':
                return self.connmgr
            else:
                raise ValueError("Unknown id: " + id)
        device = mock.Mock()
        device.get_service_by_id = mock.Mock(side_effect=gsbyid)
        self.avcp = AVControlPoint(device, None)

        # mock away instance ID business since these methods check for 
        # attributes that will be auto-added by the mock service.
        self.avcp.allocate_instance_id = mock.Mock(return_value="0")
        self.avcp.release_instance_id = mock.Mock()

        # suppress logging
        self.avcp.msg = lambda *args: None

    def test_get_scrub_without_uri(self):
        duration, position = self.avcp.get_scrub()
        self.assertEqual(duration, 0.0)
        self.assertEqual(position, 0.0)

    def test_is_playing_without_uri(self):
        playing = self.avcp.is_playing()
        self.assertEqual(playing, False)

    def test_set_sid_allocates_instance_id(self):
        self.avcp.set_session_id("123")
        self.assertTrue(self.avcp.allocate_instance_id.called)

    def test_set_sid_with_none_releases_instance_id(self):
        self.avcp.set_session_id(None)
        self.assertTrue(self.avcp.release_instance_id.called)

    def test_set_sid_with_duplicate_raises_error(self):
        self.avcp.set_session_id("123")
        self.assertRaises(SessionRejectedError, self.avcp.set_session_id, "456")

    def test_play_sets_uri_and_starts_playing(self):
        self.avcp.set_session_id("123")
        self.avcp.play("http://www.example.com/video.avi", 0.1)

        self.avtransport.SetAVTransportURI.assert_called_with(
            InstanceID="0",
            CurrentURI="http://www.example.com/video.avi",
            CurrentURIMetaData="")
        self.avtransport.Play.assert_called_with(InstanceID="0", Speed="1")

    def test_play_doesnt_seek_without_preset_scrub(self):
        self.avcp.set_session_id("123")
        self.avcp.play("http://www.example.com/video.avi", 0.1)
        self.assertFalse(self.avtransport.Seek.called)

    def test_set_scrub_doesnt_seek_without_uri(self):
        self.avcp.set_scrub(5.0)
        self.assertFalse(self.avtransport.Seek.called)

    def test_play_seeks_with_preset_scrub(self):
        self.avcp.set_session_id("123")
        self.avcp.set_scrub(5.0)
        self.avcp.play("http://www.example.com/video.avi", 0.1)

        self.avtransport.Seek.assert_called_once_with(InstanceID="0",
                                                      Unit="REL_TIME",
                                                      Target="0:00:05")

    def test_set_scrub_seeks_with_uri(self):
        self.avcp.set_session_id("123")
        self.avcp.play("http://www.example.com/video.avi", 0.1)

        self.avcp.set_scrub(5.0)
        self.avtransport.Seek.assert_called_with(InstanceID="0",
                                                 Unit="REL_TIME",
                                                 Target="0:00:05")
