# Especificación técnica — Nivel 3

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

## Lineamientos arquitectónicos

### 1. Estructura y modularidad
Implementa las capas de presentación, lógica de negocio y acceso a
datos con separación estricta de responsabilidades. Cada módulo debe
tener una única responsabilidad (principio de responsabilidad única de
SOLID) y una interfaz de comunicación clara hacia las demás capas, sin
saltos directos entre capas no adyacentes.

### 2. Dependencias e integración
Usa Mongoose como ODM para el acceso a datos en MongoDB. Aplica
inyección de dependencias donde corresponda, y evita el acoplamiento
directo entre la lógica de negocio y frameworks o librerías
específicas (por ejemplo, la lógica de negocio no debe depender
directamente de Express ni de Mongoose).

### 3. Transversales de calidad
- Incluye pruebas unitarias automatizadas para la lógica de negocio.
- Implementa manejo explícito de errores y validación de entradas en
  cada capa (backend y frontend).
- Evita la duplicación de código y las funciones o clases con
  complejidad excesiva.
- Documenta brevemente, en el README, las decisiones de diseño
  adoptadas y su justificación.

Entrega el proyecto completo y funcional, listo para ejecutarse
localmente.
