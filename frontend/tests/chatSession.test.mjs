import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import test from "node:test"
import ts from "typescript"

const source = readFileSync(new URL("../src/api/chatSession.ts", import.meta.url), "utf8")
// Strip only the default transport import; each test injects a controlled stream.
const js = ts.transpileModule(source.replace(source.split("\n")[0],
  'const chatApi = { stream: () => { throw new Error("inject transport") } }'), {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
}).outputText
const { createChatSession } = await import("data:text/javascript;base64," + Buffer.from(js).toString("base64"))

function controlled() {
  let send, finish, signal
  const session = createChatSession((payload, onEvent, abortSignal) => {
    send = onEvent; signal = abortSignal
    return new Promise((resolve, reject) => {
      finish = resolve
      signal.addEventListener("abort", () => reject(new Error("aborted")))
    })
  })
  return { session, send: event => send(event), finish: () => finish(), signal: () => signal }
}

test("leaving the page unsubscribes without aborting; return sees live reasoning/tools/body", async () => {
  const c = controlled()
  const unsubscribe = c.session.subscribe(() => {})
  const pending = c.session.start({ question: "hello", agent_id: "agent" })
  c.send({ type: "meta", conversation_id: "conversation" })
  c.send({ type: "content", text: "first" })
  unsubscribe()
  assert.equal(c.signal().aborted, false)
  c.send({ type: "reasoning", text: "checking" })
  c.send({ type: "tool_start", id: "call", name: "lookup", arguments: "{}" })
  c.send({ type: "tool_end", id: "call", result: "data" })
  c.send({ type: "content", text: " second" })
  let updates = 0
  const leaveAgain = c.session.subscribe(() => updates++)
  assert.equal(c.session.getSnapshot().messages[1].content, "first second")
  assert.equal(c.session.getSnapshot().messages[1].reasoning, "checking")
  assert.equal(c.session.getSnapshot().messages[1].tools[0].result, "data")
  assert.equal(c.session.getSnapshot().activeConvId, "conversation")
  c.send({ type: "done" }); c.finish(); await pending
  assert.equal(c.session.getSnapshot().typing, false)
  assert.ok(updates > 0)
  leaveAgain()
})

test("completion with no mounted page remains available on return", async () => {
  const c = controlled()
  const pending = c.session.start({ question: "hello" })
  await c.session.start({ question: "duplicate" })
  assert.equal(c.session.getSnapshot().messages.length, 2)
  c.send({ type: "content", text: "completed elsewhere" })
  c.send({ type: "done" }); c.finish(); await pending
  assert.equal(c.session.getSnapshot().messages[1].content, "completed elsewhere")
  assert.equal(c.session.getSnapshot().typing, false)
})

test("explicit stop aborts and retains partial content and interruption status", async () => {
  const c = controlled()
  const pending = c.session.start({ question: "hello" })
  c.send({ type: "content", text: "partial" })
  c.session.stop(); await pending
  assert.equal(c.signal().aborted, true)
  assert.equal(c.session.getSnapshot().messages[1].content, "partial")
  assert.match(c.session.getSnapshot().messages[1].status, /已停止/)
  assert.equal(c.session.getSnapshot().typing, false)
})
