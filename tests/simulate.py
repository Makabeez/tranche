"""Local simulation of tranche.py with a mocked genlayer module.

Runs the state machine through every path and checks that value is conserved:
everything escrowed or bonded ends up paid out, refunded, or still held.
"""
import sys, types, json

TRANSFERS = []
STATE = {"sender": None, "value": 0, "body": "", "jury": None}


class UserError(Exception):
    pass


class Address:
    def __init__(self, h):
        self.as_hex = h.lower()


class _Msg:
    @property
    def sender_address(self):
        return Address(STATE["sender"])

    @property
    def value(self):
        return STATE["value"]


def contract_interface(cls):
    class R:
        def __init__(self, addr):
            self.addr = addr

        def emit_transfer(self, value):
            TRANSFERS.append((self.addr.as_hex, int(value)))
    return R


class _Resp:
    def __init__(self, b):
        self.body = b.encode()


gl = types.ModuleType("genlayer")
gl.contract = types.SimpleNamespace(Contract=object)
gl.storage = types.SimpleNamespace(TreeMap=type("TM", (dict,), {"__class_getitem__": classmethod(lambda c, k: c)}))
ident = lambda f: f
gl.public = types.SimpleNamespace(
    write=types.SimpleNamespace(payable=ident, __call__=ident), view=ident)


class _W:
    payable = staticmethod(ident)

    def __call__(self, f):
        return f


gl.public.write = _W()
gl.message = _Msg()
gl.vm = types.SimpleNamespace(UserError=UserError)
gl.evm = types.SimpleNamespace(contract_interface=contract_interface)
gl.nondet = types.SimpleNamespace(
    web=types.SimpleNamespace(get=lambda url: _Resp(STATE["body"])),
    exec_prompt=lambda p: STATE["jury"](p))
gl.eq_principle = types.SimpleNamespace(prompt_comparative=lambda fn, principle: fn())
gtypes = types.ModuleType("genlayer.types")
gtypes.Address = Address
gtypes.u256 = int
gtypes.__all__ = ["Address", "u256"]
sys.modules["genlayer"] = gl
sys.modules["genlayer.types"] = gtypes

src = open(sys.argv[1] if len(sys.argv) > 1 else "tranche.py").read()
ns = {}
exec(compile(src, "tranche.py", "exec"), ns)
Tranche = ns["Tranche"]

FUNDER = "0x" + "a" * 40
BUILDER = "0x" + "B" * 40
OTHER = "0x" + "c" * 40
SHA = "d190a68915108b2335d25b6512535f5533a5cb27"
URL = "https://api.github.com/repos/x/y/contents?ref=" + SHA
LISTING = json.dumps([{"name": n, "type": "file"} for n in ["web_claims.py", "README.md", "tests", "LICENSE"]])
ERROR = '{"message":"Not Found","documentation_url":"https://docs.github.com/rest","status":"404"}'
RATE = '{"message":"API rate limit exceeded for 1.2.3.4. (But here\'s the good news...)","documentation_url":"https://docs.github.com/rest/overview/rate-limits"}'


def call(who, fn, *a, value=0):
    STATE["sender"], STATE["value"] = who, value
    return fn(*a)


def expect_error(who, fn, *a, value=0, contains=""):
    try:
        call(who, fn, *a, value=value)
    except UserError as e:
        assert contains in str(e), (contains, str(e))
        return str(e)
    raise AssertionError("expected UserError: " + contains)


def g(c, gid):
    return json.loads(c.get_grant(gid))


def jury_all(val):
    def f(prompt):
        n = prompt.split("<terms>")[1].split("</terms>")[0].strip().count("\n") + 1
        return json.dumps({"rulings": [{"id": i, "met": val} for i in range(n)]})
    return f


STATE["sender"] = FUNDER
c = Tranche("Tranche test")
c.grants = gl.storage.TreeMap()
held = {"v": 0}
A = 10 ** 17

