"""Convierte los horarios oficiales (PDF) de la E.P. de Ingeniería de Sistemas en docs/horarios_2026.json.

Uso (solo cuando llegue un horario nuevo):
    pip install pdfplumber pandas openpyxl
    python scripts/fuentes/extraer_horarios.py horario_2026_1.pdf:2026-1 horario_2026_2.pdf:2026-2
"""
import json
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

import pandas as pd
import pdfplumber

ROOT = Path(__file__).resolve().parents[2]
MALLA = ROOT / "docs" / "malla_curricular_bd_2019.xlsx"
SALIDA = ROOT / "docs" / "horarios_2026.json"
MAPEO = {}
ROMANOS = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8, "IX": 9, "X": 10}
SIN_DOCENTE = {"", "PEDIR APOYO INTERNO", "FALTA DOCENTE"}
DEPARTAMENTOS = {"CCNN": "DPTO. CIENCIAS NATURALES", "FH": "DPTO. HUMANIDADES"}
# Códigos del horario fuente con errores de digitación
CORRECCION_CODIGOS = {"10553": "101553", "10015": "100015"}


def norm(texto):
    texto = unicodedata.normalize("NFD", str(texto or "")).encode("ascii", "ignore").decode().upper()
    texto = re.sub(r"\(.*?\)", " ", texto)
    texto = re.sub(r"[^A-Z0-9 ]", " ", texto)
    texto = re.sub(r"\b(DE|DEL|LA|LAS|EL|LOS|Y|E|EN)\b", " ", texto)
    texto = texto.replace("BASES", "BASE").replace("DESING", "DESIGN").replace("PMBOOK", "PMBOK")
    texto = re.sub(r"\bFUNDAMENTO\b", "FUNDAMENTOS", texto)
    return " ".join(texto.split())


def horas(celda):
    nums = [(h, m) for h, m in re.findall(r"(\d{1,2})[:.\-](\d{2})", celda or "") if int(h) < 24 and int(m) < 60]
    if len(nums) < 2:
        return None
    (h1, m1), (h2, m2) = nums[0], nums[1]
    return f"{int(h1):02d}:{m1}", f"{int(h2):02d}:{m2}"


def docente(valor):
    valor = re.sub(r"_APOYO$", "", (valor or "").strip()).strip(" -")
    if valor in SIN_DOCENTE:
        return None
    return DEPARTAMENTOS.get(valor, valor)


def main(fuentes):
    malla = pd.read_excel(MALLA, sheet_name="CURSO", dtype=object)
    por_nombre = {norm(r["nombre_curso"]): r for r in malla.to_dict("records")}
    secciones, codigos, sin_match = [], {}, set()

    for fuente in fuentes:
        archivo, periodo = fuente.rsplit(":", 1)
        with pdfplumber.open(archivo) as pdf:
            filas = [
                [(c or "").replace("\n", " ").strip() for c in fila]
                for pagina in pdf.pages
                for tabla in pagina.extract_tables()
                for fila in tabla
            ]
        for fila in filas:
            if len(fila) != 18 or fila[0] in ("CODIGO", "COD") or not fila[3]:
                continue
            cod, nombre, cupo, turno, sec, _cr, _ht, _hp, _th, ciclo, *dias, doc, aula = fila
            clave = norm(nombre)
            curso = por_nombre.get(clave) or next((v for k, v in por_nombre.items() if k in clave or clave in k), None)
            MAPEO.setdefault(nombre, curso["nombre_curso"]) if curso is not None else None
            if curso is None:
                sin_match.add(nombre)
                continue
            sesiones = []
            for i, celda in enumerate(dias, start=1):
                rango = horas(celda)
                if rango:
                    sesiones.append({"dia": i, "inicio": rango[0], "fin": rango[1]})
            if not sesiones:
                continue
            cod = CORRECCION_CODIGOS.get(cod, cod)
            if cod:
                codigos[str(curso["id_curso"])] = cod
            secciones.append({
                "periodo": periodo,
                "id_curso_malla": int(curso["id_curso"]),
                "ciclo": ROMANOS.get(ciclo, int(curso["id_semestre"])),
                "seccion": sec,  # A, B, C (cursos regulares) o E (electivos: una sola sección)
                "turno": turno,
                "cupo": int(cupo or 30),
                "docente": docente(doc),
                "aula": aula.strip() or None,
                "sesiones": sesiones,
            })

    # Aula faltante: la más usada por el mismo ciclo y sección en ese período (aula base del grupo)
    grupos = {}
    for s in secciones:
        if s["aula"]:
            grupos.setdefault((s["periodo"], s["ciclo"], s["seccion"]), Counter())[s["aula"]] += 1
    for s in secciones:
        if not s["aula"]:
            comun = grupos.get((s["periodo"], s["ciclo"], s["seccion"]))
            s["aula"] = comun.most_common(1)[0][0] if comun else None

    SALIDA.write_text(json.dumps({"codigos": codigos, "secciones": secciones}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(secciones)} secciones, {len(codigos)} códigos -> {SALIDA}")
    if "-v" in sys.argv:
        for fuente_nombre, malla_nombre in sorted(MAPEO.items()):
            print(f"  {fuente_nombre[:50]:50} -> {malla_nombre}")
    if sin_match:
        print("Sin correspondencia en la malla (omitidos):", sorted(sin_match))


if __name__ == "__main__":
    main([a for a in sys.argv[1:] if a != "-v"])
