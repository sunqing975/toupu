import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import test from "node:test"
import ts from "typescript"
const source = readFileSync(new URL("../src/components/Dialog.tsx", import.meta.url), "utf8")
const js = ts.transpileModule(source, {compilerOptions: {target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX}}).outputText
function harness() {
  const refs = []; let cursor = 0; const effects = []
  const react = {useRef: value => refs[cursor++] ?? (refs[cursor-1] = {current:value}), useEffect: fn => effects.push(fn)}
  const exports = {}
  const require = name => name === "react" ? react : name === "lucide-react" ? {X:()=>null} : {jsx:(type,props)=>({type,props}), jsxs:(type,props)=>({type,props})}
  new Function("require","exports",js)(require,exports)
  return {render(open,onClose) {cursor=0;effects.length=0;const tree=exports.Dialog({open,title:"test",onClose,children:null});return {tree,effects:[...effects],ref:refs[0]}}}
}
test("prop-driven native close cannot dismiss switched market dialog", () => {
  const h=harness();let dismissed=0
  let r=h.render(true,()=>dismissed++)
  const native={open:false,showModal(){this.open=true},close(){this.open=false}}
  r.ref.current=native;r.effects.forEach(f=>f());assert.equal(native.open,true)
  r=h.render(false,()=>dismissed++);r.effects.forEach(f=>f());r.tree.props.onClose()
  assert.equal(dismissed,0)
})
test("user close still dismisses an open controlled dialog", () => {
  const h=harness();let dismissed=0;const r=h.render(true,()=>dismissed++)
  r.ref.current={open:false};r.tree.props.onClose();assert.equal(dismissed,1)
})
