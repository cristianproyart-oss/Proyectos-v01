"""Pruebas de las partes Python (no necesitan Civil 3D). Ejecuta: python -m unittest tests/test_all.py"""
import json, os, subprocess, sys, tempfile, unittest, zipfile
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, os.path.join(ROOT, "sac"), os.path.join(ROOT, "mcp")]
import make_sample, pktlib as L, pkt_tool, fake_bridge

class Pkt(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.a = os.path.join(self.d, "a.pkt"); make_sample.build(self.a)
        self.b = os.path.join(self.d, "b.pkt"); make_sample.build(self.b, descriptor=True)

    def test_roundtrip_identical(self):
        for p in (self.a, self.b):
            raw = open(p, "rb").read()
            self.assertEqual(L.Package.from_bytes(raw).to_bytes(), raw)

    def test_edit_keeps_rest(self):
        for p in (self.a, self.b):
            pkg = L.Package.open(p)
            t, enc, bom = L.decode_text(pkg.read("Subassembly.xaml"))
            t2, n = L.edit_attr(t, lambda tag: tag.attrs.get("DisplayName") == "L1", "Codes", 'Top,"X"')
            self.assertEqual(n, 1)
            pkg.write_entry("Subassembly.xaml", L.encode_text(t2, enc, bom))
            new = pkg.to_bytes()
            z = zipfile.ZipFile(__import__("io").BytesIO(new)); self.assertIsNone(z.testzip())
            x = z.read("Subassembly.xaml").decode("utf-8-sig")
            self.assertIn('Codes="Top,&quot;X&quot;"', x)
            self.assertIn("<!-- comentario que debe conservarse -->", x)
            self.assertEqual(z.read("Packet.xml"), zipfile.ZipFile(p).read("Packet.xml"))
            self.assertEqual(z.comment, b"comentario zip")
            self.assertTrue(x.startswith("<Activity") and t2.count("\n") == t.count("\n"))

    def test_analyze(self):
        pkg = L.Package.open(self.a)
        an = L.analyze_xaml(L.decode_text(pkg.read("Subassembly.xaml"))[0])
        self.assertEqual([p["name"] for p in an.params], ["Ancho", "Prof", "SuperficieTN", "AreaSalida"])
        self.assertEqual(an.defaults, {"Ancho": "0.6", "Prof": "0.3"})
        self.assertEqual(an.params[2]["kind"], "target")
        self.assertEqual(an.counts.get("point"), 1); self.assertEqual(an.counts.get("decision"), 1)
        self.assertEqual(an.activity_prefixes, ["asa1"])

    def test_rename_class(self):
        t = L.decode_text(L.Package.open(self.a).read("Subassembly.xaml"))[0]
        t2, old, k = pkt_tool.rename_class(t, "Nuevo")
        self.assertEqual((old, k), ("CunetaPrueba", 2))
        self.assertIn('x:Class="Nuevo" this:Nuevo.Ancho="0.6"', t2)

    def test_compare(self):
        exp = {"points": [{"codes": ["ETW"], "offset": 0.6, "elevation": -0.3}]}
        self.assertEqual(pkt_tool.compare(exp, {"points": [{"codes": ["ETW"], "offset": 0.6000001, "elevation": -0.3}]}, 1e-3), [])
        self.assertTrue(pkt_tool.compare(exp, {"points": [{"codes": ["ETW"], "offset": 0.7, "elevation": -0.3}]}, 1e-3))

class Mcp(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.srv, self.calls = fake_bridge.serve(self.d)

    def tearDown(self):
        self.srv.close()

    def rpc(self, msgs):
        env = dict(os.environ, LOCALAPPDATA=self.d)
        inp = "\n".join(json.dumps(m) for m in msgs) + "\n"
        r = subprocess.run([sys.executable, os.path.join(ROOT, "mcp", "civil_agent_mcp.py")], input=inp.encode(),
                           capture_output=True, env=env, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr.decode())
        return [json.loads(l) for l in r.stdout.decode().splitlines() if l.strip()]

    def test_protocol(self):
        out = self.rpc([
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "run_query", "arguments": {"code": "return 1;"}}},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "run_modify", "arguments": {"code": "x", "confirmed": False, "summary": "s"}}},
            {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "run_modify", "arguments": {"code": "x", "confirmed": True, "summary": "s"}}},
            {"jsonrpc": "2.0", "id": 6, "method": "tools/call", "params": {"name": "lookup_api", "arguments": {"query": "Alignment.GetProfileIds"}}},
            {"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": "capture_view", "arguments": {}}},
            {"jsonrpc": "2.0", "id": 8, "method": "tools/call", "params": {"name": "get_context", "arguments": {}}},
            {"jsonrpc": "2.0", "id": 9, "method": "tools/call", "params": {"name": "run_query", "arguments": {"code": "ERRCOMP"}}},
        ])
        by = {o["id"]: o for o in out}
        self.assertEqual(len(out), 9)  # la notificación no responde
        self.assertEqual(by[1]["result"]["serverInfo"]["name"], "civil-agent")
        self.assertIn("get_context", by[1]["result"]["instructions"])
        self.assertEqual({t["name"] for t in by[2]["result"]["tools"]}, {"get_context", "run_query", "run_modify", "lookup_api", "capture_view"})
        self.assertFalse(by[3]["result"]["isError"]); self.assertIn("commit=False", by[3]["result"]["content"][0]["text"])
        self.assertTrue(by[4]["result"]["isError"])
        self.assertIn("commit=True", by[5]["result"]["content"][0]["text"])
        self.assertIn("GetProfileIds", by[6]["result"]["content"][0]["text"])
        self.assertEqual(by[7]["result"]["content"][0]["type"], "image")
        self.assertFalse(by[8]["result"]["isError"])
        self.assertTrue(by[9]["result"]["isError"]); self.assertIn("línea 2", by[9]["result"]["content"][0]["text"])
        ops = [c["op"] for c in self.calls]
        self.assertEqual(ops.count("modify"), 1)  # confirmed=False no llega al add-in
        self.assertTrue(all(c["token"] == "t0k3n" for c in self.calls))

    def test_bad_token(self):
        p = os.path.join(self.d, "Civil3DAgent", "session.json")
        s = json.load(open(p)); s["token"] = "malo"; json.dump(s, open(p, "w"))
        out = self.rpc([{"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "run_query", "arguments": {"code": "1"}}}])
        self.assertTrue(out[0]["result"]["isError"]); self.assertIn("token", out[0]["result"]["content"][0]["text"])

    def test_civil_call(self):
        env = dict(os.environ, LOCALAPPDATA=self.d)
        r = subprocess.run([sys.executable, os.path.join(ROOT, "mcp", "civil_call.py"), "query", "-e", "return 1;"], capture_output=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr); self.assertTrue(json.loads(r.stdout)["ok"])
        r = subprocess.run([sys.executable, os.path.join(ROOT, "mcp", "civil_call.py"), "modify", "-e", "x"], capture_output=True, env=env)
        self.assertEqual(r.returncode, 2)

if __name__ == "__main__":
    unittest.main()
