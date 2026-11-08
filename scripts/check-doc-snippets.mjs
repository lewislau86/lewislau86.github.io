// VitePress reads snippet files from disk, including untracked local files.
// Require @/ imports and local Markdown images to survive a fresh Git checkout.
import { execFileSync } from 'node:child_process'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { dirname, join, relative, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const docs = join(root, 'docs')
const tracked = new Set(execFileSync('git', ['ls-files', '-z'], {
  cwd: root, encoding: 'utf8',
}).split('\0'))
// `git add -N` lists paths without staging their contents. Those files still
// disappear from a fresh checkout, so they must not satisfy this check.
for (const path of execFileSync('git', [
  'diff', '--name-only', '--diff-filter=A', '--ita-invisible-in-index', '-z',
], { cwd: root, encoding: 'utf8' }).split('\0')) tracked.delete(path)
const errors = []
const imports = new Set()
const images = new Set()

function checkFile(target, location, kind) {
  let exists = false
  try { exists = statSync(join(root, target)).isFile() } catch (error) {
    if (!['ENOENT', 'ENOTDIR'].includes(error.code)) throw error
  }
  if (!exists) errors.push(`${location}: missing ${kind} file: ${target}`)
  else if (!tracked.has(target)) errors.push(`${location}: untracked ${kind} file: ${target} (include it in the commit)`)
}

function checkDirectory(directory) {
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    const path = join(directory, entry.name)
    if (entry.isDirectory()) {
      if (!['.vitepress', 'public'].includes(entry.name)) checkDirectory(path)
      continue
    }
    if (!entry.name.endsWith('.md')) continue
    let fence
    for (const [index, line] of readFileSync(path, 'utf8').split('\n').entries()) {
      if (fence) {
        if (new RegExp(`^ {0,3}${fence[0]}{${fence.length},}\\s*$`).test(line)) fence = undefined
        continue
      }
      const opening = line.match(/^ {0,3}(`{3,}|~{3,})/)
      if (opening) {
        fence = opening[1]
        continue
      }
      const location = `${relative(root, path)}:${index + 1}`
      const snippet = line.match(/^\s*<<<\s+@\/([^#\s{\[]+)/)
      if (snippet) {
        const target = relative(root, resolve(docs, snippet[1]))
        imports.add(target)
        checkFile(target, location, 'snippet')
      }
      for (const image of line.matchAll(/!\[[^\]]*\]\(\/(?!\/)([^\s)#?]+)(?:[?#][^\s)]*)?\)/g)) {
        const target = relative(root, resolve(docs, 'public', decodeURIComponent(image[1])))
        images.add(target)
        checkFile(target, location, 'image')
      }
    }
  }
}

checkDirectory(docs)
if (errors.length) {
  console.error('Documentation source check failed:\n' + errors.join('\n'))
  process.exit(1)
}
console.log(`Documentation snippets: ${imports.size} files exist and are tracked by Git.`)
console.log(`Documentation images: ${images.size} local files exist and are tracked by Git.`)
