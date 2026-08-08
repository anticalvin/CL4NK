#!/usr/bin/env python3
"""Adversarial boundary tests for CL4NK tools. Uses only the standard library."""
import os, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
import tools

class ToolBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name).resolve(); self.ctx={"workspace":str(self.root),"command_allowlist":["python","python3"]}
        (self.root/"ok.txt").write_text("hello CL4NK",encoding="utf-8")
    def tearDown(self): self.tmp.cleanup()

    def test_parent_traversal_rejected(self):
        with self.assertRaises(ValueError): tools.execute("read_file",{"path":"../../etc/passwd"},self.ctx)

    def test_absolute_escape_rejected(self):
        with self.assertRaises(ValueError): tools.execute("read_file",{"path":"/etc/passwd"},self.ctx)

    def test_symlink_escape_rejected(self):
        outside=Path(self.tmp.name).parent/"cl4nk-outside-test.txt"; outside.write_text("secret",encoding="utf-8")
        link=self.root/"escape"
        try: link.symlink_to(outside)
        except (OSError,NotImplementedError): self.skipTest("symlinks unavailable")
        try:
            with self.assertRaises(ValueError): tools.execute("read_file",{"path":"escape"},self.ctx)
        finally:
            try: outside.unlink()
            except OSError: pass

    def test_unknown_arguments_fail_closed(self):
        with self.assertRaises(ValueError): tools.execute("read_file",{"path":"ok.txt","surprise":"boom"},self.ctx)

    def test_missing_required_argument_fails(self):
        with self.assertRaises(ValueError): tools.execute("write_file",{"content":"x"},self.ctx)

    def test_oversized_write_rejected(self):
        with self.assertRaises(ValueError): tools.execute("write_file",{"path":"big.txt","content":"x"*(tools.MAX_TEXT+1)},self.ctx)

    def test_private_network_fetch_blocked(self):
        with self.assertRaises(ValueError): tools.execute("fetch_url",{"url":"http://127.0.0.1:8000/secret"},self.ctx)
        with self.assertRaises(ValueError): tools.execute("fetch_url",{"url":"http://169.254.169.254/latest/meta-data/"},self.ctx)

    def test_command_requires_allowlisted_executable(self):
        with self.assertRaises(PermissionError): tools.execute("run_command",{"argv":["sh","-c","echo nope"]},self.ctx)

    def test_command_is_argv_not_shell(self):
        result=tools.execute("run_command",{"argv":["python","-c","print('safe')"]},self.ctx)
        self.assertEqual(result["returncode"],0); self.assertEqual(result["stdout"].strip(),"safe")

    def test_command_cwd_cannot_escape(self):
        with self.assertRaises(ValueError): tools.execute("run_command",{"argv":["python","-V"],"cwd":"../../"},self.ctx)

    def test_schema_rejects_wrong_types(self):
        with self.assertRaises(ValueError): tools.execute("read_file",{"path":123},self.ctx)
        with self.assertRaises(ValueError): tools.execute("run_command",{"argv":"python -V"},self.ctx)

    def test_public_host_guard_rejects_dns_to_private_ip(self):
        fake=[(2,1,6,'',('10.0.0.4',0))]
        with patch('socket.getaddrinfo',return_value=fake):
            with self.assertRaises(ValueError): tools._validated_url('https://example.invalid/x')

if __name__=='__main__': unittest.main(verbosity=2)
