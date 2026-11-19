"""Convert rFactor 2 GMT v2.52 binaries to Automobilista 1 / rFactor 1 GMT v2.20.

Blender's io_rf2_gmt_release addon exports only gMotor 2.5 (GMOTOR_GMT_2.52)
files: an 884-byte header (magic at 0x1BC), 156-byte mesh descriptors,
interleaved 96-byte TVertex2 records, and single-level materials with 180-byte
texture records.

Automobilista 1 (gMotor 2.0) requires GMOTOR_GMT_2.20 files: a 740-byte header
(magic at 0x1D4), 132-byte mesh descriptors, split 32-byte TVertex / 32-byte
TexturesUV / optional 24-byte UVTangents arrays per mesh, and 3-level
(L0/L1/L2) materials with 172-byte texture records using shaders defined in
AMS1's coreshaders.mas.
"""
import struct

try:
    import numpy as _np
except ImportError:
    _np = None

RF1_GMT_MAGIC = bytes.fromhex("c8cfd2d8ced8e6c3d6ded8bebba8bf90")  # GMOTOR_GMT_2.20\0
RF2_GMT_MAGIC = bytes.fromhex("c8cfd2d8ced8e6c3d6ded8bebbabc190")  # GMOTOR_GMT_2.52\0

RF1_MAGIC_OFFSET = 0x1D4
RF2_MAGIC_OFFSET = 0x1BC

RF1_HEADER_SIZE = 0x2E4  # 740 bytes; MeshOffset = 0x2E0 (relative to byte 4)
RF2_HEADER_SIZE = 0x378  # 888 bytes; MeshOffset = 0x374 (relative to byte 4)

RF1_GMT_FLAGS = 0x00000020
RF1_MESH_SIZE = 132
RF2_MESH_SIZE = 156

FACE_SIZE = 32
NORMAL_SIZE = 16
RF1_VERTEX_SIZE = 32
RF1_UV_SIZE = 32
RF1_TANGENT_SIZE = 24
RF2_VERTEX_SIZE = 96

RF1_MAT_HEADER_SIZE = 144
RF1_SHADER_INFO_SIZE = 264
RF1_MAT_POST_SHADERS_PAD = 32
RF1_TEXTURE_SIZE = 172

RF2_MAT_HEADER_SIZE = 260
RF2_TEXTURE_SIZE = 180

MESH_FLAG_TANGENTS = 0x00000004
MAT_FLAG_RF2_CARBODY = 0x00002000
TEX_FLAG_COLOR_KEY = 0x00000080


def is_rf1_gmt(data):
    """Return True when raw GMT bytes already carry the GMOTOR_GMT_2.20 magic."""
    return (len(data) >= RF1_MAGIC_OFFSET + len(RF1_GMT_MAGIC)
            and data[RF1_MAGIC_OFFSET:RF1_MAGIC_OFFSET + len(RF1_GMT_MAGIC)] == RF1_GMT_MAGIC)


def is_rf2_gmt(data):
    """Return True when raw GMT bytes carry the GMOTOR_GMT_2.52 magic."""
    return (len(data) >= RF2_MAGIC_OFFSET + len(RF2_GMT_MAGIC)
            and data[RF2_MAGIC_OFFSET:RF2_MAGIC_OFFSET + len(RF2_GMT_MAGIC)] == RF2_GMT_MAGIC)


def _pad_ascii(text, size):
    encoded = text.encode("ascii", errors="replace")[:size - 1]
    return encoded + b"\x00" * (size - len(encoded))


def _rf2_tex_to_rf1(tex_raw, stage):
    """Shrink a 180-byte rF2 texture record to the 172-byte AMS1/rF1 layout."""
    out = bytearray(RF1_TEXTURE_SIZE)
    out[:108] = tex_raw[:108]
    struct.pack_into("<I", out, 88, stage)
    flags = struct.unpack_from("<I", out, 64)[0]
    alpha_ref = struct.unpack_from("<I", out, 100)[0]
    if not (flags & TEX_FLAG_COLOR_KEY) and alpha_ref == 0:
        struct.pack_into("<I", out, 100, 1)
    return bytes(out)


def _tex_stage(tex_raw, fallback):
    stage = struct.unpack_from("<I", tex_raw, 88)[0]
    return stage if 0 <= stage < 4 else fallback


