import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
from timecanvas import v4l2

FORMATS = """ioctl: VIDIOC_ENUM_FMT
\tType: Video Capture

\t[0]: 'MJPG' (Motion-JPEG, compressed)
\t\tSize: Discrete 1920x1080
\t\t\tInterval: Discrete 0.033s (30.000 fps)
\t\t\tInterval: Discrete 0.067s (15.000 fps)
\t\t\tInterval: Discrete 0.033s (30.000 fps)
\t\tSize: Discrete 1280x720
\t\t\tInterval: Discrete 0.033s (30.000 fps)
\t\t\tInterval: Discrete 0.040s (25.000 fps)
\t[1]: 'YUYV' (YUYV 4:2:2)
\t\tSize: Discrete 640x480
\t\t\tInterval: Discrete 0.033s (30.000 fps)
"""
CTRLS = """User Controls

                     brightness 0x00980900 (int)    : min=-64 max=64 step=1 default=0 value=0
        white_balance_automatic 0x0098090c (bool)   : default=1 value=1
error 71 getting ctrl Gamma
      white_balance_temperature 0x0098091a (int)    : min=2800 max=6500 step=1 default=4600 value=4600 flags=inactive

Camera Controls

                  auto_exposure 0x009a0901 (menu)   : min=0 max=3 default=3 value=3 (Aperture Priority Mode)
\t\t\t\t1: Manual Mode
\t\t\t\t3: Aperture Priority Mode
"""


class V(unittest.TestCase):
    def test_modes_dedupe_and_format_filter(self):
        m = v4l2.parse_modes(FORMATS)
        self.assertEqual(m, {(1920, 1080): [30, 15], (1280, 720): [30, 25]})   # YUYV 640x480 excluded, duplicates collapsed
        self.assertEqual(v4l2.mode_list(m)[0], (1920, 1080, 30))
        self.assertTrue(v4l2.valid_mode(m, 1280, 720, 25))
        for bad in ((1920, 1080, 25), (640, 480, 30), (1920, 1081, 30), (0, 0, 0)):
            self.assertFalse(v4l2.valid_mode(m, *bad))

    def test_ctrls_types_menus_inactive(self):
        c = {x["name"]: x for x in v4l2.parse_ctrls(CTRLS)}
        self.assertEqual(set(c), {"brightness", "white_balance_automatic", "white_balance_temperature", "auto_exposure"})
        self.assertEqual((c["brightness"]["min"], c["brightness"]["max"], c["brightness"]["default"]), ("-64", "64", "0"))
        self.assertTrue(c["white_balance_temperature"]["inactive"]); self.assertFalse(c["brightness"]["inactive"])
        self.assertEqual(c["auto_exposure"]["menu"], [(1, "Manual Mode"), (3, "Aperture Priority Mode")])
        self.assertEqual(c["white_balance_automatic"]["type"], "bool")


if __name__ == "__main__":
    unittest.main()
