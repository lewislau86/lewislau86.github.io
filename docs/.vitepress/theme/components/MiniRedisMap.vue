<script setup lang="ts">
import { computed, ref } from 'vue'
import { useSvgLinkPrefetchFix } from './svgLinks'
import { withBase } from 'vitepress'

// mini-redis 全书架构图。每章开头用 <MiniRedisMap active="tokio-server" /> 高亮本章涉及的部件；
// 不传 active 时显示完整地图（总览页、第 0 章）。章节与部件的对应关系只在 highlight 里维护。
const props = defineProps<{ active?: string }>()

type Node = { id: string; label: string; sub?: string; ch: number; slug: string; x: number; y: number; w: number; h: number }
const nodes: Node[] = [
  { id: 'cli', label: 'CLI / 你的程序', ch: 1, slug: 'first-run', x: 30, y: 70, w: 190, h: 40 },
  { id: 'client', label: 'Client', sub: 'Buffered / Blocking', ch: 9, slug: 'clients', x: 30, y: 135, w: 190, h: 48 },
  { id: 'connc', label: 'Connection', sub: '命令 → Frame → 字节', ch: 4, slug: 'resp-and-connection', x: 30, y: 208, w: 190, h: 48 },
  { id: 'serverrun', label: 'server::run', sub: '运行时、监听、关闭信号', ch: 5, slug: 'tokio-server', x: 330, y: 62, w: 200, h: 48 },
  { id: 'listener', label: 'Listener', sub: '取配额 → accept → spawn', ch: 5, slug: 'tokio-server', x: 330, y: 130, w: 200, h: 48 },
  { id: 'shutdown', label: 'Shutdown 通知', sub: 'broadcast + mpsc', ch: 10, slug: 'shutdown-and-tests', x: 560, y: 62, w: 170, h: 48 },
  { id: 'read', label: 'Connection::read_frame', sub: '字节 → Frame', ch: 4, slug: 'resp-and-connection', x: 345, y: 228, w: 230, h: 44 },
  { id: 'cmd', label: 'Command::from_frame', sub: 'Parse → Set / Get …', ch: 3, slug: 'request-path', x: 345, y: 284, w: 230, h: 44 },
  { id: 'apply', label: 'apply', sub: 'Set / Get / Publish / Subscribe', ch: 3, slug: 'request-path', x: 345, y: 340, w: 230, h: 44 },
  { id: 'purge', label: '后台清理任务', sub: 'sleep_until / Notify', ch: 7, slug: 'expiration', x: 600, y: 228, w: 130, h: 48 },
  { id: 'entries', label: 'entries', sub: 'HashMap 键值', ch: 6, slug: 'shared-storage', x: 345, y: 448, w: 120, h: 44 },
  { id: 'expirations', label: 'expirations', sub: 'BTreeSet 过期索引', ch: 7, slug: 'expiration', x: 608, y: 448, w: 122, h: 44 },
  { id: 'pubsub', label: 'pub_sub', sub: '频道 → broadcast', ch: 8, slug: 'pubsub', x: 477, y: 448, w: 120, h: 44 }
]

const highlight: Record<string, string[]> = {
  'first-run': ['cli', 'client', 'serverrun'],
  'rust-foundations': ['cmd', 'entries'],
  'request-path': ['client', 'connc', 'tcp', 'read', 'cmd', 'apply', 'entries'],
  'resp-and-connection': ['connc', 'tcp', 'read'],
  'tokio-server': ['serverrun', 'listener', 'handler'],
  'shared-storage': ['db', 'entries'],
  'expiration': ['expirations', 'purge'],
  'pubsub': ['pubsub', 'apply'],
  'clients': ['client', 'connc'],
  'shutdown-and-tests': ['serverrun', 'shutdown', 'handler'],
  'ttl-test-debugging': ['expirations', 'purge', 'read']
}
const on = computed(() => new Set(highlight[props.active ?? ''] ?? []))
const isOn = (id: string) => on.value.has(id)
const href = (slug: string) => withBase(`/mini-redis/${slug}`)
const svgRoot = ref<SVGSVGElement | null>(null)
useSvgLinkPrefetchFix(svgRoot)
</script>

