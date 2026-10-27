'use strict';
/** Creates orders and order_items. */
module.exports = {
  async up(queryInterface, Sequelize) {
    await queryInterface.createTable('orders', {
      id: { type: Sequelize.INTEGER, primaryKey: true, autoIncrement: true, allowNull: false },
      user_id: { type: Sequelize.INTEGER, allowNull: false, references: { model: 'users', key: 'id' }, onDelete: 'CASCADE' },
      status: { type: Sequelize.STRING(20), allowNull: false, defaultValue: 'pending' },
      total: { type: Sequelize.DECIMAL(12, 2), allowNull: false },
    });
    await queryInterface.createTable('order_items', {
      order_id: { type: Sequelize.INTEGER, allowNull: false },
      product_ref: { type: Sequelize.INTEGER, allowNull: false },
      quantity: { type: Sequelize.INTEGER, allowNull: false },
    });
  },
  async down(queryInterface) {
    await queryInterface.dropTable('order_items');
    await queryInterface.dropTable('orders');
  },
};
