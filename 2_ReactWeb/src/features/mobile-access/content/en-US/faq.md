# Frequently asked questions

## Connection timeout

Check **Settings → Network settings**. System proxy mode needs an actual system proxy address, not just a running proxy app. PAC scripts are not evaluated; use the proxy app's HTTP address as a custom proxy if needed. Save and retry in Connection.

## A 502 appears but the bot still works

Fetching the settings status and receiving Telegram messages are separate requests. A temporary status-query error clears after a successful refresh. An enable/authorization failure stays visible until another operation. Check Logs for receiving or delivery failures before recreating the bot.

## My account does not appear after /start

Use a private chat with the exact bot shown in settings and enable the connection. The Connection tab refreshes every five seconds. Check logs and networking if it still does not appear. Unapproved users cannot submit tasks.

## Changing credentials

Disable the connection, edit Token or Bot API, then enable again. An empty token field reuses the saved token. A token for another bot selects an independent connection with separate authorization and tasks.

## Webhook or competing receiver

Do not connect the same bot to two receiving programs. If a webhook exists, verify that the old service is no longer needed and remove it there. Tiance does not remove it silently. Stop duplicate polling instances before retrying. [Receiving updates](https://core.telegram.org/bots/api#getupdates)

## Files were not submitted

Check `/status` before sending. Without a selection the file is not saved; select a conversation and resend. Uncaptioned files wait for instructions: inspect `/files` and send a text request. Resend failed downloads if still needed; unrelated text can continue without switching conversations. `/clear` removes references, not files.

## Large recordings fail to download

The default cloud `getFile` limit is 20 MB. A separately deployed, reachable Local Bot API server is required for larger downloads. Tiance does not install one. [Local Bot API](https://core.telegram.org/bots/api#using-a-local-bot-api-server)

## Do desktop messages also return to my phone?

Only tasks submitted from the mobile entry point automatically return results to their originating account. New desktop messages in that conversation do not. Explicit file-tool calls send to the IDs provided to the tool.

## Can I quit Tiance? How long are logs kept?

Keep Tiance and its desktop connection running, or minimize to the tray. Automatic wake is planned, not available.

Logs begin with this version and keep the latest 1,000 events per connection in the local global database. They contain operational metadata, not tokens, message bodies or file content. Older events are not reconstructed. Full conversations and model requests remain in their project records.
