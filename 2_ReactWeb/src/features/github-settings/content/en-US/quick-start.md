# Quick Start

## 0. Confirm network access to GitHub

Sign-in and repository operations require access to `github.com`, `api.github.com`, and GitHub's device verification page. Open [GitHub](https://github.com/) in your browser first. If it cannot be reached, check the current network, DNS, system proxy, firewall, or organization policy. You can also configure an approved proxy in Tiance Network Settings and test again.

Do not repeatedly start sign-in while the network is unavailable. Device codes expire; start a new sign-in after connectivity is restored.

## 1. Install the Tiance Desktop GitHub App

Open the [Tiance Desktop installation page](https://github.com/apps/tiance-desktop/installations/new). Regular users **install the existing App** and do not need to create a GitHub App.

## 2. Choose a personal account or organization

- First-time users should install it on their personal account.
- Organizations may require administrator approval. A `Request` button does not indicate a Tiance error.

## 3. Grant sufficient repository scope and permissions

New users should choose **All repositories**. Current and future repositories will then work without repeatedly changing the installation.

You can install and sign in even when the account has no repositories. Afterward, ask Tiance AI to create the first repository; with **All repositories**, it enters the authorized scope automatically.

The installation should grant these repository permissions:

| Permission | Level | Purpose |
| --- | --- | --- |
| Metadata | Read | Identify repositories |
| Contents | Read and write | Files, branches, tags, and releases |
| Administration | Read and write | Create, update, fork, or delete repositories |
| Pull requests | Read and write | Create, review, and merge PRs |
| Issues | Read and write | Issues, comments, and labels |
| Actions | Read and write | View, run, rerun, or cancel workflows |
| Workflows | Read and write | Update workflow files |

Accept any requested permission update before continuing. Read-only access is insufficient for publishing, synchronization, and repository creation.

Experienced users may choose **Only select repositories** and maintain the scope themselves.

## 4. Finish device sign-in in Tiance

1. Open the “Sign in” tab on this page.
2. Select “Sign in to GitHub”.
3. Enter the code shown by Tiance on GitHub's official device page.
4. Approve access and return to Tiance; the page updates automatically.

Do not send the device code to AI. Tiance stores the resulting authorization securely on this computer.

## 5. Verify the setup

On the “Sign in” tab, confirm that:

1. The displayed GitHub account is correct.
2. No GitHub App capability is reported missing.
3. The target repository appears as read/write.

Users without a repository only need to verify the account and App capabilities, then ask AI to create the first repository.

## Create your own GitHub App (custom builds)

Regular users can skip this section. Maintainers of a custom Tiance build should:

1. Create an App under GitHub `Settings → Developer settings → GitHub Apps`.
2. Enable **Device Flow**. Tiance does not need a web callback or Client Secret.
3. Disable Webhooks if they are not otherwise required.
4. Configure the repository permissions listed above.
5. Install the App on an account; **All repositories** is the easiest starting point.
6. Copy the **Client ID** and add it to `1_PythonServer/.env` in the source workspace:

```text
GITHUB_CLIENT_ID=your Client ID
```

Restart Tiance. Never commit a Client Secret, access token, or other credential.
