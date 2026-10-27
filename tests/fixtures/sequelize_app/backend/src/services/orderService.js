const { Op } = require('sequelize');

/** Lists the orders of a user, newest first. */
async function listOrders(models, userId) {
  return models.Order.findAll({ where: { user_id: userId }, order: [['created_at', 'DESC']] });
}

/** Finds a user by e-mail or name. */
async function findUser(models, email) {
  return models.User.findOne({ where: { [Op.or]: [{ email }, { name: email }] } });
}

/** Raw SQL with parameters, and one built by interpolation (injectable). */
async function raw(sequelize, status) {
  await sequelize.query('SELECT * FROM orders WHERE status = :status', { replacements: { status } });
  return sequelize.query(`SELECT * FROM orders WHERE total > ${status}`);
}

module.exports = { listOrders, findUser, raw };
