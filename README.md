# Matrícula UNFV — Backend

API REST en Flask para el plan de estudios 2019 de Ingeniería de Sistemas (el Plan 2010 fue retirado), con los horarios oficiales 2026-1 y 2026-2: secciones A, B, C (y E para electivos), turnos M/T/N, docentes, aulas (Pabellón B · Aula 505, Laboratorio de Cómputo 1…) y códigos oficiales de asignatura. Usa PostgreSQL, Alembic mediante Flask-Migrate, JWT y CORS restringido.

## Roles y accesos

| Rol | Cómo ingresa | Puede |
| --- | --- | --- |
| **Alumno** | Usuario = código (o `código@unfv.edu.pe`). Contraseña inicial = código; se exige cambiarla en el primer ingreso. | Matricularse y retirar cursos en períodos abiertos, ver su malla, horario e historial (solo lectura), descargar su ficha PDF, cambiar su contraseña y datos de contacto. |
| **Administrador** | Usuario `admin` (configurable con `ADMIN_USER`). Contraseña inicial `ADMIN_PASSWORD` (por defecto `Admin2026!`); se exige cambiarla al entrar. | Registrar alumnos, editar datos/plan/estado, restablecer contraseñas, **crear las cuentas del personal con sus nombres y apellidos y asignarles el rol**, crear períodos académicos y **supervisar el avance de las actas de notas**. Solo registra notas históricas (cursos llevados antes del sistema). |
| **Jefe de Departamento** | Correo o usuario de su cuenta. | Fase 1: crea los horarios de cada curso (secciones, turno, días y horas). No asigna docentes ni aulas. |
| **Director de Escuela** | Correo o usuario. | Fase 2: asigna el docente de cada sección (o devuelve los horarios al jefe con un motivo). Establece los horarios y abre/cierra la matrícula. **Aprueba u observa las actas de notas** de los docentes. |
| **Asistente de Escuela** | Correo o usuario. | Fase 3: asigna pabellón, aula o laboratorio a cada sección o a cada sesión. |
| **Docente** | Correo o usuario (contraseña inicial = usuario). | Fase 4: ve su horario, confirma cada sección o reporta un problema. Desde la fase 5: **registra las notas de sus salones y envía el acta firmada (PDF)** al Director. |

**Cuentas del personal**: el administrador las crea con nombres y apellidos; el usuario sigue el formato UNFV: inicial del primer nombre + apellido paterno + inicial del materno (`José Alvarado Torres` → `jalvaradot`, correo `jalvaradot@unfv.edu.pe`; contraseña inicial = usuario, con cambio obligatorio). Si el usuario ya existe se agrega un número (`jalvaradot2`). Las cuentas creadas con el formato anterior se migran solas una vez al arrancar. Todos los roles tienen recuperación de contraseña.

**Cuentas de prueba compartidas** (se muestran en el login). El script de la base las crea o **las repara en cada arranque** (contraseña conocida, activas y sin cambio obligatorio) y su contraseña no se puede cambiar desde el sistema, así nadie deja a los demás sin acceso. Con `CUENTAS_PRUEBA=false` se desactivan.

| Rol | Usuario | Contraseña |
| --- | --- | --- |
| Administrador | `adminprueba` | `Admin2026!` |
| Jefe de Departamento | `jefedepartamentoescuelasistemas@unfv.edu.pe` | `Jefe2026!` |
| Director de Escuela | `directorescuelasistemas@unfv.edu.pe` | `Director2026!` |
| Asistente de Escuela | `asistenteescuelasistemas@unfv.edu.pe` | `Asistente2026!` |
| Docente | `jalvaradot@unfv.edu.pe` | `Docente2026!` |
| Alumno | `20260001` | `20260001` |

El administrador real (`admin`, contraseña inicial `ADMIN_PASSWORD`) no es una cuenta de prueba: debe cambiar su contraseña al primer ingreso. **El servidor exige ese cambio**: con la contraseña inicial solo se puede consultar el perfil y cambiarla. Una cuenta desactivada, o con otro rol, pierde el acceso aunque tenga un token vigente.

Además se crea una cuenta por cada docente de los horarios oficiales (contraseña inicial = usuario).

## Proceso de horarios por fases

Cada período tiene un proceso con 6 fases (más el cierre). Cada rol solo edita directamente en su fase; fuera de ella todo cambio se pide con una **solicitud de cambio** que el rol responsable acepta, rechaza o acepta con otra alternativa, con un hilo de mensajes para coordinar.

