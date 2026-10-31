import unittest

from porch_zones import PorchZones


def walk(zones, rows, start=0):
    events = []
    for i, y in enumerate(rows):
        points = [] if y is None else [(.6, y, .3)]
        events += zones.observe(points, start + i)
    return events


class PorchZoneTests(unittest.TestCase):
    def test_measured_walk_up_and_back_down_is_a_departure(self):
        z = PorchZones()
        events = walk(z, [.70, .76, .84, .97, 1.0, 1.0, .93, .82, .78, .72, None, None])
        self.assertEqual(events[0], 'approach')
        self.assertIn('door', events)
        self.assertIn('leaving', events)
        self.assertTrue(z.departing(11))

    def test_single_low_frame_on_porch_is_not_a_departure(self):
        z = PorchZones()
        events = walk(z, [.75, .86, .90, .79, .88, .90])
        self.assertNotIn('leaving', events)
        self.assertFalse(z.departing(5))

    def test_standing_on_the_porch_edge_never_flaps(self):
        z = PorchZones()
        events = walk(z, [.75, .88, .96, .80, .79, .81, .79, .80, .78, .80])
        self.assertNotIn('leaving', events)

    def test_frame_edge_box_is_ignored(self):
        z = PorchZones()
        for i, (x, y) in enumerate([(.6, .9), (.95, 1.0), (.95, .74), (.95, .74), (.95, 1.0)]):
            self.assertNotIn('leaving', z.observe([(x, y, .3)], i))

    def test_coming_back_cancels_departure(self):
        z = PorchZones()
        walk(z, [.75, .9, 1.0, .78, .74, .72])
        self.assertTrue(z.departing(5))
        self.assertIn('returned', z.observe([(.6, .9, .3)], 6))
        self.assertFalse(z.departing(6))

    def test_door_dwell_tolerates_single_missed_frame(self):
        z = PorchZones()
        walk(z, [.8, .96, 1.0, None, 1.0, 1.0])
        self.assertGreaterEqual(z.at_door_for(5), 4)


if __name__ == '__main__':
    unittest.main()



class WebcamDepartureTests(unittest.TestCase):
    def walk(self, feet_heights, step=.25, start=100.0):
        from visitor_motion import WebcamDeparture
        d = WebcamDeparture()
        states = []
        for i, (feet, height) in enumerate(feet_heights):
            box = (feet - height, .4, feet, .6, .9)
            states.append(d.observe([box], start + i * step, 1, True))
        return states

    def test_walking_away_down_the_path_is_a_departure(self):
        path = [(.98, .9)] * 4 + [(.95, .85), (.9, .75), (.84, .65), (.78, .58), (.72, .5), (.68, .45)]
        self.assertTrue(self.walk(path)[-1])

    def test_fidgeting_at_the_pumpkin_is_not(self):
        path = [(.98, .9), (.95, .88), (.99, .9), (.96, .87), (.97, .9), (.94, .86), (.98, .9)] * 2
        self.assertFalse(any(self.walk(path)))

    def test_arriving_is_not(self):
        path = [(.6, .4), (.65, .45), (.72, .5), (.8, .6), (.9, .75), (.97, .9)]
        self.assertFalse(any(self.walk(path)))

    def test_back_on_the_sidewalk_after_being_close(self):
        path = [(.97, .9)] * 3 + [(.6, .3), (.48, .2)]
        self.assertTrue(self.walk(path)[-1])

    def test_turning_back_cancels(self):
        path = [(.98, .9)] * 4 + [(.9, .75), (.82, .62), (.74, .52), (.7, .48), (.8, .6), (.9, .78)]
        self.assertFalse(self.walk(path)[-1])

    def test_passer_by_on_the_sidewalk_is_not_a_departure(self):
        # Visitor was close, then stepped out of view behind the camera; a passer-by appears far away.
        path = [(.97, .9)] * 4 + [(.42, .12), (.41, .12), (.42, .12)]
        self.assertFalse(any(self.walk(path)))

