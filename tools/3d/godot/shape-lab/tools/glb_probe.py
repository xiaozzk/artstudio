# -*- coding: utf-8 -*-
"""shape-lab · GLB 容器解析（**纯标准库**，不 import bpy、不依赖 numpy）。

只做"读容器 + 提取事实"，判定逻辑留在 `bake.py`（报告口径集中在一处）。
给 bake.py 的自检 a 用，也给独立验收者（verifier）复算用。

    from glb_probe import parse_glb, container_facts
    info = parse_glb("tmp/shape-lab/glb/Female_Ranger.glb")
    facts = container_facts(info)

GLB 结构（glTF 2.0）：
  12 字节头 = magic 'glTF' + uint32 version + uint32 length
  之后是若干 chunk：uint32 chunkLength + uint32 chunkType + data
    0x4E4F534A = 'JSON'（第一块，必须）
    0x004E4942 = 'BIN\\0'（可选）
"""
import json
import struct

_MAGIC = b"glTF"
_CHUNK_JSON = 0x4E4F534A
_CHUNK_BIN = 0x004E4942


def target_proxy_disp(prim, target_index):
    """morph target 位移量的**逐轴下界**（米）：`max_axis max(|min|, |max|)`。

    glTF 的 morph target POSITION 是位移向量，accessor 自带 min/max 数组 →
    不开二进制就能判断"这个 target 是不是空的"。数学上它 ≤ 真实最大位移模长
    （向量模长 ≥ 任一分量绝对值），所以可以拿去和上游 manifest 的 max_disp 对上界比对；
    旋转变换（Blender Z-up → glTF Y-up）只置换分量，不改这个量的取值集合。
    """
    if target_index >= len(prim.get("targets_detail", [])):
        return None
    d = prim["targets_detail"][target_index]
    if not d.get("min") or not d.get("max"):
        return None
    return max(max(abs(a), abs(b)) for a, b in zip(d["min"], d["max"]))


def parse_glb(path):
    """解析 GLB，返回 {header, chunks, gltf, bin_bytes, file_size}。格式不对直接抛异常。"""
    with open(path, "rb") as f:
        raw = f.read()
    if len(raw) < 12:
        raise ValueError("%s: 文件不足 12 字节（%d）" % (path, len(raw)))
    magic, version, length = struct.unpack_from("<4sII", raw, 0)
    if magic != _MAGIC:
        raise ValueError("%s: magic 不是 glTF 而是 %r" % (path, magic))
    if version != 2:
        raise ValueError("%s: glTF version=%d（本工具只支持 2）" % (path, version))
    if length != len(raw):
        raise ValueError("%s: 头部 length=%d 与实际文件大小 %d 不符" % (path, length, len(raw)))

    chunks = []
    off = 12
    gltf = None
    bin_bytes = 0
    while off + 8 <= len(raw):
        clen, ctype = struct.unpack_from("<II", raw, off)
        data = raw[off + 8: off + 8 + clen]
        if len(data) != clen:
            raise ValueError("%s: chunk 截断（声明 %d，实际 %d）" % (path, clen, len(data)))
        name = {_CHUNK_JSON: "JSON", _CHUNK_BIN: "BIN"}.get(ctype, "0x%08X" % ctype)
        chunks.append({"type": name, "length": clen, "offset": off + 8})
        if ctype == _CHUNK_JSON:
            gltf = json.loads(data.decode("utf-8"))
        elif ctype == _CHUNK_BIN:
            bin_bytes += clen
        off += 8 + clen
    if gltf is None:
        raise ValueError("%s: 没有 JSON chunk" % path)
    return {
        "path": path,
        "header": {"magic": magic.decode("ascii"), "version": version, "length": length},
        "chunks": chunks,
        "gltf": gltf,
        "bin_bytes": bin_bytes,
        "file_size": len(raw),
    }


