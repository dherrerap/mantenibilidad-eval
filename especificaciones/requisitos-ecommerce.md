# Requerimientos funcionales — E-commerce

Aplicación web de comercio electrónico.

## Funcionalidades principales
- Catálogo de productos: imagen, nombre, precio, descripción y stock
  disponible.
- Carrito de compras: agregar, eliminar y modificar cantidades. El
  carrito vive en el cliente hasta el checkout.
- Registro e inicio de sesión de usuarios. Todos los usuarios tienen el
  mismo rol (no hay administradores).
- Checkout que simule una compra (no requiere pasarela de pago real).
- Persistencia de productos, usuarios y pedidos en MongoDB.
- Consulta de los pedidos propios con su estado actual.

## Datos iniciales
Si la base de datos está vacía, el backend debe insertar al iniciar
estos productos:

| Nombre   | Precio | Stock |
|----------|-------:|------:|
| Camiseta |  10.00 |    20 |
| Taza     |   5.00 |     2 |
| Libro    |  20.00 |    50 |

Cada producto lleva además una descripción y una URL de imagen
cualesquiera.

## Lógica de negocio obligatoria
- **Descuento por volumen**: si un usuario agrega 3 o más unidades de
  un mismo producto al carrito, se aplica un 10% de descuento sobre esa
  línea del pedido (sobre el total de la línea, no solo sobre las
  unidades adicionales). El cálculo debe reflejarse en el carrito antes
  del checkout. Los importes se redondean a 2 decimales.
  - 2 × Camiseta → línea de 20.00
  - 3 × Camiseta → línea de 27.00 (30.00 − 10%)
  - 5 × Camiseta → línea de 45.00 (50.00 − 10%)
  - 3 × Camiseta + 1 × Libro → total de 47.00
- **Validación de stock**: no se puede completar un checkout si la
  cantidad solicitada de algún producto excede el stock disponible en
  ese momento. Si algún producto no alcanza, no se descuenta stock de
  ninguno. Al confirmar la compra, el stock del producto debe
  descontarse.
  - Con Taza en stock 2: comprar 2 Taza es válido y deja el stock en 0;
    comprar 3 Taza se rechaza y el stock se mantiene en 2.
- **Estados del pedido**: cada pedido se crea en estado `pendiente` y
  solo puede avanzar `pendiente → pagado → despachado`, un paso a la
  vez y sin retroceder. Cualquier usuario autenticado puede avanzar el
  estado de sus propios pedidos (es una simulación). El usuario debe
  poder ver el estado actual de sus pedidos anteriores y no puede ver
  los de otros usuarios.

## Interfaz HTTP mínima del backend
Además de lo que necesite tu interfaz de usuario, el backend debe
exponer estas rutas bajo `/api`, con cuerpos y respuestas en JSON. Se
usan para verificar la entrega de forma automática.

| Ruta | Descripción | Respuesta |
|------|-------------|-----------|
| `POST /api/auth/register` con `{name, email, password}` | Registra un usuario | `201`; `409` si el email ya existe |
| `POST /api/auth/login` con `{email, password}` | Inicia sesión | `200` con `{token}`; `401` si las credenciales son inválidas |
| `GET /api/products` | Lista el catálogo | `200`, arreglo de `{id, name, price, description, imageUrl, stock}` |
| `POST /api/cart/quote` con `{items: [{productId, quantity}]}` | Calcula el carrito con el descuento por volumen | `200` con `{lines: [{productId, quantity, unitPrice, lineTotal}], total}` |
| `POST /api/checkout` con `{items: [{productId, quantity}]}` | Confirma la compra (requiere sesión) | `201` con `{id, status, total}`; `409` si falta stock |
| `GET /api/orders` | Lista los pedidos del usuario (requiere sesión) | `200`, arreglo de `{id, status, total}` |
| `PATCH /api/orders/:id/status` con `{status}` | Avanza el estado del pedido (requiere sesión) | `200`; `409` si la transición no es válida |

Las rutas protegidas reciben el encabezado `Authorization: Bearer <token>`
y responden `401` si no se envía un token válido.

Entrega el proyecto completo y funcional, listo para ejecutarse
localmente.
