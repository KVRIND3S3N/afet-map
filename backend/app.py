# app.py
import os
import json
from decimal import Decimal
from contextlib import contextmanager

from flask import Flask, jsonify, request
from flask_cors import CORS
from dotenv import load_dotenv

import psycopg2
from psycopg2.extras import RealDictCursor

# ──────────────────────────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────────────────────────
load_dotenv()

DATABASE_URL     = os.getenv("DATABASE_URL", "postgresql://postgres:2323@localhost:5432/afet")
POSTGIS_SCHEMA   = os.getenv("POSTGIS_SCHEMA", "public")
BURN_AREAS_TABLE = os.getenv("BURN_AREAS_TABLE", "burn_areas")  # ya da "_burn_union"
ASSEMBLY_TABLE   = os.getenv("ASSEMBLY_TABLE", "assembly_areas")
ASSEMBLY_GEOM_COLUMN = os.getenv("ASSEMBLY_GEOM_COLUMN", "geometry")


HOST             = os.getenv("HOST", "127.0.0.1")
PORT             = int(os.getenv("PORT", "5000"))
DEBUG            = bool(int(os.getenv("DEBUG", "1")))

# ──────────────────────────────────────────────────────────────────────────────
# App
# ──────────────────────────────────────────────────────────────────────────────
app = Flask(__name__)
CORS(app)

# ──────────────────────────────────────────────────────────────────────────────
# DB helpers
# ──────────────────────────────────────────────────────────────────────────────

@contextmanager
def get_conn():
    conn = psycopg2.connect(DATABASE_URL)
    try:
        yield conn
    finally:
        conn.close()

class DecimalEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, Decimal):
            return float(o)
        return super().default(o)

def ok(data, status=200):
    return app.response_class(
        response=json.dumps(data, cls=DecimalEncoder, ensure_ascii=False),
        status=status,
        mimetype="application/json"
    )

def bad_request(msg, status=400):
    return ok({"error": msg}, status=status)

# ──────────────────────────────────────────────────────────────────────────────
# Utilities
# ──────────────────────────────────────────────────────────────────────────────

def build_feature_collection(query_sql, params=None):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query_sql, params or {})
            rows = cur.fetchall()

            features = []
            for i, row in enumerate(rows, start=1):
                features.append({
                    "type": "Feature",
                    "id": i,
                    "geometry": row["geometry"],
                    "properties": {}  # şimdilik boş
                })

            return {"type": "FeatureCollection", "features": features}

def ensure_lon_lat():
    try:
        lon = float(request.args.get("lon", "").strip())
        lat = float(request.args.get("lat", "").strip())
    except Exception:
        return None, None, "Geçerli ?lon= ve ?lat= değerleri veriniz (örn: ?lon=31.16&lat=40.84)."
    if not (-180 <= lon <= 180 and -90 <= lat <= 90):
        return None, None, "Koordinatlar aralık dışında."
    return lon, lat, None

# ──────────────────────────────────────────────────────────────────────────────
# Routes
# ──────────────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return ok({"status": "ok"})

@app.get("/api/burn-areas")
def burn_areas():
    """
    Yanık alanları GeoJSON döndürür.
    - mode=union  -> _burn_union (tek feature, MultiPolygon)
    - mode=polys  -> burn_polys  (çoklu feature, properties.class + severity_label)
    - tolerance   -> metre cinsinden sadeleştirme (opsiyonel)
    """
    mode = (request.args.get("mode") or "union").lower()

    tol_param = request.args.get("tolerance")
    try:
        tolerance = float(tol_param) if tol_param else None
    except:
        return bad_request("tolerance sayısal olmalı (metre).")

    union_table = f'{POSTGIS_SCHEMA}."_burn_union"'
    polys_table = f'{POSTGIS_SCHEMA}."burn_polys"'

    # Kaynak ve props (polys: class + label, union: boş props)
    if mode == "polys":
        base_sql = f"""
            SELECT
                t.geometry AS geom,
                jsonb_build_object(
                    'class', t.class,
                    'severity_label', CASE t.class
                        WHEN 4 THEN 'Yüksek'
                        WHEN 3 THEN 'Orta-Yüksek'
                        WHEN 2 THEN 'Orta-Düşük'
                        WHEN 1 THEN 'Düşük'
                        ELSE 'Etkilenmemiş'
                    END
                ) AS props
            FROM {polys_table} t
        """
    else:
        base_sql = f"""
            SELECT
                t.geometry AS geom,
                '{{}}'::jsonb AS props
            FROM {union_table} t
        """

    # Sadeleştirme (metre) için: 4326 -> 3857 -> simplify -> 4326
    if tolerance and tolerance > 0:
        geom_expr = f"""
            ST_Transform(
                ST_SimplifyPreserveTopology(
                    ST_Transform(geom, 3857),
                    {tolerance}
                ),
                4326
            )
        """
    else:
        geom_expr = "geom"

    sql = f"""
        WITH src AS (
            {base_sql}
        ),
        numbered AS (
            SELECT row_number() OVER () AS _fid, {geom_expr} AS geom, props
            FROM src
        )
        SELECT jsonb_build_object(
            'type','FeatureCollection',
            'features', COALESCE(jsonb_agg(
                jsonb_build_object(
                    'type','Feature',
                    'id', _fid,
                    'geometry', ST_AsGeoJSON(geom)::jsonb,
                    'properties', props
                )
            ), '[]'::jsonb)
        ) AS fc
        FROM numbered;
    """

    try:
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(sql)
                row = cur.fetchone()
                return ok(row["fc"])
    except Exception as e:
        return bad_request(f"Yanık alanları okunamadı: {e}")






