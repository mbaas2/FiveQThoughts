import struct
import unittest
import zlib
from unittest.mock import patch

import app


class QrCodeTest(unittest.TestCase):
    def test_windows_qr_is_png_with_quiet_zone(self):
        with patch('platform.system', return_value='Windows'):
            png = app.generate_qr_png_bytes('fiveq://setup?key=test')
        self.assertTrue(png.startswith(b'\x89PNG\r\n\x1a\n'))
        width, height = struct.unpack('>II', png[16:24])
        self.assertEqual(width, height)
        idat_length = struct.unpack('>I', png[33:37])[0]
        self.assertEqual(png[37:41], b'IDAT')
        pixels = zlib.decompress(png[41:41 + idat_length])
        self.assertEqual(pixels[:width + 1], b'\x00' + b'\xff' * width)
        self.assertIn(b'\x00', pixels[width + 1:])


if __name__ == '__main__':
    unittest.main()
