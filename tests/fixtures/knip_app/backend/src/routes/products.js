const { Router } = require('express'); const db = require('../db'); const r = Router(); r.get('/', async (q, s) => s.json(await db.query('select 1'))); module.exports = r;