spec = json.dumps([
    {"amount": str(A), "terms": ["contains: web_claims.py", "contains: README.md"]},
    {"amount": str(2 * A), "terms": ["array_min: $ >= 3", "the repository includes a tests directory"]},
    {"amount": str(A), "terms": ["contains: CHANGELOG.md"]},
])

# --- opening -----------------------------------------------------------
expect_error(FUNDER, c.open_grant, "g1", "brief", BUILDER, spec, value=3 * A, contains="must equal the sum")
expect_error(FUNDER, c.open_grant, "g1", "brief", "0x123", spec, value=4 * A, contains="builder must be")
expect_error(FUNDER, c.open_grant, "g1", "brief", BUILDER, "[]", value=0, contains="at least one")
expect_error(FUNDER, c.open_grant, "g1", "brief", BUILDER, '[{"amount":"-5","terms":["x"]}]', value=0, contains="whole number")
call(FUNDER, c.open_grant, "g1", "brief", BUILDER, spec, value=4 * A); held["v"] += 4 * A
expect_error(FUNDER, c.open_grant, "g1", "brief", BUILDER, spec, value=4 * A, contains="already exists")
assert g(c, "g1")["builder"] == BUILDER.lower()

# --- submit guards -----------------------------------------------------
expect_error(OTHER, c.submit, "g1", 0, URL, contains="only the builder")
expect_error(BUILDER, c.submit, "g1", 1, URL, contains="delivered in order")
expect_error(BUILDER, c.submit, "g1", 0, "https://github.com/x/y/tree/main", contains="immutable")
expect_error(FUNDER, c.finalize, "g1", 0, contains="nothing to finalize")

# --- tranche 0: inadmissible fetch, retry, mechanical approval ---------
call(BUILDER, c.submit, "g1", 0, URL)
STATE["body"] = RATE
v = call(OTHER, c.settle, "g1", 0)
assert "INADMISSIBLE" in v and "rate-limited" in v, v
STATE["body"] = ERROR
v = call(OTHER, c.settle, "g1", 0)
assert "API error object" in v, v
expect_error(FUNDER, c.cancel, "g1", contains="cannot cancel while tranche 0 is INADMISSIBLE")
STATE["body"] = LISTING
STATE["jury"] = lambda p: (_ for _ in ()).throw(AssertionError("jury must not run"))
v = call(OTHER, c.settle, "g1", 0)
assert v.startswith("RULED APPROVED") and "no jury" in v, v
expect_error(FUNDER, c.cancel, "g1", contains="cannot cancel")
expect_error(BUILDER, c.appeal, "g1", 0, value=A, contains="only the party")
expect_error(FUNDER, c.appeal, "g1", 0, value=A - 1, contains="bond must equal")
call(OTHER, c.finalize, "g1", 0)
assert TRANSFERS[-1] == (BUILDER.lower(), A); held["v"] -= A
st = g(c, "g1"); assert st["current"] == 1 and st["tranches"][0]["status"] == "PAID"

# --- tranche 1: jury rejects, builder appeals and loses, resubmits, passes
call(BUILDER, c.submit, "g1", 1, URL)
STATE["jury"] = jury_all(False)
v = call(OTHER, c.settle, "g1", 1)
assert v.startswith("RULED REJECTED") and "jury convened" in v, v
call(BUILDER, c.appeal, "g1", 1, value=2 * A); held["v"] += 2 * A
v = call(OTHER, c.settle, "g1", 1)   # second review agrees: rejected -> upheld
st = g(c, "g1")["tranches"][1]
assert st["status"] == "OPEN" and "upheld" in st["settlement"], st
assert TRANSFERS[-1] == (FUNDER.lower(), 2 * A), TRANSFERS[-1]; held["v"] -= 2 * A
call(BUILDER, c.submit, "g1", 1, URL)
STATE["jury"] = jury_all(True)
v = call(OTHER, c.settle, "g1", 1)
assert v.startswith("RULED APPROVED") and "jury convened" in v, v

