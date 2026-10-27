const { Model, DataTypes } = require('sequelize');

/** User model (class style, Model.init). Its table is already created by a migration: the migration decides. */
class User extends Model {
  static associate(models) {
    this.hasMany(models.Order, { foreignKey: 'user_id' });
  }
}

module.exports = (sequelize) => {
  User.init({
    name: { type: DataTypes.STRING, allowNull: false },
    email: { type: DataTypes.STRING, unique: true },
  }, { sequelize, modelName: 'User', tableName: 'users', underscored: true });
  return User;
};