def _map_material_for_ams1(rf2_shader, textures):
    """Map an rF2 shader and its textures to AMS1's 3-level shader set.

    Returns (has_bump, uv_perm, shader_levels) where:
      - has_bump: whether AMS1 needs the 24-byte UVTangents block (mflags |= 4)
      - uv_perm: 4-tuple mapping AMS1 TEXCOORD[k] <- rF2 UV[uv_perm[k]]
      - shader_levels: list of 3 tuples (shader_name, [(tex_raw, stage), ...])
    """
    shader = rf2_shader.strip().upper()

    if shader == "L2BUMPSPECMAPT0XT1" and len(textures) >= 4:
        # rF2 L2BUMPSPECMAPT0XT1 does not exist in AMS1 coreshaders.mas.
        # AMS1's L2BumpSpecMapT0MulT1Custom (REIZA.GFX / USER.GFX) performs
        # the exact base*detail multiply with specular and bump maps using
        # stage order (0=sBase, 1=sSpec, 2=sBump, 3=sBase1).
        base, detail, spec, bump = textures[0], textures[1], textures[2], textures[3]
        uv_perm = (
            _tex_stage(base, 0),
            _tex_stage(spec, 2),
            _tex_stage(bump, 3),
            _tex_stage(detail, 1),
        )
        levels = [
            ("L0DIFFUSET0", [(base, 0)]),
            ("L1DIFFUSET0", [(base, 0)]),
            ("L2BUMPSPECMAPT0MULT1CUSTOM", [
                (base, 0),
                (spec, 1),
                (bump, 2),
                (detail, 3),
            ]),
        ]
        return True, uv_perm, levels

    if shader == "L2BUMPSPECMAPT0" and len(textures) >= 3:
        base, spec, bump = textures[0], textures[1], textures[2]
        uv_perm = (
            _tex_stage(base, 0),
            _tex_stage(spec, 1),
            _tex_stage(bump, 2),
            3,
        )
        levels = [
            ("L0DIFFUSET0", [(base, 0)]),
            ("L1DIFFUSET0", [(base, 0)]),
            ("L2BUMPSPECMAPT0", [
                (base, 0),
                (spec, 1),
                (bump, 2),
            ]),
        ]
        return True, uv_perm, levels

    if shader == "L2DIFFUSET0" or len(textures) == 1:
        base = textures[0]
        uv_perm = (_tex_stage(base, 0), 1, 2, 3)
        levels = [
            ("L0DIFFUSET0", [(base, 0)]),
            ("L1DIFFUSET0", [(base, 0)]),
            ("L2DIFFUSET0", [(base, 0)]),
        ]
        return False, uv_perm, levels

    has_bump = "BUMP" in shader
    l01 = [(textures[0], 0)] if textures else []
    l2 = [(tex, idx) for idx, tex in enumerate(textures)]
    levels = [
        ("L0DIFFUSET0", l01),
        ("L1DIFFUSET0", l01),
        (shader or "L2DIFFUSET0", l2),
    ]
    return has_bump, (0, 1, 2, 3), levels


