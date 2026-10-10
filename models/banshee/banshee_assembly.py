"""
Banshee Jet 80+ aerial target - procedural Blender model with internal equipment
================================================================================
Builds the twin-turbojet Banshee Jet 80+ as separate parts that can be taken apart:

    skins       NoseCone, FuselageLower, FuselageUpper, Hatch, EngineCowl (+ Fin, Rudder)
    wings       Wing.L / Wing.R plugged into sockets of the lower fuselage on two joiner tubes,
                each with two elevon panels, their servos, linkages and one linkage fairing
    structure   Frame_1..3, EngineCradle, ExhaustBulkhead_Lower / _Upper, Spar_Front / _Rear
    equipment   LunebergLens, AvionicsTray + FlightComputer, Battery.L/.R, Receiver,
                Transponder, PowerUnit, ParachuteTray + Parachute, FuelTank_Fwd / _Main,
                EquipmentShelf + EngineECU.L/.R, FuelPump.L/.R, Engine.L / Engine.R
    (every object name carries the prefix  Jet80_)

The outer shape follows the published span / length / height (2.49 / 2.90 / 0.78 m) and
photographs.  The inside is an illustrative layout for assembly animations: what a
recoverable target of this kind carries, placed and sized to fit this model - it is
not taken from the real aircraft.

Exploded view / assembly sequence
    Jet80_ROOT["explode"]   0 = assembled ... 1 = fully exploded     (N panel > Item > Properties)
    Every part has the custom properties  assembly_order,  explode_offset (root axes, m)  and
    explode_window (the stretch of the slider over which it moves).  Parts leave in reverse
    build order, so sliding 1 -> 0 plays the assembly.  The timeline (frames 1-240) plays
    the same sequence through Jet80_ROOT["explode_anim"].

Movable parts (origin on the hinge line, rotate about LOCAL X only, limited to +/-30 deg):
    Jet80_Elevon_In.L / Out.L / In.R / Out.R     +X = trailing edge DOWN
    Jet80_Rudder                                 +X = trailing edge LEFT
Each elevon panel is driven through servo arm - push-rod - horn (parallelogram four-bar):
the arm copies the panel rotation and the rod, a child of the panel, tracks the arm pin.

Conventions:  units = metres,  nose = -Y,  up = +Z,  aircraft left wing = +X.
The root empty sits on the fuselage axis at 25 % of the wing mean aerodynamic chord.

Run inside Blender:  Scripting workspace > Open > Run Script
Run headless:        blender -b -P banshee_assembly.py
"""
import math
import os
from bisect import bisect_right

import bpy
import bmesh
from mathutils import Matrix, Vector

# ----------------------------------------------------------------------------
#  Parameters
# ----------------------------------------------------------------------------
SPAN = 2.49                 # wingspan (published)
SEMI = SPAN / 2.0
C_TIP = 0.32                # wing tip chord
SWEEP_LE = 41.0             # leading-edge sweep, deg (trailing edge unswept)
TAU_ROOT, TAU_TIP = 0.075, 0.090   # wing thickness ratio root / tip
R_TIP = 0.030               # wing-tip rounding radius
HINGE_GAP = 0.002           # radial gap between control-surface nose and cove
SIDE_GAP = 0.0025           # spanwise gap at each end of a control surface
PANEL_GAP = 0.004           # gap between the inboard and outboard elevon panels
TE_THICK = 0.0025           # trailing-edge thickness
LIMIT_ELEVON = 30.0         # +/- travel, deg
LIMIT_RUDDER = 30.0
HORN_OFFSET = 0.008         # horn centre to the panel end at the split
HORN_PIN = 0.020            # push-rod pin height above the panel skin
SERVO_AHEAD = 0.105         # servo output shaft ahead of the hinge line (= push-rod length)
ARM_HUB_R = 0.0065          # servo-arm hub radius
POCKET = dict(half_x=0.0042, half_y=0.0185, depth=0.0085, top=0.024)   # slot for the servo arm
N_RING = 56                 # points round a fuselage section
K_SPLIT = 1                 # ring cells above the centre line that stay on the lower fuselage
SHELL = 0.003               # fuselage skin thickness
SEAM = 0.0008               # gap drawn between neighbouring skin panels
Y_ROOT = 0.07               # the wing panels end here, inside the fuselage
SOCKET_GAP = 0.0012         # clearance of the wing-root socket in the fuselage
SPARS = ((0.30, 0.015), (0.65, 0.010))   # wing joiner tubes: (fraction of root chord, radius)
SPAR_REACH = 0.40           # how far the joiner tubes reach into each wing panel
SERVO = dict(along=0.038, chord=0.040, thick=0.020, shaft=0.010)   # elevon servo body

JET = dict(
    prefix="Jet80_", collection="Banshee Jet 80+",
    length=2.90, wing_xte=2.55, wing_z=-0.055,
    body=dict(nose=0.34, hatch=(0.46, 0.94), cowl=1.79, tail=2.80),
    elevon=dict(y_in=0.235, y_split=0.665, y_out=0.95, c_in=0.135, c_out=0.105),
    linkage=dict(                    # upper surface: screwed cover plate + open-ended hood
        upper=True,
        hood=dict(length=0.272, setback=0.018, width=0.062, height=0.030, cavity=0.125,
                  w=([0, .12, .35, .70, 1.0], [0, .42, .72, .93, 1.0]),
                  h=([0, .12, .35, .70, 1.0], [0, .22, .52, .86, 1.0]),
                  n=([0, 1.0], [2.3, 2.3])),
        plate=dict(centre=0.172, a_front=0.150, a_rear=0.146, half_w=0.095, expo=3.2,
                   taper=0.30, thick=0.0012, screws=(35, 95, 150, -35, -95, -150)),
    ),
    fin=dict(z_base=0.160, z_tip=0.630, c_root=0.66, c_tip=0.20, xte_base=2.70,
             sweep_te=22.0, tau_root=0.070, tau_tip=0.085, z_start=0.122,
             flare_t=1.25, flare_h=0.040, flare_x=0.20, flare_hx=0.050,
             r_tip=0.035, k_le=2.6, k_te=0.3,
             rud_z0=0.225, rud_z1=0.586, rud_frac=(0.27, 0.40)),
)
COLORS = dict(                       # sRGB hex, roughness, metallic, clear-coat
    jet_orange=("#EE3D14", 0.42, 0.0, 0.20),
    jet_yellow=("#F5C80F", 0.42, 0.0, 0.20),
    marking_black=("#0E0E0E", 0.55, 0.0, 0.0),
    dark_interior=("#161514", 0.70, 0.0, 0.0),
    steel_bright=("#B9B7B2", 0.28, 1.0, 0.0),
    steel_burnt=("#4A4038", 0.38, 1.0, 0.0),
    brass=("#B58A34", 0.32, 1.0, 0.0),
    nylon_black=("#1B1B1D", 0.50, 0.0, 0.0),
    aluminium=("#8D8D8A", 0.50, 1.0, 0.0),
    composite=("#CDBF98", 0.78, 0.0, 0.0),        # bare laminate: inside of the skins, frames
    carbon=("#1C1D20", 0.34, 0.0, 0.30),
    tank_white=("#E9E6DA", 0.42, 0.0, 0.10),
    lens_white=("#F2F0EA", 0.60, 0.0, 0.0),
    anodised_grey=("#5B5E63", 0.40, 1.0, 0.0),
    anodised_dark=("#2A2C30", 0.42, 1.0, 0.0),
    battery_blue=("#274A8C", 0.55, 0.0, 0.0),
    label_white=("#E8E8E6", 0.60, 0.0, 0.0),
    chute_orange=("#F0641E", 0.85, 0.0, 0.0),
    chute_white=("#EFECE4", 0.88, 0.0, 0.0),
    rubber=("#141414", 0.80, 0.0, 0.0),
    servo_black=("#202124", 0.48, 0.0, 0.0),
    plywood=("#C9A873", 0.70, 0.0, 0.0),
)


