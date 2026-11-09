import pathlib, unittest, re
ROOT=pathlib.Path(__file__).parents[1]
class ReleaseContract(unittest.TestCase):
    def test_no_bundled_fonts(self):
        self.assertFalse(list(ROOT.rglob('*.ttf')))
    def test_installer_stages_before_activation(self):
        s=(ROOT/'install.sh').read_text()
        self.assertEqual(s.count('mv "$stage/sboc" /opt/sboc/sboc'),1)
        self.assertLess(s.index('"$PY" -m compileall'),s.index('mv "$stage/sboc" /opt/sboc/sboc'))
        self.assertLess(s.index('FONT_BASE='),s.index('mv "$stage/sboc" /opt/sboc/sboc'))
        self.assertIn('trap rollback EXIT',s)
        self.assertEqual(len(re.findall(r"^step '",s,re.M)),7)
    def test_license_and_security_docs(self):
        for name in ('README.md','LICENSE','SECURITY.md','TESTING.md','AUDIT.md','CHANGELOG.md'):
            self.assertTrue((ROOT/name).is_file(),name)
    def test_version(self):
        from sboc import __version__
        self.assertEqual(__version__,'0.2.43')
if __name__=='__main__':unittest.main()
