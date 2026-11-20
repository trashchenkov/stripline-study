"""Модель FEMM для электростатики из проверенной геометрии: Lua-скрипт для femm.exe (п. 6 ТЗ).

Скрипт строит задачу ei_* (newdocument(1) — электростатика), назначает воздух, электроды как области без сетки
с потенциалом на контуре, внешнюю границу без свойства (естественное условие dV/dn = 0), сохраняет .fee, строит
сетку, решает и пишет в текстовый файл: число элементов и узлов, потенциалы в контрольных точках, V и E
в точках выборки (точки подготовлены заранее в файле, их выбор — в sampling_points).
"""
from __future__ import annotations

import math
from typing import Dict, List, Tuple

import geomodel as gm


def sampling_points(geometry: dict, physics: dict) -> List[Tuple[float, float]]:
    """Точки выборки поля: окно sampling.region, в воздухе, не ближе offset к электродам; без окрестностей острых углов."""
    sp = physics['sampling']
    reg, step, off = sp['region'], sp['step_mm'], sp['offset_from_conductors_mm']
    excl = sp.get('exclude_sharp_corners_radius_mm', 0.0)
    electrodes = {oid: gm.contour(o) for oid, o in ((o['id'], o) for o in geometry['objects']) if oid in physics['conductors']}
    # острые углы (излом касательной) — по контуру, независимо от записи геометрии
    sharp = [q for c in electrodes.values() for q in gm.sharp_corners(c)]
    boxes = {oid: gm.bbox(c) for oid, c in electrodes.items()}
    pts = []
    nx = int(round((reg['x1'] - reg['x0']) / step))
    ny = int(round((reg['y1'] - reg['y0']) / step))
    for i in range(nx + 1):
        x = reg['x0'] + i * step
        for j in range(ny + 1):
            y = reg['y0'] + j * step
            p = (x, y)
            ok = True
            for oid, c in electrodes.items():
                x0, y0, x1, y1 = boxes[oid]
                if x0 - off <= x <= x1 + off and y0 - off <= y <= y1 + off:
                    if gm.point_in_contour(p, c) or min(gm.point_seg_dist(p, s)[0] for s in c) < off:
                        ok = False
                        break
            if ok and any(gm.dist(p, q) < excl for q in sharp):
                ok = False
            if ok:
                pts.append((round(x, 6), round(y, 6)))
    return pts


def viz_points(geometry: dict, physics: dict):
    """Регулярная сетка для карты поля (physics.visualization): узлы вне электродов; возвращает (описание сетки, точки)."""
    vz = physics['visualization']
    reg, step = vz['region'], vz['step_mm']
    nx = int(round((reg['x1'] - reg['x0']) / step)) + 1
    ny = int(round((reg['y1'] - reg['y0']) / step)) + 1
    electrodes = [gm.contour(o) for o in geometry['objects'] if o['id'] in physics['conductors']]
    boxes = [gm.bbox(c) for c in electrodes]
    pts = []
    for j in range(ny):
        y = reg['y0'] + j * step
        for i in range(nx):
            x = reg['x0'] + i * step
            inside = any(b[0] <= x <= b[2] and b[1] <= y <= b[3] and gm.point_in_contour((x, y), c) for c, b in zip(electrodes, boxes))
            if not inside:
                pts.append((i, j, round(x, 6), round(y, 6)))
    return {'x0': reg['x0'], 'y0': reg['y0'], 'step': step, 'nx': nx, 'ny': ny}, pts


def _air_point(domain, holes):
    """Точка в расчётной области вне электродов: от угла габарита внутрь, пока не попадём в воздух."""
    x0, y0, x1, y1 = gm.bbox(domain)
    for k in range(1, 50):
        p = (x0 + k * 0.01 * (x1 - x0), y1 - k * 0.01 * (y1 - y0))
        if gm.point_in_contour(p, domain) and not any(gm.point_in_contour(p, h) for h in holes):
            return p
    raise gm.GeometryError('не найдена точка воздуха для метки области')


def _n(v: float) -> str:
    """Координата для FEMM: округление до 1e-9 мм. Без него конец дуги, пересчитанный через центр, даёт
    -1.1e-16 вместо 0 — FEMM получает два почти совпадающих узла, и построение сетки зависает."""
    v = round(v, 9)
    return f'{0.0 if v == 0 else v:.12g}'


def _q(path: str) -> str:
    return '"' + path.replace('\\', '/') + '"'


