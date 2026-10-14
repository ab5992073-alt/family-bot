# Staff Grand Bot — patched source

## Included
- `main.py` — patched bot source
- `requirements.txt` — Python dependencies

## Changes made
- Removed active Zam-bank behavior and schema migration code; historical database table/data are not dropped or deleted.
- Removed the timezone keyboard handler/button; the owner's `/timezone` command remains.
- Reminder destination now supports `группа`, `личка`, and `владельцу`.
- Owner can use reminder create/list/edit/toggle/delete even if `can_reminders` is disabled.
- Owner clicking `📨 Report` sees saved incoming reports instead of being asked to send a report to administration.
- `/ahelp` lists implemented commands and separates owner-only commands.
- `/kto` is the supported command name (Telegram commands cannot contain Cyrillic letters).
- Preserved safe Google Sheets replacement logic to avoid overwriting larger sheets with empty/smaller query results.

## Important database note
This source does not repair a mismatched/empty `DATABASE_URL`. If the production database query returns 0 applications while the spreadsheet has 28, do not clear the spreadsheet or change the database URL blindly. First confirm which PostgreSQL database the Render service is connected to and inspect its row counts without modifying data.