| Fase | Quién | Qué pasa |
| --- | --- | --- |
| 1. Horarios por curso | Jefe de Departamento | Crea las secciones (puede copiar un período anterior del mismo semestre como base) y las envía al director. |
| 2. Asignación de docentes | Director de Escuela | Asigna docentes (se validan cruces del docente). Puede devolver al jefe con un motivo. |
| 3. Confirmación y aulas | Jefe + Director + Asistente | Jefe y director confirman; el asistente asigna aulas (se validan cruces por sesión) y publica para los docentes. |
| 4. Confirmación docente | Docentes | Cada docente confirma sus secciones o reporta un problema. |
| 5. Matrícula abierta | Alumnos | **Automático**: cuando todos los docentes confirman (y no quedan solicitudes abiertas) los horarios quedan establecidos y se abre la matrícula. |
| 6. Ajustes | Todos por solicitud | Hasta `DIAS_AJUSTE_HORARIO` días (14) después del inicio de clases. |
| 7. Cerrado | — | El director cierra el proceso y la matrícula. |

Las pantallas del personal muestran siempre el período en proceso (se elige solo; nadie cambia de período ni de fase a mano). Los alumnos solo ven y se matriculan en períodos en fase 5 o 6 y antes de la fecha de fin del período (los períodos terminados se cierran solos). Si un cambio aprobado modifica el horario o el aula de una sección, el docente debe volver a confirmarla. Al crear un período nuevo (panel del administrador) empieza en la fase 1.

**Calendario**: el período AAAA-1 empieza un **lunes de marzo, abril o mayo**; el fin se calcula solo (16 semanas de clases, termina el sábado de la semana 16). Sigue 1 semana de vacaciones y el AAAA-2 empieza el lunes siguiente (se calcula solo a partir del AAAA-1). Un período en programación sin matrículas se puede eliminar desde el panel.

**Horarios**: las clases van en bloques de 50 minutos desde las 08:00 (08:00, 08:50, 09:40, …, 22:10). Cada sección debe dictar al menos las horas semanales del plan de estudios oficial (HT + HP; el plan indica un total de (HT+HP) × 16 por semestre). Los horarios oficiales 2026 cumplen ese mínimo y algunas secciones tienen 1 a 3 horas extra de práctica, por eso se exige el mínimo y no un valor exacto.

Al registrar un alumno solo se envían `cod_alumno`, `nombres`, `apellidos` e `id_plan` (1 = Plan 2019). El correo `código@unfv.edu.pe` y la contraseña inicial (el código) se generan automáticamente.

## Reglas principales

- **Horarios**: cada sección tiene varias sesiones semanales (`seccion_sesion`). Llevar todos los cursos de un ciclo en la misma sección no genera cruces; los cruces se validan sesión por sesión.
- **Vacantes**: se muestra capacidad, matriculados y reservas activas. A los alumnos que repiten el curso se les permite un sobrecupo (hasta `SOBRECUPO_REPITENTES` por sección, según cuántos repitentes aptos haya).
- **Carrito**: el alumno reúne secciones de su ciclo y de otros ciclos (cursos que repite o que aún no llevó) y las matricula en un paso. Cada ítem reserva la vacante `CARRITO_MINUTOS` (10 por defecto). Se valida plan, prerrequisitos, cruces, duplicados, vacantes y el máximo de `MAX_CREDITS` créditos.
- **Notas**: N1, N2, N3 → promedio redondeado (desde x.5 sube: 10.5 = 11; 10.4 = 10). El sustitutorio reemplaza a la nota más baja si es mayor y el aplazado, si existe, es la nota final. También se acepta una nota final directa. Las notas de cursos llevados antes del sistema se guardan en el período `HISTORICO` (no ocupan créditos del semestre actual).
- **Sesión**: cierre por inactividad a los 10 minutos en el frontend (OWASP recomienda 2-5 min para aplicaciones de alto riesgo y 15-30 para bajo riesgo) y tiempo absoluto del token de `SESSION_HOURS` (2 h).
- **Recuperación de contraseña**: `POST /api/auth/recuperar` genera un enlace de un solo uso (vence en 30 min). Si hay SMTP configurado se envía al correo del alumno; si no, la solicitud aparece en el panel del administrador, que puede generar el enlace o restablecer la contraseña al código.

Los horarios se generan desde los PDF oficiales con `scripts/fuentes/extraer_horarios.py` y quedan en `docs/horarios_2026.json`. Para cargar un horario nuevo: regenera el JSON, sube `CATALOGO_VERSION` en `scripts/seed_database_completa.py` y despliega.

