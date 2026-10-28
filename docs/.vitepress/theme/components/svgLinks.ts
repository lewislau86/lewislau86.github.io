import { onMounted, onUpdated, type Ref } from 'vue'

// VitePress 会对页面里所有 <a> 做链接预取，并读取元素的 pathname；
// SVG 里的 <a> 没有 pathname 属性，预取时会在控制台报错。这里给它们补上 pathname。
export function useSvgLinkPrefetchFix(root: Ref<SVGSVGElement | null>) {
  const patch = () => {
    root.value?.querySelectorAll('a').forEach((a) => {
      const href = (a as unknown as SVGAElement).href
      const url = new URL(href instanceof SVGAnimatedString ? href.animVal : String(href), a.baseURI)
      Object.defineProperty(a, 'pathname', { value: url.pathname, configurable: true })
    })
  }
  onMounted(patch)
  onUpdated(patch)
}
