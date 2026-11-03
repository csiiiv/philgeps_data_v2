// Copies the filled OCDS mapping template workbooks from OCDS_ETL into
// public/downloads/ so the built site can serve them as static downloads.
// Runs automatically before every build (see package.json "prebuild").
// Tolerates missing artifacts with a warning so frontend work does not
// depend on running the OCDS pipeline first.

import { copyFileSync, mkdirSync, existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const appDir = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const sourceDir = path.resolve(appDir, '../../../OCDS_ETL/artifacts/filled_templates');
const targetDir = path.resolve(appDir, 'public/downloads');

const FILES = [
  'UNIFIED_exports_OCDS_Field_Mapping_FILLED.xlsx',
  'UNIFIED_exports_OCDS_Codelist_Mapping_FILLED.xlsx',
];

mkdirSync(targetDir, { recursive: true });

let copied = 0;
for (const name of FILES) {
  const src = path.join(sourceDir, name);
  if (!existsSync(src)) {
    console.warn(`[copy-filled-templates] missing (skipped): ${src}`);
    continue;
  }
  copyFileSync(src, path.join(targetDir, name));
  copied += 1;
}
console.log(`[copy-filled-templates] copied ${copied}/${FILES.length} workbooks to public/downloads/`);
