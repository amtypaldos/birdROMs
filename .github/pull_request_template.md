## What and why

<!-- What does this change, and why? Link the issue if there is one. -->

## How it was tested

<!-- Backend tests, frontend tests, manual steps. -->

## Checklist

- [ ] Backend tests pass (`cd backend && uv run python manage.py test`) and `makemigrations --check` is clean
- [ ] Frontend `yarn lint`, `yarn test` and `yarn build` pass
- [ ] Tests added or updated for the change
- [ ] Docs and `backend/.env.example` updated if behaviour or settings changed
- [ ] Nothing that widens what `readonly` users or anonymous visitors can see or download
- [ ] No secrets, ROMs, BIOS files or personal details in the diff
