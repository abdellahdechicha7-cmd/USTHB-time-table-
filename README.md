# USTHB Timetable

A small Django site that publishes weekly timetables for USTHB sections.
Students view it without an account; admins log in to edit.

- **Spaces**: one per major + section (e.g. `MCIL.SD · Section B`), each with its own groups, time slots, subjects, weeks and notes.
- **Weeks start empty**: each Saturday–Thursday week is filled by copying any earlier week and adjusting it. Past weeks stay browsable.
- **Change badges**: sessions copied from another week are compared with their source (New, Moved, Room changed, Changed, Cancelled).
- **Notes**: simple block notes (Editor.js), pinned to the space or attached to a week.
- **Roles**: superusers (owners) create spaces and admins; space admins edit their own spaces only.

## Run locally

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt     # Windows; use .venv/bin/python on Linux/macOS
.venv/Scripts/python manage.py migrate
.venv/Scripts/python manage.py createsuperuser
.venv/Scripts/python manage.py seed_demo                    # optional: MCIL.SD Section B demo data
.venv/Scripts/python manage.py runserver
```

Open http://127.0.0.1:8000 for the public site and http://127.0.0.1:8000/login/ for admins.

Run the tests with `.venv/Scripts/python manage.py test timetable`.

## Deploy to PythonAnywhere (free account)

1. **Upload the code**: push to GitHub, then in a PythonAnywhere *Bash console*:
   ```bash
   git clone https://github.com/<you>/<repo>.git usthb-timetable
   cd usthb-timetable
   mkvirtualenv --python=python3.13 usthb    # pick the newest Python PythonAnywhere offers
   pip install -r requirements.txt
   ```
2. **Create the web app**: *Web* tab → *Add a new web app* → *Manual configuration* → same Python version.
   - *Virtualenv*: `/home/<username>/.virtualenvs/usthb`
   - *Source code*: `/home/<username>/usthb-timetable`
3. **WSGI file** (link on the Web tab): replace its content with
   ```python
   import os, sys
   path = '/home/<username>/usthb-timetable'
   if path not in sys.path:
       sys.path.insert(0, path)
   os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings'
   os.environ['DJANGO_SECRET_KEY'] = '<long random string>'   # python -c "import secrets; print(secrets.token_urlsafe(50))"
   os.environ['DJANGO_DEBUG'] = '0'
   os.environ['DJANGO_ALLOWED_HOSTS'] = '<username>.pythonanywhere.com'
   from django.core.wsgi import get_wsgi_application
   application = get_wsgi_application()
   ```
4. **Database and static files** (Bash console, virtualenv active):
   ```bash
   python manage.py migrate
   python manage.py collectstatic --noinput
   python manage.py createsuperuser
   ```
   Web tab → *Static files*: URL `/static/` → directory `/home/<username>/usthb-timetable/staticfiles`.
5. Web tab: turn on **Force HTTPS**, then **Reload**.

**Updating later:** `git pull && python manage.py migrate && python manage.py collectstatic --noinput`, then *Reload*.

**Free-tier note:** PythonAnywhere asks you to log in and press *Run until 3 months from today* on the Web tab periodically, or the site is disabled.
