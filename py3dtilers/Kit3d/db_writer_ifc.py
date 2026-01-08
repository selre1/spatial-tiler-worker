import json, hashlib, zlib
from typing import Any, Dict, List, Optional, Tuple
from pathlib import Path
import numpy as np
import psycopg2


def _material_to_rgba_and_extras(mat: Any) -> Tuple[List[float], Dict[str, Any]]:
    if isinstance(mat, dict):
        pbr = mat.get("pbrMetallicRoughness") or {}
        bc = pbr.get("baseColorFactor")
        if isinstance(bc, (list, tuple)) and len(bc) == 4:
            rgba = [float(x) for x in bc]
        else:
            rgba = [1.0, 1.0, 1.0, 1.0]
        return rgba, mat

    try:
        pbr = getattr(mat, "pbrMetallicRoughness", None)
        bc = getattr(pbr, "baseColorFactor", None)
        if bc and len(bc) == 4:
            rgba = [float(x) for x in bc]
        else:
            rgba = [1.0, 1.0, 1.0, 1.0]
        return rgba, {"_material_repr": str(mat)}
    except Exception:
        return [1.0, 1.0, 1.0, 1.0], {"_material_repr": str(mat)}


def _rgba_to_hex(rgba: List[float]) -> str:
    # rgba는 0~1 float 가정 (baseColorFactor)
    r, g, b, a = rgba

    def clamp01(x: float) -> float:
        return max(0.0, min(1.0, float(x)))

    def to2(x: float) -> str:
        v = int(round(clamp01(x) * 255))
        return f"{v:02X}"

    return "#" + to2(r) + to2(g) + to2(b) + to2(a)


def _fingerprint(rgba: List[float], extras: Dict[str, Any]) -> str:
    payload = {"rgba": rgba, "extras": extras}
    s = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


def _encode_triangles_blob(triangles: List) -> Tuple[bytes, int, Dict[str, Any]]:
    arr = np.asarray(triangles, dtype=np.float32)  # (n,3,3)
    raw = arr.tobytes(order="C")
    blob = zlib.compress(raw, level=3)
    meta = {"codec": "zlib", "dtype": "float32", "shape": list(arr.shape)}
    return blob, int(arr.shape[0]), meta


def _triangles_to_polyhedralsurface_ewkt(triangles: List, srid: int = 5186) -> str:
    # (주의) 이건 엄청 무거움. 지금 구조 유지 시 필요하면 쓰되, 큰 모델이면 병목.
    faces = []
    for tri in triangles:
        p0, p1, p2 = tri
        ring = [p0, p1, p2, p0]
        ring_str = ", ".join([f"{p[0]} {p[1]} {p[2]}" for p in ring])
        faces.append(f"(({ring_str}))")
    wkt = "POLYHEDRALSURFACE Z (" + ",".join(faces) + ")"
    return f"SRID={srid};{wkt}"


def _build_mesh_shaders(
    tri_count: int,
    material_parts_local: Optional[List[Dict[str, Any]]] = None,
    default_hex: str = "#F0F0F0FF",
) -> Dict[str, Any]:
    basecolors = [default_hex] * tri_count
    material_parts_local = material_parts_local or []

    for part in material_parts_local:
        rgba, _ = _material_to_rgba_and_extras(part["material"])
        hexcolor = _rgba_to_hex(rgba)

        for idx in (part.get("face_indices") or []):
            if isinstance(idx, int) and 0 <= idx < tri_count:
                basecolors[idx] = hexcolor

    return {
        "PbrMetallicRoughness": {
            "BaseColors": basecolors
        }
    }