def container_facts(info):
    """把 glTF JSON 提炼成断言要用的形状（名字、morph、skin、权重）。"""
    g = info["gltf"]
    accessors = g.get("accessors", [])
    buffer_views = g.get("bufferViews", [])
    materials = [m.get("name") for m in g.get("materials", [])]

    def _image_bytes(img):
        bv = img.get("bufferView")
        if bv is None:
            return None
        return buffer_views[bv].get("byteLength")

    meshes = []
    for mi, m in enumerate(g.get("meshes", [])):
        prims = []
        for p in m.get("primitives", []):
            targets = p.get("targets", [])
            extras = p.get("extras") or {}
            tnames = extras.get("targetNames")
            idx_acc = p.get("indices")
            index_count = accessors[idx_acc].get("count") if idx_acc is not None else None
            pos_acc = (p.get("attributes") or {}).get("POSITION")
            position_count = accessors[pos_acc].get("count") if pos_acc is not None else None
            base_acc = accessors[pos_acc] if pos_acc is not None else {}
            # morph target 的 POSITION 存的是**位移量**，accessor 自带 min/max →
            # 不用解码二进制就能证明"morph 不是空的"（详见 target_proxy_disp）。
            targets_detail = []
            for t in targets:
                ta = t.get("POSITION")
                tacc = accessors[ta] if ta is not None else {}
                targets_detail.append({
                    "accessor": ta,
                    "count": tacc.get("count"),
                    "min": tacc.get("min"),
                    "max": tacc.get("max"),
                    "has_normal": "NORMAL" in t,
                })
            prims.append({
                "targets": len(targets),
                "target_names": tnames,
                "targets_detail": targets_detail,
                "extras_keys": sorted(extras.keys()),
                "index_count": index_count,
                "triangles": (index_count // 3) if index_count else None,
                "position_count": position_count,
                "position_min": base_acc.get("min"),
                "position_max": base_acc.get("max"),
                "has_normals": "NORMAL" in (p.get("attributes") or {}),
                "has_texcoords": "TEXCOORD_0" in (p.get("attributes") or {}),
                "has_joints": "JOINTS_0" in (p.get("attributes") or {}),
                "material": materials[p["material"]] if "material" in p else None,
                "mode": p.get("mode", 4),
            })
        # morph 名字实测落在 **mesh 层的 extras.targetNames**（Blender 5.2 的写法），
        # primitive 层的 extras 是 None；两种位置都认，并把来源记下来。
        mesh_extras = m.get("extras") or {}
        mesh_tnames = mesh_extras.get("targetNames")
        prim_tname_sets = sorted({tuple(p["target_names"]) for p in prims if p["target_names"]},
                                 key=list)
        if mesh_tnames:
            resolved, resolved_src = list(mesh_tnames), "mesh.extras.targetNames"
        elif len(prim_tname_sets) == 1:
            resolved, resolved_src = list(prim_tname_sets[0]), "primitive.extras.targetNames"
        else:
            resolved, resolved_src = None, "absent"
        meshes.append({
            "index": mi,
            "name": m.get("name"),
            "weights": m.get("weights"),
            "weight_count": len(m["weights"]) if isinstance(m.get("weights"), list) else 0,
            "primitives": prims,
            "prim_count": len(prims),
            "morph_prim_count": sum(1 for p in prims if p["targets"] > 0),
            "target_names": sorted(prim_tname_sets, key=list),
            "resolved_target_names": resolved,
            "target_names_source": resolved_src,
            "extras_keys": sorted(mesh_extras.keys()),
            "position_count": sum(p["position_count"] or 0 for p in prims),
            "triangles": sum(p["triangles"] or 0 for p in prims),
        })

    skins = []
    for s in g.get("skins", []):
        skins.append({
            "name": s.get("name"),
            "joints": len(s.get("joints", [])),
            "skeleton": (g.get("nodes", [{}])[s["skeleton"]].get("name")
                         if s.get("skeleton") is not None else None),
        })

    node_names = [n.get("name") for n in g.get("nodes", [])]
    node_weights = [{"node": n.get("name"), "weights": n["weights"]}
                    for n in g.get("nodes", []) if "weights" in n]
    # 节点名（Godot 场景树里看到的名字）→ glTF mesh（Blender 用 mesh data 名，可能是
    # `Plane.002` 这种与物体名无关的名字，所以**一律按节点名索引、按 index 取 mesh**）
    node_mesh_pairs = [{"node": n.get("name"), "mesh": g["meshes"][n["mesh"]].get("name"),
                        "mesh_index": n["mesh"]}
                       for n in g.get("nodes", []) if "mesh" in n]
    return {
        "asset": g.get("asset", {}),
        "file_size": info["file_size"],
        "bin_bytes": info["bin_bytes"],
        "counts": {
            "nodes": len(g.get("nodes", [])),
            "meshes": len(meshes),
            "skins": len(skins),
            "materials": len(materials),
            "images": len(g.get("images", [])),
            "textures": len(g.get("textures", [])),
            "accessors": len(accessors),
            "bufferViews": len(buffer_views),
        },
        "skins": skins,
        "meshes": meshes,
        "mesh_names": [m["name"] for m in meshes],
        "node_names": node_names,
        "node_mesh_pairs": node_mesh_pairs,
        "node_weights": node_weights,
        "materials": materials,
        "images": [{"name": i.get("name"), "mimeType": i.get("mimeType"),
                    "bufferView_bytes": _image_bytes(i),
                    "uri": i.get("uri")} for i in g.get("images", [])],
        "extensions_used": g.get("extensionsUsed", []),
    }


if __name__ == "__main__":  # 手工排查用：python glb_probe.py <a.glb> [b.glb ...]
    import sys
    for path in sys.argv[1:]:
        f = container_facts(parse_glb(path))
        print("=" * 60)
        print(path)
        print(" size", f["file_size"], "asset", f["asset"].get("generator"))
        print(" counts", f["counts"])
        print(" skins", f["skins"])
        for m in f["meshes"]:
            print("  mesh %-38s prims=%d morph_prims=%d weights=%s target_names=%s(%s)" % (
                m["name"], m["prim_count"], m["morph_prim_count"], m["weights"],
                m["resolved_target_names"], m["target_names_source"]))
