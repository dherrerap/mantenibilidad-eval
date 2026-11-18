// A stand-in cinema API (requirements-cinema.md) for the differential test of the cinema acceptance suite: no generated cinema app
// exists yet. It follows the requirements with one deliberate defect, so that failing cases are compared too: GET /api/orders gives
// each total as a string ("18.00") instead of a JSON number.
//   node tests/js/mock_cinema.mjs <port>
import http from "node:http";

const port = Number(process.argv[2] || 4100);
const users = new Map(), tokens = new Map(), orders = [];
const movies = [{ id: 1, title: "Movie One", description: "First", imageUrl: "/m1.png" }, { id: 2, title: "Movie Two", description: "Second", imageUrl: "/m2.png" }];
const at = (h, m) => { const d = new Date(); d.setHours(h, m, 0, 0); d.setDate(d.getDate() + 1); return d.toISOString(); };
const showtimes = [[1, 1, 14, 0], [2, 1, 16, 30], [3, 2, 20, 0], [4, 2, 21, 0]].map(([id, movieId, h, m]) => ({ id, movieId, startsAt: at(h, m), room: `Room ${movieId}`, price: h >= 17 ? 9 : 6 }));
const seats = new Map();  // showtime id -> [{id, label, status, holder}]
let seatId = 1, orderId = 1;
for (const st of showtimes) seats.set(st.id, [..."ABCD"].flatMap((r) => [1, 2, 3, 4, 5].map((n) => ({ id: seatId++, label: `${r}${n}`, status: "available", holder: null }))));

const send = (res, status, body) => { res.writeHead(status, { "Content-Type": "application/json" }); res.end(body === undefined ? "" : JSON.stringify(body)); };
const user = (req) => tokens.get(String(req.headers.authorization || "").replace(/^Bearer /, "")) || null;
const pick = (st, ids) => (seats.get(st) || []).filter((s) => ids.map(String).includes(String(s.id)));

http.createServer((req, res) => {
  let raw = "";
  req.on("data", (c) => { raw += c; });
  req.on("end", () => {
    let body = {};
    try { body = raw ? JSON.parse(raw) : {}; } catch { return send(res, 400, { error: "bad json" }); }
    const u = new URL(req.url, "http://h"), p = u.pathname, m = req.method;
    let mm;
    if (m === "POST" && p === "/api/auth/register") {
      if (users.has(body.email)) return send(res, 409, { error: "exists" });
      users.set(body.email, { id: users.size + 1, ...body });
      return send(res, 201, { id: users.size, email: body.email });
    }
    if (m === "POST" && p === "/api/auth/login") {
      const x = users.get(body.email);
      if (!x || x.password !== body.password) return send(res, 401, { error: "bad credentials" });
      const t = `t${x.id}-${tokens.size}`;
      tokens.set(t, x);
      return send(res, 200, { token: t });
    }
    if (m === "GET" && p === "/api/movies") return send(res, 200, movies);
    if (m === "GET" && p === "/api/showtimes") return send(res, 200, showtimes);
    if (m === "GET" && (mm = /^\/api\/showtimes\/(\w+)\/seats$/.exec(p))) {
      const list = seats.get(Number(mm[1]));
      return list ? send(res, 200, list.map(({ id, label, status }) => ({ id, label, status }))) : send(res, 404, { error: "no showtime" });
    }
    if (m === "POST" && (mm = /^\/api\/showtimes\/(\w+)\/quote$/.exec(p))) {
      const st = showtimes.find((s) => s.id === Number(mm[1]));
      if (!st) return send(res, 404, { error: "no showtime" });
      const n = pick(st.id, body.seatIds || []).length;
      return send(res, 200, { unitPrice: st.price, total: st.price * n, seats: n });
    }
    const me = user(req);
    if (m === "POST" && (mm = /^\/api\/showtimes\/(\w+)\/lock$/.exec(p))) {
      if (!me) return send(res, 401, { error: "auth" });
      const chosen = pick(Number(mm[1]), body.seatIds || []);
      if (!chosen.length || chosen.some((s) => s.status === "sold" || (s.status === "locked" && s.holder !== me.id))) return send(res, 409, { error: "taken" });
      for (const s of chosen) { s.status = "locked"; s.holder = me.id; }
      return send(res, 200, { seatIds: chosen.map((s) => s.id), expiresAt: new Date(Date.now() + 600000).toISOString() });
    }
    if (m === "POST" && p === "/api/checkout") {
      if (!me) return send(res, 401, { error: "auth" });
      const st = showtimes.find((s) => String(s.id) === String(body.showtimeId));
      const chosen = st ? pick(st.id, body.seatIds || []) : [];
      if (!st || !chosen.length || chosen.some((s) => s.status === "sold" || (s.status === "locked" && s.holder !== me.id))) return send(res, 409, { error: "unavailable" });
      for (const s of chosen) { s.status = "sold"; s.holder = me.id; }
      const o = { id: orderId++, userId: me.id, showtimeId: st.id, seatIds: chosen.map((s) => s.id), total: st.price * chosen.length };
      orders.push(o);
      return send(res, 201, o);
    }
    if (m === "GET" && p === "/api/orders") {
      if (!me) return send(res, 401, { error: "auth" });
      return send(res, 200, orders.filter((o) => o.userId === me.id).map((o) => ({ ...o, total: o.total.toFixed(2) })));  // the deliberate defect
    }
    return send(res, 404, { error: "not found" });
  });
}).listen(port, "127.0.0.1");
