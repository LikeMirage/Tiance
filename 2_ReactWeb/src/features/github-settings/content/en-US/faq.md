# Frequently Asked Questions

## Signed in, but no repositories appear

Confirm that Tiance Desktop is installed on the account or organization that owns the repository. Open `Installed GitHub Apps → Tiance Desktop → Configure`, choose `All repositories` or add the repository under `Only select repositories`, save, and refresh Tiance.

## Why is a repository read-only?

At least one of the account access, App permission, or repository scope layers does not allow writes. Confirm the required read/write permissions and accept any updated App permissions.

## GitHub shows `Request`

The organization requires administrator approval. Wait for an owner to approve it or install the App on a personal account first.

## Can I sign in with no repositories?

Yes. Choose `All repositories`, finish sign-in, and ask AI to create the first repository afterward.

## Why does a new repository not appear?

Refresh when using `All repositories`. With `Only select repositories`, add it in the App installation settings first.

## Is signing out the same as uninstalling the App?

No. Signing out only removes this computer's credential. Suspend or uninstall Tiance Desktop from GitHub Installed Apps to revoke App access.

## Should I send a password or token to AI?

No. Use unified sign-in and never put credentials in conversations, project files, or public repositories.

## Sign-in never completes

Confirm authorization in the browser, then verify access to `github.com` and `api.github.com`. If the code expired during a network interruption, cancel and start again after connectivity returns.

## Custom App sign-in fails

Verify Device Flow, the Client ID, App installation, repository permissions, and acceptance of updated permissions. A Client ID is not an App ID or Client Secret.