## Actas de notas (docente → Director de Escuela)

1. Desde la fase 5 el docente ve **sus salones** y registra N1, N2, N3, sustitutorio y aplazado de cada alumno. Es un borrador: todavía no afecta el registro académico.
2. Descarga el acta generada por el sistema, la firma y la sube escaneada en PDF (máx. 5 MB; se guarda en la base de datos porque el disco de Render es temporal).
3. Al enviarla (todos los alumnos deben tener nota) pasa al **Director de Escuela**, que la **aprueba** (las notas se copian al registro de cada alumno) o la **observa** con un comentario (vuelve al docente). Una acta aprobada se puede **reabrir** para corregirla.
4. El administrador ve el avance por período en «Seguimiento de notas». Las notas de cursos del sistema ya no las registra el administrador.

## Requisitos y arranque local

1. Instala PostgreSQL y crea una base: `createdb matricula`.
2. Crea y activa un entorno virtual: `python -m venv .venv`, luego `.venv\Scripts\activate` en Windows.
3. Instala dependencias: `pip install -r requirements.txt`.
4. Copia `.env.example` a `.env` y configura `DATABASE_URL`, `SECRET_KEY`, `JWT_SECRET_KEY` y `FRONTEND_ORIGIN`.
5. Inicializa la base: `python scripts/seed_database_completa.py`. Es **seguro ejecutarlo siempre** (Render lo ejecuta en cada arranque): crea tablas y columnas faltantes y crea el administrador, el personal de prueba, las cuentas de los docentes, el alumno demo `20260001` y el proceso de horarios de cada período si no existen (el período 2027-1 ya no se crea solo: lo crea el administrador; el 2027-1 de prueba de versiones anteriores se elimina una vez si no tiene matrículas). Si cambia `CATALOGO_VERSION` **no toca nada** salvo que se ejecute con `--reemplazar-catalogo` o con `REEMPLAZAR_CATALOGO=<versión>`: en ese caso reemplaza cursos y horarios conservando alumnos y personal, pero elimina las matrículas y notas del catálogo anterior. Para empezar de cero usa `--reset`.
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
| `DIAS_AJUSTE_HORARIO` | Días de ajustes de horario tras el inicio de clases (por defecto 14). |
| `CUENTAS_PRUEBA` | `true` (por defecto) mantiene las cuentas de prueba del login; `false` las desactiva. |
| `ZONA_HORARIA` | Zona para las fechas del proceso (por defecto `America/Lima`; el servidor trabaja en UTC). |
| `REEMPLAZAR_CATALOGO` | Solo para cargar un catálogo nuevo: el valor debe ser igual a `CATALOGO_VERSION`. |
| `FRONTEND_URL` | URL pública del frontend, para los enlaces de recuperación de contraseña. |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `MAIL_FROM` | Opcionales. Si se configuran, los enlaces de recuperación se envían por correo. |

En desarrollo configure `FRONTEND_ORIGIN=http://localhost:5173`. No se habilita CORS universal.

## API

