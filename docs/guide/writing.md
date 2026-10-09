# 新增与发布文档

每篇文档都是一个 Markdown 文件，保存在仓库的 `docs/` 目录中。

## 新建文档

例如，要记录一篇架构设计，可以创建 `docs/projects/architecture.md`：

```md
# 架构设计

简要说明这个项目要解决的问题。

## 背景

记录业务场景与约束。

## 方案

说明模块职责、数据流和主要取舍。

## 验证

记录已经验证的结果，以及尚未验证的部分。
```

一级标题作为文章标题，二级和三级标题会出现在右侧页内目录中。

## 加入左侧目录

打开 `docs/.vitepress/config.mts`，在 `themeConfig.sidebar` 数组中增加一个分组：

```ts
{
  text: '项目文档',
  items: [
    { text: '架构设计', link: '/projects/architecture' }
  ]
}
```

目录中的链接相对于 `docs/`，不需要写 `.md` 后缀。

## 本地预览

在仓库根目录执行：

```sh
npm ci
npm run docs:dev
```

打开终端显示的本地地址。修改 Markdown 文件后，预览页面会自动更新。

发布前可以检查构建结果：

```sh
npm run docs:build
npm run docs:preview
```

## 发布到网站

将修改提交并推送到 `master` 分支，GitHub Actions 会自动构建并部署网站。可以在仓库的 **Actions** 页面查看部署结果。

部署成功后，在 [知识库首页](https://lewislau86.github.io/) 查看更新。

也可以点击每页底部的「在 GitHub 上编辑此页」，直接在浏览器里修改并提交文档。
