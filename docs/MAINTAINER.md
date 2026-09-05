# Maintainer checklist (monthly)

Public repo. Anyone can read. Do not paste secrets into this file.

Once a month, from a clean clone of `main`:

1. GitHub **Contributors** — if a name you do not recognize appears, check the
   *commit email* before assuming they had access. Old commits using
   `login@users.noreply.github.com` (no numeric id) can be attributed to a
   random account that squatted that login.
2. **Collaborators** — should be the owner only.
3. **Deploy keys** — should be none unless you added one on purpose.
4. **Actions** runs — lint should use `GITHUB_TOKEN`, not a personal PAT.
5. Open **issues** and **PRs**.
6. `git log --format='%an <%ae>'` — expected: owner ID-prefixed
   `users.noreply.github.com`, plus GitHub's merge robot `noreply@github.com`.
   A personal mailbox on squash merges means GitHub **Emails** still exposes
   the account address; turn on “Keep my email addresses private”.

Before every push: `bash scripts/check-scrub.sh`.