# ----------------------------------------------------------------------------
#  Small utilities
# ----------------------------------------------------------------------------
def _lin(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def hex_rgba(h):
    h = h.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    return (_lin(r), _lin(g), _lin(b), 1.0)


def material(key):
    """Principled material from the COLORS table (created once, updated on re-run)."""
    name = "Banshee_" + key
    hexcol, rough, metal, coat = COLORS[key]
    col = hex_rgba(hexcol)
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    if not mat.use_nodes:
        mat.use_nodes = True
    bsdf = next((n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if bsdf:
        for sock, val in (("Base Color", col), ("Roughness", rough), ("Metallic", metal),
                          ("Coat Weight", coat), ("Coat Roughness", 0.06)):
            if sock in bsdf.inputs:
                bsdf.inputs[sock].default_value = val
    mat.diffuse_color = col          # colour shown in Solid viewport mode
    mat.roughness = rough
    mat.metallic = metal
    return mat


def pchip(xs, ys):
    """Monotone cubic interpolation through (xs, ys); flat outside the range."""
    n = len(xs)
    h = [xs[i + 1] - xs[i] for i in range(n - 1)]
    d = [(ys[i + 1] - ys[i]) / h[i] for i in range(n - 1)]
    m = [0.0] * n
    m[0], m[-1] = d[0], d[-1]
    for i in range(1, n - 1):
        if d[i - 1] * d[i] > 0.0:
            w1, w2 = 2 * h[i] + h[i - 1], h[i] + 2 * h[i - 1]
            m[i] = (w1 + w2) / (w1 / d[i - 1] + w2 / d[i])

    def f(x):
        if x <= xs[0]:
            return ys[0]
        if x >= xs[-1]:
            return ys[-1]
        i = bisect_right(xs, x) - 1
        t = (x - xs[i]) / h[i]
        t2, t3 = t * t, t * t * t
        return ((2 * t3 - 3 * t2 + 1) * ys[i] + (t3 - 2 * t2 + t) * h[i] * m[i]
                + (-2 * t3 + 3 * t2) * ys[i + 1] + (t3 - t2) * h[i] * m[i + 1])
    return f


def first_font(*paths):
    """First font file that exists on this machine (None -> Blender's built-in font)."""
    return next((p for p in paths if os.path.exists(p)), None)


FONT_DISPLAY = first_font("/usr/share/fonts/opentype/inter/InterDisplay-Black.otf",
                          "C:/Windows/Fonts/ariblk.ttf",
                          "/System/Library/Fonts/Supplemental/Arial Black.ttf",
                          "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                          "C:/Windows/Fonts/arialbd.ttf")
FONT_STENCIL = first_font("/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
                          "C:/Windows/Fonts/timesbd.ttf",
                          "/System/Library/Fonts/Supplemental/Times New Roman Bold.ttf",
                          "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf")


def frange(a, b, step):
    n = max(1, int(round((b - a) / step)))
    return [a + (b - a) * i / n for i in range(n + 1)]


class MeshData:
    """Plain vertex / face / material-index buffers that can be concatenated.

    keep[i] marks faces whose winding is already correct (open sheets such as
    lettering); all other faces are oriented by Blender when the object is made.
    """

    def __init__(self):
        self.v, self.f, self.m, self.keep = [], [], [], []

    def face(self, idx, mat=0, keep=False):
        self.f.append(list(idx))
        self.m.append(mat)
        self.keep.append(keep)

    def add(self, verts, faces, mat=0, keep=False):
        """mat: one index for all faces, or a list with one index per face."""
        base = len(self.v)
        self.v.extend(Vector(p) for p in verts)
        for k, face in enumerate(faces):
            self.face([base + i for i in face],
                      mat[k] if isinstance(mat, (list, tuple)) else mat, keep)
        return self

    def transformed(self, fn):
        out = MeshData()
        out.v = [fn(p) for p in self.v]
        out.f = [list(f) for f in self.f]
        out.m = list(self.m)
        out.keep = list(self.keep)
        return out


def mesh_object(name, data, mats, coll, parent=None, sharp_deg=40.0, merge=1e-6):
    """MeshData -> smooth-shaded mesh object with sharp edges marked by angle."""
    me = bpy.data.meshes.new(name)
    me.from_pydata([tuple(p) for p in data.v], [], data.f)
    for mt in mats:
        me.materials.append(mt)
    me.polygons.foreach_set("material_index", data.m)
    bm = bmesh.new()
    bm.from_mesh(me)
    layer = bm.faces.layers.int.new("keep_winding")
    for face, keep in zip(bm.faces, data.keep):
        face[layer] = 1 if keep else 0
    if merge:
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=merge)
    loose = [v for v in bm.verts if not v.link_faces]
    if loose:
        bmesh.ops.delete(bm, geom=loose, context="VERTS")
    bmesh.ops.recalc_face_normals(bm, faces=[f for f in bm.faces if not f[layer]])
    bm.faces.layers.int.remove(layer)
    bm.normal_update()
    lim = math.radians(sharp_deg)
    for f in bm.faces:
        f.smooth = True
    for e in bm.edges:
        e.smooth = not (len(e.link_faces) == 2 and e.calc_face_angle(0.0) > lim)
    bm.to_mesh(me)
    bm.free()
    me.update()
    ob = bpy.data.objects.new(name, me)
    coll.objects.link(ob)
    if parent is not None:
        ob.parent = parent
    return ob


def lathe(profile, origin, axis, n=32, close=False, ref=None):
    """Revolve a (s, r) profile about `axis` through `origin`.  Returns (verts, faces)."""
    axis = Vector(axis).normalized()
    ref = Vector(ref) if ref else (Vector((0, 0, 1)) if abs(axis.z) < 0.9 else Vector((1, 0, 0)))
    e1 = (ref - axis * ref.dot(axis)).normalized()
    e2 = axis.cross(e1)
    origin = Vector(origin)
    verts, faces = [], []
    for s, r in profile:
        for k in range(n):
            th = 2 * math.pi * k / n
            verts.append(origin + axis * s + (e1 * math.cos(th) + e2 * math.sin(th)) * r)
    rows = len(profile)
    for j in range(rows if close else rows - 1):
        j2 = (j + 1) % rows
        for k in range(n):
            k2 = (k + 1) % n
            faces.append([j * n + k, j * n + k2, j2 * n + k2, j2 * n + k])
    return verts, faces


def box(center, size):
    cx, cy, cz = center
    sx, sy, sz = (0.5 * s for s in size)
    v = [(cx + dx * sx, cy + dy * sy, cz + dz * sz)
         for dx in (-1, 1) for dy in (-1, 1) for dz in (-1, 1)]
    f = [[0, 1, 3, 2], [4, 6, 7, 5], [0, 4, 5, 1], [2, 3, 7, 6], [0, 2, 6, 4], [1, 5, 7, 3]]
    return v, f


def rounded_box(center, size, r=0.003, seg=2):
    """Box with rounded edges.  Returns (verts, faces)."""
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    c = Vector(center)
    for v in bm.verts:
        v.co = Vector((v.co.x * size[0], v.co.y * size[1], v.co.z * size[2])) + c
    bmesh.ops.bevel(bm, geom=list(bm.edges), offset=min(r, 0.45 * min(size)), segments=seg,
                    profile=0.5, affect="EDGES")
    bm.verts.index_update()
    verts = [v.co.copy() for v in bm.verts]
    faces = [[v.index for v in f.verts] for f in bm.faces]
    bm.free()
    return verts, faces


def lathe_bands(profile, origin, axis, n=32):
    """Like lathe(), with a material per band: profile = [(s, r, material_index), ...]
    (the index of a point applies to the band that starts there).  Returns (verts, faces, mats)."""
    verts, faces = lathe([(q[0], q[1]) for q in profile], origin, axis, n)
    mats = [q[2] for q in profile[:-1] for _ in range(n)]
    return verts, faces, mats


def lock_all(ob, select=False):
    ob.lock_location = ob.lock_rotation = ob.lock_scale = (True, True, True)
    ob.hide_select = not select


# ----------------------------------------------------------------------------
#  Lifting surfaces with hinged trailing-edge controls
#  Generic coordinates:  xi = chordwise (aft +), eta = spanwise, zeta = thickness
# ----------------------------------------------------------------------------
def naca_ht(u):
    """NACA 4-digit half-thickness for unit chord and unit thickness ratio."""
    u = min(max(u, 0.0), 1.0)
    return 5.0 * (0.2969 * math.sqrt(u) - 0.1260 * u - 0.3516 * u * u
                  + 0.2843 * u ** 3 - 0.1036 * u ** 4)


class Surface:
    """sec(eta) -> (xi_leading_edge, chord, thickness_ratio, thickness_scale)."""

    def __init__(self, sec, te_thick=TE_THICK):
        self.sec = sec
        self.te = te_thick

    def half(self, xi, eta):
        xle, c, tau, ts = self.sec(eta)
        if c < 1e-9 or ts <= 0.0:
            return 0.0
        u = min(max((xi - xle) / c, 0.0), 1.0)
        return ts * (c * tau * naca_ht(u) + 0.5 * self.te * u)


class Hinge:
    """Straight hinge line on the chord plane.

    The control-surface nose and the cove in the fixed structure are both
    surfaces of revolution about this line, so the gap stays constant while
    the surface rotates.
    """

    def __init__(self, surf, eta0, eta1, chord0, chord1, limit_deg, gap=HINGE_GAP):
        self.surf, self.eta0, self.eta1, self.gap = surf, eta0, eta1, gap
        self.limit = limit_deg
        xle0, c0, _, _ = surf.sec(eta0)
        xle1, c1, _, _ = surf.sec(eta1)
        self.H0 = Vector((xle0 + c0 - chord0, eta0, 0.0))
        self.H1 = Vector((xle1 + c1 - chord1, eta1, 0.0))
        d = self.H1 - self.H0
        self.a = d.normalized()                              # along the hinge
        self.b = Vector((self.a.y, -self.a.x, 0.0))          # in-plane, pointing aft
        self.n = Vector((0.0, 0.0, 1.0))                     # surface normal

    def part(self, eta0, eta1):
        """Hinge for a panel that covers only eta0..eta1 of this hinge line."""
        def chord(e):
            xle, c, _, _ = self.surf.sec(e)
            return xle + c - self.xi_at(e)
        return Hinge(self.surf, eta0, eta1, chord(eta0), chord(eta1), self.limit, self.gap)

    def H(self, a):
        return self.H0 + self.a * a

    def r(self, a):
        p = self.H(a)
        return self.surf.half(p.x, p.y)

    def r_cove(self, a):
        return self.r(a) + self.gap

    def xi_at(self, eta):
        return self.H((eta - self.H0.y) / self.a.y).x

    def end_gap(self, eta):
        """Spanwise clearance needed at an end cut made at eta = const.

        With a raked hinge the nose of the surface moves spanwise as it turns
        (by up to 2 r sin(rake) sin(travel/2)), so the end gap has to grow with it.
        """
        r = self.r((eta - self.H0.y) / self.a.y)
        sweep = 2.0 * r * abs(self.a.x) * math.sin(math.radians(self.limit) / 2.0)
        return max(SIDE_GAP, sweep + 0.0020)

    def polar(self, p):
        w = p - self.H0
        a = w.dot(self.a)
        rad = w - self.a * a
        return a, rad.length, math.atan2(rad.dot(self.n), -rad.dot(self.b))

    def rev_point(self, eta, phi, radius):
        """Point of the revolved surface at angle phi lying in the plane eta = const."""
        cl, sl = self.a.y, self.a.x
        a = (eta - self.H0.y) / cl
        for _ in range(10):
            a = (eta - self.H0.y - radius(a) * math.cos(phi) * sl) / cl
        return self.H(a) + (self.n * math.sin(phi) - self.b * math.cos(phi)) * radius(a)

    def cut_xi(self, eta):
        """Chordwise position where the fixed skin meets the cove at station eta."""
        xh = self.xi_at(eta)
        r0 = max(self.surf.half(xh, eta), 0.003)
        lo, hi = xh - 8.0 * r0, xh

        def f(xi):
            a, rad, _ = self.polar(Vector((xi, eta, self.surf.half(xi, eta))))
            return rad - self.r_cove(a)
        for _ in range(60):
            mid = 0.5 * (lo + hi)
            if f(mid) > 0.0:
                lo = mid
            else:
                hi = mid
        return 0.5 * (lo + hi)


def build_main(surf, etas, hinges, n_le=12, n_mid=14, n_rear=6, n_cove=6,
               w_le=0.085, le_growth=1.45, cap_start=False, cap_end=False):
    """Fixed part of a lifting surface with a cut-out for every hinge.

    Returns (verts, faces, tags, stations).  tags[i] = (kind, eta_mid, column)
    with kind in U / L / TE / COVE / RIB / CAP, used by the caller for painting.
    """
    zones = [(h.eta0 - h.end_gap(h.eta0), h.eta1 + h.end_gap(h.eta1), h) for h in hinges]
    st = [e for e in etas
          if all(abs(e - z) > 0.012 for (ea, eb, _) in zones for z in (ea, eb))]
    for ea, eb, _ in zones:
        st += [ea, eb]
    st = sorted(st)
    eps = 1e-9

    def zone_at(e):
        for z in zones:
            if z[0] - eps <= e <= z[1] + eps:
                return z
        return None

    edge_frac = []
    for ea, eb, h in zones:
        for e in (ea, eb):
            xle, c, _, _ = surf.sec(e)
            edge_frac.append((e, (h.cut_xi(e) - xle) / c))

    def split_xi(e):
        z = zone_at(e)
        if z:
            return z[2].cut_xi(e)
        xle, c, _, _ = surf.sec(e)
        frac = min(edge_frac, key=lambda t: abs(t[0] - e))[1] if edge_frac else 0.8
        return xle + frac * c

    ns, n = n_le + n_mid, n_le + n_mid + n_rear
    gn = le_growth ** n_le - 1.0
    V, F, T = [], [], []
    U, L, C = [], [], []

    def addv(p):
        V.append(p)
        return len(V) - 1

    for e in st:
        xle, c, _, _ = surf.sec(e)
        xs = split_xi(e)
        w = min(w_le, 0.25 * c)
        xi = [xle + w * (le_growth ** i - 1.0) / gn for i in range(n_le + 1)]
        span = xs - (xle + w)
        xi += [xle + w + span * (i / n_mid) ** 1.5 for i in range(1, n_mid + 1)]
        xi += [xs + (xle + c - xs) * i / n_rear for i in range(1, n_rear + 1)]
        urow, lrow = [], []
        for i, x in enumerate(xi):
            z = surf.half(x, e)
            iu = addv(Vector((x, e, z)))
            il = iu if (i == 0 or z < 1e-7) else addv(Vector((x, e, -z)))
            urow.append(iu)
            lrow.append(il)
        U.append(urow)
        L.append(lrow)
        z = zone_at(e)
        if z:
            h = z[2]
            _, _, phi_c = h.polar(V[urow[ns]])
            row = [urow[ns]]
            for k in range(1, n_cove):
                row.append(addv(h.rev_point(e, phi_c * (1.0 - 2.0 * k / n_cove), h.r_cove)))
            row.append(lrow[ns])
            C.append(row)
        else:
            C.append(None)

    def face(idx, tag):
        out = []
        for i in idx:
            if i not in out:
                out.append(i)
        if len(out) >= 3:
            F.append(out)
            T.append(tag)

    for j in range(len(st) - 1):
        em = 0.5 * (st[j] + st[j + 1])
        z0, z1 = zone_at(st[j]), zone_at(st[j + 1])
        inside = z0 is not None and z0 is z1
        for i in range(ns if inside else n):
            face([U[j][i], U[j][i + 1], U[j + 1][i + 1], U[j + 1][i]], ("U", em, i))
            face([L[j][i], L[j + 1][i], L[j + 1][i + 1], L[j][i + 1]], ("L", em, i))
        if inside:
            for k in range(n_cove):
                face([C[j][k], C[j][k + 1], C[j + 1][k + 1], C[j + 1][k]], ("COVE", em, k))
        else:
            face([U[j][n], L[j][n], L[j + 1][n], U[j + 1][n]], ("TE", em, n))
    for j, e in enumerate(st):
        z = zone_at(e)
        if z and (abs(e - z[0]) < eps or abs(e - z[1]) < eps):
            face([U[j][i] for i in range(ns, n + 1)] + [L[j][i] for i in range(n, ns - 1, -1)]
                 + [C[j][k] for k in range(n_cove - 1, 0, -1)], ("RIB", e, ns))
    for flag, j in ((cap_start, 0), (cap_end, len(st) - 1)):
        if flag:
            face([U[j][i] for i in range(n + 1)] + [L[j][i] for i in range(n, 0, -1)],
                 ("CAP", st[j], 0))
    return V, F, T, st


def build_control(surf, hinge, etas, n_arc=8, n_chord=6):
    """Control surface: half-round nose centred on the hinge + aft aerofoil section.

    Returns (verts, faces, tags); tags[i] = (kind, cell) with kind in
    NOSE / LOW / UP / TE / CAP and cell counted aft from the hinge line.
    """
    h = hinge
    st = sorted([h.eta0, h.eta1] + [e for e in etas if h.eta0 + 0.012 < e < h.eta1 - 0.012])
    V, F, T = [], [], []
    m = n_arc + 1 + 2 * n_chord
    for e in st:
        ring = [h.rev_point(e, math.pi / 2 - math.pi * k / n_arc, h.r) for k in range(n_arc + 1)]
        xh = h.xi_at(e)
        xle, c, _, _ = surf.sec(e)
        up, low = [], []
        for i in range(1, n_chord + 1):
            x = xh + (xle + c - xh) * i / n_chord
            z = surf.half(x, e)
            up.append(Vector((x, e, z)))
            low.append(Vector((x, e, -z)))
        V += ring + low + up[::-1]
    for j in range(len(st) - 1):
        for k in range(m):
            k2 = (k + 1) % m
            F.append([j * m + k, j * m + k2, (j + 1) * m + k2, (j + 1) * m + k])
            if k < n_arc:
                T.append(("NOSE", k))
            elif k < n_arc + n_chord:
                T.append(("LOW", k - n_arc))
            elif k == n_arc + n_chord:
                T.append(("TE", n_chord))
            else:
                T.append(("UP", n_arc + 2 * n_chord - k))
    F.append(list(range(m)))
    F.append([(len(st) - 1) * m + k for k in range(m)])
    T += [("CAP", 0), ("CAP", 0)]
    return V, F, T


def make_control(name, hinge_name, data, mats, hinge, to_world, want_dir, coll, root, limit_deg):
    """Hinge empty (fixed frame, X along the hinge) + control mesh as its child.

    `data` is a MeshData in generic surface coordinates.  Returns the control
    object, the hinge empty and the generic -> control-local mapping.
    """
    p0, p1 = to_world(hinge.H0), to_world(hinge.H1)
    xl = (p1 - p0).normalized()
    if xl.dot(Vector(want_dir)) < 0.0:
        xl = -xl
    zl = (to_world(hinge.H0 + hinge.n) - p0).normalized()
    yl = zl.cross(xl).normalized()
    zl = xl.cross(yl).normalized()
    rot = Matrix((xl, yl, zl)).transposed()           # columns = local axes
    origin = 0.5 * (p0 + p1)
    rot_t = rot.transposed()

    def to_local(p):
        return rot_t @ (to_world(Vector(p)) - origin)

    emp = bpy.data.objects.new(hinge_name, None)
    emp.empty_display_type = "ARROWS"
    emp.empty_display_size = 0.05
    coll.objects.link(emp)
    emp.parent = root
    emp.location = origin
    emp.rotation_euler = rot.to_euler("XYZ")
    lock_all(emp)

    local = data.transformed(to_local)
    zero = to_world(Vector((0, 0, 0)))
    ex, ey, ez = (to_world(Vector(e)) - zero for e in ((1, 0, 0), (0, 1, 0), (0, 0, 1)))
    if ex.dot(ey.cross(ez)) < 0.0:                    # mirrored mapping: fix pre-wound faces
        local.f = [f[::-1] if k else f for f, k in zip(local.f, local.keep)]
    ob = mesh_object(name, local, mats, coll, emp)
    ob.rotation_mode = "XYZ"
    ob.lock_location = (True, True, True)
    ob.lock_scale = (True, True, True)
    ob.lock_rotation = (False, True, True)
    con = ob.constraints.new("LIMIT_ROTATION")
    con.name = "Hinge travel"
    con.owner_space = "LOCAL"
    con.use_limit_x = con.use_limit_y = con.use_limit_z = True
    con.min_x, con.max_x = -math.radians(limit_deg), math.radians(limit_deg)
    con.min_y = con.max_y = con.min_z = con.max_z = 0.0
    con.use_transform_limit = True
    ob["travel_limit_deg"] = float(limit_deg)
    return ob, emp, to_local


# ----------------------------------------------------------------------------
#  Fuselage: skin panels and inner solids lofted through super-elliptic sections
# ----------------------------------------------------------------------------
def section_point(s, th, inset=0.0):
    """Point (x, z) of a super-elliptic section at angle th (0 = left flank, pi/2 = top)."""
    c, sn = math.cos(th), math.sin(th)
    ex, b = (s.get("nt", 2.0), s["bt"]) if sn >= 0.0 else (s.get("nb", 2.0), s["bb"])
    return (math.copysign(abs(c) ** (2.0 / ex), c) * (s["a"] - inset),
            s.get("zc", 0.0) + math.copysign(abs(sn) ** (2.0 / ex), sn) * (b - inset))


class Loft:
    """Fuselage skin lofted through super-elliptic sections.

    sec(x) -> dict(a, bt, bb, nt, nb, zc) at aircraft station x; xs = stations of the grid.
    Skin panels are cut out of the grid as shells of finite thickness, and solids that
    follow the inner contour (tanks, frames, floors) are built from the same sections.
    """

    def __init__(self, sec, xs, n=N_RING, tip=0.02):
        self.sec, self.xs, self.n, self.tip = sec, list(xs), n, tip

    def is_pole(self, x, inset):
        return self.sec(x)["a"] - inset <= 1e-6 or (inset > 0.0 and x < self.tip)

    def point(self, x, th, inset=0.0):
        s = self.sec(x)
        if self.is_pole(x, inset):
            return Vector((0.0, max(x, self.tip) if inset > 0.0 else x, s.get("zc", 0.0)))
        px, pz = section_point(s, th, inset)
        return Vector((px, x, pz))

    def top(self, x, inset=0.0):
        s = self.sec(x)
        return s.get("zc", 0.0) + s["bt"] - inset

    def bottom(self, x, inset=0.0):
        s = self.sec(x)
        return s.get("zc", 0.0) - s["bb"] + inset

    def halfwidth(self, x, z, inset=0.0):
        """Half width of the section at height z."""
        s = self.sec(x)
        dz = z - s.get("zc", 0.0)
        b, ex = (s["bt"], s.get("nt", 2.0)) if dz >= 0.0 else (s["bb"], s.get("nb", 2.0))
        a, b = s["a"] - inset, b - inset
        t = abs(dz) / b if b > 1e-9 else 2.0
        return a * (1.0 - t ** ex) ** (1.0 / ex) if (a > 0.0 and t < 1.0) else 0.0

    def cells(self, x0, x1, k0=0, k1=None):
        """Grid cells between stations x0..x1 and ring points k0..k1 (k1 exclusive)."""
        k1 = self.n if k1 is None else k1
        return {(j, k % self.n) for j in range(len(self.xs) - 1)
                if self.xs[j] >= x0 - 1e-7 and self.xs[j + 1] <= x1 + 1e-7 for k in range(k0, k1)}

    def shell(self, cells, mat, thick=SHELL, inner=1, off=0.0, gap=SEAM):
        """Skin panel made of the given grid cells (j, k): cell (j, k) lies between
        stations j, j+1 and ring points k, k+1.

        mat(j, k) -> material index of the outer face; inside faces and edges get `inner`.
        Where another panel adjoins, the outline is pulled back by gap / 2.
        """
        n, xs = self.n, self.xs
        last = len(xs) - 1
        md = MeshData()
        index = {}

        def state(j, k):                     # 1 = this panel, 0 = neighbour, None = off the grid
            if not 0 <= j < last:
                return None
            return 1 if (j, k % n) in cells else 0

        def vert(j, k, layer):
            k %= n
            if (j, k, layer) in index:
                return index[(j, k, layer)]
            A, B, C, D = state(j - 1, k - 1), state(j - 1, k), state(j, k - 1), state(j, k)
            sx = ((D == 1 and B == 0) or (C == 1 and A == 0)) - ((B == 1 and D == 0) or (A == 1 and C == 0))
            st = ((D == 1 and C == 0) or (B == 1 and A == 0)) - ((C == 1 and D == 0) or (A == 1 and B == 0))
            x, th, inset = xs[j] + 0.5 * gap * sx, 2.0 * math.pi * k / n, off + layer * thick
            if st and not self.is_pole(x, inset):
                px, pz = section_point(self.sec(x), th, inset)
                th += 0.5 * gap * st / max(math.hypot(px, pz - self.sec(x).get("zc", 0.0)), 1e-4)
            p = self.point(x, th, inset)
            key = ("pole", layer, round(p.y, 7)) if self.is_pole(x, inset) else (j, k, layer)
            if key not in index:
                index[key] = len(md.v)
                md.v.append(p)
            index[(j, k, layer)] = index[key]
            return index[key]

        def face(idx, m):
            out = []
            for i in idx:
                if i not in out:
                    out.append(i)
            if len(out) >= 3:
                md.face(out, m)

        for j, k in sorted(cells):
            o = [vert(j, k, 0), vert(j, k + 1, 0), vert(j + 1, k + 1, 0), vert(j + 1, k, 0)]
            i = [vert(j, k, 1), vert(j, k + 1, 1), vert(j + 1, k + 1, 1), vert(j + 1, k, 1)]
            inn = inner(j, k) if callable(inner) else inner
            face(o, mat(j, k))
            face(i[::-1], inn)
            for (dj, dk), (p, q) in (((-1, 0), (0, 1)), ((1, 0), (2, 3)), ((0, -1), (3, 0)), ((0, 1), (1, 2))):
                if state(j + dj, k + dk) != 1:
                    face([o[p], o[q], i[q], i[p]], inn)
        return md

    def block(self, x0, x1, z0, z1, inset, half_w=None, m=10, mat=0, bevel=0.0):
        """Solid between the planes x0, x1 and z0, z1, bounded sideways by the skin
        contour moved in by `inset` (or by +/-half_w where that is narrower).
        bevel > 0 chamfers the two end faces."""
        xs = [x0] + [x for x in self.xs if x0 + bevel + 1e-6 < x < x1 - bevel - 1e-6] + [x1]
        if bevel > 0.0:
            xs = [x0, x0 + bevel] + xs[1:-1] + [x1 - bevel, x1]
        md = MeshData()
        rows = []
        for i_x, x in enumerate(xs):
            d = bevel if (bevel > 0.0 and i_x in (0, len(xs) - 1)) else 0.0
            ins = inset + d
            top, bot = self.top(x, ins), self.bottom(x, ins)
            za, zb = max(z0 + d, bot), min(z1 - d, top)
            on_a, on_b = za <= bot + 1e-9, zb >= top - 1e-9       # end lies on the contour
            right = []
            for i in range(m + 1):
                t = i / m
                if on_a and on_b:
                    t = 0.5 * (1.0 - math.cos(math.pi * t))
                elif on_b:
                    t = math.sin(0.5 * math.pi * t)
                elif on_a:
                    t = 1.0 - math.cos(0.5 * math.pi * t)
                z = za + (zb - za) * t
                w = self.halfwidth(x, z, ins)
                right.append((min(w, half_w - d) if half_w is not None else w, z))
            rows.append(len(md.v))
            md.v += [Vector((w, x, z)) for w, z in right] + [Vector((-w, x, z)) for w, z in reversed(right)]
        cnt = 2 * (m + 1)
        for a, b in zip(rows[:-1], rows[1:]):
            for i in range(cnt):
                i2 = (i + 1) % cnt
                md.face([a + i, a + i2, b + i2, b + i], mat)
        md.face([rows[0] + i for i in range(cnt)], mat)
        md.face([rows[-1] + i for i in range(cnt)], mat)
        return md


def offset_polygon(pts, d):
    """Move the outline of a closed 2D polygon outwards by d (mitred corners)."""
    n = len(pts)
    area = sum(pts[i][0] * pts[(i + 1) % n][1] - pts[(i + 1) % n][0] * pts[i][1] for i in range(n))
    sgn = 1.0 if area > 0.0 else -1.0
    out = []
    for i in range(n):
        p0, p1, p2 = pts[i - 1], pts[i], pts[(i + 1) % n]
        n1 = Vector((p1[1] - p0[1], p0[0] - p1[0])).normalized() * sgn
        n2 = Vector((p2[1] - p1[1], p1[0] - p2[0])).normalized() * sgn
        mid = n1 + n2
        mid = mid.normalized() if mid.length > 1e-9 else n1
        k = d / max(mid.dot(n1), 0.35)
        out.append((p1[0] + mid.x * k, p1[1] + mid.y * k))
    return out


# ----------------------------------------------------------------------------
#  Wing
# ----------------------------------------------------------------------------
def wing_geometry(cfg):
    tl = math.tan(math.radians(SWEEP_LE))
    xte = cfg["wing_xte"]
    c_root = C_TIP + SEMI * tl                       # chord on the centreline
    xle0 = xte - c_root
    lam = C_TIP / c_root
    mac = (2.0 / 3.0) * c_root * (1 + lam + lam * lam) / (1 + lam)
    y_mac = (SEMI / 3.0) * (1 + 2 * lam) / (1 + lam)
    x_ref = xle0 + y_mac * tl + 0.25 * mac           # 25 % MAC -> model origin

    def sec(eta):
        y = abs(eta)
        xle, x_te = xle0 + y * tl, xte
        tau = TAU_ROOT + (TAU_TIP - TAU_ROOT) * min(y / SEMI, 1.0)
        ts = 1.0
        y0 = SEMI - R_TIP
        if y > y0:
            q = min((y - y0) / R_TIP, 1.0)
            cb = math.sqrt(max(0.0, 1.0 - q * q))
            ts = cb
            xle += 1.2 * R_TIP * (1.0 - cb)
            x_te -= 0.5 * R_TIP * (1.0 - cb)
        return xle, x_te - xle, tau, ts

    return dict(sec=sec, x_ref=x_ref, xle0=xle0, c_root=c_root, mac=mac, y_mac=y_mac)


def spar_stations(geo):
    """Aircraft stations of the wing joiner tubes."""
    xle, c, _, _ = geo["sec"](Y_ROOT)
    return [(xle + frac * c, r) for frac, r in SPARS]


def add_wing(cfg, coll, root, mats, paint, extra_stations=()):
    """Left and right wing panel.  Each has a trailing-edge cut-out for its two elevon
    panels, a closed root rib at Y_ROOT (inside the fuselage) and bores for the joiner tubes."""
    geo = wing_geometry(cfg)
    surf = Surface(geo["sec"])
    x_ref, zw = geo["x_ref"], cfg["wing_z"]
    el = cfg["elevon"]
    master = {1: Hinge(surf, el["y_in"], el["y_out"], el["c_in"], el["c_out"], LIMIT_ELEVON),
              -1: Hinge(surf, -el["y_out"], -el["y_in"], el["c_out"], el["c_in"], LIMIT_ELEVON)}

    half = frange(0.0, SEMI - R_TIP, 0.075)
    half += [SEMI - R_TIP + R_TIP * math.sin(math.radians(b)) for b in (22, 42, 58, 70, 80, 86, 90)]
    half += list(extra_stations)
    half = sorted(set(round(y, 6) for y in half))
    etas = sorted(set([-y for y in half] + half))

    def to_world(p):
        return Vector((p.y, p.x - x_ref, zw + p.z))

    rib = len(mats)                                   # slot of the bare laminate (root rib, bores, bays)
    mats = list(mats) + [material("composite")]
    objs = {}
    for side, tag in ((1, "L"), (-1, "R")):
        st = sorted(side * y for y in [Y_ROOT] + [y for y in half if y > Y_ROOT + 0.012])
        V, F, T, _ = build_main(surf, st, [master[side]], cap_start=(side == 1), cap_end=(side == -1))
        data = MeshData().add([to_world(p) for p in V], F,
                              [rib if t[0] == "CAP" else paint(t) for t in T])
        ob = mesh_object(cfg["prefix"] + "Wing." + tag, data, mats, coll, root)
        bores = MeshData()
        for x, r in spar_stations(geo):
            v, f = lathe([(Y_ROOT - 0.01, 0.0), (Y_ROOT - 0.01, r + 0.0007),
                          (SPAR_REACH + 0.004, r + 0.0007), (SPAR_REACH + 0.004, 0.0)],
                         (0.0, x - x_ref, zw), (side, 0.0, 0.0), 24)
            bores.add(v, f, 0)
        subtract(ob, bores, rib)
        objs[side] = ob
    return dict(objs=objs, surf=surf, geo=geo, to_world=to_world, master=master, etas=etas,
                rib=rib, x_ref=x_ref, z=zw)


def wing_socket(wing, d=SOCKET_GAP, reach=0.34):
    """Both wing roots made larger by d all round: the cutter for the sockets in the fuselage."""
    surf, to_world = wing["surf"], wing["to_world"]
    us = [(i / 40.0) ** 2 for i in range(41)]
    cnt = 2 * len(us) - 1
    md = MeshData()
    for side in (1, -1):
        rows = []
        for y in [Y_ROOT - 0.012] + frange(Y_ROOT, reach, 0.09)[1:]:
            eta = side * y
            xle, c, _, _ = surf.sec(eta)
            up = [(xle + u * c, surf.half(xle + u * c, eta)) for u in us]
            ring = offset_polygon(up + [(x, -z) for x, z in reversed(up[1:])], d)
            rows.append(len(md.v))
            md.v += [to_world(Vector((x, eta, z))) for x, z in ring]
        for a, b in zip(rows[:-1], rows[1:]):
            for i in range(cnt):
                i2 = (i + 1) % cnt
                md.face([a + i, a + i2, b + i2, b + i])
        md.face([rows[0] + i for i in range(cnt)])
        md.face([rows[-1] + i for i in range(cnt)])
    return md


# ----------------------------------------------------------------------------
#  Elevon panels, control horns, push-rods and the shared linkage fairing
# ----------------------------------------------------------------------------
def horn(surf, hinge, eta_h, upper, thick=0.0025):
    """Control horn standing on the panel skin, pin directly over the hinge line."""
    sg = 1.0 if upper else -1.0
    xh = hinge.xi_at(eta_h)

    def skin(x):
        return surf.half(x, eta_h)
    zp = skin(xh) + HORN_PIN
    prof = [(xh + 0.006, skin(xh + 0.006) - 0.002), (xh + 0.040, skin(xh + 0.040) - 0.002),
            (xh + 0.007, zp + 0.0045), (xh - 0.0045, zp + 0.0045), (xh - 0.0045, zp - 0.0045)]
    n = len(prof)
    verts = [Vector((x, eta_h + d, sg * z)) for d in (-0.5 * thick, 0.5 * thick) for x, z in prof]
    faces = [list(range(n)), list(range(n, 2 * n))]
    faces += [[i, (i + 1) % n, n + (i + 1) % n, n + i] for i in range(n)]
    return verts, faces, Vector((xh, eta_h, sg * zp))


def pushrod_mesh(length):
    """Rigid rod along local +Y: clevis on the horn pin (origin) and on the arm pin (+length)."""
    md = MeshData()
    for y0, y1 in ((-0.004, 0.012), (length - 0.012, length + 0.004)):
        v, f = box((0.0, 0.5 * (y0 + y1), 0.0), (0.0056, y1 - y0, 0.006))
        md.add(v, f, 0)
    for y0, y1 in ((0.012, 0.027), (length - 0.027, length - 0.012)):
        v, f = lathe([(y0, 0.0), (y0, 0.0026), (y1, 0.0026), (y1, 0.0)], (0, 0, 0), (0, 1, 0), 8)
        md.add(v, f, 0)
    v, f = lathe([(0.027, 0.0), (0.027, 0.0018), (length - 0.027, 0.0018), (length - 0.027, 0.0)],
                 (0, 0, 0), (0, 1, 0), 10)
    md.add(v, f, 0)
    return md


def servo_arm_mesh(radius, sg):
    """Servo output arm in hinge-frame axes: shaft along X at the origin, tip pin at Z = sg * radius."""
    md = MeshData()
    v, f = lathe([(-0.0022, 0.0), (-0.0022, ARM_HUB_R), (0.0022, ARM_HUB_R), (0.0022, 0.0)],
                 (0, 0, 0), (1, 0, 0), 20)
    md.add(v, f, 0)
    prof = [(-0.0045, 0.0), (0.0045, 0.0), (0.0032, radius), (0.0, radius + 0.0035), (-0.0032, radius)]
    n, t = len(prof), 0.00125
    verts = [Vector((dx, y, sg * z)) for dx in (-t, t) for y, z in prof]
    faces = [list(range(n)), list(range(n, 2 * n))]
    faces += [[i, (i + 1) % n, n + (i + 1) % n, n + i] for i in range(n)]
    md.add(verts, faces, 0)
    v, f = lathe([(-0.0042, 0.0), (-0.0042, 0.0016), (0.0042, 0.0016), (0.0042, 0.0)],
                 (0, 0, sg * radius), (1, 0, 0), 10)
    md.add(v, f, 1)
    return md


def linkage_points(surf, hinge, eta_h, upper):
    """Pins of one panel linkage in generic coordinates.

    The horn pin stands over the hinge line; the servo shaft lies on the chord
    plane SERVO_AHEAD in front of it; arm radius = horn radius.
    """
    sg = 1.0 if upper else -1.0
    base = hinge.H((eta_h - hinge.H0.y) / hinge.a.y)
    radius = surf.half(base.x, base.y) + HORN_PIN
    up = hinge.n * sg
    shaft = base - hinge.b * SERVO_AHEAD
    return dict(eta=eta_h, radius=radius, pin=base + up * radius, shaft=shaft,
                tip=shaft + up * radius, a=hinge.a, b=hinge.b, up=up)


def pocket_box(lp):
    """Slot that lets the servo arm pass from inside the wing through the skin."""
    c = lp["shaft"]
    verts = [c + lp["a"] * (sx * POCKET["half_x"]) + lp["b"] * (sy * POCKET["half_y"]) + lp["up"] * w
             for sx in (-1, 1) for sy in (-1, 1) for w in (-POCKET["depth"], POCKET["top"])]
    return verts, box((0, 0, 0), (1, 1, 1))[1]


def refine_patch(me, centre, axes, half, radius=0.11):
    """Cut a small rectangle of edges into the skin around `centre` (model coordinates).

    The slot boolean then only touches faces inside that rectangle, i.e. under
    the fairing, and the visible skin keeps its regular quads and shading.
    """
    bm = bmesh.new()
    bm.from_mesh(me)
    for axis, h in zip(axes, half):
        for sign in (-1.0, 1.0):
            faces = [f for f in bm.faces if (f.calc_center_median() - centre).length < radius]
            geom = set(faces)
            for f in faces:
                geom.update(f.edges)
                geom.update(f.verts)
            bmesh.ops.bisect_plane(bm, geom=list(geom), dist=1e-6,
                                   plane_co=centre + axis * (sign * h), plane_no=axis)
    bm.to_mesh(me)
    bm.free()
    me.update()


def shade(me, sharp_deg=40.0):
    """Smooth shading with sharp edges marked by angle."""
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.normal_update()
    lim = math.radians(sharp_deg)
    for f in bm.faces:
        f.smooth = True
    for e in bm.edges:
        e.smooth = not (len(e.link_faces) == 2 and e.calc_face_angle(0.0) > lim)
    bm.to_mesh(me)
    bm.free()
    me.update()


def subtract(ob, cutter, slot=None, sharp_deg=40.0):
    """Exact boolean difference ob - cutter, applied to ob's mesh.

    cutter: an object, or a MeshData given in the coordinates of ob's mesh.
    slot:   material slot of ob for the faces made by the cut.
    """
    tmp = None
    if isinstance(cutter, MeshData):
        tmp = cutter = mesh_object("tmp_cutter", cutter, [], ob.users_collection[0], ob.parent)
        tmp.matrix_parent_inverse = ob.matrix_parent_inverse.copy()
        tmp.matrix_basis = ob.matrix_basis.copy()
    if slot is not None:                      # cut faces take the cutter's material index
        cutter.data.materials.clear()
        for mt in ob.data.materials:
            cutter.data.materials.append(mt)
        cutter.data.polygons.foreach_set("material_index", [slot] * len(cutter.data.polygons))
    mod = ob.modifiers.new("cut", "BOOLEAN")
    mod.operation = "DIFFERENCE"
    mod.object = cutter
    mod.solver = "EXACT"
    if slot is not None:
        mod.material_mode = "INDEX"
    bpy.context.view_layer.update()
    dg = bpy.context.evaluated_depsgraph_get()
    new = bpy.data.meshes.new_from_object(ob.evaluated_get(dg))
    old = ob.data
    ob.modifiers.remove(mod)
    name = old.name
    ob.data = new
    bpy.data.meshes.remove(old)
    new.name = name
    shade(new, sharp_deg)
    if tmp is not None:
        me = tmp.data
        bpy.data.objects.remove(tmp, do_unlink=True)
        bpy.data.meshes.remove(me)


def take_mesh(ob):
    """Read an object's mesh back into a MeshData and delete the object."""
    md = MeshData()
    me = ob.data
    md.v = [v.co.copy() for v in me.vertices]
    for p in me.polygons:
        md.face(list(p.vertices), p.material_index)
    bpy.data.objects.remove(ob, do_unlink=True)
    bpy.data.meshes.remove(me)
    return md


def servo_mesh(direction):
    """Elevon servo in hinge-frame axes (X along the hinge, Y forward, Z up), output shaft
    at the origin.  direction = +1 / -1: side of the arm on which the body lies."""
    md = MeshData()
    la, lc, lt = SERVO["along"], SERVO["chord"], SERVO["thick"]
    xc = direction * (0.0035 + 0.5 * la)
    yc = SERVO["shaft"] - 0.5 * lc
    v, f = box((xc, yc, 0.0), (la, lc, lt))
    md.add(v, f, 0)
    for y in (yc + 0.5 * lc + 0.003, yc - 0.5 * lc - 0.003):          # mounting lugs
        v, f = box((xc, y, 0.0), (0.014, 0.006, 0.0025))
        md.add(v, f, 0)
    v, f = box((xc, yc, 0.0), (0.66 * la, 0.56 * lc, lt + 0.0006))    # label
    md.add(v, f, 1)
    return md


def servo_bay(l_in, l_out, surf):
    """Box cut out of the wing under the access cover: room for the two servo bodies."""
    mid = 0.5 * (l_in["shaft"] + l_out["shaft"])
    a, b, up = l_in["a"], l_in["b"], l_in["up"]
    half_a = 0.5 * (l_out["shaft"] - l_in["shaft"]).length + 0.0035 + SERVO["along"] + 0.0015
    b0, b1 = -(SERVO["shaft"] + 0.0095), SERVO["chord"] - SERVO["shaft"] + 0.0075
    w0, w1 = -(0.5 * SERVO["thick"] + 0.0015), surf.half(mid.x, mid.y) + 0.012
    verts = [mid + a * (sa * half_a) + b * sb + up * w
             for sa in (-1, 1) for sb in (b0, b1) for w in (w0, w1)]
    return verts, box((0, 0, 0), (1, 1, 1))[1], dict(centre=mid + b * (0.5 * (b0 + b1)),
                                                     half=(half_a, 0.5 * (b1 - b0)))


def hood(surf, eta_c, xi0, xi1, w_fn, h_fn, n_fn, upper, wall=0.0015, seat=0.0004,
         n_len=28, n_arc=14):
    """Fairing shell standing on the skin from xi0 to xi1, open underneath and at its aft end.

    eta_c(xi) is the span position of its centre line; w_fn / h_fn / n_fn give width,
    height and super-ellipse exponent of the cross-section along the length (0..1).
    Returns (verts, faces, material_index): 0 = outside and edges, 1 = inside.
    """
    sg = 1.0 if upper else -1.0

    def arch(xi, w, h, n):
        pts = []
        for k in range(n_arc + 1):
            th = math.pi * k / n_arc
            c = math.copysign(abs(math.cos(th)) ** (2.0 / n), math.cos(th))
            e = eta_c(xi) + 0.5 * w * c
            pts.append(Vector((xi, e, sg * (surf.half(xi, e) - seat + h * abs(math.sin(th)) ** (2.0 / n)))))
        return pts

    ts = [j / n_len for j in range(n_len + 1)]
    xis = [xi0 + (xi1 - xi0) * t for t in ts]
    V, F, M = [], [], []
    outer, inner = [], {}
    for t, xi in zip(ts, xis):
        outer.append(len(V))
        V += arch(xi, w_fn(t), h_fn(t), n_fn(t))
    j0 = n_len + 1
    while j0 > 0 and w_fn(ts[j0 - 1]) - 2.0 * wall > 0.006 and h_fn(ts[j0 - 1]) - wall > 0.004:
        j0 -= 1
    for j in range(j0, n_len + 1):
        inner[j] = len(V)
        V += arch(xis[j], w_fn(ts[j]) - 2.0 * wall, h_fn(ts[j]) - wall, n_fn(ts[j]))

    def quad(a, b, c, d, mat):
        F.append([a, b, c, d])
        M.append(mat)

    for j in range(n_len):
        for k in range(n_arc):
            quad(outer[j] + k, outer[j] + k + 1, outer[j + 1] + k + 1, outer[j + 1] + k, 0)
    hollow = 1 <= j0 < n_len
    for j in range((j0 - 1) if hollow else n_len):                  # underside of the solid nose
        quad(outer[j], outer[j + 1], outer[j + 1] + n_arc, outer[j] + n_arc, 0)
    if not hollow:
        F.append([outer[n_len] + k for k in range(n_arc + 1)])
        M.append(0)
        return V, F, M
    a, b = outer[j0 - 1], outer[j0]
    F.append([a, b, inner[j0], inner[j0] + n_arc, b + n_arc, a + n_arc])
    M.append(0)
    F.append([inner[j0] + k for k in range(n_arc + 1)])             # front wall of the cavity
    M.append(1)
    for j in range(j0, n_len):
        for k in range(n_arc):
            quad(inner[j] + k, inner[j + 1] + k, inner[j + 1] + k + 1, inner[j] + k + 1, 1)
        quad(outer[j], outer[j + 1], inner[j + 1], inner[j], 0)     # the two feet
        quad(outer[j] + n_arc, inner[j] + n_arc, inner[j + 1] + n_arc, outer[j + 1] + n_arc, 0)
    for k in range(n_arc):                                          # aft edge
        quad(outer[n_len] + k, outer[n_len] + k + 1, inner[n_len] + k + 1, inner[n_len] + k, 0)
    return V, F, M


def cover_plate(surf, eta_c, xi_c, spec, upper, n_ang=96):
    """Thin access panel following the skin (super-elliptic outline, optional taper forward)."""
    sg = 1.0 if upper else -1.0
    expo, thick = spec["expo"], spec["thick"]

    def rho(th):
        c, s = math.cos(th), math.sin(th)
        ax = spec["a_rear"] if c >= 0.0 else spec["a_front"]
        ay = spec["half_w"] * (1.0 - spec["taper"] * max(0.0, -c))
        return 1.0 / ((abs(c) / ax) ** expo + (abs(s) / ay) ** expo) ** (1.0 / expo)

    def point(th, frac, off):
        xi = xi_c + frac * rho(th) * math.cos(th)
        e = eta_c + frac * rho(th) * math.sin(th)
        return Vector((xi, e, sg * (surf.half(xi, e) + off)))

    levels = [(0.25, thick), (0.5, thick), (0.75, thick), (0.93, thick), (0.985, thick),
              (1.0, 0.45 * thick), (1.0, -0.0006)]
    V = [point(0.0, 0.0, thick)]
    for frac, off in levels:
        V += [point(2.0 * math.pi * k / n_ang, frac, off) for k in range(n_ang)]
    V.append(point(0.0, 0.0, -0.0006))
    F = []
    for k in range(n_ang):
        k2 = (k + 1) % n_ang
        F.append([0, 1 + k, 1 + k2])
        for j in range(len(levels) - 1):
            a, b = 1 + j * n_ang, 1 + (j + 1) * n_ang
            F.append([a + k, b + k, b + k2, a + k2])
        last = 1 + (len(levels) - 1) * n_ang
        F.append([last + k, len(V) - 1, last + k2])

    def on_plate(th, frac):
        """Point on the plate top surface (for screws)."""
        return point(th, frac, thick)
    return V, F, on_plate


def add_elevons(cfg, wing, coll, skin_mat, panel_mats, panel_paint, stencil=None):
    """Per wing: two elevon panels, each driven by servo - arm - push-rod - horn, the servo
    bay under an access cover, and one fairing over the two side-by-side linkages.

    Returns {"L": parts, "R": parts} with parts = dict(fairing, servos, panels, hinges)."""
    surf, to_world, el, link = wing["surf"], wing["to_world"], cfg["elevon"], cfg["linkage"]
    pre, upper = cfg["prefix"], link["upper"]
    sg = 1.0 if upper else -1.0
    steel, brass = material("steel_bright"), material("brass")
    dark, nylon = material("dark_interior"), material("nylon_black")
    servo_mats = [material("servo_black"), material("label_white")]
    hd, pl, fl = link["hood"], link["plate"], link.get("flange")
    w_fn = lambda t, f=pchip(*hd["w"]): hd["width"] * f(t)
    h_fn = lambda t, f=pchip(*hd["h"]): hd["height"] * f(t)
    n_fn = pchip(*hd["n"])
    ys, g = el["y_split"], PANEL_GAP
    zero = to_world(Vector((0.0, 0.0, 0.0)))
    out = {}
    for side, tag in ((1, "L"), (-1, "R")):
        wing_ob, master = wing["objs"][side], wing["master"][side]
        eta_c = side * ys
        xh = master.xi_at(eta_c)
        links = {name: linkage_points(surf, master, side * (ys + sign * (0.5 * g + HORN_OFFSET)), upper)
                 for name, sign in (("In", -1.0), ("Out", 1.0))}

        # ---- servo bay in the wing, under the access cover -----------------
        bv, bf, bay = servo_bay(links["In"], links["Out"], surf)
        ax = (to_world(master.a) - zero, to_world(master.b) - zero)
        refine_patch(wing_ob.data, to_world(bay["centre"]), ax,
                     (bay["half"][0] + 0.006, bay["half"][1] + 0.006))
        subtract(wing_ob, MeshData().add([to_world(q) for q in bv], bf, 0), wing["rib"])

        # ---- fixed part: access cover with arm slots, fairing shell, screws -
        slots = MeshData()
        for lp in links.values():
            v, f = pocket_box(lp)
            slots.add([to_world(q) for q in v], f, 0)
        pv, pf, on_plate = cover_plate(surf, eta_c, xh - pl["centre"], pl, upper)
        tmp = mesh_object("tmp_plate", MeshData().add([to_world(q) for q in pv], pf, 0),
                          [skin_mat, dark], coll, wing_ob)
        subtract(tmp, slots, 1)
        fair = take_mesh(tmp)
        if fl:
            fv, ff, _ = cover_plate(surf, eta_c, xh - fl["centre"], fl, upper)
            fair.add([to_world(q) for q in fv], ff, 0)
        skew = master.a.x / master.a.y            # the fairing runs along the push-rods
        hv, hf, hm = hood(surf, lambda xi: eta_c - (xi - xh) * skew,
                          xh - hd["setback"] - hd["length"], xh - hd["setback"],
                          w_fn, h_fn, n_fn, upper)
        fair.add([to_world(q) for q in hv], hf, hm)
        for ang in pl["screws"]:
            q0 = on_plate(math.radians(180.0 - ang), 0.86)
            v, f = lathe([(-0.0004, 0.0), (-0.0004, 0.0042), (0.0010, 0.0042), (0.0017, 0.0028),
                          (0.0017, 0.0)], q0, (0.0, 0.0, sg), 12, ref=(1, 0, 0))
            fair.add([to_world(q) for q in v], f, 2)
        fairing = mesh_object(pre + "LinkageFairing." + tag, fair, [skin_mat, dark, steel], coll, wing_ob)
        parts = out[tag] = dict(fairing=fairing, servos=[], panels=[], hinges=[], rods=[])

        # ---- moving part: panels with horns, servos with arms, push-rods ----
        spans = {"In": (el["y_in"], ys - 0.5 * g), "Out": (ys + 0.5 * g, el["y_out"])}
        for name, (ya, yb) in spans.items():
            key = name + "." + tag
            lp = links[name]
            e0, e1 = sorted((side * ya, side * yb))
            hinge = master.part(e0, e1)
            cv, cf, ct = build_control(surf, hinge, wing["etas"])
            data = MeshData().add(cv, cf, [panel_paint(t) for t in ct])
            hv, hf, _ = horn(surf, master, lp["eta"], upper)
            data.add(hv, hf, len(panel_mats))
            mats = list(panel_mats) + [brass]
            if stencil:
                em = 0.5 * (e0 + e1)
                xle, c, _, _ = surf.sec(em)
                xm = hinge.xi_at(em) + 0.55 * (xle + c - hinge.xi_at(em))
                tv, tf = text_decal(stencil["text"], dict(surf=surf, to_world=lambda q: q.copy()),
                                    xm, em, stencil["height"], stencil["x_scale"], upper,
                                    stencil.get("font"), stencil.get("spacing", 1.0), offset=0.0005)
                data.add(tv, tf, len(mats), keep=True)
                mats.append(material("marking_black"))
            ob, emp, to_local = make_control(pre + "Elevon_" + key, pre + "Hinge_Elevon_" + key,
                                             data, mats, hinge, to_world, (-1, 0, 0), coll, wing_ob,
                                             LIMIT_ELEVON)

            # servo body, fixed in the wing; its frame is parallel to the hinge frame
            away = -1.0 if lp["eta"] > eta_c else 1.0          # hinge-frame X points to -eta
            servo = mesh_object(pre + "Servo_" + key, servo_mesh(away), servo_mats, coll, wing_ob)
            servo.location = to_world(lp["shaft"])
            servo.rotation_euler = emp.rotation_euler
            lock_all(servo, select=True)

            # servo arm: turns about the output shaft through the panel angle
            arm = mesh_object(pre + "ServoArm_" + key, servo_arm_mesh(lp["radius"], sg),
                              [nylon, steel], coll, servo)
            tip = Vector((0.0, 0.0, sg * lp["radius"]))
            pin = arm.vertex_groups.new(name="pin")
            pin.add([v.index for v in arm.data.vertices
                     if (Vector((0.0, v.co.y, v.co.z)) - tip).length < 0.0017], 1.0, "REPLACE")
            follow = arm.constraints.new("COPY_ROTATION")
            follow.name = "Follow panel"
            follow.target = ob
            follow.use_x, follow.use_y, follow.use_z = True, False, False
            follow.target_space = follow.owner_space = "LOCAL"
            lock_all(arm)

            # push-rod: pinned to the horn (child of the panel), tracking the pin on the arm tip
            a, b = to_local(lp["pin"]), to_local(lp["tip"])
            y_ax = b - a
            length = y_ax.length
            y_ax.normalize()
            x_ax = Vector((1.0, 0.0, 0.0))
            x_ax = (x_ax - y_ax * x_ax.dot(y_ax)).normalized()
            rot = Matrix((x_ax, y_ax, x_ax.cross(y_ax))).transposed()
            rod = mesh_object(pre + "Pushrod_" + key, pushrod_mesh(length), [steel], coll, ob)
            rod.location = a
            rod.rotation_euler = rot.to_euler("XYZ")
            track = rod.constraints.new("DAMPED_TRACK")
            track.name = "Follow servo arm"
            track.target = arm
            track.subtarget = "pin"
            track.track_axis = "TRACK_Y"
            lock_all(rod)
            ob["horn_radius_mm"] = round(lp["radius"] * 1000.0, 2)
            ob["pushrod_length_mm"] = round(length * 1000.0, 2)
            parts["panels"].append(ob)
            parts["hinges"].append(emp)
            parts["servos"].append(servo)
            parts["rods"].append(rod)
    return out


# ----------------------------------------------------------------------------
#  Fin + rudder
# ----------------------------------------------------------------------------
def add_fin(cfg, coll, parent, x_ref, mat):
    f = cfg["fin"]
    height = f["z_tip"] - f["z_base"]
    tan_te = math.tan(math.radians(f["sweep_te"]))
    tan_le = tan_te + (f["c_root"] - f["c_tip"]) / height

    def sec(z):
        d = z - f["z_base"]
        xte = f["xte_base"] + d * tan_te
        xle = f["xte_base"] - f["c_root"] + d * tan_le
        tau = f["tau_root"] + (f["tau_tip"] - f["tau_root"]) * min(max(d / height, 0.0), 1.0)
        dd = max(d, 0.0)
        ts = 1.0 + f["flare_t"] * math.exp(-dd / f["flare_h"])      # root fillet
        xle -= f["flare_x"] * math.exp(-dd / f["flare_hx"])         # dorsal fillet
        z0 = f["z_tip"] - f["r_tip"]
        if z > z0:
            q = min((z - z0) / f["r_tip"], 1.0)
            cb = math.sqrt(max(0.0, 1.0 - q * q))
            ts *= cb
            xle += f["k_le"] * f["r_tip"] * (1.0 - cb)
            xte -= f["k_te"] * f["r_tip"] * (1.0 - cb)
        return xle, xte - xle, tau, ts

    surf = Surface(sec, te_thick=0.0022)
    zb, zt, rt = f["z_base"], f["z_tip"], f["r_tip"]
    etas = [f["z_start"], zb - 0.02, zb, zb + 0.01, zb + 0.022, zb + 0.038, zb + 0.06]
    etas += frange(zb + 0.09, zt - rt, 0.045)
    etas += [zt - rt + rt * math.sin(math.radians(b)) for b in (22, 42, 58, 70, 80, 86, 90)]
    etas = sorted(set(round(z, 6) for z in etas))

    c0 = sec(f["rud_z0"])[1] * f["rud_frac"][0]
    c1 = sec(f["rud_z1"])[1] * f["rud_frac"][1]
    hinge = Hinge(surf, f["rud_z0"], f["rud_z1"], c0, c1, LIMIT_RUDDER)

    def to_world(p):
        return Vector((p.z, p.x - x_ref, p.y))

    V, F, T, _ = build_main(surf, etas, [hinge], n_le=12, n_mid=10, n_rear=5,
                            w_le=0.05, cap_start=True)
    data = MeshData().add([to_world(p) for p in V], F, 0)
    fin = mesh_object(cfg["prefix"] + "Fin", data, [mat], coll, parent)
    cv, cf, _ = build_control(surf, hinge, etas, n_chord=5)
    rud, _, _ = make_control(cfg["prefix"] + "Rudder", cfg["prefix"] + "Hinge_Rudder",
                             MeshData().add(cv, cf, 0), [mat], hinge, to_world, (0, 0, -1),
                             coll, fin, LIMIT_RUDDER)
    return dict(obj=fin, rudder=rud)


# ----------------------------------------------------------------------------
#  Lettering
# ----------------------------------------------------------------------------
def text_decal(text, wing, centre_x, centre_y, cap_height, x_scale, upper, font_path=None,
               spacing=1.0, offset=0.0008, max_edge=0.02):
    """Flat lettering laid on the wing skin.  centre_x: aircraft station, centre_y: span."""
    surf, to_world = wing["surf"], wing["to_world"]
    font = None
    if font_path:
        try:
            font = bpy.data.fonts.load(font_path)
        except Exception:                     # font not installed: Blender's built-in font
            font = None
    cu = bpy.data.curves.new("tmp_text", "FONT")
    cu.body = text
    if font:
        cu.font = font
    cu.size = 1.0
    cu.space_character = spacing
    cu.align_x = "CENTER"
    tmp = bpy.data.objects.new("tmp_text", cu)
    bpy.context.scene.collection.objects.link(tmp)
    dg = bpy.context.evaluated_depsgraph_get()
    dg.update()
    me = bpy.data.meshes.new_from_object(tmp.evaluated_get(dg))
    bm = bmesh.new()
    bm.from_mesh(me)
    bpy.data.meshes.remove(me)
    bpy.data.objects.remove(tmp)
    bpy.data.curves.remove(cu)
    if font:
        bpy.data.fonts.remove(font)

    ys = [v.co.y for v in bm.verts]
    xs = [v.co.x for v in bm.verts]
    k = cap_height / (max(ys) - min(ys))
    cx, cy = 0.5 * (max(xs) + min(xs)), 0.5 * (max(ys) + min(ys))
    for v in bm.verts:
        v.co = Vector(((v.co.x - cx) * k * x_scale, (v.co.y - cy) * k, 0.0))
    bmesh.ops.triangulate(bm, faces=bm.faces)
    # glyphs such as "T" tessellate with zero-height slivers: drop them before subdividing
    slivers = [f for f in bm.faces
               if 2.0 * f.calc_area() < 2e-5 * max(e.calc_length() for e in f.edges)]
    bmesh.ops.delete(bm, geom=slivers, context="FACES_ONLY")
    bmesh.ops.delete(bm, geom=[e for e in bm.edges if not e.link_faces], context="EDGES")
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS")
    for _ in range(10):
        long_edges = [e for e in bm.edges if e.calc_length() > max_edge]
        if not long_edges:
            break
        bmesh.ops.subdivide_edges(bm, edges=long_edges, cuts=1)
        bmesh.ops.triangulate(bm, faces=bm.faces)
    bm.verts.index_update()
    sgn = 1.0 if upper else -1.0
    verts = []
    for v in bm.verts:
        # upper side: reads towards the right wing; lower side: mirrored so it reads from below
        eta = centre_y - v.co.x if upper else centre_y + v.co.x
        xi = centre_x - v.co.y
        verts.append(to_world(Vector((xi, eta, sgn * (surf.half(xi, eta) + offset)))))
    outward = to_world(Vector((0.0, 0.0, sgn))) - to_world(Vector((0.0, 0.0, 0.0)))
    faces = []
    for f in bm.faces:
        idx = [v.index for v in f.verts]
        nrm = (verts[idx[1]] - verts[idx[0]]).cross(verts[idx[2]] - verts[idx[0]])
        faces.append(idx if nrm.dot(outward) > 0.0 else idx[::-1])
    bm.free()
    return verts, faces


# ----------------------------------------------------------------------------
#  Assembly: explode offsets and build order
# ----------------------------------------------------------------------------
class Assembly:
    """Parts of one airframe with their explode offset (root axes, metres) and build order.

    finish() stores both on every part as custom properties and drives delta_location
    from root["explode"] (0 = assembled, 1 = fully exploded).  Parts leave in reverse
    build order, each over its own stretch of the slider, so sliding 1 -> 0 plays the
    assembly sequence.
    """
    SPAN = 0.20                       # share of the slider one part needs for its move

    def __init__(self, root):
        self.root, self.items, self.tracks = root, [], []

    def add(self, ob, offset=(0.0, 0.0, 0.0), order=0, label=None):
        self.items.append((ob, Vector(offset), int(order), label))
        return ob

    def _vars(self, drv):
        for name, prop in (("e", "explode"), ("a", "explode_anim")):
            var = drv.variables.new()
            var.name = name
            var.type = "SINGLE_PROP"
            var.targets[0].id = self.root
            var.targets[0].data_path = '["%s"]' % prop

    def finish(self):
        root = self.root
        for prop, text in (("explode", "0 = assembled, 1 = exploded view"),
                           ("explode_anim", "same as explode; keyframed on the timeline")):
            root[prop] = 0.0
            root.id_properties_ui(prop).update(min=0.0, max=1.0, soft_min=0.0, soft_max=1.0,
                                               description=text)
        stages = max([o for _, _, o, _ in self.items] + [1])
        root["assembly_stages"] = stages
        bpy.context.view_layer.update()
        inv = root.matrix_world.inverted()
        for ob, off, order, label in self.items:
            t0 = (stages - order) / stages * (1.0 - self.SPAN) if order > 0 else 0.0
            ob["assembly_order"] = order
            ob["explode_offset"] = [round(c, 4) for c in off]
            ob["explode_window"] = [round(t0, 4), round(t0 + self.SPAN, 4)]
            if label:
                ob["part"] = label
            if off.length < 1e-9:
                continue
            frame = (inv @ ob.parent.matrix_world).to_3x3() if ob.parent else Matrix.Identity(3)
            local = frame.inverted() @ off                  # offset in the parent's axes
            for i in range(3):
                if abs(local[i]) < 1e-7:
                    continue
                drv = ob.driver_add("delta_location", i).driver
                drv.type = "SCRIPTED"
                self._vars(drv)
                drv.expression = f"{local[i]:.5f}*smoothstep({t0:.4f},{t0 + self.SPAN:.4f},max(e,a))"
        for con in self.tracks:                             # linkages hold only when assembled
            drv = con.driver_add("influence").driver
            drv.type = "SCRIPTED"
            self._vars(drv)
            drv.expression = "1-min(1,max(e,a)*1000)"

    def timeline(self, start=1, end=216, hold=24):
        """Keyframes on root["explode_anim"]: exploded at `start`, assembled from `end` on."""
        root, sc = self.root, bpy.context.scene
        stale = bpy.data.actions.get(root.name + "_Assembly")       # left over from an earlier run
        if stale is not None and stale.users == 0:
            bpy.data.actions.remove(stale)
        for frame, value in ((start, 1.0), (end, 0.0)):
            root["explode_anim"] = value
            root.keyframe_insert('["explode_anim"]', frame=frame)
        act = root.animation_data.action
        act.name = root.name + "_Assembly"
        if hasattr(act, "fcurves"):                         # Blender 4.x
            curves = list(act.fcurves)
        else:                                               # layered actions (Blender 5.x)
            curves = [fc for layer in act.layers for strip in layer.strips
                      for bag in strip.channelbags for fc in bag.fcurves]
        for fc in curves:
            for kp in fc.keyframe_points:
                kp.interpolation = "LINEAR"
        sc.frame_start, sc.frame_end = start, end + hold
        sc.frame_set(end + hold)                            # the file opens assembled


# ----------------------------------------------------------------------------
#  Banshee Jet 80+
# ----------------------------------------------------------------------------
def nose_radius(x, length, radius, p=1.5, q=0.7):
    t = min(max(x / length, 0.0), 1.0)
    return radius * (1.0 - (1.0 - t) ** p) ** q


INTAKE = (2.035, 2.065)            # flush air intake on each flank (aircraft stations)
EXHAUST_WALL = 2.695               # aft face of the bulkhead round the jet pipes


def jet_loft(cfg):
    R, nose_len, tail = 0.13, cfg["body"]["nose"], cfg["body"]["tail"]
    half_w = pchip([nose_len, 1.45, 1.75, 2.05, 2.35, 2.60, 2.80],
                   [R, R, 0.158, 0.200, 0.208, 0.200, 0.176])
    top = pchip([nose_len, 1.30, 1.70, 2.10, 2.45, 2.65, 2.80],
                [R, R, 0.143, 0.162, 0.166, 0.156, 0.140])
    bot = pchip([nose_len, 1.45, 1.90, 2.30, 2.60, 2.80],
                [R, R, 0.145, 0.150, 0.142, 0.122])
    n_bot = pchip([1.45, 1.95, 2.45, 2.80], [2.0, 2.5, 2.3, 1.7])
    n_top = pchip([1.45, 2.00, 2.80], [2.0, 2.25, 2.1])

    def sec(x):
        if x <= nose_len:
            r = nose_radius(x, nose_len, R)
            return dict(a=r, bt=r, bb=r)
        return dict(a=half_w(x), bt=top(x), bb=bot(x), nt=n_top(x), nb=n_bot(x))

    xs = [0.0, 0.004, 0.012, 0.025, 0.045, 0.07, 0.10, 0.14, 0.18, 0.22, 0.26, 0.30, nose_len]
    xs += frange(nose_len, 1.30, 0.12)[1:] + frange(1.30, INTAKE[0], 0.035)[1:]
    xs += [INTAKE[1]] + frange(INTAKE[1], tail, 0.035)[1:]
    return Loft(sec, xs)


def fuselage_skins(cfg, loft, coll, root, mats, paint, inside, holes=frozenset()):
    """Nose cone, lower fuselage, upper fuselage, hatch and engine cowl as separate shells."""
    B, n = cfg["body"], loft.n
    lo, up = (n // 2 - K_SPLIT, n + K_SPLIT), (K_SPLIT, n // 2 - K_SPLIT)
    x_ref = wing_geometry(cfg)["x_ref"]
    hatch = loft.cells(B["hatch"][0], B["hatch"][1], 9, 19)
    skins = dict(NoseCone=loft.cells(0.0, B["nose"]),
                 FuselageLower=loft.cells(B["nose"], B["tail"], *lo),
                 FuselageUpper=loft.cells(B["nose"], B["cowl"], *up) - hatch,
                 Hatch=hatch,
                 EngineCowl=loft.cells(B["cowl"], B["tail"], *up) - holes)
    part = {}
    for name, cells in skins.items():
        data = loft.shell(cells, paint, inner=inside)
        part[name] = mesh_object(cfg["prefix"] + name,
                                 data.transformed(lambda q: Vector((q.x, q.y - x_ref, q.z))),
                                 mats, coll, root)
    return part


def register_wings(asm, wing, link, sg):
    """Explode offsets of the wing panels and of what is fitted to them."""
    for side, tag in ((1, "L"), (-1, "R")):
        asm.add(wing["objs"][side], (side * 0.62, 0.0, 0.0), 3, "wing panel")
        for ob in link[tag]["servos"]:
            asm.add(ob, (0.0, 0.0, sg * 0.10), 4, "elevon servo")
        for ob in link[tag]["panels"]:
            asm.add(ob, (0.0, 0.17, 0.0), 5, "elevon panel")
        asm.add(link[tag]["fairing"], (0.0, 0.0, sg * 0.22), 6, "linkage fairing")
        asm.tracks += [rod.constraints["Follow servo arm"] for rod in link[tag]["rods"]]


def build_jet80(origin=(0.0, 0.0, 0.0)):
    cfg = JET
    pre, B = cfg["prefix"], cfg["body"]
    coll = new_collection(cfg["collection"])
    root = new_root(cfg, coll, origin)
    asm = Assembly(root)
    orange, yellow, comp = material("jet_orange"), material("jet_yellow"), material("composite")
    dark, black = material("dark_interior"), material("marking_black")
    x_ref = wing_geometry(cfg)["x_ref"]

    # ---- fuselage skins ----------------------------------------------------
    loft = jet_loft(cfg)
    n = loft.n
    intake = loft.cells(INTAKE[0], INTAKE[1], 2, 6) | loft.cells(INTAKE[0], INTAKE[1], n // 2 - 6, n // 2 - 2)
    part = fuselage_skins(cfg, loft, coll, root, [orange, yellow, comp, dark],
                          lambda j, k: 1 if loft.xs[j] < B["nose"] - 1e-6 else 0,
                          lambda j, k: 3 if loft.xs[j] > EXHAUST_WALL - 1e-6 else 2, intake)

    # ---- wing panels in their sockets, elevons with linkage, fin, rudder ----
    wing = add_wing(cfg, coll, root, [yellow], lambda tag: 0)
    subtract(part["FuselageLower"], wing_socket(wing), 2)
    link = add_elevons(cfg, wing, coll, yellow, [yellow], lambda tag: 0,
                       stencil=dict(text="NO HAND", height=0.012, x_scale=1.15, spacing=1.08,
                                    font=FONT_STENCIL))
    fin = add_fin(cfg, coll, part["EngineCowl"], x_ref, orange)["obj"]
    inside = loft.block(1.74, B["tail"], -1.0, 1.0, 0.5 * SHELL)        # everything below the skin
    subtract(fin, inside.transformed(lambda q: Vector((q.x, q.y - x_ref, q.z))), 0)

    # ---- markings ----------------------------------------------------------
    for word, yc, side in (("BANSHEE", 0.60, 1), ("TARGET", -0.58, -1)):
        v, f = text_decal(word, wing, cfg["wing_xte"] - 0.505, yc, 0.066, 1.42, True,
                          FONT_DISPLAY, 1.06)
        mesh_object(pre + "Markings." + ("L" if side > 0 else "R"), MeshData().add(v, f, 0, keep=True),
                    [black], coll, wing["objs"][side], merge=0)

    # ---- assembly ----------------------------------------------------------
    asm.add(part["FuselageLower"], (0.0, 0.0, 0.0), 0, "lower fuselage")
    register_wings(asm, wing, link, 1.0)
    jet_equipment(cfg, loft, wing, coll, root, asm)
    asm.add(part["FuselageUpper"], (0.0, 0.0, 0.95), 15, "upper fuselage")
    asm.add(part["EngineCowl"], (0.0, 0.12, 0.95), 15, "engine cowl with fin")
    asm.add(part["Hatch"], (0.0, 0.0, 1.20), 16, "parachute hatch")
    asm.add(part["NoseCone"], (0.0, -0.55, 0.0), 17, "nose cone")
    asm.finish()
    asm.timeline()
    return root


ENGINE_Y, ENGINE_Z = 0.079, 0.036      # axis of each turbojet: off the centre line, above the datum


class Fitter:
    """Places equipment given in aircraft coordinates (lateral, station, height)."""

    def __init__(self, cfg, wing, coll, root, asm):
        self.pre, self.x_ref = cfg["prefix"], wing["x_ref"]
        self.coll, self.root, self.asm = coll, root, asm

    def model(self, data):
        return data.transformed(lambda q: Vector((q[0], q[1] - self.x_ref, q[2])))

    def place(self, name, data, mats, offset, order, label):
        ob = mesh_object(self.pre + name, self.model(data), mats, self.coll, self.root)
        self.asm.add(ob, offset, order, label)
        return ob

    def bores(self, x0, x1, radius):
        """Two cylinders along the engine axes, for cutting frames."""
        md = MeshData()
        for sy in (-ENGINE_Y, ENGINE_Y):
            v, f = lathe([(x0, 0.0), (x0, radius), (x1, radius), (x1, 0.0)], (sy, 0.0, ENGINE_Z),
                         (0.0, 1.0, 0.0), 48)
            md.add(v, f, 0)
        return self.model(md)


def jet_equipment(cfg, loft, wing, coll, root, asm):
    """Structure and equipment inside the Jet 80+.  An illustrative layout: positions and
    sizes are chosen to fit the airframe, not taken from the real aircraft."""
    fit = Fitter(cfg, wing, coll, root, asm)
    jet_structure(fit, loft, wing)
    jet_systems(fit, loft)
    jet_engines(fit, cfg["body"]["tail"])


def jet_structure(fit, loft, wing):
    """Frames, engine cradle, exhaust bulkhead and the wing joiner tubes."""
    ply, dark, carbon = material("plywood"), material("dark_interior"), material("carbon")
    gap = SHELL + 0.0006                       # parts sit just clear of the skin

    # front frame: carries the radar lens; lightening holes round the centre
    f1 = fit.place("Frame_1", loft.block(0.348, 0.354, -1.0, 1.0, gap), [ply], (0.0, 0.0, 0.20), 1, "frame")
    holes = MeshData()
    for ang in (45, 135, 225, 315):
        c = (0.070 * math.cos(math.radians(ang)), 0.0, 0.070 * math.sin(math.radians(ang)))
        v, f = lathe([(0.34, 0.0), (0.34, 0.026), (0.36, 0.026), (0.36, 0.0)], c, (0.0, 1.0, 0.0), 24)
        holes.add(v, f, 0)
    subtract(f1, fit.model(holes), 0)

    # ring frames either side of the forward tank
    for i, x in ((2, 0.975), (3, 1.195)):
        ring = Loft(loft.sec, [x, x + 0.006])
        fit.place("Frame_%d" % i, ring.shell(ring.cells(x, x + 0.006), lambda j, k: 0, thick=0.024,
                                               inner=0, off=gap, gap=0.0),
                  [ply], (0.0, 0.0, 0.20), 1, "frame")

    # engine cradle: lower half-frame with a saddle for each engine, notched for the wing roots
    cradle = fit.place("EngineCradle", loft.block(2.395, 2.403, -1.0, ENGINE_Z - 0.0005, gap + 0.0006), [ply],
                       (0.0, 0.0, 0.16), 1, "engine cradle")
    subtract(cradle, fit.bores(2.38, 2.42, 0.0582), 0)
    subtract(cradle, wing_socket(wing), 0)

    # bulkhead round the jet pipes, split at the engine axis so the engines can be lowered in
    for name, z0, z1, off, order in (("ExhaustBulkhead_Lower", -1.0, ENGINE_Z - 0.0004, (0.0, 0.24, 0.0), 1),
                                     ("ExhaustBulkhead_Upper", ENGINE_Z + 0.0004, 1.0, (0.0, 0.24, 0.40), 14)):
        ob = fit.place(name, loft.block(EXHAUST_WALL - 0.006, EXHAUST_WALL, z0, z1, gap + 0.0006), [dark],
                       off, order, "exhaust bulkhead")
        subtract(ob, fit.bores(2.67, 2.71, 0.0615), 0)

    # joiner tubes through the fuselage into both wing panels
    for (x, r), name in zip(spar_stations(wing["geo"]), ("Spar_Front", "Spar_Rear")):
        v, f = lathe([(-SPAR_REACH, r - 0.002), (-SPAR_REACH, r), (SPAR_REACH, r), (SPAR_REACH, r - 0.002)],
                     (0.0, x, wing["z"]), (1.0, 0.0, 0.0), 24, close=True)
        fit.place(name, MeshData().add(v, f, 0), [carbon], (0.0, 0.0, 0.12), 2, "wing joiner tube")


def equipment_box(center, size, r=0.004, plugs=0):
    """Electronics box in (lateral, station, height): rounded body (material 0), label on
    top (1) and connectors on the aft face (2)."""
    md = MeshData()
    cx, cy, cz = center
    sx, sy, sz = size
    v, f = rounded_box(center, size, r)
    md.add(v, f, 0)
    v, f = box((cx, cy - 0.12 * sy, cz + 0.5 * sz), (0.62 * sx, 0.42 * sy, 0.0008))
    md.add(v, f, 1)
    for i in range(plugs):
        px = cx + (i - 0.5 * (plugs - 1)) * 0.022
        v, f = lathe([(0.0, 0.0), (0.0, 0.0065), (0.009, 0.0065), (0.009, 0.0045), (0.012, 0.0045),
                      (0.012, 0.0)], (px, cy + 0.5 * sy, cz), (0.0, 1.0, 0.0), 12)
        md.add(v, f, 2)
    return md


def jet_systems(fit, loft):
    """Radar lens, avionics, recovery parachute, fuel tanks and engine accessories."""
    ply, label, steel = material("plywood"), material("label_white"), material("steel_bright")
    grey, darkm, blue = material("anodised_grey"), material("anodised_dark"), material("battery_blue")
    gap = SHELL + 0.001
    axis = (0.0, 1.0, 0.0)

    # ---- Luneberg lens (passive radar reflector) on a tube from the front frame
    lens = MeshData()
    cx, rad = 0.240, 0.085
    prof = [(cx - rad * math.cos(math.radians(a)), rad * math.sin(math.radians(a))) for a in range(0, 181, 6)]
    v, f = lathe(prof, (0, 0, 0), axis, 48)
    lens.add(v, f, 0)
    v, f = lathe([(cx + 0.070, 0.024), (cx + 0.070, 0.030), (0.3475, 0.030), (0.3475, 0.024)],
                 (0, 0, 0), axis, 32, close=True)
    lens.add(v, f, 1)
    v, f = lathe([(cx - 0.004, rad - 0.002), (cx - 0.004, rad + 0.003), (cx + 0.004, rad + 0.003),
                  (cx + 0.004, rad - 0.002)], (0, 0, 0), axis, 48, close=True)
    lens.add(v, f, 1)
    fit.place("LunebergLens", lens, [material("lens_white"), grey], (0.0, -0.26, 0.0), 12, "radar lens")

    # ---- avionics on a tray in the lower half of the forward bay -----------
    fit.place("AvionicsTray", loft.block(0.362, 0.968, -0.050, -0.046, gap), [ply],
              (0.0, 0.0, 0.27), 8, "avionics tray")
    z0 = -0.0458
    for name, y, x0, x1, w, h, body, plugs, what in (
            ("FlightComputer", 0.0, 0.385, 0.545, 0.120, 0.045, grey, 3, "flight control computer"),
            ("Battery.L", 0.030, 0.575, 0.705, 0.050, 0.040, blue, 1, "battery"),
            ("Battery.R", -0.030, 0.575, 0.705, 0.050, 0.040, blue, 1, "battery"),
            ("Receiver", 0.046, 0.735, 0.835, 0.072, 0.030, darkm, 2, "command receiver"),
            ("Transponder", -0.046, 0.735, 0.835, 0.072, 0.036, grey, 2, "transponder"),
            ("PowerUnit", 0.0, 0.865, 0.945, 0.130, 0.028, darkm, 4, "power distribution")):
        data = equipment_box((y, 0.5 * (x0 + x1), z0 + 0.5 * h), (w, x1 - x0, h), plugs=plugs)
        fit.place(name, data, [body, label, steel], (0.0, 0.0, 0.38), 9, what)

    # ---- recovery parachute on its own floor under the hatch ----------------
    fit.place("ParachuteTray", loft.block(0.455, 0.945, 0.010, 0.013, gap), [ply],
              (0.0, 0.0, 0.52), 10, "parachute floor")
    pack = loft.block(0.470, 0.930, 0.0135, 1.0, SHELL + 0.004, half_w=0.064, bevel=0.012)
    for x in (0.570, 0.800):
        strap = loft.block(x, x + 0.030, 0.0132, 1.0, SHELL + 0.0028, half_w=0.0652)
        pack.add(strap.v, strap.f, 1)
    fit.place("Parachute", pack, [material("chute_orange"), material("chute_white")],
              (0.0, 0.0, 0.66), 11, "recovery parachute")

    # ---- fuel tanks: one ahead of the wing, one above the wing roots --------
    tank_mats = [material("tank_white"), material("rubber")]
    for name, x0, x1, zlow, bands, lift in (("FuelTank_Fwd", 0.985, 1.191, -1.0, (1.020, 1.140), 0.30),
                                            ("FuelTank_Main", 1.215, 1.960, 0.006, (1.330, 1.580, 1.830), 0.34)):
        tank = loft.block(x0, x1, zlow, 1.0, SHELL + 0.004, bevel=0.010)
        for x in bands:
            band = loft.block(x, x + 0.016, zlow - 0.0005, 1.0, SHELL + 0.0028)
            tank.add(band.v, band.f, 1)
        fit.place(name, tank, tank_mats, (0.0, 0.0, lift), 7, "fuel tank")

    # ---- engine accessories on a shelf ahead of the engines -----------------
    fit.place("EquipmentShelf", loft.block(2.000, 2.235, 0.004, 0.007, gap), [ply],
              (0.0, 0.0, 0.22), 8, "equipment shelf")
    zs = 0.0072
    for sy, tag in ((0.060, "L"), (-0.060, "R")):
        ecu = equipment_box((sy, 2.065, zs + 0.012), (0.070, 0.090, 0.024), plugs=2)
        fit.place("EngineECU." + tag, ecu, [darkm, label, steel], (0.0, 0.0, 0.32), 9, "engine control unit")
        pump = MeshData()
        v, f = lathe([(2.140, 0.0), (2.140, 0.013), (2.185, 0.013), (2.185, 0.009), (2.200, 0.009),
                      (2.200, 0.0)], (sy, 0.0, zs + 0.014), axis, 20)
        pump.add(v, f, 0)
        v, f = box((sy, 2.162, zs + 0.003), (0.020, 0.030, 0.006))
        pump.add(v, f, 1)
        fit.place("FuelPump." + tag, pump, [steel, darkm], (0.0, 0.0, 0.32), 9, "fuel pump")


def jet_engines(fit, tail):
    """The two turbojets with their jet pipes."""
    mats = [material("aluminium"), material("anodised_grey"), material("steel_bright"),
            material("steel_burnt"), material("dark_interior")]
    axis = (0.0, 1.0, 0.0)
    x0 = 2.675
    body = [(2.268, 0.0, 4), (2.268, 0.045, 1), (2.259, 0.050, 1), (2.255, 0.054, 1), (2.259, 0.058, 1),
            (2.275, 0.060, 1), (2.302, 0.060, 1), (2.315, 0.056, 0), (2.500, 0.056, 2), (2.530, 0.058, 2),
            (2.560, 0.056, 3), (2.600, 0.050, 3), (2.676, 0.050, 3), (2.676, 0.0, 3)]
    for sy, tag in ((ENGINE_Y, "L"), (-ENGINE_Y, "R")):
        md = MeshData()
        c = Vector((sy, 0.0, ENGINE_Z))
        v, f, m = lathe_bands(body, c, axis, 48)                       # intake lip, casing, turbine
        md.add(v, f, m)
        v, f = lathe([(2.232, 0.0), (2.240, 0.010), (2.255, 0.017), (2.2685, 0.019), (2.2685, 0.0)],
                     c, axis, 32)                                      # starter cone
        md.add(v, f, 0)
        v, f = lathe([(2.345, 0.0555), (2.345, 0.0576), (2.359, 0.0576), (2.359, 0.0555)],
                     c, axis, 48, close=True)                          # mounting band
        md.add(v, f, 2)
        v, f = lathe([(x0, 0.060), (tail + 0.035, 0.058), (tail + 0.042, 0.055),
                      (tail + 0.040, 0.051), (x0, 0.052)], c, axis, 40, close=True)
        md.add(v, f, 2)                                                # shroud
        v, f = lathe([(x0, 0.0), (x0, 0.049), (tail + 0.075, 0.046), (tail + 0.100, 0.0425),
                      (tail + 0.100, 0.0395), (tail + 0.070, 0.043), (x0 + 0.03, 0.045),
                      (x0 + 0.03, 0.0)], c, axis, 40)
        md.add(v, f, 3)                                                # jet pipe
        v, f = lathe([(x0 + 0.03, 0.0), (x0 + 0.03, 0.026), (tail + 0.01, 0.020),
                      (tail + 0.065, 0.0)], c, axis, 24)
        md.add(v, f, 3)                                                # exhaust cone
        fit.place("Engine." + tag, md, mats, (0.0, 0.45, 0.28), 13, "turbojet")


# ----------------------------------------------------------------------------
#  Scene bookkeeping
# ----------------------------------------------------------------------------
def new_collection(name):
    old = bpy.data.collections.get(name)
    if old:                                   # rebuild from scratch when re-run
        for ob in list(old.objects):
            data = ob.data
            bpy.data.objects.remove(ob, do_unlink=True)
            if isinstance(data, bpy.types.Mesh) and data.users == 0:
                bpy.data.meshes.remove(data)
        bpy.data.collections.remove(old)
    coll = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(coll)
    return coll


def new_root(cfg, coll, origin):
    root = bpy.data.objects.new(cfg["prefix"] + "ROOT", None)
    root.empty_display_type = "PLAIN_AXES"
    root.empty_display_size = 0.25
    root.location = origin
    root["variant"] = cfg["collection"]
    root["span_m"] = SPAN
    root["length_m"] = cfg["length"]
    root["nose_to_origin_m"] = round(wing_geometry(cfg)["x_ref"], 4)
    coll.objects.link(root)
    return root


README = """Banshee Jet 80+ - Blender 모델 (내부 장비 / 분해·조립)

분해도 · 조립 순서
  Jet80_ROOT 엠프티 선택 > N 패널 > Item > Properties > explode
      0 = 조립 상태,  1 = 완전 분해.  1 -> 0 으로 움직이면 조립 순서대로 부품이 들어옵니다.
  타임라인(1-240 프레임)을 재생하면 같은 조립 과정이 재생됩니다 (explode_anim 에 키프레임).
      explode 슬라이더를 직접 쓸 때는 타임라인을 마지막 프레임에 둡니다.
  부품마다 사용자 속성이 있습니다 (웹에서 같은 연출을 만들 때 사용):
      assembly_order   조립 순서 (0 = 기준 부품인 하부 동체)
      explode_offset   분해 위치까지의 이동량 [x, y, z] m  (ROOT 축 기준)
      explode_window   explode 슬라이더에서 이 부품이 움직이는 구간 [시작, 끝]
      part             부품 설명

부품 구성 (이름 앞에 Jet80_ 가 붙습니다)
  외피      NoseCone, FuselageLower, FuselageUpper, Hatch, EngineCowl(+Fin, Rudder)
  날개      Wing.L / Wing.R - 하부 동체 소켓에 끼우고 조이너 튜브 2개(Spar_Front / _Rear)로 연결
            Elevon_In/Out, Servo_In/Out(+ServoArm), Pushrod, LinkageFairing
  구조      Frame_1..3, EngineCradle, ExhaustBulkhead_Lower / _Upper
  장비      LunebergLens, AvionicsTray, FlightComputer, Battery.L/.R, Receiver, Transponder,
            PowerUnit, ParachuteTray, Parachute, FuelTank_Fwd / _Main,
            EquipmentShelf, EngineECU.L/.R, FuelPump.L/.R, Engine.L / Engine.R
  내부 장비의 종류·위치·크기는 조립 연출용으로 이 모델에 맞춰 정한 것이며 실기 자료가 아닙니다.

조종면
  Elevon_In.L / Out.L / In.R / Out.R, Rudder 를 선택해 Rotation X 값을 바꿉니다 (+/-30 deg 제한).
  부호:  엘레본 +X = 뒷전 아래,  러더 +X = 뒷전 왼쪽
  서보암 - 푸시로드 - 혼 링키지는 조립 상태(explode = 0)에서 조종면을 따라 움직입니다.

좌표:  기수 = -Y,  위 = +Z,  좌측 날개 = +X,  단위 m
원점:  주익 평균공력시위(MAC) 25 % 지점의 동체 축선
"""


def build_all():
    build_jet80()
    txt = bpy.data.texts.get("README_Banshee") or bpy.data.texts.new("README_Banshee")
    txt.clear()
    txt.write(README)
    bpy.context.view_layer.update()


if __name__ == "__main__":
    build_all()
