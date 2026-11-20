"""Исполнительный компонент FEMM: явные входы (геометрия, постановка, уровень сетки, папка) и выходы (result.json).

Режимы запуска:
- wine    — femm.exe внутри Wine на macOS/Linux;
- windows — femm.exe напрямую на Windows;
- pseudo  — псевдорешатель ТОЛЬКО для проверки интерфейса: результат помечен physical = false
            и не засчитывается как физический (п. 11 ТЗ).
Если FEMM не найден, запуск завершается ошибкой; «успеха» без решателя не бывает (п. 6 ТЗ).

Настройка: переменные окружения FEMM_MODE (wine|windows|pseudo), FEMM_EXE (путь к femm.exe),
WINE (путь к wine). По умолчанию: Wine Stable.app и ~/.wine/drive_c/femm42/bin/femm.exe.
"""
from __future__ import annotations

import json
import math
import os
import platform
import shutil
import signal
import subprocess
import time
from typing import Dict, List, Optional

import femm_lua

DEFAULT_WINE = '/Applications/Wine Stable.app/Contents/Resources/wine/bin/wine'
DEFAULT_FEMM_WINE = os.path.expanduser('~/.wine/drive_c/femm42/bin/femm.exe')
DEFAULT_FEMM_WIN = r'C:\femm42\bin\femm.exe'


class FemmUnavailable(RuntimeError):
    pass


class FemmFailed(RuntimeError):
    pass


def detect_mode() -> str:
    mode = os.environ.get('FEMM_MODE')
    if mode:
        return mode
    if platform.system() == 'Windows':
        return 'windows'
    return 'wine'


def _wine() -> str:
    w = os.environ.get('WINE') or (DEFAULT_WINE if os.path.exists(DEFAULT_WINE) else shutil.which('wine'))
    if not w or not os.path.exists(w):
        raise FemmUnavailable('Wine не найден: установите Wine (см. engineering/README.md) или задайте WINE=/путь/к/wine')
    return w


def check_environment(mode: Optional[str] = None) -> dict:
    """Что есть в среде для запуска FEMM; ошибки — FemmUnavailable с объяснением."""
    mode = mode or detect_mode()
    if mode == 'pseudo':
        return {'mode': 'pseudo', 'physical': False}
    if mode == 'wine':
        wine = _wine()
        exe = os.environ.get('FEMM_EXE', DEFAULT_FEMM_WINE)
        if not os.path.exists(exe):
            raise FemmUnavailable(f'femm.exe не найден в {exe}: установите FEMM 4.2 в Wine или задайте FEMM_EXE')
        ver = subprocess.run([wine, '--version'], capture_output=True, text=True, timeout=60).stdout.strip()
        return {'mode': 'wine', 'wine': wine, 'wine_version': ver, 'femm_exe': exe, 'physical': True}
    if mode == 'windows':
        exe = os.environ.get('FEMM_EXE', DEFAULT_FEMM_WIN)
        if not os.path.exists(exe):
            raise FemmUnavailable(f'femm.exe не найден в {exe}: задайте FEMM_EXE')
        return {'mode': 'windows', 'femm_exe': exe, 'physical': True}
    raise FemmUnavailable(f'неизвестный FEMM_MODE={mode!r}')


def _to_femm_path(path: str, mode: str) -> str:
    """Путь, понятный femm.exe: под Wine корень файловой системы — диск Z:."""
    path = os.path.abspath(path)
    return ('Z:' + path) if mode == 'wine' else path


