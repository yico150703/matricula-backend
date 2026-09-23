"""Create a local test student without embedding credentials in source code."""
import argparse
from datetime import date
from pathlib import Path
import sys
from werkzeug.security import generate_password_hash

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models import Alumno, Plan  # noqa: E402

parser = argparse.ArgumentParser()
parser.add_argument("--codigo", required=True)
parser.add_argument("--email", help="Por defecto <codigo>@unfv.edu.pe")
parser.add_argument("--password", help="Por defecto el propio código (se exigirá cambiarla)")
parser.add_argument("--nombres", required=True)
parser.add_argument("--apellidos", required=True)
parser.add_argument("--plan", type=int, choices=[1, 2], required=True)
parser.add_argument("--fecha-ingreso", default=date.today().isoformat())
args = parser.parse_args()
email = (args.email or f"{args.codigo}@unfv.edu.pe").lower()
password = args.password or args.codigo

app = create_app()
with app.app_context():
    if not db.session.get(Plan, args.plan):
        raise SystemExit("El plan no existe. Ejecute primero scripts/seed_curricula.py")
    if db.session.get(Alumno, args.codigo) or Alumno.query.filter_by(email=email).first():
        raise SystemExit("Ya existe un alumno con ese código o email.")
    db.session.add(Alumno(cod_alumno=args.codigo, email=email, password_hash=generate_password_hash(password), debe_cambiar_password=args.password is None, nombres=args.nombres, apellidos=args.apellidos, id_plan=args.plan, estado="activo", fecha_ingreso=date.fromisoformat(args.fecha_ingreso)))
    db.session.commit()
print("Alumno de prueba creado.")
