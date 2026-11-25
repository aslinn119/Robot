import unittest
from robot_strategy.head_motion import trajectory


class HeadMotionTests(unittest.TestCase):
    def test_axes_and_return(self):
        for action, axis in (('nod', 1), ('shake', 0)):
            points = trajectory(action, [1., 2.])
            self.assertEqual(points[-1], (1., 2.))
            self.assertTrue(all(p[1-axis] == (1., 2.)[1-axis] for p in points))
            self.assertLess(max(abs(b[axis]-a[axis]) for a,b in zip(points, points[1:])), .3)

    def test_center(self):
        self.assertEqual(trajectory('center', [3., -2.])[-1], (0., 0.))
        points = trajectory('center', [-17., 0.])
        self.assertEqual(points[-1], (0., 0.))
        self.assertTrue(all(-17 <= p[0] <= 0 and p[1] == 0 for p in points))
        self.assertLessEqual(max(abs(b[0]-a[0]) * 50 for a,b in zip(points, points[1:])), 7.51)
        with self.assertRaises(ValueError):
            trajectory('nod', [-17., 0.])
        with self.assertRaises(ValueError):
            trajectory('center', [-31., 0.])

    def test_limits(self):
        for start, amplitude in (([float('nan'), 0], 5), ([0, 0], 21), ([14, 0], 20)):
            with self.assertRaises(ValueError):
                trajectory('shake', start, amplitude)

    def test_revised_parameters(self):
        nod = trajectory('nod', [0., 0.], 10., 1.)
        shake = trajectory('shake', [0., 0.], 12., 1.)
        self.assertEqual(len(nod), 100)
        self.assertEqual(max(p[1] for p in nod), 10.)
        self.assertEqual(len(shake), 150)
        self.assertEqual((min(p[0] for p in shake), max(p[0] for p in shake)), (-12., 12.))
