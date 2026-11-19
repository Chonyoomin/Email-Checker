# Optional Gmail setup

Local paste/import works without Google setup. Use your own Cloud project and
Desktop app client. Google console setup references were checked November 17, 2026.

## Prepare Google Cloud

In [Google Cloud Console](https://console.cloud.google.com/), create/select one
project and enable Gmail API. Configure Google Auth platform Branding and Audience.
For a personal account choose External/Testing and add your intended Gmail account
under Test users. Internal applies to an eligible Workspace organization.
In Data Access add `https://www.googleapis.com/auth/gmail.readonly`.

Create an OAuth client of type **Desktop app**, then download its JSON. Keep it
outside this repository, for example in a private folder under LocalAppData.
Do not use an API key, service account or Web application client. The application
handles its loopback redirect; no public callback server is needed.

## Connect locally

Set `EMAIL_CHECK_GMAIL_CLIENT_FILE` in the ignored `.env` to the absolute JSON path.
Leave host at `127.0.0.1`, restart the app, select Gmail and Connect. Complete
Google sign-in and read-only consent yourself in a regular browser. Return to the
app, refresh the list, select a non-sensitive test message, preview and scan.
Disconnect clears local credentials and attempts remote revocation; report any
revocation error separately. Read-only access includes message bodies but does not
permit the app to send, delete or modify email.

Tokens use the OS protected store, not a plaintext token file. Do not paste JSON,
codes, tokens or email content into an AI chat or project memory. The setup assistant
needs only the path; the app reads credentials when you choose to connect.
[Protected storage](CREDENTIAL_STORAGE.md), [runtime behavior](GMAIL_RUNTIME.md).

Keep Testing/test-user configuration for this local prototype; public OAuth
distribution has additional requirements. Gmail setup and your account must be
verified separately; earlier development smoke checks are not a check of your account.

References: [Google Gmail quickstart](https://developers.google.com/workspace/gmail/api/quickstart/python),
[desktop OAuth](https://developers.google.com/identity/protocols/oauth2/native-app).
