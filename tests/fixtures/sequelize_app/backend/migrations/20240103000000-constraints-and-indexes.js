'use strict';
/** Adds constraints and indexes afterwards (addConstraint / addIndex). */
module.exports = {
  async up(queryInterface) {
    await queryInterface.addConstraint('order_items', { fields: ['order_id', 'product_ref'], type: 'primary key', name: 'order_items_pk' });
    await queryInterface.addConstraint('order_items', {
      fields: ['order_id'], type: 'foreign key', name: 'order_items_order_fk',
      references: { table: 'orders', field: 'id' }, onDelete: 'cascade',
    });
    await queryInterface.addConstraint('orders', { fields: ['total'], type: 'check', where: { total: { gte: 0 } }, name: 'orders_total_chk' });
    await queryInterface.addIndex('orders', ['user_id'], { name: 'orders_user_id_idx' });
  },
  async down(queryInterface) {
    await queryInterface.removeIndex('orders', 'orders_user_id_idx');
  },
};
