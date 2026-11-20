#!/usr/bin/env python3
"""Цикл сессии: исполнитель в pty, оператор через OpenCode headless.

    python runner/session_loop.py T2 --stack runner/adapters/profiles/opencode.json --profile A --run-id r-test --max-turns 1
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from operator_client import ask  # noqa: E402
from pty_driver import PtySession  # noqa: E402

FINAL = re.compile(r"^\s*\[FINAL\]\s*", re.I)
CHECK_RU = {
    "geometry_present": "геометрия не сдана",
    "geometry_saved": "итоговая геометрия не сдана",
    "radius_matches_result": "радиус в отчёте не совпадает с геометрией",
    "sampling_points": "точки выборки слишком близко к проводнику",
    "units": "не те единицы",
    "conductor_size": "неверные размеры проводника",
    "plane_size": "неверные размеры плоскостей",
    "radius": "неверный радиус кромок",
    "radius_range": "радиус вне допустимого диапазона",
    "gap_top": "мал верхний зазор",
    "gap_bottom": "мал нижний зазор",
    "gap_balance": "зазоры несимметричны",
    "potentials": "неверные потенциалы",
    "closed": "контур не замкнут",
    "self_intersections": "контур самопересекается",
    "convergence": "нет сеточной сходимости",
    "max_e": "превышен предел max|E|",
    "capacitance": "ёмкость вне диапазона",
    "protected": "изменены защищённые объекты",
    "convergence_control": "нет сходимости в контрольных точках",
    "w_recalc": "W′ не сходится с C′ и U",
    "ranking": "ранжирование не соответствует W′",
    "optimum": "не обоснован оптимум",
    "conflict_declared": "не заявлен конфликт",
    "reason_14_gt_10": "не объяснена причина конфликта",
    "alternative_valid": "альтернатива недопустима",
    "points_count": "неполная сетка",
    "grid": "сетка не та",
    "valid_geometry": "есть недопустимые варианты",
    "gaps": "нарушены зазоры",
    "width": "неверная ширина",
}


def now():
    return dt.datetime.now().isoformat(timespec="seconds")


def log(path, **kw):
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": now(), **kw}, ensure_ascii=False) + "\n")


def build_operator_prompt(task_dir, profile_path, spec, faq, final_q):
    profile = open(profile_path, encoding="utf-8").read()
    faq_text = "\n".join(f"- {x['q']} → {x['a']}" for x in json.load(open(faq))["items"])
    return f"""{profile}

# Задача

{spec}

# FAQ

{faq_text}

# Правила

- Ты ведёшь диалог, не пишешь код, не правишь файлы и не диагностируешь стенд.
- Файлы сам не читаешь: видишь только сообщения исполнителя, список файлов и проверки.
- Смотри на ответ исполнителя и на соответствие ТЗ; не разбирай код.
- Говори как инженер: что нарушено по ТЗ и что требуется. 2–4 предложения.
- Когда результат достаточен по критериям и в проверках нет `fail`, **обязательно** начни ответ с `[FINAL]`, даже если хочется разбора. 3–5 предложений, не больше. Финальный вопрос задаст ведущий.
  «{final_q}» — только для справки, сам его не задавай.
- Если рано — задай вопрос, попроси доказательства или укажи на невыполненное требование.
- Если в блоке «Проверки» есть `fail` — не закрывай сессию: назови проваленный пункт и потребуй устранить.
  Отдельно проверь, что правка сдана файлом геометрии, а не только описана в отчёте.