Las respuestas de error tienen la forma `{"error":"...","detail":"..."}`. Los catálogos y secciones son públicos. El JWT incluye el claim `rol` (`alumno`, `admin`, `jefe`, `director`, `asistente` o `docente`): el alumno solo accede a sus propios datos, el administrador a todos y cada rol del personal solo a las acciones de su función.

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
| `POST /api/alumnos/:codigo/calificar` | admin | Solo notas históricas (cursos llevados antes del sistema): `cod_curso` y `n1`, `n2`, `n3` (+ `sustitutorio`, `aplazado`) o `nota`. |
| `PATCH /api/matriculas/:nro/detalle/:id_seccion/nota` | admin | Corrige notas del histórico. |
| `GET /api/docente/salones?periodo=` · `GET /api/docente/salones/:id` | docente | Sus salones con el estado del acta; alumnos y notas de un salón. |
| `PUT /api/docente/salones/:id/notas` | docente | Guarda el borrador: `{"notas": {"<código>": {"n1", "n2", "n3", "sustitutorio", "aplazado"}}}`. |
| `POST /api/docente/salones/:id/acta` | docente | Multipart con `archivo` (PDF): envía el acta al Director. |
| `GET /api/actas?periodo=` · `GET /api/actas/:id` | director, admin | Estado de las actas de todos los salones y detalle de una. |
| `GET /api/actas/:id/pdf` | director, admin, docente dueño | PDF del acta firmada. |
| `POST /api/actas/:id/revisar` | director | `accion`: `aprobar`, `observar` o `reabrir` (con `observacion`). |
| `POST /api/auth/recuperar` · `GET/POST /api/auth/restablecer` | público | Recuperación de contraseña con enlace de un solo uso. |
| `GET /api/admin/solicitudes-password` · `POST .../:id/atender` | admin | Atiende solicitudes (`enlace`, `restablecer`, `descartar`). |
| `GET/POST /api/admin/usuarios` · `PATCH .../:id` · `POST .../:id/reset-password` | admin | Personal: listar, crear (`nombres`, `apellidos`, `rol`), cambiar rol o estado, restablecer contraseña. |
| `POST /api/admin/periodos` · `DELETE /api/admin/periodos/:id` | admin | Crea un período en la fase 1 (`cod_per_acad` y, para el AAAA-1, `fecha_inicio`: lunes de marzo a mayo; el fin y el AAAA-2 se calculan solos). Elimina un período en programación sin matrículas. |
| `GET /api/proceso/periodos` | personal / admin | Procesos por período con fase, conteos y aulas disponibles. |
| `GET /api/proceso/:id` | jefe, director, asistente, admin | Cursos y secciones del período con docente, aula y alertas de cruce. |
| `GET /api/proceso/docentes?periodo=` | jefe, director, asistente | Docentes con sus horas asignadas. |
| `POST /api/proceso/:id/secciones` · `PUT/DELETE /api/proceso/secciones/:id` · `POST /api/proceso/:id/copiar` | jefe (fase 1) | Crear, editar, eliminar secciones o copiar un período base. |
| `PUT /api/proceso/secciones/:id/docente` | director (fase 2) | `id_docente`. |
| `PUT /api/proceso/secciones/:id/aula` | asistente (fase 3) | `aula` y opcional `sesion` (índice) para asignar por sesión. |
| `POST /api/proceso/:id/accion` | jefe, director, asistente | `enviar_director`, `devolver_jefe` (con `motivo`), `enviar_confirmacion`, `confirmar`, `enviar_docentes`, `iniciar_ajustes`, `cerrar` (el paso a la fase 5 es automático). |
| `GET/POST /api/proceso/:id/solicitudes` | personal | Solicitudes de cambio (`id_seccion`, `tipo`: horario/docente/aula, `descripcion`, `propuesta`). |
| `POST /api/proceso/solicitudes/:id/mensajes` · `POST .../resolver` | personal · rol destino | Mensajes del hilo; `accion` aprobar/rechazar con `respuesta` y `propuesta` alternativa opcional. |
| `GET /api/docente/horario?periodo=` · `POST /api/docente/secciones/:id/confirmar` | docente | Horario del docente (desde la fase 4) y confirmación por sección. |
| `GET /api/admin/resumen` | admin | Indicadores del panel. |

## Render + PostgreSQL

1. Sube este directorio como repositorio independiente `matricula-backend` a GitHub.
2. En Render, crea un **Blueprint** desde el repositorio y selecciona `render.yaml`, o crea manualmente una Web Service Python con build `pip install -r requirements.txt` y start `gunicorn wsgi:app --bind 0.0.0.0:$PORT`.
3. Crea o enlaza Render Postgres y asigna su **Internal Database URL** a `DATABASE_URL`.
4. Define secretos largos para `SECRET_KEY` y `JWT_SECRET_KEY`; define `FRONTEND_ORIGIN` con la URL de producción de Vercel (sin barra final; si lo dejas en `*` se acepta cualquier origen). Agrega también `http://localhost:5173` separado por coma solo si lo necesitas en desarrollo.
5. El `startCommand` ejecuta `python scripts/seed_database_completa.py; gunicorn …`: el script completa lo que falte y repara las cuentas de prueba, y si fallara el API arranca igual (por eso se usa `;` y no `&&`). No borra datos. Define `ADMIN_PASSWORD` en Render si no quieres la contraseña inicial por defecto. Si el servicio se creó a mano (no como Blueprint), copia este comando en *Settings → Start Command*.
6. Copia la URL pública final, por ejemplo `https://matricula-backend.onrender.com/api`, para usarla como `VITE_API_URL` del frontend.

JWT se eligió frente a sesión de servidor porque Vercel y Render viven en orígenes distintos: el token se transmite explícitamente en `Authorization`, evita depender de cookies cross-site y mantiene la API sin estado entre réplicas.
