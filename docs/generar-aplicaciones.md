# Generar las aplicaciones (paso 1)

El evaluador recibe aplicaciones ya hechas. Esta guía describe cómo producirlas con un agente de IA de forma comparable.
Si ya tiene las aplicaciones, salte a "Uso" en el [README](../README.md).

## Qué hay en `especificaciones/`

| Archivo | Contenido |
|---|---|
| `requisitos-ecommerce.md` | Qué debe hacer la aplicación (igual para todos los niveles). |
| `tecnico-n1.md` | Nivel 1: solo stack MERN, monolito en capas y condiciones de entrega. |
| `tecnico-n2.md` | Nivel 2: N1 más atributos de calidad esperados (entendible, modificable, testeable). |
| `tecnico-n3.md` | Nivel 3: N2 más lineamientos arquitectónicos explícitos (SRP, inyección de dependencias, pruebas unitarias, validación, documentación de decisiones). |
| `prompt-combinador.md` | El prompt que combina una especificación técnica con los requisitos. `{NIVEL}` se reemplaza por `n1`, `n2` o `n3`. |

Para otro dominio u otra escala de niveles, cambie estos archivos y mantenga el nombre `tecnico-<nivel>.md`.

## Regla de oro: aislamiento

Cada aplicación se genera **sin ningún contexto de las otras**, para que un nivel no influya en otro:

- Una carpeta nueva y vacía por aplicación, por ejemplo `apps/claude-n1`, `apps/claude-n2`, `apps/claude-n3`.
- Dentro de cada una, solo `requisitos-ecommerce.md` y **el** `tecnico-<nivel>.md` que le corresponde.
- Una sesión nueva del agente (sin historial), abierta en esa carpeta, con el texto de `prompt-combinador.md`
  (`{NIVEL}` reemplazado) y nada más. No añada pistas ni mencione la rúbrica.
- No evalúe ni abra los resultados de otra aplicación antes de terminar de generar todas.

## Opciones para generar

**A mano.** Abra el agente de su preferencia en la carpeta de cada app y pegue el prompt. Es lo más simple y no requiere
ninguna herramienta extra.

**Con el CLI de un agente.** `run_experimento.py` crea la carpeta, copia las especificaciones y lanza el agente
(`claude` o `codex` deben estar instalados):

```
python run_experimento.py --agente claude --nivel N1 --sin-aceptacion --sin-pruebas
```

**Con subagentes** (por ejemplo, desde una sesión de Claude Code): lance uno por nivel, pasándole únicamente el prompt y la
carpeta de trabajo, y prohíbale leer fuera de ella. Verifique después que no haya archivos fuera de cada carpeta.

## Condiciones de entrega que el evaluador espera

`backend/` y `frontend/` en la raíz, cada uno con `package.json`, instalables con `npm install` y ejecutables con
`npm start`; `README.md` con instrucciones. Si falta alguno, el análisis de paquetes y de pruebas no verá esa parte.

## Después

1. Anote el **modelo** que generó las aplicaciones: lo pedirá `--modelo`.
2. Ejecute `python eval.py doctor` y luego `python eval.py evaluar`.
3. Opcional: para saber si la aplicación realmente funciona, use la compuerta de aceptación
   (`acceptance_check.py`, requiere MongoDB) o pruébela a mano.
