# Especificación técnica — Nivel 1

Vas a construir una **aplicación web**.

## Stack obligatorio
Debes usar el stack MERN:
- MongoDB como base de datos
- Express.js para el backend
- React para el frontend
- Node.js como entorno de ejecución del servidor

Puedes usar JavaScript o TypeScript, a tu criterio.

## Estilo arquitectónico
La aplicación debe ser un **monolito organizado en capas** (no se
aceptan microservicios, arquitecturas serverless ni aplicaciones
móviles nativas).

## Condiciones de entrega
- En la raíz del proyecto deben existir las carpetas `backend/` y
  `frontend/`, cada una con su propio `package.json`.
- Cada carpeta debe poder instalarse con `npm install` y ejecutarse con
  `npm start`.
- El backend debe tomar el puerto en el que escucha de la variable de
  entorno `PORT` y la URL de conexión a MongoDB de la variable de
  entorno `MONGODB_URI`.
- En la raíz debe existir un `README.md` con las instrucciones de
  instalación y ejecución y la estructura del proyecto.

## Lineamientos adicionales
No hay lineamientos adicionales sobre cómo organizar las capas
internamente, ni sobre prácticas de calidad. Toma tú las decisiones de
diseño, organización del código y estructura del proyecto que
consideres adecuadas.

Entrega el proyecto completo y funcional, listo para ejecutarse
localmente.
