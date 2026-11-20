#!/usr/bin/env python3
"""Build/check appendix tables from the selected local runs; --from-csv needs no runs archive."""
import argparse
import csv
import io
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs/article"
COLS = "run task stack profile condition passed final seconds turns messages work_messages pre_final".split()
NUMS = COLS[5:]


def from_logs():
    result = []
    for selected in json.loads((ROOT / "analysis/runs.json").read_text()):
        folder = ROOT / selected["dir"]
        meta = json.loads((folder / "meta.json").read_text())
        reports = sorted((folder / "checks").glob("t*.json"), key=lambda p: int(p.stem[1:]))
        last = json.loads(reports[-1].read_text()) if reports else {}
        groups = defaultdict(list)
        log = folder / "operator.jsonl"
        for line in log.read_text().splitlines() if log.exists() else []:
            msg = json.loads(line)
            groups[msg["turn"]].append((msg.get("text", "").strip(), msg.get("verdict")))
        replies = [text for group in groups.values() for text, _ in group if text]
        def final(text):
            return text.lower().startswith("[final]")
        finals = sum(map(final, replies))
        sec = (datetime.fromisoformat(meta["ended"]) - datetime.fromisoformat(meta["started"])).total_seconds()
        row = {key: selected[key] for key in COLS[:5]}
        passed = last.get("passed", False) and not any(c["status"] == "fail" for c in last["checks"])
        row.update(passed=int(passed), final=int(bool(finals)), seconds=int(sec), turns=meta["turns"],
                   messages=len(replies), work_messages=len(replies)-finals,
                   pre_final=sum(bool(text) and not final(text) for group in groups.values()
                                 if group[-1][1] and final(group[-1][0]) for text, _ in group[:-1]))
        if any(row[k] != selected[k] for k in ("passed", "final", "seconds", "turns")) or meta["run_id"] != row["run"]:
            raise ValueError(f"Расхождение с индексом: {folder.name}")
        result.append(row)
    return sorted(result, key=lambda x: tuple(x[k] for k in ("task", "stack", "profile", "condition")))


def table(headers, rows):
    return "\n".join("| " + " | ".join(map(str, line)) + " |" for line in [headers, ["---"]*len(headers), *rows])


def appendix(rows):
    pairs = defaultdict(dict)
    for r in rows:
        if r["task"] != "T1" and r["stack"] in ("codex", "claude"):
            pairs[r["task"], r["stack"], r["profile"]][r["condition"]] = r
    durations = []
    for task in ("T2", "T3", "T4", "T5"):
        matched = [p for key, p in pairs.items() if key[0] == task and all(p[c]["messages"] for c in ("helpers", "raw"))]
        durations.append([task, len(matched), *(f"{median(p[c]['seconds'] for p in matched):g}".replace(".", ",")
                                                  for c in ("helpers", "raw"))])
    modes = {"helpers": "с библиотекой", "raw": "без библиотеки", "shared": "без библиотеки"}
    matrix = [[f"`{r['run']}`", r["task"], r["profile"], modes[r["condition"]],
               *("да" if r[k] else "нет" for k in ("passed", "final")),
               *(r[k] for k in ("seconds", "turns", "messages", "work_messages"))] for r in rows]
    return """# Приложение В. Сводные данные

[К материалам статьи](../../README.md) · [Правила отбора и подсчёта](reproduce.md) · [Все строки в CSV](sessions.csv)

## В1. Длительность в сопоставимых парах

Пара — один исполнитель (Claude Code или Codex CLI), одна задача и один профиль оператора, с библиотекой и без неё. В обеих сессиях должна быть хотя бы одна непустая реплика оператора, в том числе закрывающая. У Claude Code с профилем A в T2 и T3 без библиотеки реплик не было; эти две пары не включены. Время — от старта до закрытия сессии, а не время решения поля в FEMM. Медианы описывают только перечисленные пары и не оценивают ожидаемое ускорение.

""" + table(["Задача", "Пар", "С библиотекой, медиана, с", "Без библиотеки, медиана, с"], durations) + """

## В2. Все 54 сессии

A — инструкция инженера, C — студента; это профили одной модели, а не участники-люди. Зачёт относится к сданным файлам, а [FINAL] — к сообщению оператора. Ходы — счётчик ведущего; нулевое число ходов не означает, что исполнитель не создал файлов. Два зачёта OpenCode без библиотеки в T2 и T3 (профиль A) получены с использованием кода из соседних каталогов. В T1 библиотека не выдавалась ни в одной сессии.

«Непустых» и «рабочих» — числа **сгенерированных** реплик оператора. Рабочими считаются непустые реплики без начального [FINAL]. Двенадцать из них предшествовали закрывающему ответу на том же ходу и по протоколу были заменены до отправки. В CSV это отдельный столбец `pre_final`.

""" + table(["Запуск", "Задача", "Профиль", "Режим", "Зачёт", "[FINAL]", "Время, с", "Ходов", "Непустых", "Рабочих"], matrix) + "\n"


def main():
    p = argparse.ArgumentParser(description=__doc__)
    opts = p.add_mutually_exclusive_group()
    opts.add_argument("--write", action="store_true", help="обновить CSV и Markdown из архива")
    opts.add_argument("--from-csv", action="store_true", help="сверить таблицы по опубликованному CSV, без журналов")
    args = p.parse_args()
    if args.from_csv:
        with (DOC / "sessions.csv").open() as f:
            rows = [{k: int(v) if k in NUMS else v for k,v in r.items()} for r in csv.DictReader(f)]
    else:
        rows = from_logs()
    cells = {(r["task"], r["stack"], r["profile"], r["condition"]) for r in rows}
    totals = tuple(sum(r[k] for r in rows) for k in ("passed", "messages", "work_messages", "pre_final"))
    if not (len(rows) == len(cells) == 54 and totals == (48, 104, 60, 12)):
        raise ValueError("Состав выборки или итоговые числа изменились")
    with (DOC / "manual-review.csv").open() as f:
        manual = list(csv.DictReader(f))
    reviewed = {m["run"] for m in manual}
    if not (len(reviewed) == 31 and reviewed <= {r["run"] for r in rows if r["passed"]}
            and all(m["verdict"] == "confirmed" for m in manual)
            and Counter(m["task"] for m in manual) == {"T2":11, "T4":20, "T5":10}):
        raise ValueError("Изменились качественные оценки")
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=COLS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    for name, content in [("sessions.csv", buf.getvalue()), ("sessions.md", appendix(rows))]:
        path = DOC / name
        if args.write:
            path.write_text(content)
        elif path.read_text() != content:
            raise SystemExit(f"Требует сверки: {path}")
    print("54 сессии; 48 зачётов; 104 реплики (44 закрывающих, 60 рабочих, из них 12 заменены); 41 качественная оценка.")


if __name__ == "__main__":
    main()
