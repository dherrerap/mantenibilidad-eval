const { Sequelize, DataTypes } = require('sequelize');
const sequelize = new Sequelize(process.env.DATABASE_URL);

/** Models only (no migrations): the schema comes from sync(). */
const Student = sequelize.define('Student', { name: { type: DataTypes.STRING, allowNull: false } });
const Course = sequelize.define('Course', { title: { type: DataTypes.STRING, allowNull: false }, price: { type: DataTypes.FLOAT } });
const Teacher = sequelize.define('Teacher', { name: DataTypes.STRING }, { timestamps: false });

Student.belongsToMany(Course, { through: 'Enrollments' });
Course.belongsToMany(Student, { through: 'Enrollments' });
Teacher.hasMany(Course, { foreignKey: 'teacherId' });
Course.belongsTo(Teacher, { foreignKey: 'teacherId' });

module.exports = { sequelize, Student, Course, Teacher };
