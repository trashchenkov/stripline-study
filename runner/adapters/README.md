# Транспорт

Один pty/tmux-адаптер на все CLI-харнессы.

## Интерфейс

```
start(profile, workspace, limits) -> session
send(session, text) -> ack
waitTurn(session) -> {text, status, usage?}
interrupt(session)
stop(session)
```

## Профили запуска

В `profiles/` — команда, аргументы, env, cwd, шаблон готовности и приглашения. Отдельный файл на харнесс.

## Правила

- Фиксированный размер 160×48.
- Текст + Enter, bracketed paste для многострочного.
- Ждать приглашение и затишье вывода; лимит ожидания — сессионный.
- ANSI снимать, сырой поток писать в `raw/`.
- Токены и tool calls — из логов харнесса постфактум.
- API-адаптер добавляется только при неустойчивости pty.