<template>
  <figure :class="['mr-map', { compact: !!active }]">
    <svg ref="svgRoot" viewBox="0 0 760 530" role="img" aria-label="mini-redis 架构图：客户端进程中的 Client 与 Connection 通过 TCP 字节流连接服务端；服务端由 server::run 启动 Listener，为每个连接创建 Handler 任务，依次读帧、解析命令、执行 apply，访问共享的 Db；后台任务清理过期键，Shutdown 负责停机通知">
      <defs>
        <marker id="mr-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M0,0 L10,5 L0,10 z" class="mr-arrowhead" />
        </marker>
      </defs>

      <!-- 进程边框 -->
      <rect x="12" y="30" width="226" height="250" rx="12" class="mr-process" />
      <text x="24" y="52" class="mr-group">客户端进程</text>
      <rect x="312" y="30" width="436" height="490" rx="12" class="mr-process" />
      <text x="324" y="52" class="mr-group">服务端进程</text>

      <!-- Handler 与 Db 容器 -->
      <a :href="href('tokio-server')">
        <rect x="333" y="200" width="254" height="196" rx="10" :class="['mr-container', { active: isOn('handler') }]" />
        <text x="345" y="219" class="mr-container-label">Handler 任务（每个连接一个）· 第 5 章</text>
      </a>
      <a :href="href('shared-storage')">
        <rect x="333" y="414" width="405" height="94" rx="10" :class="['mr-container', { active: isOn('db') }]" />
        <text x="345" y="434" class="mr-container-label">Db = Arc&lt;Shared&gt;，所有任务共享一份 · 第 6 章</text>
      </a>

      <!-- TCP -->
      <a :href="href('resp-and-connection')">
        <path d="M222,222 H343" :class="['mr-tcp', { active: isOn('tcp') }]" marker-end="url(#mr-arrow)" />
        <path d="M343,262 H222" :class="['mr-tcp', { active: isOn('tcp') }]" marker-end="url(#mr-arrow)" />
        <text x="282" y="212" text-anchor="middle" class="mr-edge-label">请求</text>
        <text x="282" y="280" text-anchor="middle" class="mr-edge-label">响应</text>
        <text x="282" y="246" text-anchor="middle" :class="['mr-tcp-label', { active: isOn('tcp') }]">TCP·RESP</text>
      </a>

      <!-- 客户端内部 -->
      <line x1="125" y1="110" x2="125" y2="133" class="mr-edge" marker-end="url(#mr-arrow)" />
      <line x1="125" y1="183" x2="125" y2="206" class="mr-edge" marker-end="url(#mr-arrow)" />

      <!-- 服务端内部 -->
      <line x1="430" y1="110" x2="430" y2="128" class="mr-edge" marker-end="url(#mr-arrow)" />
      <line x1="430" y1="178" x2="430" y2="198" class="mr-edge" marker-end="url(#mr-arrow)" />
      <line x1="460" y1="272" x2="460" y2="282" class="mr-edge" marker-end="url(#mr-arrow)" />
      <line x1="460" y1="328" x2="460" y2="338" class="mr-edge" marker-end="url(#mr-arrow)" />
      <line x1="405" y1="384" x2="405" y2="446" class="mr-edge" marker-end="url(#mr-arrow)" />
      <path d="M530,86 H558" class="mr-edge" marker-end="url(#mr-arrow)" />
      <path d="M645,110 V160 H560 V198" class="mr-dashed" marker-end="url(#mr-arrow)" />
      <text x="650" y="150" class="mr-edge-label">停机时通知</text>
      <path d="M665,276 V446" class="mr-dashed" marker-end="url(#mr-arrow)" />
      <text x="671" y="360" class="mr-edge-label">删除到期键</text>
      <path d="M537,384 V446" class="mr-dashed" marker-end="url(#mr-arrow)" />
      <text x="543" y="404" class="mr-edge-label">订阅</text>

      <a v-for="n in nodes" :key="n.id" :href="href(n.slug)">
        <rect :x="n.x" :y="n.y" :width="n.w" :height="n.h" rx="8" :class="['mr-node', { active: isOn(n.id) }]" />
        <text :x="n.x + n.w / 2" :y="n.sub ? n.y + n.h / 2 - 5 : n.y + n.h / 2 + 1" text-anchor="middle" dominant-baseline="middle" class="mr-label">{{ n.label }}</text>
        <text v-if="n.sub" :x="n.x + n.w / 2" :y="n.y + n.h / 2 + 12" text-anchor="middle" dominant-baseline="middle" class="mr-sub">{{ n.sub }}</text>
        <text :x="n.x + n.w - 5" :y="n.y + 11" text-anchor="end" class="mr-ch">{{ n.ch }}</text>
      </a>
    </svg>
    <figcaption>
      mini-redis 全书地图。<span v-if="on.size"><span class="mr-key">高亮</span>是本章讲解的部件；</span>实线箭头是同一任务内的调用，虚线是跨任务的通知或消息；右上角数字是主讲章节，点击部件可跳转。
    </figcaption>
  </figure>
