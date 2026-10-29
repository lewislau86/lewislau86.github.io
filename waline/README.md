# Waline 评论服务

Vercel 项目的 Root Directory 设为本目录 `waline`。服务端使用 Waline 官方的 `@waline/vercel`，数据库使用 Neon PostgreSQL。

1. 在 Vercel 导入本仓库，新建独立项目，Root Directory 选择 `waline`。
2. 在 Vercel Storage 关联 Neon 数据库；按 [Waline 官方部署说明](https://waline.js.org/guide/deploy/vercel.html) 执行 `waline.pgsql` 建表脚本。数据库连接信息只保存在 Vercel 的环境变量中。
3. `vercel.json` 已开启评论审核和 60 秒的 IP 发帖间隔，并把请求来源限定为本站与评论服务域名。保持这些设置后部署服务。
4. 访问 `<Waline 服务地址>/ui/register` 创建首个管理员账号，然后在后台审核留言。管理员账号由站长自己创建，密码不要写入仓库。
5. 将服务地址（例如 `https://...vercel.app`）写入本站 GitHub 仓库变量 `WALINE_SERVER_URL`；本地预览时可设置 `VITE_WALINE_SERVER_URL`。GitHub Pages 构建会将它传给 VitePress。

站内评论允许不登录、昵称留空。旧的 giscus 评论仍保存在 GitHub Discussions，Waline 不会自动导入这些内容。
