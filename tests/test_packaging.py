"""Regression for opkg's non-recursive extraction into a clean filesystem."""
import io
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from build import archive, files_for


class OpkgExtractionTests(unittest.TestCase):
    def extract_like_opkg(self, package):
        expected = files_for(package)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with tarfile.open(fileobj=io.BytesIO(archive(expected)), mode='r:') as tar:
                for item in tar:
                    dest = root / item.name
                    self.assertEqual((item.uid, item.gid), (0, 0))
                    # Explicitly forbid implicit parent creation: this is the
                    # relevant behavior of libopkg/pkg_extract.c.
                    self.assertTrue(dest.parent.is_dir(), 'Missing parent for ' + item.name)
                    if item.isdir():
                        self.assertEqual(item.mode, 0o755)
                        dest.mkdir()
                    else:
                        with dest.open('wb') as stream:
                            stream.write(tar.extractfile(item).read())
            for rel, content, _ in expected:
                self.assertEqual((root / rel).read_bytes(), content)

    def test_frontend_installs_into_clean_root(self):
        self.extract_like_opkg('luci-app-netmon')

    def test_backend_installs_into_clean_root(self):
        self.extract_like_opkg('netmon')


if __name__ == '__main__':
    unittest.main()
