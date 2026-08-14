# Capabilities and Permissions

## What unified sign-in enables

- Create, inspect, update, fork, or delete GitHub repositories.
- Commit, push, pull, and manage branches and tags.
- Work with pull requests, issues, releases, and Actions.
- Read authorized private repositories as online markets.
- Synchronize project, knowledge, experience, role, theme, tool, or provider collections with private repositories.

Local Git operations and reads from public repositories should not require GitHub sign-in. Authorization is needed for private resources and GitHub writes.

## Effective access is the intersection of three layers

| Layer | Meaning |
| --- | --- |
| GitHub account access | What your account can do in the repository |
| GitHub App permissions | Whether Tiance Desktop may perform contents, PR, issue, or Actions operations |
| App repository scope | Whether the repository is included in the App installation |

All three layers must allow writing before Tiance can publish or synchronize changes.

## Recommended setup for new users

- Install on a personal account.
- Choose **All repositories**.
- Accept all requested repository permissions.
- Verify that the Tiance page shows complete capabilities and read/write repositories.

This is suitable for a new GitHub account without sensitive repositories. The scope can be restricted later.

## Credentials and safety

Prefer unified sign-in. Do not send GitHub passwords, tokens, or device codes to AI. Credentials are stored in dedicated local secret data, not in projects, tool parameters, or ordinary logs.

Signing out of Tiance clears this computer's credential; it does not delete repositories or uninstall the GitHub App.