@app.get("/api/route-to-fire")
def route_to_fire():
    lon, lat, err = ensure_lon_lat()
    if err:
        return bad_request(err)

    # Varsayılan 20 m sadeleştirme (0 verirsen kapatılır)
    tol_param = request.args.get("tolerance")
    tolerance = float(tol_param) if tol_param is not None else 20.0

    # Yakınlık filtresi (km) opsiyonel
    max_km_param = request.args.get("max_km")
    max_km = float(max_km_param) if max_km_param else None

    burn_table = f'{POSTGIS_SCHEMA}."{BURN_AREAS_TABLE}"'

    sql = f"""
    WITH
    src AS (
        SELECT ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), 4326) AS pt
    ),
    candidate AS (
        SELECT geometry
        FROM {burn_table}
        WHERE geometry IS NOT NULL AND NOT ST_IsEmpty(geometry)
          AND (
            %(max_km)s IS NULL OR
            ST_DWithin(geometry::geography, (SELECT pt FROM src)::geography, %(max_km)s * 1000.0)
          )
        ORDER BY geometry <-> (SELECT pt FROM src)
        LIMIT 1
    ),
    dest AS (
        SELECT ST_ClosestPoint((SELECT geometry FROM candidate), (SELECT pt FROM src)) AS geometry
    ),
    line_raw AS (
        SELECT
            ST_ShortestLine((SELECT pt FROM src), (SELECT geometry FROM candidate)) AS geom_line,
            ST_Distance(
                (SELECT pt FROM src)::geography,
                (SELECT geometry FROM candidate)::geography
            ) AS distance_m
    ),
    line AS (
        SELECT
            CASE
                WHEN %(tol)s > 0
                THEN ST_Transform(
                       ST_SimplifyPreserveTopology(
                         ST_Transform(geom_line, 3857),
                         %(tol)s
                       ),
                       4326
                     )
                ELSE geom_line
            END AS geometry,
            distance_m
        FROM line_raw
    ),
    out_features AS (
        SELECT 1 AS kind, distance_m, geometry FROM line
        UNION ALL
        SELECT 2 AS kind, NULL::double precision AS distance_m,
               CASE
                 WHEN %(tol)s > 0
                 THEN ST_Transform(
                        ST_SimplifyPreserveTopology(
                          ST_Transform((SELECT geometry FROM dest), 3857),
                          %(tol)s
                        ),
                        4326
                      )
                 ELSE (SELECT geometry FROM dest)
               END AS geometry
        UNION ALL
        SELECT 3 AS kind, NULL::double precision AS distance_m, (SELECT pt FROM src) AS geometry
    )
    SELECT jsonb_build_object(
        'type','FeatureCollection',
        'features', COALESCE(jsonb_agg(
            jsonb_build_object(
                'type','Feature',
                'id', kind,
                'geometry', ST_AsGeoJSON(geometry)::jsonb,
                'properties', jsonb_build_object(
                    'role', CASE kind WHEN 1 THEN 'line' WHEN 2 THEN 'destination' WHEN 3 THEN 'origin' END,
                    'distance_m', distance_m,
                    'distance_km', CASE
  WHEN distance_m IS NULL THEN NULL
  ELSE ROUND((distance_m/1000.0)::numeric, 3)::float8
END

                )
            )
        ), '[]'::jsonb)
    ) AS fc
    FROM out_features;
    """
    try:
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(sql, {"lon": lon, "lat": lat, "tol": tolerance, "max_km": max_km})
                row = cur.fetchone()
                return ok(row["fc"])
    except Exception as e:
        return bad_request(f"Rota hesaplanamadı: {e}")


