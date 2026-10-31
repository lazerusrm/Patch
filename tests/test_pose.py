import unittest
import numpy as np
import pose


def person(**points):
    keypoints = [(0, 0, 0)] * 17
    for name, (x, y) in points.items():
        keypoints[pose.K[name]] = (x, y, .9)
    return {'box': (.1, .3, .9, .7, .9), 'keypoints': keypoints}


BODY = dict(nose=(.5, .2), left_shoulder=(.45, .32), right_shoulder=(.55, .32), left_hip=(.46, .55), right_hip=(.54, .55))


class PoseTests(unittest.TestCase):
    def test_one_and_two_hands_up(self):
        one = person(**BODY, left_elbow=(.43, .22), left_wrist=(.42, .1), right_elbow=(.57, .42), right_wrist=(.57, .5))
        both = person(**BODY, left_elbow=(.43, .22), left_wrist=(.42, .08), right_elbow=(.57, .22), right_wrist=(.58, .08))
        self.assertEqual(pose.hands_raised(one), 1)
        self.assertEqual(pose.hands_raised(both), 2)
        self.assertFalse(pose.hands_on_head(both))  # Straight up is not on the head.

    def test_hands_on_head_is_not_raising_a_hand(self):
        head = person(**BODY, left_elbow=(.38, .2), left_wrist=(.47, .17), right_elbow=(.62, .2), right_wrist=(.53, .17))
        self.assertTrue(pose.hands_on_head(head))
        self.assertEqual(pose.hands_raised(head), 0)

    def test_arms_out_and_flex(self):
        t = person(**BODY, left_elbow=(.35, .32), left_wrist=(.25, .33), right_elbow=(.65, .32), right_wrist=(.75, .33))
        self.assertTrue(pose.arms_out(t))
        flex = person(**BODY, left_elbow=(.36, .33), left_wrist=(.37, .22))
        self.assertTrue(pose.flexing(flex))

    def test_decode_finds_one_person_from_raw_heads(self):
        outputs = {}
        for grid in (20, 40, 80):
            box = np.full((1, grid, grid, 64), -5.0); box[..., 0::16] = 5  # all DFL mass on bin 0 -> tiny boxes
            cls = np.zeros((1, grid, grid, 1))
            kps = np.zeros((1, grid, grid, 51))
            outputs[f'b{grid}'], outputs[f'c{grid}'], outputs[f'k{grid}'] = box, cls, kps
        outputs['c20'][0, 10, 10, 0] = .9
        outputs['b20'][0, 10, 10, :] = -5; outputs['b20'][0, 10, 10, 2::16] = 5  # 2 bins each side
        people = pose.decode(outputs)
        self.assertEqual(len(people), 1)
        y1, x1, y2, x2, score = people[0]['box']
        self.assertAlmostEqual(score, .9, places=3)
        self.assertAlmostEqual((x1 + x2) / 2, 10.5 * 32 / 640, places=3)