def _split_vertices(data, vert_offset_bytes, vert_count, uv_perm, need_tangents):
    """Split 96-byte rF2 TVertex2 records into rF1 vertices, UVs, and tangents."""
    if vert_count == 0:
        return b"", b"", (b"" if need_tangents else None)

    span = vert_count * RF2_VERTEX_SIZE
    raw = memoryview(data)[vert_offset_bytes:vert_offset_bytes + span]

    if _np is not None:
        arr = _np.frombuffer(raw, dtype=_np.uint8).reshape(vert_count, RF2_VERTEX_SIZE)
        # rF1 TVertex (32B): pos(12) + norm(12) + dcolor(4) + scolor=0(4)
        verts = _np.zeros((vert_count, RF1_VERTEX_SIZE), dtype=_np.uint8)
        verts[:, :28] = arr[:, :28]

        # rF1 TexturesUV (32B): 4 UV pairs (8B each), permuted from bytes 64..96
        uvs = _np.empty((vert_count, RF1_UV_SIZE), dtype=_np.uint8)
        for dst_i, src_i in enumerate(uv_perm):
            src_off = 64 + src_i * 8
            dst_off = dst_i * 8
            uvs[:, dst_off:dst_off + 8] = arr[:, src_off:src_off + 8]

        if need_tangents:
            # rF1 UVTangents (24B): tangent(12) + bitangent(12) from bytes 40..64
            tangents = _np.ascontiguousarray(arr[:, 40:64]).tobytes()
        else:
            tangents = None
        return verts.tobytes(), uvs.tobytes(), tangents

    verts = bytearray(vert_count * RF1_VERTEX_SIZE)
    uvs = bytearray(vert_count * RF1_UV_SIZE)
    tangents = bytearray(vert_count * RF1_TANGENT_SIZE) if need_tangents else None
    p0, p1, p2, p3 = (64 + s * 8 for s in uv_perm)
    for i in range(vert_count):
        s = i * RF2_VERTEX_SIZE
        dv = i * RF1_VERTEX_SIZE
        verts[dv:dv + 28] = raw[s:s + 28]
        du = i * RF1_UV_SIZE
        uvs[du:du + 8] = raw[s + p0:s + p0 + 8]
        uvs[du + 8:du + 16] = raw[s + p1:s + p1 + 8]
        uvs[du + 16:du + 24] = raw[s + p2:s + p2 + 8]
        uvs[du + 24:du + 32] = raw[s + p3:s + p3 + 8]
        if need_tangents:
            dt = i * RF1_TANGENT_SIZE
            tangents[dt:dt + 24] = raw[s + 40:s + 64]
    return bytes(verts), bytes(uvs), (bytes(tangents) if need_tangents else None)


def _bbox_corners(bbox_min, bbox_max):
    """Build the 8 bounding-box corners in rF1 bottom-then-top order."""
    x0, y0, z0 = bbox_min
    x1, y1, z1 = bbox_max
    return (
        x1, y0, z0,
        x1, y0, z1,
        x0, y0, z1,
        x0, y0, z0,
        x1, y1, z0,
        x1, y1, z1,
        x0, y1, z1,
        x0, y1, z0,
    )


