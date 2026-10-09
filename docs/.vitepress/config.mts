import { defineConfig } from 'vitepress'
import tinyllmSidebar from './tinyllm-sidebar.json'

export default defineConfig({
  lang: 'zh-CN',
  title: 'Lewis 的知识库',
  description: '按主题整理技术研究、项目文档与学习笔记。',
  base: '/',
  markdown: { math: true },
  sitemap: { hostname: 'https://lewislau86.github.io' },
  head: [['link', { rel: 'icon', type: 'image/svg+xml', href: '/favicon.svg' }]],
  themeConfig: {
    logo: '/favicon.svg',
    nav: [
      { text: '文档', link: '/' },
      { text: 'TinyLLM', link: '/tinyllm/' },
      { text: '关于', link: '/about' }
    ],
    sidebar: {
      '/tinyllm/': tinyllmSidebar,
      '/': [
      {
        text: '知识库',
        items: [
          { text: '文档首页', link: '/' },
          { text: 'TinyLLM 教程', link: '/tinyllm/' },
          { text: '关于', link: '/about' }
        ]
      },
      {
        text: '使用指南',
        collapsed: false,
        items: [
          { text: '新增与发布文档', link: '/guide/writing' },
          { text: 'Markdown 写作示例', link: '/guide/markdown' }
        ]
      }
      ]
    },
    notFound: {
      title: '文档未找到',
      quote: '这篇文档可能已移动或尚未创建，请返回首页查找。',
      linkLabel: '返回文档首页',
      linkText: '返回文档首页'
    },
    outline: { level: [2, 3], label: '本页目录' },
    docFooter: { prev: '上一篇', next: '下一篇' },
    sidebarMenuLabel: '文档目录',
    returnToTopLabel: '返回顶部',
    darkModeSwitchLabel: '外观',
    lightModeSwitchTitle: '切换为浅色模式',
    darkModeSwitchTitle: '切换为深色模式',
    skipToContentLabel: '跳转到正文',
    editLink: {
      pattern: ({ relativePath }) => relativePath.startsWith('tinyllm/')
        ? `https://github.com/lewislau86/tinyllm/edit/main/${relativePath.slice('tinyllm/'.length).replace(/^index\.md$/, 'README.md')}`
        : `https://github.com/lewislau86/lewislau86.github.io/edit/master/docs/${relativePath}`,
      text: '在 GitHub 上编辑此页'
    },
    socialLinks: [{ icon: 'github', link: 'https://github.com/lewislau86/lewislau86.github.io' }],
    search: {
      provider: 'local',
      options: {
        locales: {
          root: {
            translations: {
              button: { buttonText: '搜索文档', buttonAriaLabel: '搜索文档' },
              modal: {
                displayDetails: '显示详细内容',
                resetButtonTitle: '清除搜索',
                backButtonTitle: '关闭搜索',
                noResultsText: '没有找到相关内容',
                footer: { selectText: '选择', navigateText: '切换', closeText: '关闭' }
              }
            }
          }
        }
      }
    }
  }
})
