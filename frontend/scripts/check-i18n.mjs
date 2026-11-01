import ts from 'typescript'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const dictionary = fs.readFileSync(path.join(root, 'src/locales/en.ts'), 'utf8')
const compiled = ts.transpileModule(dictionary, { compilerOptions: { module: ts.ModuleKind.ESNext } }).outputText
const { en } = await import('data:text/javascript;base64,' + Buffer.from(compiled).toString('base64'))
const missing = new Set()
const keys = new Set()
for (const file of ['main.tsx', 'demo.ts', 'LanguageMenu.tsx']) {
  const source = ts.createSourceFile(file, fs.readFileSync(path.join(root, 'src', file), 'utf8'), ts.ScriptTarget.Latest, true)
  function inspect(node) {
    if (ts.isCallExpression(node) && node.expression.getText(source) === 't') {
      function key(child) {
        if (ts.isConditionalExpression(child)) { key(child.whenTrue); key(child.whenFalse); return }
        if (ts.isStringLiteral(child)) {
          keys.add(child.text)
          if (!(child.text in en)) missing.add(child.text)
        } else ts.forEachChild(child, key)
      }
      if (node.arguments[0]) key(node.arguments[0])
    }
    if (ts.isJsxText(node) && /[\u3400-\u9fff]/u.test(node.text)) missing.add('Untranslated JSX: ' + node.text)
    ts.forEachChild(node, inspect)
  }
  inspect(source)
}
for (const [source, target] of Object.entries(en)) {
  const params = value => [...value.matchAll(/\{\d+\}/g)].map(x => x[0]).sort().join(',')
  if (params(source) !== params(target)) missing.add('Interpolation mismatch: ' + source)
}
if (missing.size) {
  console.error([...missing].join('\n'))
  process.exit(1)
}
console.log(`Translation check passed: ${keys.size} UI strings; ${Object.keys(en).length} translations.`)
