const express = require('express'); const products = require('./routes/products'); const app = express(); app.use('/api/products', products); module.exports = app;
