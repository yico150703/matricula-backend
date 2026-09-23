# Matrícula UNFV — Backend

API REST en Flask para los planes curriculares 2010 y vigente 2019 de Ingeniería de Sistemas. Usa PostgreSQL, Alembic mediante Flask-Migrate, JWT y CORS restringido.

## Roles y accesos

| Rol | Cómo ingresa | Puede |
| --- | --- | --- |
| **Alumno** | Usuario = código (o `código@unfv.edu.pe`). Contraseña inicial = código; se exige cambiarla en el primer ingreso. | Matricularse y retirar cursos en períodos abiertos, ver su malla, horario e historial (solo lectura), descargar su ficha PDF, cambiar su contraseña y datos de contacto. |
| **Administrador** | Usuario `admin` (configurable con `ADMIN_USER`). Contraseña inicial `ADMIN_PASSWORD` (por defecto `Admin2026!`); se exige cambiarla al entrar. | Registrar alumnos, editar datos/plan/estado, restablecer contraseñas, registrar y corregir notas, abrir o cerrar períodos. |

Al registrar un alumno solo se envían `cod_alumno`, `nombres`, `apellidos` e `id_plan` (1 = Plan 2019 vigente, 2 = Plan 2010). El correo `código@unfv.edu.pe` y la contraseña inicial (el código) se generan automáticamente.

## Requisitos y arranque local

1. Instala PostgreSQL y crea una base: `createdb matricula`.
2. Crea y activa un entorno virtual: `python -m venv .venv`, luego `.venv\Scripts\activate` en Windows.
3. Instala dependencias: `pip install -r requirements.txt`.
4. Copia `.env.example` a `.env` y configura `DATABASE_URL`, `SECRET_KEY`, `JWT_SECRET_KEY` y `FRONTEND_ORIGIN`.
5. Inicializa la base: `python scripts/seed_database_completa.py`. Es **seguro ejecutarlo siempre**: crea tablas y columnas faltantes, carga el catálogo solo si la base está vacía y crea el administrador y el alumno demo `20260001` si no existen. No borra datos. Para empezar de cero usa `--reset`.
6. Inicia la API: `flask --app wsgi:app run --debug`.

La comprobación se expone en `GET /health` (incluye el estado de la base de datos).

## Variables de entorno

| Variable | Uso |
| --- | --- |
| `DATABASE_URL` | URL de PostgreSQL. Render la inyecta desde su base administrada. |
| `SECRET_KEY` | Clave interna de Flask. |
| `JWT_SECRET_KEY` | Firma independiente de tokens JWT. |
| `FRONTEND_ORIGIN` | URL exacta de Vercel, por ejemplo `https://matricula-frontend.vercel.app`. Admite valores separados por comas para desarrollo. |
| `PASSING_GRADE` | Nota mínima aprobatoria, por defecto `11`. |
| `MAX_CREDITS` | Tope de créditos por período, por defecto `26`. |
| `ADMIN_USER` / `ADMIN_PASSWORD` | Usuario y contraseña inicial del administrador (se crea solo si no existe). |

En desarrollo configure `FRONTEND_ORIGIN=http://localhost:5173`. No se habilita CORS universal.

## API

Las respuestas de error tienen la forma `{"error":"...","detail":"..."}`. Los catálogos y secciones son públicos. El JWT incluye el claim `rol` (`alumno` o `admin`): el alumno solo accede a sus propios datos y el administrador a todos.

| Método y ruta | Acceso | Descripción |
| --- | --- | --- |
| `POST /api/auth/login` | público | `usuario` (código, correo o usuario admin) y `password`. Devuelve `access_token`, `rol` y `usuario`. |
| `GET /api/auth/me` | sesión | Perfil y rol del usuario autenticado. |
| `POST /api/auth/cambiar-password` | sesión | `password_actual`, `password_nueva` (mín. 6, distinta del código). |
| `PATCH /api/auth/perfil` | sesión | Alumno: `email_personal`, `telefono`. Admin: `nombres`, `email`. |
| `GET /api/planes`, `GET /api/planes/:id/cursos?ciclo=N` | público | Planes y cursos. |
| `GET /api/periodos` | público | Períodos académicos. |
| `GET /api/periodos/:id/secciones?plan=&curso=` | público | Secciones, horario, aula y vacantes. |
| `GET /api/alumnos/:codigo/malla` | alumno dueño / admin | Estado de cada curso (aprobado, en curso, disponible, desaprobado, bloqueado). |
| `GET /api/alumnos/:codigo/historial` | alumno dueño / admin | Cursos por período y nota final. |
| `POST /api/matriculas` | alumno dueño / admin | `cod_alumno`, `id_periodo`, `secciones`. Valida plan, prerrequisitos, cupo, cruces, duplicados y tope de créditos. |
| `GET /api/matriculas/:codigo?periodo=:id` | alumno dueño / admin | Matrícula del período. |
| `DELETE /api/matriculas/:nro/detalle/:id_seccion` | alumno dueño / admin | Retira una sección sin nota y libera la vacante. |
| `GET /api/alumnos?q=` | admin | Lista y búsqueda de alumnos. |
| `POST /api/alumnos` | admin | Registra alumno (`cod_alumno`, `nombres`, `apellidos`, `id_plan`). |
| `PATCH /api/alumnos/:codigo` | admin | Edita `nombres`, `apellidos`, `id_plan`, `estado`. |
| `POST /api/alumnos/:codigo/reset-password` | admin | La contraseña vuelve a ser el código y se exige cambiarla. |
| `POST /api/alumnos/:codigo/calificar` | admin | `cod_curso`, `nota` (0–20). Califica la matrícula existente del curso o registra la nota. |
| `PATCH /api/matriculas/:nro/detalle/:id_seccion/nota` | admin | Corrige `nota_final`. |
| `PATCH /api/periodos/:id` | admin | `estado`: `en_curso` o `cerrado`. |
| `GET /api/admin/resumen` | admin | Indicadores del panel. |

## Render + PostgreSQL

1. Sube este directorio como repositorio independiente `matricula-backend` a GitHub.
2. En Render, crea un **Blueprint** desde el repositorio y selecciona `render.yaml`, o crea manualmente una Web Service Python con build `pip install -r requirements.txt` y start `gunicorn wsgi:app --bind 0.0.0.0:$PORT`.
3. Crea o enlaza Render Postgres y asigna su **Internal Database URL** a `DATABASE_URL`.
4. Define secretos largos para `SECRET_KEY` y `JWT_SECRET_KEY`; define `FRONTEND_ORIGIN` con la URL de producción de Vercel. Agrega también `http://localhost:5173` separado por coma solo si lo necesitas en desarrollo.
5. El `startCommand` ejecuta `python scripts/seed_database_completa.py` antes de gunicorn. Ya **no borra la base** en cada reinicio: solo completa lo que falte, así los alumnos y matrículas registrados se conservan. Define `ADMIN_PASSWORD` en Render si no quieres la contraseña inicial por defecto.
6. Copia la URL pública final, por ejemplo `https://matricula-backend.onrender.com/api`, para usarla como `VITE_API_URL` del frontend.

JWT se eligió frente a sesión de servidor porque Vercel y Render viven en orígenes distintos: el token se transmite explícitamente en `Authorization`, evita depender de cookies cross-site y mantiene la API sin estado entre réplicas.
