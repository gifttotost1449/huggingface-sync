# Hugging Face Spaces 自动同步

[![查看最新同步报告](https://img.shields.io/badge/%E6%9F%A5%E7%9C%8B%E6%9C%80%E6%96%B0%E5%90%8C%E6%AD%A5%E6%8A%A5%E5%91%8A-Open-1f7a8c?style=for-the-badge)](reports/latest.md)

把 Hugging Face 上的所有 Space 同步到这个 GitHub 仓库，自动按账号与 Space 分文件夹保存。

## 3 步开始

1. 进入仓库 `Settings -> Secrets and variables -> Actions`。
2. 新增密钥：`HF_ACCOUNTS_JSON`。
3. 填入你的 API key（多个 key 用英文逗号分隔）：

```
hf_xxx,hf_yyy
```

## 同步结果长什么样

同步后的路径会是：

```
sync/<账号>/<space>/
```

示例：

```
https://github.com/<GitHub用户名>/<仓库>/sync/<账号>/<space>
```

## 同步频率

每天 UTC 03:00 自动同步，也可以手动触发 `Sync Hugging Face Spaces` 工作流。

## 同步报告内容

- 账号总览与每个 Space 的同步状态
- 变更情况、文件数、大小、耗时、更新时间等细节

## 可选配置

- `SYNC_INCLUDE`：仅同步指定 Space（space 名或 `owner/space`，英文逗号分隔）
- `SYNC_EXCLUDE`：排除指定 Space（space 名或 `owner/space`，英文逗号分隔）
- `SYNC_RETRIES`：失败重试次数（默认 2）
- `SYNC_RETRY_DELAY`：重试初始间隔秒数（默认 2）
- `SYNC_SPACE_SLEEP`：每个 Space 同步后的等待秒数（默认 0）

## 注意事项

- API key 需要有访问对应 Space 的权限（包括私有 Space）。
- 账号名会自动识别，不需要手动填写。
