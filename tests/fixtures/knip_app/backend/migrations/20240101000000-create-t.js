'use strict';
module.exports = { up: async (qi) => qi.createTable('t', {}), down: async (qi) => qi.dropTable('t') };
