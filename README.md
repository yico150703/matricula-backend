# Matrícula UNFV — Backend

API REST en Flask para los planes curriculares 2010 y vigente 2019 de Ingeniería de Sistemas. Usa PostgreSQL, Alembic mediante Flask-Migrate, JWT y CORS restringido.

## Requisitos y arranque local

1. Instala PostgreSQL y crea una base: `createdb matricula`.
2. Crea y activa un entorno virtual: `python -m venv .venv`, luego `.venv\Scripts\activate` en Windows.
3. Instala dependencias: `pip install -r requirements.txt`.
4. Copia `.env.example` a `.env` y configura `DATABASE_URL`, `SECRET_KEY`, `JWT_SECRET_KEY` y `FRONTEND_ORIGIN`.
5. Aplica el esquema versionado: `flask --app wsgi:app db upgrade`.
6. Carga el catálogo exacto de los Excel incluidos en `docs/`: `python scripts/seed_curricula.py`.
7. Inicia la API: `flask --app wsgi:app run --debug`.

La comprobación se expone en `GET /health`. El seed es idempotente y valida antes de escribir: Plan 2010 tiene 62 cursos y 57 relaciones; la malla 2019 contiene exactamente 82 cursos fuente y 69 relaciones. Los códigos 38, 45 y 53 no se crean porque no existen en el Excel original.

Para crear un alumno solo de desarrollo, después del seed:

```powershell
python scripts/create_student.py --codigo 20260001 --email alumno@unfv.edu.pe --password Cambiar123! --nombres Ana --apellidos Pérez --plan 2
```

Los datos operativos —períodos, docentes, aulas y secciones— se administran en PostgreSQL antes de abrir la matrícula. El seed curricular no inventa estos datos.

## Variables de entorno

| Variable | Uso |
| --- | --- |
| `DATABASE_URL` | URL de PostgreSQL. Render la inyecta desde su base administrada. |
| `SECRET_KEY` | Clave interna de Flask. |
| `JWT_SECRET_KEY` | Firma independiente de tokens JWT. |
| `FRONTEND_ORIGIN` | URL exacta de Vercel, por ejemplo `https://matricula-frontend.vercel.app`. Admite valores separados por comas para desarrollo. |
| `PASSING_GRADE` | Nota mínima aprobatoria, por defecto `11`. |

En desarrollo configure `FRONTEND_ORIGIN=http://localhost:5173`. No se habilita CORS universal.

## API

Las respuestas de error tienen la forma `{"error":"...","detail":"..."}`. Los catálogos y secciones son públicos; los datos de alumno y matrícula requieren `Authorization: Bearer <JWT>` y solo aceptan al alumno dueño del recurso.

| Método y ruta | Descripción |
| --- | --- |
| `POST /api/auth/login` | Recibe `email`, `password`; devuelve JWT y alumno. |
| `GET /api/auth/me` | Perfil del alumno autenticado. |
| `GET /api/planes` | Planes cargados. |
| `GET /api/planes/:id/cursos?ciclo=N` | Cursos del plan, filtrables por ciclo. |
| `GET /api/cursos/:id/prerrequisitos` | Prerrequisitos de un curso. El `id` es el identificador interno devuelto por la API; el código fuente está en `codigo_curso`. |
| `GET /api/alumnos/:codigo/malla` | Malla con estado aprobado, en curso, disponible o bloqueado. |
| `GET /api/alumnos/:codigo/historial` | Cursos por período y nota final. |
| `GET /api/periodos` | Períodos académicos. |
| `GET /api/periodos/:id/secciones?curso=:id` | Secciones, horario, aula y vacantes. |
| `POST /api/matriculas` | Crea/agrega detalles de matrícula. Cuerpo: `cod_alumno`, `id_periodo`, `secciones` (arreglo de IDs). |
| `GET /api/matriculas/:codigo?periodo=:id` | Matrícula del período. |
| `DELETE /api/matriculas/:nro/detalle/:id_seccion` | Retira una sección activa e incrementa su cupo. |

`POST /api/matriculas` bloquea concurrentemente las secciones y valida plan, todos los prerrequisitos aprobados en períodos cerrados, cupo, cruces de horarios —incluso con secciones ya matriculadas— y duplicidad de curso en el período. Los conflictos devuelven `409`.

## Render + PostgreSQL

1. Sube este directorio como repositorio independiente `matricula-backend` a GitHub.
2. En Render, crea un **Blueprint** desde el repositorio y selecciona `render.yaml`, o crea manualmente una Web Service Python con build `pip install -r requirements.txt` y start `gunicorn wsgi:app --bind 0.0.0.0:$PORT`.
3. Crea o enlaza Render Postgres y asigna su **Internal Database URL** a `DATABASE_URL`.
4. Define secretos largos para `SECRET_KEY` y `JWT_SECRET_KEY`; define `FRONTEND_ORIGIN` con la URL de producción de Vercel. Agrega también `http://localhost:5173` separado por coma solo si lo necesitas en desarrollo.
5. En cada despliegue, ejecuta antes de iniciar `flask --app wsgi:app db upgrade && python scripts/seed_curricula.py`. `render.yaml` ya lo declara como `preDeployCommand`.
6. Copia la URL pública final, por ejemplo `https://matricula-backend.onrender.com/api`, para usarla como `VITE_API_URL` del frontend.

JWT se eligió frente a sesión de servidor porque Vercel y Render viven en orígenes distintos: el token se transmite explícitamente en `Authorization`, evita depender de cookies cross-site y mantiene la API sin estado entre réplicas.
