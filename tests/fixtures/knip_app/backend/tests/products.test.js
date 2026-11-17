const request = require('supertest'); const app = require('../src/app'); test('x', async () => { await request(app).get('/api/products'); });
