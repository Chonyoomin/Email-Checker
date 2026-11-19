# AI setup prompts

Open this repository folder in your coding assistant, then copy the entire prompt
from the matching file. The prompts work with agents that can run local commands;
they do not require LangChain or a cloud AI API in the application.

1. [Install on Windows](01-install-windows.md).
2. [Configure optional Gmail](02-gmail-setup.md).
3. [Verify an existing installation](03-verify.md).
4. [Resume development](04-resume-development.md).

The installation prompt explicitly authorizes its project-local dependencies and
public checkpoint download. It does not authorize system-wide installs, reading
credential contents, Google sign-in, training, publishing or changing model choices.
Use a fresh clone and your own accounts; do not paste email contents or secrets into chat.
