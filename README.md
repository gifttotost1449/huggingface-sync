# Hugging Face Spaces Auto Sync

[![Sync Report](https://img.shields.io/badge/%E6%9F%A5%E7%9C%8B%E6%9C%80%E6%96%B0%E5%90%8C%E6%AD%A5%E6%8A%A5%E5%91%8A-Open-1f7a8c?style=for-the-badge)](reports/latest.md)

This repository syncs all Hugging Face Spaces into GitHub via Actions.

## Setup

1. Add a secret in your repo: `Settings -> Secrets and variables -> Actions` and create `HF_ACCOUNTS_JSON`.
2. Example payload (multi-account, one folder per account):

```json
[
  {
    "username": "your-hf-username",
    "token": "hf_xxx"
  },
  {
    "username": "your-org-name",
    "token": "hf_xxx",
    "folder": "your-org-name"
  }
]
```

Notes:
- The token needs read access to the Spaces you want to sync (including private Spaces).
- To sync org Spaces, set `username` to the org name and optionally set `folder` for the target directory.

## Layout

```
spaces/
  <account>/
    <space>/
      ... space files ...
reports/
  latest.md
```

## Schedule

Runs daily at 03:00 UTC. You can also trigger `Sync Hugging Face Spaces` manually.
