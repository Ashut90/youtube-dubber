# Contributing to YT Dubber

Thanks for your interest! All contributions are welcome — bug fixes, new languages,
UI improvements, performance work, or documentation.

> **Rule #1: Fork the repo. Do not push directly to `main`.**

> **Rule #2: This project is GPL-3.0. Your fork must:**
> - Credit the original: **Ashut90 / youtube-dubber**
> - Stay open source under GPL-3.0
> - State what you changed
>
> Silent forks that strip attribution or go closed-source violate the license.
> If you want to discuss an exception, [open a Discussion](../../discussions).

---

## Before you start — say hello

If you're planning a significant change (new feature, architecture change, new language),
**open a Discussion first**. This avoids duplicate work and lets us align on direction
before you invest time writing code.

---

## Workflow

```
1. Fork  →  2. Clone YOUR fork  →  3. Branch  →  4. PR to main
```

### 1. Fork

Click **Fork** on the GitHub page. This gives you your own copy to work in.
Never clone the original repo directly — you won't have push access.

### 2. Clone your fork

```bash
git clone https://github.com/<YOUR_USERNAME>/youtube-dubber.git
cd youtube-dubber
```

### 3. Add the upstream remote (keeps your fork in sync)

```bash
git remote add upstream https://github.com/Ashut90/youtube-dubber.git
```

### 4. Create a branch

```bash
git checkout -b feat/your-feature-name
```

Use a descriptive branch name:
- `feat/add-indonesian-language`
- `fix/arabic-caption-encoding`
- `docs/improve-setup-guide`

### 5. Make your changes

Follow the existing code style. Keep commits focused — one logical change per commit.

### 6. Test your change

```bash
# Backend
python3 -c "import ast; ast.parse(open('backend/dub_video.py').read()); print('OK')"

# Frontend
node --check frontend/main.js

# Run the app
cd frontend && npm start
```

### 7. Push and open a Pull Request

```bash
git push origin feat/your-feature-name
```

Then open a PR on GitHub from your fork's branch to `main` on the original repo.
Write a short description of **what** you changed and **why**.

### 8. Sync your fork with upstream before starting new work

```bash
git fetch upstream
git checkout main
git merge upstream/main
```

---

## Adding a new language

1. Open `backend/languages.py`
2. Add an entry to `LANGUAGES` with:
   - `name`, `script`, `voice_male`, `voice_female` (from [edge-tts voices](https://github.com/rany2/edge-tts))
   - `full_stop` character for the language
   - `fillers` — 4–5 natural spoken filler words
   - `keep_english: True` for code-switch (Indian / East Asian), `False` for full translation
3. Add the `<option>` to both dropdowns in `frontend/renderer/index.html`
4. Test with a short video

---

## Reporting a bug

Open a GitHub Issue with:
- What you expected
- What actually happened
- Terminal output / screenshot
- Your OS and GPU (relevant for the mpv / renderer setup)

---

## Code of Conduct

Be respectful. Constructive feedback only.