def lua_script(geometry: dict, physics: dict, level: dict, paths: Dict[str, str]) -> str:
    """paths: fee, points, result — пути в виде, понятном femm.exe (под Wine — Z:/...)."""
    pr = physics['problem']
    L = []
    w = L.append
    w('-- создано engineering/femm_lua.py; электростатика FEMM 4.2')
    w('newdocument(1)')
    w(f'ei_probdef("{pr["units"]}", "{pr["type"]}", {pr["precision"]}, {pr["depth_mm"]}, {pr["min_angle_deg"]})')
    for name, m in physics['materials'].items():
        w(f'ei_addmaterial("{name}", {m["ex"]}, {m["ey"]}, {m["qv"]})')
    for oid, c in physics['conductors'].items():
        w(f'ei_addconductorprop("{c["name"]}", {c["potential_V"]}, 0, 1)')

    maxseg = level['arc_maxseg_deg']
    contours = gm.objects_contours(geometry)
    for oid, c in contours.items():
        w(f'-- {oid}')
        for s in c:  # узлы — концы сегментов, каждый один раз (контур замкнут: конец = начало следующего)
            w(f'ei_addnode({_n(s.a[0])}, {_n(s.a[1])})')
        for s in c:
            if isinstance(s, gm.Line):
                w(f'ei_addsegment({_n(s.a[0])}, {_n(s.a[1])}, {_n(s.b[0])}, {_n(s.b[1])})')
            else:
                a, b = (s.a, s.b) if s.sweep > 0 else (s.b, s.a)  # FEMM строит дугу против часовой от первой точки
                w(f'ei_addarc({_n(a[0])}, {_n(a[1])}, {_n(b[0])}, {_n(b[1])}, {_n(math.degrees(abs(s.sweep)))}, {maxseg})')
        # свойства контура: на электродах — потенциал и размер элементов, на внешней границе — ничего
        cond = physics['conductors'].get(oid)
        for s in c:
            if isinstance(s, gm.Line):
                mx, my = (s.a[0] + s.b[0]) / 2, (s.a[1] + s.b[1]) / 2
                w('ei_clearselected()')
                w(f'ei_selectsegment({_n(mx)}, {_n(my)})')
                if cond:
                    w(f'ei_setsegmentprop("<None>", {level["boundary_elem_mm"]}, 0, 0, 0, "{cond["name"]}")')
                else:
                    w('ei_setsegmentprop("<None>", 0, 1, 0, 0, "<None>")')
            else:
                mid = s.start + s.sweep / 2
                mx, my = s.c[0] + s.r * math.cos(mid), s.c[1] + s.r * math.sin(mid)
                w('ei_clearselected()')
                w(f'ei_selectarcsegment({_n(mx)}, {_n(my)})')
                w(f'ei_setarcsegmentprop({maxseg}, "<None>", 0, 0, "{cond["name"] if cond else "<None>"}")')
    w('ei_clearselected()')

    air_label = None
    # метки областей: электроды — во внутренней точке, без сетки; воздух — у края расчётной области вне электродов
    for o in geometry['objects']:
        block = physics['blocks'].get(o['id'])
        if block is None:
            continue
        c = contours[o['id']]
        if block == '<No Mesh>':
            x, y = gm.interior_point(c)
        else:
            x, y = _air_point(c, [contours[i] for i, b in physics['blocks'].items() if b == '<No Mesh>' and i in contours])
            air_label = (x, y)
        w(f'ei_addblocklabel({_n(x)}, {_n(y)})')
        w(f'ei_selectlabel({_n(x)}, {_n(y)})')
        if block == '<No Mesh>':
            w('ei_setblockprop("<No Mesh>", 0, 0, 0)')
        else:
            w(f'ei_setblockprop("{block}", 0, {level["air_elem_mm"]}, 0)')
        w('ei_clearselected()')

    w(f'ei_saveas({_q(paths["fee"])})')
    w('ei_createmesh()')
    w('ei_analyze(1)')
    w('ei_loadsolution()')
    w(f'out = openfile({_q(paths["result"])}, "w")')
    w('write(out, "elements ", eo_numelements(), "\\n")')
    w('write(out, "nodes ", eo_numnodes(), "\\n")')
    # интегральные величины: заряд проводников (на глубину модели) и энергия поля в воздухе — для ёмкости
    for oid, c in physics['conductors'].items():
        w(f'Vc, Qc = eo_getconductorproperties("{c["name"]}")')
        w(f'write(out, "conductor {oid} ", Vc, " ", Qc, "\\n")')
    if air_label:
        w(f'eo_selectblock({_n(air_label[0])}, {_n(air_label[1])})')
        w('write(out, "energy ", eo_blockintegral(0), "\\n")')
        w('eo_clearblock()')
    for cp in physics.get('control_points', []):
        w(f'V = eo_getpointvalues({cp["x"]}, {cp["y"]})')
        w(f'write(out, "control {cp["id"]} ", V, "\\n")')
    w(f'pts = openfile({_q(paths["points"])}, "r")')
    w('x = read(pts, "*n")')
    w('while x do')
    w('  y = read(pts, "*n")')
    w('  V, Dx, Dy, Ex, Ey = eo_getpointvalues(x, y)')
    w('  write(out, "p ", x, " ", y, " ", V, " ", Ex, " ", Ey, "\\n")')
    w('  x = read(pts, "*n")')
    w('end')
    w('closefile(pts)')
    if paths.get('viz'):  # карта поля для изображения (только на заданном уровне сетки)
        w(f'vz = openfile({_q(paths["viz"])}, "r")')
        w(f'vo = openfile({_q(paths["viz_out"])}, "w")')
        w('x = read(vz, "*n")')
        w('while x do')
        w('  y = read(vz, "*n")')
        w('  V, Dx, Dy, Ex, Ey = eo_getpointvalues(x, y)')
        w('  write(vo, V, " ", Ex, " ", Ey, "\\n")')
        w('  x = read(vz, "*n")')
        w('end')
        w('closefile(vz)')
        w('closefile(vo)')
    w('write(out, "done\\n")')
    w('closefile(out)')
    w('quit()')
    return '\n'.join(L) + '\n'