class IFCDBWriter:
    def __init__(self, db_config: str, *, write_geom: bool = True):
        self.conn = psycopg2.connect(db_config)
        self.conn.autocommit = False
        self.write_geom = write_geom
        self._mat_cache: Dict[str, int] = {}
        self.run_id: Optional[int] = None

    def close(self):
        self.conn.commit()
        self.conn.close()

    def create_run(self, ifc_path: str) -> int:
        p = Path(ifc_path)
        ifc_name = p.name
        ifc_hash = None

        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ifc_run (ifc_name, ifc_hash)
                VALUES (%s, %s)
                RETURNING run_id
                """,
                (ifc_name, ifc_hash)
            )
            self.run_id = cur.fetchone()[0]
        self.conn.commit()
        return self.run_id

    def upsert_material(self, material_obj: Any) -> int:
        rgba, extras = _material_to_rgba_and_extras(material_obj)
        fp = _fingerprint(rgba, extras)
        if fp in self._mat_cache:
            return self._mat_cache[fp]

        basecolor_hex = _rgba_to_hex(rgba)

        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ifc_material (basecolor_hex, rgba, extras, fingerprint)
                VALUES (%s, %s, %s::jsonb, %s)
                ON CONFLICT (fingerprint) DO UPDATE
                SET basecolor_hex = EXCLUDED.basecolor_hex,
                    rgba = EXCLUDED.rgba,
                    extras = EXCLUDED.extras
                RETURNING material_id
                """,
                (basecolor_hex, rgba, json.dumps(extras, ensure_ascii=False), fp),
            )
            mid = cur.fetchone()[0]
            self._mat_cache[fp] = mid
            return mid

    def upsert_object(
        self,
        guid: str,
        ifc_class: str,
        ifc_group: Optional[str],
        ifc_space: Optional[str],
        props: Dict[str, Any],
        centroid_xyz: Tuple[float, float, float],
    ):
        if self.run_id is None:
            raise RuntimeError("run_id is not set. Call create_run(ifc_path) first.")

        x, y, z = centroid_xyz
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ifc_object (guid, run_id, ifc_class, ifc_group, ifc_space, props, centroid)
                VALUES (
                  %s, %s, %s, %s, %s,
                  %s::jsonb,
                  ST_SetSRID(ST_MakePoint(%s,%s,%s), 5186)
                )
                ON CONFLICT (guid) DO UPDATE
                SET run_id = EXCLUDED.run_id,
                    ifc_class = EXCLUDED.ifc_class,
                    ifc_group = EXCLUDED.ifc_group,
                    ifc_space = EXCLUDED.ifc_space,
                    props = EXCLUDED.props,
                    centroid = EXCLUDED.centroid
                """,
                (guid, self.run_id, ifc_class, ifc_group, ifc_space,
                 json.dumps(props, ensure_ascii=False),
                 float(x), float(y), float(z))
            )

    def upsert_mesh(self, guid: str, triangles: List, shaders: Optional[Dict[str, Any]]):
        blob, tri_count, meta = _encode_triangles_blob(triangles)

        ewkt = None
        if self.write_geom:
            ewkt = _triangles_to_polyhedralsurface_ewkt(triangles, srid=5186)

        shaders_json = None if shaders is None else json.dumps(shaders, ensure_ascii=False)

        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ifc_mesh (guid, geom, triangles_blob, triangles_count, shaders, extras)
                VALUES (
                  %s,
                  CASE WHEN %s IS NULL THEN NULL ELSE ST_GeomFromEWKT(%s) END,
                  %s,
                  %s,
                  %s::jsonb,
                  %s::jsonb
                )
                ON CONFLICT (guid) DO UPDATE
                SET geom = COALESCE(EXCLUDED.geom, ifc_mesh.geom),
                    triangles_blob = EXCLUDED.triangles_blob,
                    triangles_count = EXCLUDED.triangles_count,
                    shaders = EXCLUDED.shaders,
                    extras = EXCLUDED.extras
                """,
                (
                    guid,
                    ewkt, ewkt,
                    psycopg2.Binary(blob),
                    tri_count,
                    shaders_json,
                    json.dumps(meta, ensure_ascii=False),
                )
            )

    def upsert_material_parts(self, guid: str, material_parts_local: List[Dict[str, Any]]):
        with self.conn.cursor() as cur:
            for part in material_parts_local:
                mid = self.upsert_material(part["material"])
                face_idx = part.get("face_indices") or []
                cur.execute(
                    """
                    INSERT INTO ifc_object_material_part (guid, material_id, face_indices)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (guid, material_id) DO UPDATE
                    SET face_indices = EXCLUDED.face_indices
                    """,
                    (guid, mid, face_idx)
                )

    def save_ifc_object(self, obj):
        guid = obj.get_id()
        props = obj.get_batchtable_data()
        cx, cy, cz = obj.get_centroid()

        self.upsert_object(
            guid=guid,
            ifc_class=obj.ifcClass,
            ifc_group=getattr(obj, "ifcGroup", None),
            ifc_space=getattr(obj, "ifcSpace", None),
            props=props,
            centroid_xyz=(cx, cy, cz)
        )

        triangles = obj.geom.triangles[0]
        tri_count = len(triangles)

        mpl = getattr(obj, "material_parts_local", None) or []

        # material 파트는 테이블에 저장
        if mpl:
            self.upsert_material_parts(guid, mpl)

        # ★ pg2b3dm용 shaders는 guid별로 "triangle count만큼 펼쳐서" ifc_mesh.shaders에 저장
        shaders = _build_mesh_shaders(tri_count, material_parts_local=mpl, default_hex="#FFFFFFFF")
        self.upsert_mesh(guid, triangles, shaders)

        self.conn.commit()
