import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import test from "node:test"
import ts from "typescript"
const source = readFileSync(new URL("../src/api/marketFormat.ts", import.meta.url), "utf8")
const js = ts.transpileModule(source, {compilerOptions: {target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext}}).outputText
const {fmtMoney, fmtNav, fmtQuantity} = await import("data:text/javascript;base64," + Buffer.from(js).toString("base64"))
test("market money uses two decimal places without changing source", () => {
  const source = "25917.162016"
  assert.equal(fmtMoney(source), "25,917.16")
  assert.equal(fmtMoney("-3529.787012"), "-3,529.79")
  assert.equal(fmtMoney("0"), "0.00")
  assert.equal(fmtMoney("-0.000001"), "0.00")
  assert.equal(source, "25917.162016")
})
test("NAVs retain four places and quantities remove six-place noise", () => {
  assert.equal(fmtNav("1.303700"), "1.3037")
  assert.equal(fmtNav("5.887000"), "5.8870")
  assert.equal(fmtQuantity("9257.290000"), "9,257.29")
  assert.equal(fmtQuantity("100.000000"), "100")
  assert.equal(fmtMoney(null), "—")
  assert.equal(fmtNav("NaN"), "—")
})
