# Matrícula UNFV — Backend

API REST en Flask para el plan de estudios 2019 de Ingeniería de Sistemas (el Plan 2010 fue retirado), con los horarios oficiales 2026-1 y 2026-2: secciones A, B, C (y E para electivos), turnos M/T/N, docentes, aulas (Pabellón B · Aula 505, Laboratorio de Cómputo 1…) y códigos oficiales de asignatura. Usa PostgreSQL, Alembic mediante Flask-Migrate, JWT y CORS restringido.

## Roles y accesos

| Rol | Cómo ingresa | Puede |
| --- | --- | --- |
| **Alumno** | Usuario = código (o `código@unfv.edu.pe`). Contraseña inicial = código; se exige cambiarla en el primer ingreso. | Matricularse y retirar cursos en períodos abiertos, ver su malla, horario e historial (solo lectura), descargar su ficha PDF, cambiar su contraseña y datos de contacto. |
| **Administrador** | Usuario `admin` (configurable con `ADMIN_USER`). Contraseña inicial `ADMIN_PASSWORD` (por defecto `Admin2026!`); se exige cambiarla al entrar. | Registrar alumnos, editar datos/plan/estado, restablecer contraseñas, registrar y corregir notas, abrir o cerrar períodos. |

Al registrar un alumno solo se envían `cod_alumno`, `nombres`, `apellidos` e `id_plan` (1 = Plan 2019). El correo `código@unfv.edu.pe` y la contraseña inicial (el código) se generan automáticamente.

## Reglas principales

- **Horarios**: cada sección tiene varias sesiones semanales (`seccion_sesion`). Llevar todos los cursos de un ciclo en la misma sección no genera cruces; los cruces se validan sesión por sesión.
- **Vacantes**: se muestra capacidad, matriculados y reservas activas. A los alumnos que repiten el curso se les permite un sobrecupo (hasta `SOBRECUPO_REPITENTES` por sección, según cuántos repitentes aptos haya).
- **Carrito**: el alumno reúne secciones de su ciclo y de otros ciclos (cursos que repite o que aún no llevó) y las matricula en un paso. Cada ítem reserva la vacante `CARRITO_MINUTOS` (10 por defecto). Se valida plan, prerrequisitos, cruces, duplicados, vacantes y el máximo de `MAX_CREDITS` créditos.
- **Notas**: N1, N2, N3 → promedio redondeado (desde x.5 sube: 10.5 = 11; 10.4 = 10). El sustitutorio reemplaza a la nota más baja si es mayor y el aplazado, si existe, es la nota final. También se acepta una nota final directa. Las notas de cursos llevados antes del sistema se guardan en el período `HISTORICO` (no ocupan créditos del semestre actual).
- **Sesión**: cierre por inactividad a los 10 minutos en el frontend (OWASP recomienda 2-5 min para aplicaciones de alto riesgo y 15-30 para bajo riesgo) y tiempo absoluto del token de `SESSION_HOURS` (2 h).
- **Recuperación de contraseña**: `POST /api/auth/recuperar` genera un enlace de un solo uso (vence en 30 min). Si hay SMTP configurado se envía al correo del alumno; si no, la solicitud aparece en el panel del administrador, que puede generar el enlace o restablecer la contraseña al código.

Los horarios se generan desde los PDF oficiales con `scripts/fuentes/extraer_horarios.py` y quedan en `docs/horarios_2026.json`. Para cargar un horario nuevo: regenera el JSON, sube `CATALOGO_VERSION` en `scripts/seed_database_completa.py` y despliega.

## Requisitos y arranque local

1. Instala PostgreSQL y crea una base: `createdb matricula`.
2. Crea y activa un entorno virtual: `python -m venv .venv`, luego `.venv\Scripts\activate` en Windows.
3. Instala dependencias: `pip install -r requirements.txt`.
4. Copia `.env.example` a `.env` y configura `DATABASE_URL`, `SECRET_KEY`, `JWT_SECRET_KEY` y `FRONTEND_ORIGIN`.
5. Inicializa la base: `python scripts/seed_database_completa.py`. Es **seguro ejecutarlo siempre**: crea tablas y columnas faltantes y crea el administrador y el alumno demo `20260001` si no existen. Si cambia `CATALOGO_VERSION`, reemplaza cursos y horarios **conservando alumnos y administradores** (las matrículas y notas de prueba del catálogo anterior se eliminan). Para empezar de cero usa `--reset`.
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
| `SOBRECUPO_REPITENTES` | Vacantes extra por sección para alumnos que repiten el curso (por defecto 5). |
| `CARRITO_MINUTOS` | Minutos de reserva de vacantes en el carrito (por defecto 10). |
| `SESSION_HOURS` | Duración máxima del token de sesión (por defecto 2). |
| `FRONTEND_URL` | URL pública del frontend, para los enlaces de recuperación de contraseña. |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `MAIL_FROM` | Opcionales. Si se configuran, los enlaces de recuperación se envían por correo. |

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
| `GET /api/alumnos/:codigo/oferta?periodo=:id` | alumno dueño / admin | Cursos del plan programados en el período con estado, secciones, sesiones y vacantes. |
| `GET/POST/DELETE /api/carrito/:codigo` | alumno dueño / admin | Ver, agregar (`id_periodo`, `secciones`), quitar o vaciar el carrito. |
| `POST /api/carrito/:codigo/confirmar` | alumno dueño / admin | Matricula todo el carrito. |
| `POST /api/matriculas` | alumno dueño / admin | `cod_alumno`, `id_periodo`, `secciones`. Valida plan, prerrequisitos, cupo, cruces, duplicados y tope de créditos. |
| `GET /api/matriculas/:codigo?periodo=:id` | alumno dueño / admin | Matrícula del período. |
| `DELETE /api/matriculas/:nro/detalle/:id_seccion` | alumno dueño / admin | Retira una sección sin nota y libera la vacante. |
| `GET /api/alumnos?q=` | admin | Lista y búsqueda de alumnos. |
| `POST /api/alumnos` | admin | Registra alumno (`cod_alumno`, `nombres`, `apellidos`, `id_plan`). |
| `PATCH /api/alumnos/:codigo` | admin | Edita `nombres`, `apellidos`, `id_plan`, `estado`. |
| `POST /api/alumnos/:codigo/reset-password` | admin | La contraseña vuelve a ser el código y se exige cambiarla. |
| `POST /api/alumnos/:codigo/calificar` | admin | `cod_curso` y `n1`, `n2`, `n3` (+ `sustitutorio`, `aplazado`) o `nota`. Califica la matrícula existente o registra la nota en el histórico. |
| `PATCH /api/matriculas/:nro/detalle/:id_seccion/nota` | admin | Corrige las notas de una matrícula. |
| `POST /api/auth/recuperar` · `GET/POST /api/auth/restablecer` | público | Recuperación de contraseña con enlace de un solo uso. |
| `GET /api/admin/solicitudes-password` · `POST .../:id/atender` | admin | Atiende solicitudes (`enlace`, `restablecer`, `descartar`). |
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
