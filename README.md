# altare-grab

Altare 免费服务器在线轮询：由 GitHub Actions 定时执行，不需要本地电脑保持开机。

## 工作方式

- 每 30 分钟运行一次（也可在 Actions 页面手动触发）。
- 先查询团队现有服务器，已有实例则直接跳过，不会重复创建。
- 没有实例时向 `us-lax`（洛杉矶）发起创建请求：Ubuntu 24.04、4096 MiB 内存、125% CPU、40960 MiB 磁盘、SSH 密码登录。
- 遇到 `No capacity`（503）、限流（429）、面板繁忙（500）都只记录结果，等待下一轮继续。
- 创建成功后把实例信息写入本次运行的 Summary，并可选推送 PushPlus 微信通知。

## 需要的仓库 Secrets

在 `Settings → Secrets and variables → Actions` 中添加：

| Name | 必填 | 说明 |
| --- | --- | --- |
| `ALTARE_TOKEN` | 是 | Altare CLI 会话令牌（`altr login` 后写入 `%APPDATA%\altr\config.json` 的 token 字段）。API 令牌 `alt_...` 没有创建权限，不能用于此任务。 |
| `SSH_PASSWORD` | 是 | 创建实例时设置的 root 登录密码（至少 10 位）。 |
| `PUSHPLUS_TOKEN` | 否 | PushPlus 推送令牌，留空则不推送。 |

## 手动触发

Actions → `altare-grab` → Run workflow，可在 `location` 里改区域代码（`us-lax` / `fi-hel` / `sg` 等）。

## 本地试跑

```bash
export ALTARE_TOKEN='...'
export SSH_PASSWORD='...'
export LOCATION='us-lax'
python3 grab.py
```
