/** Coupon: no migration creates it, so only the model defines it (lowest source of preference). */
module.exports = (sequelize, DataTypes) => {
  const Coupon = sequelize.define('Coupon', {
    code: { type: DataTypes.STRING(20), allowNull: false, unique: true },
    percent: { type: DataTypes.INTEGER, allowNull: false },
  });
  Coupon.associate = (models) => {
    Coupon.belongsTo(models.User);
  };
  return Coupon;
};