</template>

<style scoped>
.mr-map { margin: 1.25rem 0 1.75rem; }
.mr-map a, .mr-map a:hover { text-decoration: none; }
.mr-map svg { width: 100%; max-width: 720px; height: auto; display: block; margin: 0 auto; font-family: var(--vp-font-family-base); }
.mr-map.compact svg { max-width: 600px; }
.mr-map figcaption { font-size: 0.85rem; color: var(--vp-c-text-2); text-align: center; margin-top: 0.5rem; line-height: 1.6; }
.mr-process { fill: none; stroke: var(--vp-c-divider); stroke-width: 1.5; }
.mr-group { font-size: 13px; font-weight: 600; fill: var(--vp-c-text-2); }
.mr-container { fill: none; stroke: var(--vp-c-text-3); stroke-width: 1.2; stroke-dasharray: 6 4; }
.mr-container.active { stroke: var(--vp-c-brand-1); stroke-width: 2.4; stroke-dasharray: none; fill: var(--vp-c-brand-soft); }
.mr-container-label { font-size: 11.5px; fill: var(--vp-c-text-2); }
.mr-node { fill: var(--vp-c-bg-soft); stroke: var(--vp-c-text-3); stroke-width: 1.2; transition: fill .15s; }
.mr-node.active { fill: var(--vp-c-brand-soft); stroke: var(--vp-c-brand-1); stroke-width: 2.4; }
a:hover .mr-node { fill: var(--vp-c-default-soft); }
a:hover .mr-node.active { fill: var(--vp-c-brand-soft); }
.mr-label { font-size: 13.5px; font-weight: 600; fill: var(--vp-c-text-1); pointer-events: none; }
.mr-sub { font-size: 11px; fill: var(--vp-c-text-2); pointer-events: none; }
.mr-ch { font-size: 10px; fill: var(--vp-c-text-3); pointer-events: none; }
.mr-edge { stroke: var(--vp-c-text-2); stroke-width: 1.4; fill: none; }
.mr-dashed { stroke: var(--vp-c-text-3); stroke-width: 1.4; fill: none; stroke-dasharray: 4 3; }
.mr-arrowhead { fill: var(--vp-c-text-2); }
.mr-tcp { stroke: var(--vp-c-text-2); stroke-width: 2.2; fill: none; }
.mr-tcp.active { stroke: var(--vp-c-brand-1); stroke-width: 3.2; }
.mr-tcp-label { font-size: 11.5px; font-weight: 600; fill: var(--vp-c-text-2); }
.mr-tcp-label.active { fill: var(--vp-c-brand-1); }
.mr-edge-label { font-size: 10.5px; fill: var(--vp-c-text-3); }
.mr-key { background: var(--vp-c-brand-soft); border: 1.5px solid var(--vp-c-brand-1); border-radius: 4px; padding: 0 4px; }
</style>
