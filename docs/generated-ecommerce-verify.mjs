import assert from 'node:assert/strict';
import { writeFileSync } from 'node:fs';
const base = process.argv[2];
const output = process.argv[3];
const checks = [];
let token, otherToken, products, shirt, mug, book, order;
async function request(method, path, body, auth) {
  const response = await fetch(base + '/api' + path, {
    method, headers: { 'Content-Type': 'application/json', ...(auth ? { Authorization: 'Bearer ' + auth } : {}) },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }), signal: AbortSignal.timeout(15000)
  });
  let data;
  try { data = await response.json(); } catch { data = null; }
  return { status: response.status, data };
}
async function check(name, run) {
  try { await run(); checks.push({ name, ok: true }); }
  catch (error) { checks.push({ name, ok: false, error: error.message }); }
}
function status(result, expected) { assert.equal(result.status, expected, JSON.stringify(result)); return result.data; }
function numeric(value) { assert.equal(typeof value, 'number'); assert.ok(Number.isFinite(value)); }
const users = [
  { name: 'QA Ann', email: 'qa-ann@example.test', password: 'Passw0rd!x' },
  { name: 'QA Bob', email: 'qa-bob@example.test', password: 'Passw0rd!x' }
];
await check('catalog and initial PostgreSQL seed', async () => {
  products = status(await request('GET', '/products'), 200);
  assert.ok(Array.isArray(products));
  shirt = products.find(p => p.name === 'T-shirt'); mug = products.find(p => p.name === 'Mug'); book = products.find(p => p.name === 'Book');
  for (const [product, price, stock] of [[shirt, 10, 20], [mug, 5, 2], [book, 20, 50]]) {
    assert.ok(product); numeric(product.price); assert.equal(product.price, price); assert.equal(product.stock, stock);
    assert.equal(typeof product.description, 'string'); assert.equal(typeof product.imageUrl, 'string');
  }
});
await check('register two independent users', async () => { for (const user of users) status(await request('POST', '/auth/register', user), 201); });
await check('duplicate registration returns 409', async () => { status(await request('POST', '/auth/register', users[0]), 409); });
await check('incorrect credentials return 401', async () => { status(await request('POST', '/auth/login', { ...users[0], password: 'incorrect' }), 401); });
await check('login returns bearer tokens', async () => {
  token = status(await request('POST', '/auth/login', users[0]), 200).token;
  otherToken = status(await request('POST', '/auth/login', users[1]), 200).token;
  assert.equal(typeof token, 'string'); assert.equal(typeof otherToken, 'string'); assert.ok(token && otherToken);
});
await check('protected endpoints reject missing session', async () => {
  status(await request('GET', '/orders'), 401);
  status(await request('POST', '/checkout', { items: [{ productId: shirt.id, quantity: 1 }] }), 401);
  status(await request('PATCH', '/orders/1/status', { status: 'paid' }), 401);
});
for (const [quantity, expected] of [[2, 20], [3, 27], [5, 45]]) {
  await check(`volume discount: ${quantity} T-shirt totals ${expected}`, async () => {
    const quote = status(await request('POST', '/cart/quote', { items: [{ productId: shirt.id, quantity }] }), 200);
    numeric(quote.total); numeric(quote.lines[0].unitPrice); numeric(quote.lines[0].lineTotal);
    assert.equal(quote.total, expected); assert.equal(quote.lines[0].lineTotal, expected);
  });
}
await check('combined quote totals 47', async () => {
  const quote = status(await request('POST', '/cart/quote', { items: [{ productId: shirt.id, quantity: 3 }, { productId: book.id, quantity: 1 }] }), 200);
  assert.equal(quote.total, 47);
});
await check('invalid negative quantities rejected', async () => {
  const quote = await request('POST', '/cart/quote', { items: [{ productId: shirt.id, quantity: -1 }] });
  assert.ok(quote.status === 400 || quote.status === 422, JSON.stringify(quote));
});
await check('insufficient stock rolls back every product', async () => {
  status(await request('POST', '/checkout', { items: [{ productId: mug.id, quantity: 3 }, { productId: book.id, quantity: 1 }] }, token), 409);
  const catalog = status(await request('GET', '/products'), 200);
  assert.equal(catalog.find(p => p.id === mug.id).stock, 2); assert.equal(catalog.find(p => p.id === book.id).stock, 50);
  assert.deepEqual(status(await request('GET', '/orders', undefined, token), 200), []);
});
await check('checkout persists pending order and discounts', async () => {
  order = status(await request('POST', '/checkout', { items: [{ productId: shirt.id, quantity: 3 }, { productId: book.id, quantity: 1 }] }, token), 201);
  assert.ok(order.id); assert.equal(order.status, 'pending'); numeric(order.total); assert.equal(order.total, 47);
  const catalog = status(await request('GET', '/products'), 200);
  assert.equal(catalog.find(p => p.id === shirt.id).stock, 17); assert.equal(catalog.find(p => p.id === book.id).stock, 49);
});
await check('orders belong to authenticated user only', async () => {
  const mine = status(await request('GET', '/orders', undefined, token), 200); assert.ok(mine.some(p => p.id === order.id));
  assert.deepEqual(status(await request('GET', '/orders', undefined, otherToken), 200), []);
  const forbidden = await request('PATCH', '/orders/' + order.id + '/status', { status: 'paid' }, otherToken);
  assert.ok(forbidden.status === 403 || forbidden.status === 404, JSON.stringify(forbidden));
});
await check('state machine refuses skipping pending to shipped', async () => { status(await request('PATCH', '/orders/' + order.id + '/status', { status: 'shipped' }, token), 409); });
await check('state machine advances pending to paid', async () => { status(await request('PATCH', '/orders/' + order.id + '/status', { status: 'paid' }, token), 200); });
await check('state machine refuses going back to pending', async () => { status(await request('PATCH', '/orders/' + order.id + '/status', { status: 'pending' }, token), 409); });
await check('state machine advances paid to shipped and persists', async () => {
  status(await request('PATCH', '/orders/' + order.id + '/status', { status: 'shipped' }, token), 200);
  const mine = status(await request('GET', '/orders', undefined, token), 200); assert.equal(mine.find(p => p.id === order.id).status, 'shipped');
});
await check('buying the last two mugs leaves zero stock', async () => {
  const bought = status(await request('POST', '/checkout', { items: [{ productId: mug.id, quantity: 2 }] }, token), 201);
  assert.equal(bought.total, 10);
  const catalog = status(await request('GET', '/products'), 200); assert.equal(catalog.find(p => p.id === mug.id).stock, 0);
});
await check('concurrent purchases cannot oversell', async () => {
  const body = { items: [{ productId: shirt.id, quantity: 10 }] };
  const results = await Promise.all([request('POST', '/checkout', body, token), request('POST', '/checkout', body, otherToken)]);
  assert.deepEqual(results.map(r => r.status).sort(), [201, 409]);
  const catalog = status(await request('GET', '/products'), 200); assert.equal(catalog.find(p => p.id === shirt.id).stock, 7);
});
const report = { base, passed: checks.filter(c => c.ok).length, total: checks.length, checks };
writeFileSync(output, JSON.stringify(report, null, 2));
console.log(JSON.stringify(report, null, 2));
process.exitCode = report.passed === report.total ? 0 : 1;