@app.get("/api/route-to-assembly")
def route_to_assembly():
    lon, lat, err = ensure_lon_lat()
    if err:
        return bad_request(err)

    # Varsayılan 20 m sadeleştirme (0 verirsen kapatılır)
    tol_param = request.args.get("tolerance")
    tolerance = float(tol_param) if tol_param is not None else 20.0

    # Yakınlık filtresi (km) opsiyonel
    max_km_param = request.args.get("max_km")
    max_km = float(max_km_param) if max_km_param else None

    assembly_table = f'{POSTGIS_SCHEMA}."{ASSEMBLY_TABLE}"'
    geom_col = ASSEMBLY_GEOM_COLUMN  # örn: geom_point

    sql = f"""
    WITH
    src AS (
        SELECT ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), 4326) AS pt
    ),
    candidate AS (
        SELECT {geom_col} AS geometry
        FROM {assembly_table}
        WHERE {geom_col} IS NOT NULL AND NOT ST_IsEmpty({geom_col})
          AND (
            %(max_km)s IS NULL OR
            ST_DWithin({geom_col}::geography, (SELECT pt FROM src)::geography, %(max_km)s * 1000.0)
          )
        ORDER BY {geom_col} <-> (SELECT pt FROM src)
        LIMIT 1
    ),
    dest AS (
        SELECT ST_ClosestPoint((SELECT geometry FROM candidate), (SELECT pt FROM src)) AS geometry
    ),
    line_raw AS (
        SELECT
            ST_ShortestLine((SELECT pt FROM src), (SELECT geometry FROM candidate)) AS geom_line,
            ST_Distance(
                (SELECT pt FROM src)::geography,
                (SELECT geometry FROM candidate)::geography
            ) AS distance_m
    ),
    line AS (
        SELECT
            CASE
                WHEN %(tol)s > 0
                THEN ST_Transform(
                       ST_SimplifyPreserveTopology(
                         ST_Transform(geom_line, 3857),
                         %(tol)s
                       ),
                       4326
                     )
                ELSE geom_line
            END AS geometry,
            distance_m
        FROM line_raw
    ),
    out_features AS (
        SELECT 1 AS kind, distance_m, geometry FROM line
        UNION ALL
        SELECT 2 AS kind, NULL::double precision AS distance_m,
               CASE
                 WHEN %(tol)s > 0
                 THEN ST_Transform(
                        ST_SimplifyPreserveTopology(
                          ST_Transform((SELECT geometry FROM dest), 3857),
                          %(tol)s
                        ),
                        4326
                      )
                 ELSE (SELECT geometry FROM dest)
               END AS geometry
        UNION ALL
        SELECT 3 AS kind, NULL::double precision AS distance_m, (SELECT pt FROM src) AS geometry
    )
    SELECT jsonb_build_object(
        'type','FeatureCollection',
        'features', COALESCE(jsonb_agg(
            jsonb_build_object(
                'type','Feature',
                'id', kind,
                'geometry', ST_AsGeoJSON(geometry)::jsonb,
                'properties', jsonb_build_object(
                    'role', CASE kind WHEN 1 THEN 'line' WHEN 2 THEN 'destination' WHEN 3 THEN 'origin' END,
                    'distance_m', distance_m,
                    'distance_km', CASE
  WHEN distance_m IS NULL THEN NULL
  ELSE ROUND((distance_m/1000.0)::numeric, 3)::float8
END

                )
            )
        ), '[]'::jsonb)
    ) AS fc
    FROM out_features;
    """
    try:
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(sql, {"lon": lon, "lat": lat, "tol": tolerance, "max_km": max_km})
                row = cur.fetchone()
                return ok(row["fc"])
    except Exception as e:
        return bad_request(f"Rota hesaplanamadı: {e}")
    
@app.get("/api/assembly-areas")
def assembly_areas():
    table = f'{POSTGIS_SCHEMA}."{ASSEMBLY_TABLE}"'
    geom_col = ASSEMBLY_GEOM_COLUMN
    sql = f"""
    WITH src AS (
      SELECT
        {geom_col} AS geom,
        jsonb_strip_nulls(jsonb_build_object(
          'ADI', "ADI",
          'ILCE', "ILCE",
          'MAHALLE', "MAHALLE",
          'YOL', "YOL",
          'KAPINO', "KAPINO"
        )) AS props
      FROM {table}
      WHERE {geom_col} IS NOT NULL AND NOT ST_IsEmpty({geom_col})
    ),
    numbered AS (
      SELECT row_number() OVER() AS id, geom, props FROM src
    )
    SELECT jsonb_build_object(
      'type','FeatureCollection',
      'features', COALESCE(jsonb_agg(
        jsonb_build_object(
          'type','Feature',
          'id', id,
          'geometry', ST_AsGeoJSON(geom)::jsonb,
          'properties', props
        )
      ), '[]'::jsonb)
    ) AS fc
    FROM numbered;
    """
    try:
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(sql)
                row = cur.fetchone()
                return ok(row["fc"])
    except Exception as e:
        return bad_request(f"Toplanma alanları okunamadı: {e}")

@app.get("/api/burn-summary")
def burn_summary():
    table = f'{POSTGIS_SCHEMA}."burn_polys"'
    sql = f"""
    SELECT
      class,
      ROUND((SUM(ST_Area(geometry::geography))/1e6)::numeric, 3) AS area_km2,
      COUNT(*) AS n_polys
    FROM {table}
    GROUP BY class
    ORDER BY class;
    """
    try:
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(sql)
                rows = cur.fetchall()
                return ok({"summary": rows})
    except Exception as e:
        return bad_request(f"Özet hesaplanamadı: {e}")





# ──────────────────────────────────────────────────────────────────────────────
# Entry
# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app.run(host=HOST, port=PORT, debug=DEBUG)
