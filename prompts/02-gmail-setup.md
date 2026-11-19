# Copy-paste prompt: optional Gmail

```text
Help configure this installed local app for one Gmail account. Read AGENTS.md,
docs/GMAIL_SETUP.md, docs/CREDENTIAL_STORAGE.md and docs/GMAIL_RUNTIME.md. Keep the
current model and loopback-only hosting. First verify local readiness without
reading any mailbox or retained-feedback content.

Walk me through the Google Cloud project, Gmail API, consent/test user,
gmail.readonly scope and Desktop app client. I will handle the browser and download
the JSON outside this repository. Ask for only the file path; never ask for, print
or copy credential contents, OAuth codes, tokens or email contents. You may set
EMAIL_CHECK_GMAIL_CLIENT_FILE to that path in my local ignored configuration with
my authorization, preserving existing settings. Do not open the JSON yourself.

I will perform sign-in/consent, select a non-sensitive test email and report only
whether connect, list, preview, scan and disconnect work. Do not broaden scopes or
use a plaintext token file. Save outcomes and generic errors only. Keep local
paste/import usable. Do not train, publish or claim Gmail accuracy from this check.
```
