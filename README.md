# Hugging Face Spaces 自动同步

[![查看最新同步报告](https://img.shields.io/badge/%E6%9F%A5%E7%9C%8B%E6%9C%80%E6%96%B0%E5%90%8C%E6%AD%A5%E6%8A%A5%E5%91%8A-Open-1f7a8c?style=for-the-badge)](reports/latest.md)

这个仓库通过 GitHub Actions 自动同步 Hugging Face 的 Space 文件到本仓库。

## 使用方法

1. 在仓库中新增密钥：`Settings -> Secrets and variables -> Actions` 创建 `HF_ACCOUNTS_JSON`。
2. 示例（多账号，每个账号一个文件夹）：

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
- If you only have tokens, set `HF_ACCOUNTS_JSON` to a comma-separated list like `hf_xxx,hf_yyy` and usernames will be detected automatically.

## 目录结构

```
spaces/
  <账号>/
    <space>/
      ... space files ...
reports/
  latest.md
```

注意事项：
- Token 需要具备访问目标 Space 的权限（包括私有 Space）。
- 若需要同步组织 Space，可将 `username` 设为组织名，并可用 `folder` 自定义同步目录名。
- 仅提供 token 时，可将 `HF_ACCOUNTS_JSON` 设置为英文逗号分隔的列表，例如 `hf_xxx,hf_yyy`，用户名会自动识别。

## 同步频率

默认每天 UTC 03:00 自动同步，也可以手动触发 `Sync Hugging Face Spaces` 工作流。
