// Reproducible CC0 asset import. Run from the repository root.
import { mkdir, writeFile } from 'node:fs/promises'
import { dirname, join } from 'node:path'
const root = 'apps/desktop/public/assets/landscape'
async function download(url, path) {
  const response = await fetch(url)
  if (!response.ok) throw new Error(`${response.status}: ${url}`)
  await mkdir(dirname(path), { recursive: true })
  await writeFile(path, Buffer.from(await response.arrayBuffer()))
}
async function files(id) { return (await fetch(`https://api.polyhaven.com/files/${id}`)).json() }
for (const id of ['grass_ground', 'plaster_grey_04', 'wood_floor']) {
  const asset = await files(id)
  await Promise.all(['Diffuse', 'nor_gl', 'Rough'].map(key => download(asset[key]['1k'].jpg.url, join(root, id, `${key}.jpg`))))
  console.log(`Downloaded ${id}`)
}
if (process.argv.includes('--textures-only')) process.exit(0)
const tree = (await files('island_tree_01')).gltf['1k'].gltf
await download(tree.url, join(root, 'tree-source', 'tree.gltf'))
await Promise.all(Object.entries(tree.include).map(([path, file]) => download(file.url, join(root, 'tree-source', path))))
// glTF export uses a separate opacity mask for foliage.
const source = await files('island_tree_01')
function findAlpha(object) {
  for (const [key, value] of Object.entries(object)) {
    if (key.includes('leaves_alpha_1k') && value.url) return value.url
    if (value && typeof value === 'object') { const found = findAlpha(value); if (found) return found }
  }
}
const alpha = findAlpha(source)
if (alpha) await download(alpha, join(root, 'tree-leaves-alpha.png'))
console.log('Downloaded tree source; optimize before shipping (see landscape/LICENSES.md).')