def solve(geometry: dict, physics: dict, level: dict, workdir: str, tag: str, mode: Optional[str] = None,
          timeout: int = 180, viz: bool = False) -> dict:
    """Строит и решает модель FEMM на одном уровне сетки. Возвращает словарь результата и пишет <tag>.result.json."""
    env = check_environment(mode)
    os.makedirs(workdir, exist_ok=True)
    base = os.path.join(workdir, tag)
    pts = femm_lua.sampling_points(geometry, physics)
    with open(base + '.points.txt', 'w') as f:
        f.write('\n'.join(f'{x} {y}' for x, y in pts) + '\n')
    m = env['mode']
    paths = {'fee': _to_femm_path(base + '.fee', m), 'points': _to_femm_path(base + '.points.txt', m),
             'result': _to_femm_path(base + '.out.txt', m)}
    grid = None
    if viz and physics.get('visualization'):
        grid, vpts = femm_lua.viz_points(geometry, physics)
        with open(base + '.viz.txt', 'w') as f:
            f.write('\n'.join(f'{x} {y}' for _, _, x, y in vpts) + '\n')
        paths['viz'] = _to_femm_path(base + '.viz.txt', m)
        paths['viz_out'] = _to_femm_path(base + '.vizout.txt', m)
    script = femm_lua.lua_script(geometry, physics, level, paths)
    with open(base + '.lua', 'w') as f:
        f.write(script)
    if os.path.exists(base + '.out.txt'):
        os.remove(base + '.out.txt')

    t0 = time.time()
    if m == 'pseudo':
        log = _pseudo(geometry, physics, pts, base + '.out.txt')
    else:
        cmd = ([env['wine']] if m == 'wine' else []) + [env['femm_exe'], f'-lua-script={_to_femm_path(base + ".lua", m)}', '-windowhide']
        log = ''
        # зависание femm.exe под Wine (редко, при параллельных запусках) прерывается и запуск повторяется один раз;
        # повторное зависание — ошибка решателя, а не «успех»
        for attempt in (1, 2):
            # вывод — в файл, а не в канал: при зависании femm.exe держит канал открытым, и subprocess.run с timeout
            # ждал его закрытия часами; группа процессов убивается целиком
            with open(base + '.stdout.txt', 'w') as fo:
                proc = subprocess.Popen(cmd, stdout=fo, stderr=subprocess.STDOUT, start_new_session=True,
                                        env={**os.environ, 'WINEDEBUG': '-all', 'WINEDLLOVERRIDES': 'winedbg.exe=d'} if m == 'wine' else None)
                try:
                    rc = proc.wait(timeout=timeout)
                    log += f'$ {" ".join(cmd)}\nexit {rc}\n'
                    break
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    subprocess.run(['pkill', '-9', '-f', os.path.basename(base) + '.lua'], capture_output=True)
                    proc.wait()
                    log += f'попытка {attempt}: femm.exe не завершился за {timeout} с — прерван\n'
                    if attempt == 2:
                        with open(base + '.log', 'w') as f:
                            f.write(log)
                        raise FemmFailed(f'femm.exe не завершился за {timeout} с дважды (зависание решателя)')
    secs = time.time() - t0
    with open(base + '.log', 'w') as f:
        f.write(log)

    res = parse_output(base + '.out.txt', physics)
    if grid is not None and m != 'pseudo':
        res['field'] = os.path.basename(base + '.field.json')
        _save_field(grid, vpts, base + '.vizout.txt', base + '.field.json')
    res.update({'tag': tag, 'level': level['level'], 'mode': m, 'physical': env['physical'], 'seconds': round(secs, 1),
                'n_sample_points': len(pts), 'files': {k: os.path.basename(base + ext) for k, ext in
                                                       (('fee', '.fee'), ('lua', '.lua'), ('log', '.log'), ('out', '.out.txt'))}})
    with open(base + '.result.json', 'w') as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    return res


def parse_output(path: str, physics: dict) -> dict:
    """Разбор вывода скрипта; без маркера done или без элементов сетки — ошибка решателя."""
    if not os.path.exists(path):
        raise FemmFailed(f'FEMM не создал файл результата {os.path.basename(path)} (см. .log)')
    lines = open(path).read().split('\n')
    if 'done' not in lines:
        raise FemmFailed('вывод FEMM оборван (нет маркера done)')
    res: Dict = {'controls': {}}
    best = (-1.0, None)
    n = 0
    for ln in lines:
        p = ln.split()
        if not p:
            continue
        if p[0] in ('elements', 'nodes'):
            res[p[0]] = int(float(p[1]))
        elif p[0] == 'conductor':
            res.setdefault('conductors', {})[p[1]] = {'V': float(p[2]), 'Q_C': float(p[3])}
        elif p[0] == 'energy':
            res['energy_J'] = float(p[1])
        elif p[0] == 'control':
            res['controls'][p[1]] = float(p[2])
        elif p[0] == 'p':
            x, y, V, Ex, Ey = map(float, p[1:6])
            E = math.hypot(Ex, Ey)
            n += 1
            if E > best[0]:
                best = (E, (x, y))
    if not res.get('elements'):
        raise FemmFailed('сетка не построена (0 элементов)')
    if n == 0:
        raise FemmFailed('нет значений поля в точках выборки')
    # единицы: FEMM в электростатике выдаёт E в В/м
    res['max_E_V_per_m'] = best[0]
    res['max_E_kV_per_mm'] = best[0] / 1e6
    res['max_E_at'] = list(best[1])
    res['n_values'] = n
    return res


def _pseudo(geometry: dict, physics: dict, pts: List, out: str) -> str:
    """Псевдорешатель для тестов интерфейса: однородное поле U/зазор. Физического смысла не имеет."""
    import geomodel as gm
    cs = gm.objects_contours(geometry)
    ids = list(physics['conductors'])
    d = gm.contour_distance(cs[ids[0]], cs[ids[1]])[0]
    U = abs(physics['conductors'][ids[0]]['potential_V'] - physics['conductors'][ids[1]]['potential_V'])
    E = U / (d / 1000.0)
    with open(out, 'w') as f:
        f.write('elements 1\nnodes 3\n')
        for cp in physics.get('control_points', []):
            f.write(f'control {cp["id"]} {U / 2}\n')
        for x, y in pts[:10]:
            f.write(f'p {x} {y} {U / 2} {E} 0\n')
        f.write('done\n')
    return 'pseudo-solver: только для проверки интерфейса, не физический результат'


def _save_field(grid: dict, vpts: list, out_path: str, json_path: str):
    """Карта поля: |E| (кВ/мм) и V (В) на регулярной сетке; узлы внутри электродов — null."""
    vals = open(out_path).read().split('\n')
    n = grid['nx'] * grid['ny']
    E, V = [None] * n, [None] * n
    for (i, j, _, _), line in zip(vpts, vals):
        p = line.split()
        if len(p) < 3:
            continue
        v, ex, ey = map(float, p[:3])
        k = j * grid['nx'] + i
        E[k] = round(math.hypot(ex, ey) / 1e6, 5)
        V[k] = round(v, 3)
    with open(json_path, 'w') as f:
        json.dump({**grid, 'E_kV_per_mm': E, 'V': V}, f)
