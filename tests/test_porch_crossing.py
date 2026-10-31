import unittest
from types import SimpleNamespace
from unittest.mock import patch
from porch_crossing import PorchCrossing


def box(y, x=.6):
    return [y - .3, x - .08, y, x + .08, .9]


class CrossingTests(unittest.TestCase):
    def test_audio_priority_keeps_small_presence_frames_alive(self):
        from unifi_client import UniFiBridge
        bridge=UniFiBridge();bridge.audio_requests=1
        now=[0.0];fetches=[]
        def fetch(width):
            fetches.append((now[0],width))
            if len(fetches)==3:bridge.stop.set()
            return now[0],object()
        bridge.fetch_frame=fetch
        with patch('unifi_client.time.monotonic',side_effect=lambda:now[0]), \
             patch.object(bridge.stop,'wait',side_effect=lambda seconds:now.__setitem__(0,now[0]+seconds)):
            bridge.watch_camera()
            self.assertIsNotNone(bridge.latest_frame())
        self.assertEqual([width for _,width in fetches],[320,320,320])
        self.assertLessEqual(max(b[0]-a[0] for a,b in zip(fetches,fetches[1:])),2.2)

    def test_audio_priority_holds_snapshot_downloads_until_all_requests_finish(self):
        from unifi_client import UniFiBridge
        bridge = UniFiBridge()
        self.assertEqual(bridge.audio_requests,0)
        with bridge.audio_priority():
            with bridge.audio_priority():
                self.assertEqual(bridge.audio_requests,2)
            self.assertEqual(bridge.audio_requests,1)
        self.assertEqual(bridge.audio_requests,0)

    def test_fresh_measured_exit_is_not_vetoed_by_webcam_seeing_departing_person(self):
        from pumpkin import Pumpkin
        p = object.__new__(Pumpkin)
        p.bridge = SimpleNamespace(enabled=True, presence_until=0)
        p.motion = SimpleNamespace(departing=True)
        p.crossing = SimpleNamespace(departing=True)
        p.crossing_enabled = False
        p.doorbell_observed, p.doorbell_near, p.webcam_seen = 100, 0, 90
        with patch('pumpkin.time.monotonic', return_value=101):
            self.assertFalse(p.departing())
            p.crossing_enabled = True
            self.assertTrue(p.departing())
            p.webcam_seen = 100
            self.assertTrue(p.departing())
            p.doorbell_near = 1
            self.assertFalse(p.departing())
            p.doorbell_near = 0
            p.webcam_seen, p.doorbell_observed = 90, 95
            self.assertFalse(p.departing())

    def test_shared_camera_cache_expires_without_another_request(self):
        from unifi_client import UniFiBridge
        client = UniFiBridge()
        frame = object()
        client.camera_frame = (100, frame)
        with patch('unifi_client.time.monotonic', return_value=102):
            self.assertIs(client.latest_frame()[1], frame)
        with patch('unifi_client.time.monotonic', return_value=104):
            self.assertIsNone(client.latest_frame())

    def test_arrival_exit_and_turnaround(self):
        gate = PorchCrossing()
        events = []
        for now, y in enumerate((.70, .71, .77, .82, .83, .80, .73, .72)):
            events.extend(gate.observe([box(y)], now))
        self.assertEqual(events, ['arriving', 'leaving'])
        self.assertTrue(gate.departing)
        gate.observe([box(.79)], 8)
        self.assertFalse(gate.departing)

    def test_one_hz_walker_can_cross_between_consecutive_frames(self):
        gate=PorchCrossing()
        self.assertEqual(gate.observe([box(.70)],0),[])
        self.assertEqual(gate.state,'approaching')
        self.assertEqual(gate.observe([box(.94)],1),['arriving'])
        self.assertEqual(gate.state,'at_doorstep')
        self.assertEqual(gate.near_count,1)
        self.assertEqual(gate.observe([box(.72)],2),['leaving'])
        self.assertEqual(gate.state,'leaving')
        self.assertEqual(gate.near_count,0)

    def test_lost_detection_stale_feed_and_jitter_are_not_departures(self):
        gate = PorchCrossing()
        for now, y in enumerate((.82, .83, .78, .76, .80, .78)):
            self.assertEqual(gate.observe([box(y)], now), [])
        for now in range(6, 15):
            self.assertEqual(gate.observe([], now), [])
            self.assertFalse(gate.departing)
        self.assertEqual(gate.observe([box(.7)], 30), [])

    def test_group_member_stays_and_occluded_member_blocks_farewell(self):
        gate = PorchCrossing()
        for now in (0, 1):
            gate.observe([box(.85, .5), box(.85, .72)], now)
        for now, y in enumerate((.81, .73, .72), 2):
            gate.observe([box(y, .5), box(.85, .72)], now)
        self.assertFalse(gate.departing)
        for now in (5, 6, 7, 8):
            gate.observe([box(.71, .5)], now)
        self.assertTrue(gate.uncertain)
        self.assertFalse(gate.departing)

    def test_cached_frame_street_and_outside_gate_cannot_cross(self):
        gate = PorchCrossing()
        self.assertEqual(gate.people([box(.6)]), [])
        for now, y in enumerate((.7, .71, .82, .83)):
            self.assertEqual(gate.observe([box(y, .9)], now), [])
            self.assertEqual(gate.observe([box(y, .9)], now), [])
        self.assertFalse(gate.departing)

    def test_ambiguous_group_assignment_does_not_invent_crossing(self):
        gate = PorchCrossing()
        for now in (0, 1):
            gate.observe([box(.71, .59), box(.71, .61)], now)
        for now in (2, 3):
            self.assertEqual(gate.observe([box(.83, .6)], now), [])


if __name__ == '__main__':
    unittest.main()
