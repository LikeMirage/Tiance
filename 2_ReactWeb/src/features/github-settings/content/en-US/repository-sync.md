# Repositories and Synchronization

## Three repository purposes

| Type | Purpose | Where to use it |
| --- | --- | --- |
| Private online market | Browse and install individual items | Each collection's online market |
| Collection sync repository | Back up and synchronize an entire collection | Each collection's Cloud Sync board |
| Standard Git repository | Maintain commits, branches, and history for one regular project | Git and GitHub tools |

They can share one GitHub sign-in, but their repository contracts and interfaces are different.

## Create a first synchronization repository

1. Complete sign-in and full authorization.
2. Ask AI to create a private repository, or create an empty one on GitHub.
3. If the App uses `Only select repositories`, add the new repository to its installation scope.
4. Open the target collection's online or Cloud Sync board and bind the repository.
5. Preview the change list before the first push.

One repository per collection is recommended for clarity.

## Safe synchronization

Pull: `Select repository → Preview pull → Review additions, updates, and deletions → Confirm`

Push: `Select repository → Preview push → Review additions, updates, and deletions → Confirm`

Preview does not modify local or remote content. If either side changes afterward, create a new preview before execution.

Use Cloud Sync for a whole collection, Git tools for the current regular project, and a market source when installing individual items from a private repository.
