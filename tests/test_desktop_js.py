"""Check the uncompiled module and its SDK interactions without Desktop."""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="Node is not installed")


def test_desktop_is_valid_esm():
    result = subprocess.run([NODE, "--input-type=module", "--check"],
                            input=(ROOT / "desktop/plugin.js").read_text(),
                            text=True, capture_output=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr


SDK_CHECK = r"""
import assert from 'node:assert/strict'
import fs from 'node:fs'
import vm from 'node:vm'
const values = {
  focusedSessionId: 'runtime-a', focusedStoredSessionId: 'stored/a',
  focusedSessionOwner: { connectionId: 'local', profile: 'default' },
  connectionId: 'local', profile: 'default',
}
let visible = true, epoch = 1, queries = [], writes = [], invalidations = [], notices = [], failed = false
const state = Object.fromEntries(Object.keys(values).map(key => [key, { get: () => values[key] }]))
const data = {
  target: { target: 'server' },
  devices: [{ id: 'device', name: 'macbook', online: true, os: 'macOS', home: '/home/device', last_seen: 1 }],
  requests: [{ id: 'request', device_id: 'device', preview: 'pwd', state: 'running',
               tail: '<script>not markup</script>', created_at: 1, exit_code: null }],
}
const host = { state, paneVisibility: id => {
  assert.equal(id, 'dirtside:pane')
  return { get: () => visible }
} }
const exports = {
  host, useValue: atom => atom.get(), useGatewayActivationEpoch: () => epoch,
  gatewayActivationEpoch: () => epoch, PANES_AREA: 'panes', STATUSBAR_AREAS: { right: 'statusBar.right' },
  StatusDot: props => ({ dot: props.tone }),
  useQuery: options => { queries.push(options); return { data: data[options.queryKey.at(-1)],
    isError: failed, error: failed ? new Error('Backend disabled') : null } },
  useQueryClient: () => ({ invalidateQueries: async key => invalidations.push(key) }),
}
function synthetic(values) {
  return new vm.SyntheticModule(Object.keys(values), function() {
    for (const [key, value] of Object.entries(values)) this.setExport(key, value)
  })
}
const modules = {
  '@hermes/plugin-sdk': synthetic(exports),
  react: synthetic({ useState: () => [null, value => notices.push(value)] }),
  'react/jsx-runtime': synthetic({ jsx: (type, props) => ({ type, props }), jsxs: (type, props) => ({ type, props }) }),
}
const module = new vm.SourceTextModule(fs.readFileSync(process.argv[2], 'utf8'))
await module.link(name => { assert.ok(modules[name], name); return modules[name] })
await module.evaluate()
const { default: plugin, DirtsidePane, TargetChip, readScope } = module.namespace
let contributions = []
const ctx = { register: c => contributions.push(c), rest: async (path, options) => {
  writes.push({ path, options }); return {}
} }
plugin.register(ctx)
assert.equal(plugin.defaultEnabled, false)
assert.deepEqual(contributions.map(c => c.area), ['panes', 'statusBar.right'])
function nodes(tree) {
  if (Array.isArray(tree)) return tree.flatMap(nodes)
  if (!tree || typeof tree !== 'object') return [tree]
  return [tree, ...nodes(tree.props?.children)]
}
function render() { queries = []; return nodes(DirtsidePane({ ctx })) }
let tree = render()
assert.equal(readScope().key, 'stored/a')
for (const resource of ['devices', 'requests']) {
  const query = queries.find(q => q.queryKey.at(-1) === resource)
  assert.equal(query.enabled, true); assert.equal(query.refetchInterval, 2000)
}
assert.ok(tree.includes('<script>not markup</script>'))
assert.ok(tree.includes('/home/device'))
const select = tree.find(n => n?.type === 'select')
await select.props.onChange({ target: { value: 'macbook' } })
assert.deepEqual(writes[0], { path: '/sessions/stored%2Fa/target',
  options: { method: 'PUT', body: { target: 'macbook' } } })
assert.equal(invalidations.length, 1)
const revoke = tree.find(n => n?.type === 'button')
await revoke.props.onClick()
assert.equal(writes.at(-1).path, '/devices/macbook/revoke')
assert.equal(writes.at(-1).options.method, 'POST')
visible = false
render()
assert.ok(queries.filter(q => ['devices', 'requests'].includes(q.queryKey.at(-1)))
  .every(q => !q.enabled && q.refetchInterval === false))
visible = true
values.focusedStoredSessionId = 'stored-b'
const count = writes.length
await select.props.onChange({ target: { value: 'server' } })
assert.equal(writes.length, count, 'an old picker must not mutate the newly focused chat')
tree = render()
let release
ctx.rest = () => new Promise(resolve => { release = resolve })
const pending = queries.find(q => q.queryKey.at(-1) === 'target').queryFn()
epoch += 1
release({ target: 'macbook' })
await assert.rejects(pending, /chat or gateway changed/)
values.focusedSessionOwner = { connectionId: 'remote', profile: 'default' }
tree = render()
assert.equal(tree.find(n => n?.type === 'select').props.disabled, true)
assert.equal(tree.find(n => n?.type === 'select').props.value, '')
assert.ok(!tree.includes('/home/device'))
assert.ok(queries.every(q => !q.enabled))
assert.ok(TargetChip({ ctx }).props.children.includes('other gateway'))
values.focusedSessionOwner = { connectionId: 'local', profile: 'default' }
tree = render()
ctx.rest = async () => { throw new Error('Write refused') }
await tree.find(n => n?.type === 'select').props.onChange({ target: { value: 'server' } })
assert.equal(notices.at(-1).error, 'Write refused')
tree = render()
ctx.rest = () => new Promise(resolve => { release = resolve })
const staleWrite = tree.find(n => n?.type === 'select').props.onChange({ target: { value: 'server' } })
const noticeCount = notices.length
epoch += 1
release({ target: 'server' })
await staleWrite
assert.equal(notices.length, noticeCount, 'stale writes must not publish a notice in the new scope')
failed = true
tree = render()
assert.ok(tree.includes('Backend disabled'))
assert.ok(!tree.includes('/home/device'))
assert.ok(TargetChip({ ctx }).props.children.includes('target unavailable'))
values.focusedSessionId = null
values.focusedStoredSessionId = null
tree = render()
assert.equal(tree.find(n => n?.type === 'select').props.disabled, true)
console.log('Desktop SDK behavior passed: registration, polling, target, revoke, focus and stale replies.')
"""


def test_desktop_sdk_behavior():
    result = subprocess.run([NODE, "--experimental-vm-modules", "--input-type=module", "-",
                             str(ROOT / "desktop/plugin.js")], input=SDK_CHECK,
                            text=True, capture_output=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Desktop SDK behavior passed" in result.stdout
