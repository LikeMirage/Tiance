# Commands and files

Send these in a private chat with your bot, or choose them from its command menu.

| Command | Action |
| --- | --- |
| `/projects` | Choose a collection, category and project |
| `/sessions` | Choose a main conversation in the current project |
| `/new Phone test` | Create and select a conversation; the title is optional |
| `/newcategory Office` | Create a category in the collection being browsed |
| `/newproject Meeting notes` | Create and select a project in the current specific category |
| `/map` | Show the current collection → categories → projects → main conversations |
| `/model` | Choose a provider, then a model for the target conversation |
| `/history` | Read the target conversation's most recent five user/AI turns |
| `/status` | Show the selected project, conversation, model and running state |
| `/stop` | Pause the selected conversation; wait for confirmation before resending |
| `/files` | List file references waiting to be submitted |
| `/clear` | Clear pending references, keeping downloaded files |
| `/help`, `/start` | Show instructions and navigation buttons |

## Recent history and media

Use **View previous 5 turns** or `/history`. It returns the most recent five turns in chronological order, with user text, reference names/paths, final AI replies and failure/pause status. Running replies are marked incomplete. Long text is split without truncation; thinking and tool execution bodies are not sent. This does not call a model or change the selected conversation. A button on an old reply still reads that reply's conversation.

Voice notes, audio files, ordinary videos and round video messages use the normal file intake. Originals are saved under the target project's `远程收件/Telegram/` directory; uncaptioned files wait for instructions. Unsupported messages and completed download failures do not block later text. An instruction waiting on a failed download is rejected once to avoid processing incomplete files; resend the file if needed, or send another text instruction.

## Switching conversations

Category and project lists include creation and diagram buttons. After clicking a creation button, send the command and name shown in its reply. Choose a specific category before creating a project; “All projects” is not a destination category. Creation follows the desktop rules, including provider creation in the model collection. Provider API settings and models still need configuration on the desktop.

Diagrams cover only the collection being browsed, stop at main conversations, and include empty categories and projects. Larger diagrams are split into original PNG files that can be opened and zoomed. Mobile creation refreshes desktop lists without changing the desktop selection or draft.

Use `/model` or **Switch model** after choosing a conversation. Only enabled providers' available chat models are listed. The change preserves prompts and other settings, and affects the next message, not a task already running. Buttons on an older reply still target the conversation identified in that reply.

Use **Reply to this conversation** below a bot reply, or Telegram's native Reply action on that message. Both select its associated conversation. Child-conversation controls navigate AI children, user branches and the four functional groups recursively. All collections except Settings support conversations.

You can switch while another task runs. Its answer still identifies the original project and conversation. A running target rejects new instructions: pause or wait, then resend.

## Receiving and returning files

Documents, recordings, images and video are saved as original files. Models and tools handle their content. Normal replies return only the final answer, error or pause status; long replies are split, and file paths in text do not automatically upload files.

To get a file back, ask the AI to use the enabled **Telegram file sending tool** with an explicit connection ID, chat ID and local file path. Incoming mobile messages include source IDs at the end. The tool sends to the specified recipient rather than guessing; enable it in the tool collection if necessary.
