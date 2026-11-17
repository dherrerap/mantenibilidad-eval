const { Pool } = require('pg'); module.exports = new Pool(); module.exports.unusedHelper = () => 1;