# funder appeals the approval and the second review overturns it
call(FUNDER, c.appeal, "g1", 1, value=2 * A); held["v"] += 2 * A
STATE["jury"] = jury_all(False)
call(OTHER, c.settle, "g1", 1)
st = g(c, "g1")["tranches"][1]
assert st["status"] == "OPEN" and "overturned" in st["settlement"], st
assert TRANSFERS[-1] == (FUNDER.lower(), 2 * A); held["v"] -= 2 * A

# builder resubmits, approved, funder appeals, upheld -> builder gets bond + tranche
call(BUILDER, c.submit, "g1", 1, URL)
STATE["jury"] = jury_all(True)
call(OTHER, c.settle, "g1", 1)
call(FUNDER, c.appeal, "g1", 1, value=2 * A); held["v"] += 2 * A
call(OTHER, c.settle, "g1", 1)
assert TRANSFERS[-1] == (BUILDER.lower(), 4 * A), TRANSFERS[-1]; held["v"] -= 4 * A
st = g(c, "g1"); assert st["current"] == 2 and st["tranches"][1]["status"] == "PAID"
assert st["tranches"][1]["attempts"] == 3

# --- tranche 2: mechanical failure, jury skipped, then funder cancels ---
call(BUILDER, c.submit, "g1", 2, URL)
STATE["jury"] = lambda p: (_ for _ in ()).throw(AssertionError("jury must not run"))
v = call(OTHER, c.settle, "g1", 2)
assert v.startswith("RULED REJECTED") and "no jury" in v, v
expect_error(FUNDER, c.cancel, "g1", contains="cannot cancel while tranche 2 is RULED")
call(OTHER, c.finalize, "g1", 2)
assert g(c, "g1")["tranches"][2]["status"] == "OPEN"
expect_error(OTHER, c.cancel, "g1", contains="only the funder")
call(FUNDER, c.cancel, "g1")
assert TRANSFERS[-1] == (FUNDER.lower(), A); held["v"] -= A
st = g(c, "g1"); assert st["status"] == "CANCELLED"
expect_error(BUILDER, c.submit, "g1", 2, URL, contains="grant is CANCELLED")

# --- truncation: builder may resubmit after INCONCLUSIVE ----------------
call(FUNDER, c.open_grant, "g2", "b", BUILDER, json.dumps([{"amount": str(A), "terms": ["contains: x"]}]), value=A); held["v"] += A
call(BUILDER, c.submit, "g2", 0, URL)
STATE["body"] = "x" * 7000
v = call(OTHER, c.settle, "g2", 0)
assert v.startswith("INCONCLUSIVE"), v
expect_error(OTHER, c.settle, "g2", 0, contains="nothing to judge")
STATE["body"] = LISTING.replace("LICENSE", "x-file")
call(BUILDER, c.submit, "g2", 0, URL)
v = call(OTHER, c.settle, "g2", 0)
assert v.startswith("RULED APPROVED"), v
call(OTHER, c.finalize, "g2", 0); held["v"] -= A
assert g(c, "g2")["status"] == "COMPLETE"

# --- jury output validation reverts, nothing stored ----------------------
call(FUNDER, c.open_grant, "g3", "b", BUILDER, json.dumps([{"amount": str(A), "terms": ["judged one", "judged two"]}]), value=A); held["v"] += A
call(BUILDER, c.submit, "g3", 0, URL)
STATE["body"] = LISTING
for bad in ['{"rulings":[{"id":0,"met":true}]}',
            '{"rulings":[{"id":0,"met":true},{"id":0,"met":false}]}',
            '{"rulings":[{"id":0,"met":"yes"},{"id":1,"met":true}]}',
            '{"rulings":[{"id":0,"met":true},{"id":5,"met":true}]}']:
    STATE["jury"] = lambda p, b=bad: b
    before = c.grants["g3"]
    expect_error(OTHER, c.settle, "g3", 0)
    assert c.grants["g3"] == before

paid_out = sum(v for _, v in TRANSFERS)
print("transfers:", len(TRANSFERS), "| total paid out:", paid_out / 1e18, "GEN")
print("still held by contract (g3):", held["v"] / 1e18, "GEN")
assert held["v"] == A
print("ALL PATHS OK")
