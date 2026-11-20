# Ведущий сессии

Реализовано: `pty_driver.py`, `operator_client.py`, `session_loop.py`.
Захват экрана: `--capture` (PNG каждые 2 с и на границах хода), `--gif` (сборка `session.gif`).

```
.venv/bin/python runner/session_loop.py T2 --stack runner/adapters/profiles/opencode.json --profile A --run-id r-001 --capture --gif
```

Оператор — OpenCode headless (`--agent plan`), модель `OPERATOR_MODEL` (по умолчанию ds41-local/flash).

## Изоляция

- workspace — отдельный git-корень, `PWD` выставляется в workspace;
- иначе агент видит родительский репозиторий, tasks и hidden.

## Интерфейс адаптера

```
start(task, workspace, profile, limits) -> session
send(session, text) -> ack
waitTurn(session) -> {text, tool_calls, usage, status}
output(session) -> last message
usage(session) -> tokens/durations
stop(session, reason)
```

## Ход

1. Сборщик готовит `workspace`.
2. Ведущий стартует сессию через адаптер.
3. Отправляет стартовый текст из `spec.md`.
4. Ждёт завершение хода.
5. Чистит ANSI, пишет `agent.jsonl`, отдаёт оператору сообщение, файлы, проверки.
6. Получает ответ оператора, снимает `[FINAL]`.
7. Повтор до `[FINAL]` или лимита.
8. Задаёт финальный вопрос, если нужно.
9. Закрывает, копирует workspace в `runs/`, пишет метаданные.

## Транспорт

Один pty/tmux-адаптер. Харнесс запускается как CLI в фиксированном окне, текст отправляется в pty, вывод читается из него, ANSI снимается. API-адаптеры — только если pty окажется неустойчивым.

## Профили запуска

На каждый харнесс: команда, аргументы, env, cwd, проверка готовности, шаблон приглашения. Профили в `adapters/profiles/`.

## Правила

- Исполнитель видит только текст.
- `[FINAL]` и служебные заметки не попадают в его историю.
- Проверки не блокируют ход.
- Отмена — через адаптер.
