# Quick start

## 1. Create a bot

Open [@BotFather](https://t.me/BotFather) in Telegram and send `/newbot`. Enter a display name, then an available username ending in `bot`. Copy the Bot Token and keep the bot's link. If you already have a bot, use its existing token. Paste the token into settings, not into an AI conversation. [Official tutorial](https://core.telegram.org/bots/tutorial)

## 2. Connect in Tiance

1. Open **Settings → Remote Access → Telegram → Connection**.
2. Paste the token into **Bot Token**. Leave the advanced Bot API address as `https://api.telegram.org`.
3. Turn on Telegram access. Wait for the bot's name and ready status. If validation fails, correct the issue and try again.
4. Use **Access scope** beside allowed users to enable collections for this bot. Switches save automatically. Only Projects is enabled by default; each connection has its own scope.

For `ConnectTimeout`, open **Settings → Network settings**. Select system proxy if your proxy app has enabled it. Otherwise select custom proxy, enter the actual HTTP host and port shown by your proxy app, save, and retry. Do not use Tiance's service port as the proxy port.

## 3. Allow your account

1. On your phone, open your bot and tap **Start** or send `/start` in a private chat.
2. Return to **Connection** in Tiance. Wait for your account to appear under allowed users.
3. Check its name, username and ID, then enable its access switch.
4. Wait for the bot's access confirmation. Do not authorize unfamiliar accounts.

## 4. Choose a conversation

1. Send `/projects`. A single enabled collection opens directly; two or more show a collection picker. Then select a category and project. With no collections enabled, content access is unavailable.
2. Select an existing conversation, or send `/new Phone test` from the project's main-conversation list to create one.
3. Send `/status`. Verify the project, conversation and model. To change it, send `/model`, choose a provider and then a model. If the list is empty, add a model and enable its provider in the desktop model collection first.
4. Send “Reply with received”. The final answer should arrive on your phone; the full process is visible in the desktop conversation.

Further text goes to that selection until you change it. No project or conversation prefix is needed.

After a collection is disabled, its old buttons, selected conversations and replies to old messages no longer grant access. Send `/projects` to choose again. Tasks already running continue on the desktop, but content outside the scope is not returned through this bot.

## 5. Send files

Choose a conversation first, attach the original file, and wait for the saved confirmation. Send multiple files, check `/files`, then send the processing instructions.

Files go into `远程收件/Telegram/<random directory>/` inside the target project. A single file with a caption submits that caption after downloading. For albums, wait for collection to finish and send instructions separately. Files sent without a selected conversation must be resent after selecting one.

Use a small file for the first test. The default cloud download limit is 20 MB; larger files require a separately deployed Local Bot API server. [File documentation](https://core.telegram.org/bots/api#getfile)

Keep Tiance running; minimizing to the tray is fine. Automatic wake after quitting is not implemented.
