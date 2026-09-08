import { describe, expect, it } from 'vitest'
import { existsSync, readdirSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const sourceRoot = resolve(import.meta.dirname)

function sourceFiles(directory) {
  if (!existsSync(directory)) return []
  return readdirSync(directory, { recursive: true })
    .filter(name => /\.(js|vue)$/.test(name))
    .map(name => resolve(directory, name))
}

describe('frontend module boundaries', () => {
  it('does not restore source files under legacy top-level directories', () => {
    for (const directory of ['api', 'stores', 'views', 'components']) {
      expect(sourceFiles(resolve(sourceRoot, directory)), directory).toEqual([])
    }
  })

  it('keeps shared modules independent from business features', () => {
    for (const file of sourceFiles(resolve(sourceRoot, 'shared'))) {
      expect(readFileSync(file, 'utf8'), file).not.toMatch(/@\/features\/(screening|quality)/)
    }
  })
})
