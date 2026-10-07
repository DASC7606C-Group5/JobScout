import { readFile, writeFile } from 'node:fs/promises'

import openapiTS, { astToString } from 'openapi-typescript'

const spec = JSON.parse(await readFile('../.tools/openapi.json', 'utf8'))
await writeFile(
  '../src/api/openapi.gen.ts',
  astToString(await openapiTS(spec, { defaultNonNullable: false })),
)
const names = Object.keys(spec.components.schemas)
const identifier = (name: string) =>
  name.replace(/[-_](\w)/g, (_, letter: string) => letter.toUpperCase())
await writeFile(
  '../src/api/types.gen.ts',
  `// Generated from the backend OpenAPI schema.\nimport type { components } from './openapi.gen'\n` +
    names
      .map(
        (name) =>
          `export type ${identifier(name)} = components['schemas'][${JSON.stringify(name)}]`,
      )
      .join('\n') +
    '\n',
)