- Не называй числа вне ТЗ/диапазона. Не диктуй координаты, сетку, API.
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("task")
    ap.add_argument("--stack", required=True)
    ap.add_argument("--profile", default="A")
    ap.add_argument("--run-id")
    ap.add_argument("--max-turns", type=int)
    ap.add_argument("--operator-model")
    ap.add_argument("--capture", action="store_true")
    ap.add_argument("--gif", action="store_true")
    a = ap.parse_args()
    if a.operator_model:
        os.environ["OPERATOR_MODEL"] = a.operator_model

    task_dir = os.path.join(ROOT, "tasks", a.task)
    cfg = json.load(open(os.path.join(task_dir, "task.json")))
    run_id = a.run_id or f"{a.task}-{a.profile}-{dt.datetime.now():%Y%m%d-%H%M%S}"
    out = os.path.join(ROOT, "runs", run_id)
    subprocess.run([sys.executable, os.path.join(ROOT, "tools", "build_task.py"), a.task, "--out", out],
                   check=True, capture_output=True)
    ws = os.path.join(out, "workspace")
    os.makedirs(os.path.join(out, "checks"), exist_ok=True)
    meta = {"run_id": run_id, "task": a.task, "profile": a.profile, "stack": a.stack,
            "operator_model": os.environ.get("OPERATOR_MODEL", "deepseek-v4.1-flash-1017-uncensored"), "started": now()}
    json.dump(meta, open(os.path.join(out, "meta.json"), "w"), ensure_ascii=False, indent=1)

    op_system = build_operator_prompt(task_dir, os.path.join(ROOT, "operator", "profiles", f"{a.profile}.md"),
                                      open(os.path.join(ws, "spec.md"), encoding="utf-8").read(),
                                      os.path.join(task_dir, "faq.json"), cfg["final_question"])
    op_messages: list[dict] = [{"role": "system", "content": op_system}]

    def ask_op(user: str, timeout: float = 600) -> dict:
        op_messages.append({"role": "user", "content": user})
        r = ask(op_messages, timeout=timeout)
        if r.get("text"):
            op_messages.append({"role": "assistant", "content": r["text"]})
        return r

    cap = os.path.join(out, "frames") if a.capture else None
    ex = PtySession(json.load(open(a.stack)), ws, os.path.join(out, "executor"), cap)
    t0 = time.time()
    turns = 0
    limit_turns = a.max_turns or cfg["limits"]["messages"]
    limit_seconds = cfg["limits"]["minutes"] * 60
    try:
        ex.start()
        initial = cfg["initial_prompt"]
        log(os.path.join(out, "trace.jsonl"), kind="session_start", operator="llm")
        ex.send_text(initial)
        log(os.path.join(out, "agent.jsonl"), turn=0, kind="initial_prompt", text=initial)

        while turns < limit_turns and (time.time() - t0) < limit_seconds:
            left = max(60, limit_seconds - (time.time() - t0))
            res = ex.wait_turn(timeout=left)
            screen = res.get("screen", "")
            log(os.path.join(out, "agent.jsonl"), turn=turns, kind="turn_end", status=res.get("status"),
                screen_chars=len(screen))
            if (time.time() - t0) > limit_seconds:
                log(os.path.join(out, "trace.jsonl"), kind="limit", reason="minutes")
                break
            check_file = os.path.join(out, "checks", f"t{turns}.json")
            subprocess.run([sys.executable, os.path.join(ROOT, "verifier", "verify.py"), a.task, ws, "--out", check_file],
                           capture_output=True)
            checks = json.load(open(check_file)) if os.path.exists(check_file) else {}
            files = []
            for d in ("out", "figures"):
                base = os.path.join(ws, d)
                if os.path.isdir(base):
                    files += [f"{d}/{x}" for x in sorted(os.listdir(base)) if not x.startswith(".")]
            st = {}
            for x in checks.get("checks", []):
                st[x["status"]] = st.get(x["status"], 0) + 1
            fails = [x["id"] for x in checks.get("checks", []) if x["status"] == "fail"]
            fail_text = "; ".join(CHECK_RU.get(x, x) for x in fails) or "нет"
            msg = (f"Ответ исполнителя (ход {turns + 1}):\n{screen[-2200:]}\n\n"
                   f"Файлы: {', '.join(files[:40]) or 'нет'}\n"
                   f"Проверки: pass {st.get('pass',0)}, fail {st.get('fail',0)}, manual {st.get('manual',0)}. Провалено: {fail_text}")
            r = ask_op(msg)
            turns += 1
            text = r.get("text", "")
            log(os.path.join(out, "operator.jsonl"), turn=turns, text=text, seconds=r.get("seconds"),
                usage=r.get("usage"), error=r.get("error"))
            if r.get("error"):
                r = ask_op(msg, timeout=300)
                log(os.path.join(out, "operator.jsonl"), turn=turns, text=r.get("text",""), seconds=r.get("seconds"), usage=r.get("usage"), error=r.get("error"), retry=True)
            if r.get("error"):
                break
            final = bool(FINAL.match(text))
            if not final and not fails:
                r2 = ask_op("Все проверки прошли без fail. Если результата достаточно — начни ответ с [FINAL] и коротко подтверди; если нет — назови, чего не хватает.", timeout=300)
                log(os.path.join(out, "operator.jsonl"), turn=turns, text=r2.get("text",""), seconds=r2.get("seconds"), usage=r2.get("usage"), error=r2.get("error"), verdict=True)
                if r2.get("text"):
                    text = r2["text"]
                    final = bool(FINAL.match(text))
            send = FINAL.sub("", text).strip()
            if final:
                q = cfg["final_question"]
                ex.send_text(q)
                fr = ex.wait_turn(timeout=240)
                log(os.path.join(out, "agent.jsonl"), turn=turns, kind="final", text=fr.get("screen", "")[-6000:])
                break
            if send:
                ex.send_text(send)
    finally:
        ex.stop()
        subprocess.run(["pkill", "-9", "-f", "femm.exe"], capture_output=True)
        if a.gif and cap and os.path.isdir(cap) and os.listdir(cap):
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", "4", "-i", os.path.join(cap, "%04d.png"),
                            "-vf", "scale=960:-1:flags=lanczos,split[a][b];[a]palettegen[p];[b][p]paletteuse",
                            os.path.join(out, "session.gif")], capture_output=True)
        meta["ended"] = now()
        meta["turns"] = turns
        json.dump(meta, open(os.path.join(out, "meta.json"), "w"), ensure_ascii=False, indent=1)
    print(out)


if __name__ == "__main__":
    main()
