# Coding Progression System

Геймифицированный дневник кодинга для Obsidian: один Python-скрипт превращает
данные [WakaTime](https://wakatime.com) в ежедневную заметку с XP, уровнями,
стриками, ачивками, "деревом навыков" по языкам, таблицей лидеров и другими
виджетами — всё в виде красиво оформленных карточек прямо в Obsidian.

## Скриншоты

<p align="center">
  <img src="assets/todays-session-demo.gif" width="420" alt="Today's Session — карточка дня">
  &nbsp;&nbsp;
  <img src="assets/xp-level-demo.gif" width="420" alt="XP & Level — заполнение уровня">
</p>

<table>
<tr>
<td><img src="assets/streak.png" alt="Streak"></td>
<td><img src="assets/skill-tree.png" alt="Skill Tree"></td>
</tr>
<tr>
<td><img src="assets/weekly-goals.png" alt="Weekly Goals"></td>
<td><img src="assets/todays-achievements.png" alt="Today's Achievements"></td>
</tr>
<tr>
<td><img src="assets/leaderboard.png" alt="Leaderboard"></td>
<td><img src="assets/trophy-room.png" alt="Trophy Room"></td>
</tr>
<tr>
<td><img src="assets/daily-average.png" alt="Daily Average"></td>
<td><img src="assets/xp-14-days.png" alt="XP 14 Days"></td>
</tr>
<tr>
<td><img src="assets/activity-30-days.png" alt="Activity 30 Days"></td>
<td><img src="assets/top-weeks.png" alt="Top Weeks by XP"></td>
</tr>
</table>

Это 10 из 12 виджетов заметки — плюс сама карточка "Today's Session" и XP & Level
показаны выше в виде GIF. Полный список: Today's Session, XP & Level, Streak,
Weekly Goals, Today's Achievements, Skill Tree, Trophy Room, Leaderboard,
Top Weeks by XP, Daily Average, Activity (30 Days), XP (14 Days).

## Что нужно

- Python 3.9+
- [Obsidian](https://obsidian.md) с установленным плагином **Dataview**
  (виджеты используют `dataviewjs`, поэтому в настройках Dataview должен быть
  включён JavaScript Queries)
- Аккаунт [WakaTime](https://wakatime.com) с установленным плагином-трекером
  для вашего редактора/IDE

## Установка

1. Скачайте `wakatime_to_obsidian.py` и `requirements.txt`.
2. Установите зависимости:
   ```
   pip install -r requirements.txt
   ```
3. Откройте `wakatime_to_obsidian.py` и заполните блок `НАСТРОЙКИ` в начале файла:
   - `WAKATIME_API_KEY` — ваш ключ, страница `https://wakatime.com/settings/api-key`
   - `VAULT_PATH` — абсолютный путь до вашего Obsidian vault
   - при желании поменяйте `DAILY_FOLDER` (папка для daily notes внутри vault, по умолчанию `daily`)
4. Запустите:
   ```
   python wakatime_to_obsidian.py
   ```
   Скрипт создаст заметку `<vault>/daily/ГГГГ-ММ-ДД.md` за сегодняшний день.
5. Откройте эту заметку в Obsidian — виджеты `dataviewjs` отрисуются автоматически.

Если поля не заполнены или указанный путь не существует, скрипт остановится
с понятным сообщением о том, что нужно исправить — ничего никуда не запишет.

## Автозапуск каждый вечер (необязательно)

Через cron (Linux/macOS):
```
0 23 * * * /usr/bin/python3 /полный/путь/до/wakatime_to_obsidian.py
```
На Windows для той же цели используйте Планировщик заданий.

## Настройка под себя

В начале файла, помимо ключа и пути, есть несколько групп констант,
которые можно менять без риска что-то сломать:

- `XP_PER_HOUR`, `TOP_LANG_BONUS`, `STREAK_BONUS_PER_DAY` — формула начисления XP
- `ACHIEVEMENT_THRESHOLDS` — пороги дневных ачивок (в часах)
- `ACHIEVEMENT_HOUR_BONUS` / `ACHIEVEMENT_STREAK_BONUS` / `ACHIEVEMENT_MILESTONE_BONUS` — бонусы XP за разблокированные ачивки
- `WEEKLY_GOALS` — цели на неделю (часы топ-языка, часы всего, дни подряд)

Все виджеты берут эти значения из Python-констант через f-string, поэтому
цифры в интерфейсе никогда не разойдутся с реальной логикой начисления XP.

## Важно про приватность

`WAKATIME_API_KEY` — секретный ключ, не публикуйте файл с уже заполненным
значением (например, не коммитьте его в открытый git-репозиторий).

## Лицензия

MIT — используйте, меняйте и распространяйте свободно.
