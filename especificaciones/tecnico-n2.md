# Especificación técnica — Nivel 2

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

## Atributos de calidad esperados
Es importante que el proyecto resulte fácil de mantener a futuro:
- Se debe poder entender rápidamente qué hace cada parte del código.
- Se debe poder modificar una funcionalidad sin que eso rompa otras.
- Se debe poder agregar pruebas automatizadas sobre la lógica de negocio.

Evita concentrar demasiada lógica en un solo archivo o módulo, y separa
claramente las responsabilidades del sistema (por ejemplo, la lógica de
negocio de la persistencia de datos y de la interfaz de usuario).

## Lineamientos adicionales
No se impone una forma específica de organizar las capas internamente
más allá de lo anterior. Toma las decisiones de organización del código
que consideres más adecuadas para cumplir con lo anterior.

Entrega el proyecto completo y funcional, listo para ejecutarse
localmente.