def convert_rf2_to_rf1(data, label="GMT"):
    """Convert raw rF2 GMT v2.52 bytes to AMS1/rF1 GMT v2.20 bytes.

    Already-converted rF1 GMT v2.20 inputs are returned unchanged.
    """
    if is_rf1_gmt(data):
        return data
    if not is_rf2_gmt(data):
        raise RuntimeError(
            "unsupported GMT version or corrupted header in %s" % label)
    if len(data) < RF2_HEADER_SIZE:
        raise RuntimeError("truncated rF2 GMT header in %s" % label)

    mat_off = struct.unpack_from("<I", data, 0)[0] + 4
    bbox_min = struct.unpack_from("<3f", data, 0x0C8)
    bbox_max = struct.unpack_from("<3f", data, 0x0D4)
    radius = struct.unpack_from("<f", data, 0x0E0)[0]
    origin = struct.unpack_from("<3f", data, 0x0E4)
    pivot = struct.unpack_from("<3f", data, 0x0F0)
    lod_in, lod_out = struct.unpack_from("<2f", data, 0x100)
    (vcount, voff_rel, tcount, toff_rel, nmesh, moff_rel,
     nface, foff_rel, nnorm, noff_rel, bcnt, _boff_rel) = struct.unpack_from(
        "<12I", data, 0x13C)
    name_raw = data[0x17C:0x1BC]

    if bcnt != 0:
        raise RuntimeError(
            "rigged rF2 GMT with %d bones is not supported: %s" % (bcnt, label))

    voff = voff_rel + 4
    toff = toff_rel + 4
    moff = moff_rel + 4
    foff = foff_rel + 4
    noff = noff_rel + 4

    for section, start, size in (
        ("meshes", moff, nmesh * RF2_MESH_SIZE),
        ("faces", foff, nface * FACE_SIZE),
        ("normals", noff, nnorm * NORMAL_SIZE),
        ("vertices", voff, vcount * RF2_VERTEX_SIZE),
        ("triangles", toff, tcount * 2),
    ):
        if start + size > len(data):
            raise RuntimeError(
                "truncated rF2 GMT %s section in %s" % (section, label))
    if mat_off + 4 > len(data):
        raise RuntimeError("truncated rF2 GMT materials section in %s" % label)

    # Parse rF2 materials first so each mesh knows its shader, UV permutation,
    # and whether tangent/bitangent streams are required.
    nmat = struct.unpack_from("<I", data, mat_off)[0]
    pos = mat_off + 4
    materials = []
    for mi in range(nmat):
        if pos + RF2_MAT_HEADER_SIZE > len(data):
            raise RuntimeError(
                "truncated rF2 GMT material %d in %s" % (mi, label))
        m_name = data[pos:pos + 64]
        m_flags = struct.unpack_from("<I", data, pos + 64)[0] & ~MAT_FLAG_RF2_CARBODY
        m_colors = data[pos + 68:pos + 132]
        src_blend, dst_blend = struct.unpack_from("<2I", data, pos + 132)
        spec_power = struct.unpack_from("<f", data, pos + 140)[0]
        rf2_shader = data[pos + 148:pos + 212].split(b"\x00", 1)[0].decode(
            "ascii", errors="replace")
        ntex = struct.unpack_from("<I", data, pos + 256)[0]
        pos += RF2_MAT_HEADER_SIZE
        textures = []
        for ti in range(ntex):
            if pos + RF2_TEXTURE_SIZE > len(data):
                raise RuntimeError(
                    "truncated rF2 GMT texture %d in %s" % (ti, label))
            tex_raw = data[pos:pos + RF2_TEXTURE_SIZE]
            anim = struct.unpack_from("<I", tex_raw, 72)[0]
            if anim != 1:
                raise RuntimeError(
                    "animated texture (type %d) is not supported in %s"
                    % (anim, label))
            textures.append(tex_raw)
            pos += RF2_TEXTURE_SIZE
        has_bump, uv_perm, levels = _map_material_for_ams1(rf2_shader, textures)
        materials.append({
            "name": m_name,
            "flags": m_flags,
            "colors": m_colors,
            "src_blend": src_blend,
            "dst_blend": dst_blend,
            "spec_power": spec_power,
            "has_bump": has_bump,
            "uv_perm": uv_perm,
            "levels": levels,
        })
    if pos != len(data):
        raise RuntimeError(
            "unexpected trailing bytes (%d) after rF2 GMT materials in %s"
            % (len(data) - pos, label))

    # Parse rF2 mesh descriptors.
    meshes = []
    for mi in range(nmesh):
        base = moff + mi * RF2_MESH_SIZE
        vals = struct.unpack_from("<10I", data, base)
        m_flags = vals[0]
        m_vcount = vals[1]
        m_tcount = vals[3]
        m_vstart = vals[6]
        m_tstart = vals[8]
        m_mat = vals[9]
        if m_vstart + m_vcount > vcount or m_tstart + m_tcount > tcount:
            raise RuntimeError(
                "rF2 GMT mesh %d geometry range out of bounds in %s" % (mi, label))
        if nmat and m_mat >= nmat:
            raise RuntimeError(
                "rF2 GMT mesh %d material index %d out of range in %s"
                % (mi, m_mat, label))
        meshes.append((m_flags, m_vcount, m_tcount, m_vstart, m_tstart, m_mat))

    # Assemble rF1 GMT v2.20 binary.
    out = bytearray(RF1_HEADER_SIZE + nmesh * RF1_MESH_SIZE)

    face_off = len(out)
    out.extend(data[foff:foff + nface * FACE_SIZE])

    norm_off = len(out)
    out.extend(data[noff:noff + nnorm * NORMAL_SIZE])

    first_vert_off = None
    for mi, (m_flags, m_vcount, m_tcount, m_vstart, m_tstart, m_mat) in enumerate(meshes):
        mat = materials[m_mat] if materials else None
        has_bump = bool(mat["has_bump"]) if mat else False
        uv_perm = mat["uv_perm"] if mat else (0, 1, 2, 3)

        verts_bytes, uvs_bytes, tans_bytes = _split_vertices(
            data, voff + m_vstart * RF2_VERTEX_SIZE, m_vcount, uv_perm, has_bump)

        m_voff = len(out)
        if first_vert_off is None:
            first_vert_off = m_voff
        out.extend(verts_bytes)

        m_uvoff = len(out)
        out.extend(uvs_bytes)

        if has_bump:
            m_tanoff = len(out)
            out.extend(tans_bytes)
            rf1_mflags = m_flags | MESH_FLAG_TANGENTS
            rf1_tan_rel = m_tanoff - 4
        else:
            rf1_mflags = m_flags & ~MESH_FLAG_TANGENTS
            rf1_tan_rel = 0

        m_trioff = len(out)
        tri_src = toff + m_tstart * 2
        out.extend(data[tri_src:tri_src + m_tcount * 2])

        # Write 132-byte rF1 TGMTMesh descriptor.
        mbase = RF1_HEADER_SIZE + mi * RF1_MESH_SIZE
        struct.pack_into(
            "<10I", out, mbase,
            rf1_mflags,
            m_voff - 4,
            0,
            m_uvoff - 4,
            0,
            rf1_tan_rel,
            m_vcount,
            0,
            m_tcount,
            m_trioff - 4,
        )
        struct.pack_into("<I", out, mbase + 0x38, m_mat)
        struct.pack_into("<I", out, mbase + 0x4C, 0xFFFFFFFF)

    # Write rF1 materials section.
    rf1_mat_off = len(out)
    out.extend(struct.pack("<I", len(materials)))
    for mat in materials:
        out.extend(mat["name"])
        out.extend(struct.pack("<I", mat["flags"]))
        out.extend(mat["colors"])
        out.extend(struct.pack("<2If", mat["src_blend"], mat["dst_blend"],
                               mat["spec_power"]))
        tex_entries = []
        for shader_name, level_texs in mat["levels"]:
            first_tex = len(tex_entries)
            shader_block = bytearray(RF1_SHADER_INFO_SIZE)
            struct.pack_into("<2I", shader_block, 0, first_tex, len(level_texs))
            shader_block[8:72] = _pad_ascii(shader_name, 64)
            out.extend(shader_block)
            for tex_raw, stage in level_texs:
                tex_entries.append(_rf2_tex_to_rf1(tex_raw, stage))
        out.extend(bytes(RF1_MAT_POST_SHADERS_PAD))
        out.extend(struct.pack("<I", len(tex_entries)))
        for entry in tex_entries:
            out.extend(entry)

    # Fill rF1 header (740 bytes).
    struct.pack_into("<2If", out, 0, rf1_mat_off - 4, RF1_GMT_FLAGS, radius)
    struct.pack_into("<24f", out, 0x00C, *_bbox_corners(bbox_min, bbox_max))
    struct.pack_into("<3f", out, 0x0CC, *origin)
    struct.pack_into("<3f", out, 0x0D8, *pivot)
    struct.pack_into("<2f", out, 0x0E4, lod_in, lod_out)
    struct.pack_into(
        "<8I", out, 0x174,
        nmesh,
        RF1_HEADER_SIZE - 4,
        nface,
        face_off - 4,
        nnorm,
        norm_off - 4,
        0,
        (first_vert_off - 4) if first_vert_off is not None else 0,
    )
    out[0x194:0x1D4] = name_raw
    out[0x1D4:0x1E4] = RF1_GMT_MAGIC
    return bytes(out)


