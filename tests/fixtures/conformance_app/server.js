// Fixture for contract_conformance.py: a tiny API that deviates from docs/openapi.yaml on purpose.
//   GET  /api/products  id is a string, the contract says integer          -> invalid response
//   GET  /api/health    not in the contract                                  -> undocumented route
//   POST /api/orders    201 with a valid body, 400 on invalid input (both declared)
//   GET  /api/orders/1  returns 418, a status the contract does not declare -> undocumented status
const port = Number(process.argv[2] || 4801);
require("http").createServer((q, s) => {
  s.setHeader("Content-Type", "application/json");
  let body = "";
  q.on("data", (c) => (body += c));
  q.on("end", () => {
    if (q.method === "GET" && q.url === "/api/products") return s.end(JSON.stringify([{ id: "one", name: "x", price: 10 }]));
    if (q.method === "GET" && q.url === "/api/health") return s.end(JSON.stringify({ ok: true }));
    if (q.method === "POST" && q.url === "/api/orders") {
      const qty = (JSON.parse(body || "{}") || {}).qty;
      if (!Number.isInteger(qty)) { s.statusCode = 400; return s.end(JSON.stringify({ error: "qty must be an integer" })); }
      s.statusCode = 201; return s.end(JSON.stringify({ id: 1, qty }));
    }
    s.statusCode = 418; s.end(JSON.stringify({ error: "teapot" }));
  });
}).listen(port, "127.0.0.1");
