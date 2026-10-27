/** Order model (sequelize.define style). */
module.exports = (sequelize, DataTypes) => {
  const Order = sequelize.define('Order', {
    status: { type: DataTypes.STRING, allowNull: false },
    total: { type: DataTypes.DECIMAL(12, 2), allowNull: false },
  }, { tableName: 'orders', underscored: true });
  Order.associate = (models) => {
    Order.belongsTo(models.User, { foreignKey: 'user_id' });
  };
  return Order;
};
