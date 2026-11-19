# Publish as a new GitHub repository

This folder is the repository root. It has no `.git` directory or old commit history.
Copy it out of the old project first if you want a fully separate working folder.
Do not publish the parent project or the parent `github-ready` directory.

1. Review the files and [validation report](docs/runs/bootstrap/REPORT.md).
2. Select your repository name, visibility and project license as owner. No new
   project license has been applied; see [third-party notices](THIRD_PARTY_NOTICES.md).
3. On GitHub, create an empty repository named `email-checker`. Leave its automatic
   README, license and `.gitignore` initialization options off when importing this folder.
4. In a terminal opened inside this folder, run the commands below yourself.

```powershell
git init -b main
git add .
git status --short
git diff --cached --stat
git diff --cached
```

Confirm no `.env`, credential files, tokens, databases, email corpora, virtualenv,
checkpoints or old run archives are staged. The supplied synthetic `.eml` test
fixtures and `.env.example` are intentional. Then replace `YOUR-ACCOUNT` and run:

```powershell
git commit -m "Initial clean import"
git remote add origin https://github.com/YOUR-ACCOUNT/email-checker.git
git push -u origin main
```

Use Git's normal authentication flow. Never paste a personal access token into
chat, a committed file or the remote URL. These are owner-run publication steps;
the exported setup prompts do not authorize an assistant to publish.

After upload, clone into a different empty directory and follow [setup](docs/SETUP.md)
or [the AI installation prompt](prompts/01-install-windows.md). This confirms the new
repo does not depend on files in the original workspace.

Reference: [GitHub: adding locally hosted code](https://docs.github.com/en/migrations/importing-source-code/using-the-command-line-to-import-source-code/adding-locally-hosted-code-to-github).
