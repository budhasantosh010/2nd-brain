# Runtime Global Brain Vault

This is the **local personal runtime vault**. It is created from the public `vault-template/` but must never be committed to the public product repository.

Human-facing entry points are `HOME.md`, `01 Inbox`, `03 Knowledge`, `04 Projects`, `00 Home/Needs Review.md`, and `99 Archive`. Machine state lives under `.brain/` and should normally stay out of sight.

Original source bytes live under `02 Sources/Raw` and are immutable by policy. Generated SQLite/index/cache/log state under `.brain/` is rebuildable and is not canonical ownership of your knowledge.