def make_minimal_rf1_gmt(name="skyboxi", texture="_invisible.dds"):
    """Build a valid minimal 1-triangle AMS1/rF1 GMT v2.20 binary."""
    return make_quad_rf1_gmt(
        name,
        ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 0.0, 1.0), (0.0, 0.0, 1.0)),
        texture=texture,
    )


def make_quad_rf1_gmt(name, corners, texture="_invisible.dds"):
    """Build a valid 2-triangle (4-vertex) AMS1/rF1 GMT v2.20 quad mesh."""
    xs = [c[0] for c in corners]
    ys = [c[1] for c in corners]
    zs = [c[2] for c in corners]
    bmin = (min(xs), min(ys), min(zs))
    bmax = (max(xs), max(ys), max(zs))
    center = tuple((a + b) * 0.5 for a, b in zip(bmin, bmax))
    dx, dy, dz = (b - a for a, b in zip(bmin, bmax))
    radius = max(1.0, 0.5 * (dx * dx + dy * dy + dz * dz) ** 0.5)

    # Compute face normal from first triangle (c0, c1, c2).
    u = (corners[1][0] - corners[0][0], corners[1][1] - corners[0][1], corners[1][2] - corners[0][2])
    v = (corners[2][0] - corners[0][0], corners[2][1] - corners[0][1], corners[2][2] - corners[0][2])
    nx = u[1] * v[2] - u[2] * v[1]
    ny = u[2] * v[0] - u[0] * v[2]
    nz = u[0] * v[1] - u[1] * v[0]
    nlen = (nx * nx + ny * ny + nz * nz) ** 0.5 or 1.0
    nx, ny, nz = nx / nlen, ny / nlen, nz / nlen

    out = bytearray(RF1_HEADER_SIZE + RF1_MESH_SIZE)
    face_off = len(out)
    tris = ((0, 1, 2), (0, 2, 3))
    for ti, (i0, i1, i2) in enumerate(tris):
        cx = (corners[i0][0] + corners[i1][0] + corners[i2][0]) / 3.0
        cy = (corners[i0][1] + corners[i1][1] + corners[i2][1]) / 3.0
        cz = (corners[i0][2] + corners[i1][2] + corners[i2][2]) / 3.0
        out.extend(struct.pack("<4H2I4f", i0, i1, i2, 5, 0, ti, cx, cy, cz, radius))
    norm_off = len(out)
    for _ in tris:
        out.extend(struct.pack("<3fI", nx, ny, nz, 0))
    vert_off = len(out)
    for vx, vy, vz in corners:
        out.extend(struct.pack("<6f2I", vx, vy, vz, nx, ny, nz, 0xFFFFFFFF, 0))
    uv_off = len(out)
    for u_, v_ in ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)):
        out.extend(struct.pack("<8f", u_, v_, u_, v_, u_, v_, u_, v_))
    tri_off = len(out)
    out.extend(struct.pack("<6H", 0, 1, 2, 0, 2, 3))
    mat_off = len(out)
    out.extend(struct.pack("<I", 1))
    out.extend(_pad_ascii(name, 64))
    out.extend(struct.pack("<I", 0x68900003))
    out.extend(struct.pack("<16f", *([1.0, 1.0, 1.0, 1.0] * 3 + [0.0, 0.0, 0.0, 1.0])))
    out.extend(struct.pack("<2If", 2, 1, 1.0))
    for si, sname in enumerate(("L0DIFFUSET0", "L1DIFFUSET0", "L2DIFFUSET0")):
        sb = bytearray(RF1_SHADER_INFO_SIZE)
        struct.pack_into("<2I", sb, 0, si, 1)
        sb[8:72] = _pad_ascii(sname, 64)
        out.extend(sb)
    out.extend(bytes(RF1_MAT_POST_SHADERS_PAD))
    out.extend(struct.pack("<I", 3))
    for _ in range(3):
        tb = bytearray(RF1_TEXTURE_SIZE)
        tb[:64] = _pad_ascii(texture, 64)
        struct.pack_into("<IiIIIfI", tb, 64, 0x18, -1, 1, 1, 3, 1.0, 0)
        struct.pack_into("<I", tb, 100, 1)
        out.extend(tb)
    struct.pack_into("<10I", out, RF1_HEADER_SIZE,
                     0x20004011, vert_off - 4, 0, uv_off - 4, 0, 0,
                     4, 0, 6, tri_off - 4)
    struct.pack_into("<I", out, RF1_HEADER_SIZE + 0x4C, 0xFFFFFFFF)
    struct.pack_into("<2If", out, 0, mat_off - 4, RF1_GMT_FLAGS, radius)
    struct.pack_into("<24f", out, 0x00C, *_bbox_corners(bmin, bmax))
    struct.pack_into("<3f", out, 0x0CC, *center)
    struct.pack_into("<3f", out, 0x0D8, *center)
    struct.pack_into("<2f", out, 0x0E4, 0.0, 2000.0)
    struct.pack_into("<8I", out, 0x174, 1, RF1_HEADER_SIZE - 4,
                     2, face_off - 4, 2, norm_off - 4, 0, vert_off - 4)
    out[0x194:0x1D4] = _pad_ascii(name, 64)
    out[0x1D4:0x1E4] = RF1_GMT_MAGIC
    return bytes(out)


def convert_file(path):
    """Convert a GMT file on disk from rF2 v2.52 to AMS1/rF1 v2.20 in place."""
    with open(path, "rb") as f:
        original = f.read()
    converted = convert_rf2_to_rf1(original, label=path)
    if converted is not original:
        with open(path, "wb") as f:
            f.write(converted)
        return True
    return False
