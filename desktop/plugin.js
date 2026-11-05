import {
  host, useValue, useQuery, useQueryClient, useGatewayActivationEpoch,
  gatewayActivationEpoch, PANES_AREA, STATUSBAR_AREAS, StatusDot,
} from '@hermes/plugin-sdk'
import { useState } from 'react'
import { jsx, jsxs } from 'react/jsx-runtime'

export function readScope() {
  const key = host.state.focusedStoredSessionId.get()
  const owner = host.state.focusedSessionOwner.get()
  const connection = host.state.connectionId.get()
  const profile = host.state.profile.get()
  const valid = Boolean(owner && owner.connectionId === connection && owner.profile === profile)
  const epoch = gatewayActivationEpoch()
  return { key, connection, profile, epoch, valid, token: JSON.stringify([connection, profile, epoch, key]) }
}

function useScope() {
  useValue(host.state.focusedStoredSessionId)
  useValue(host.state.focusedSessionOwner)
  useValue(host.state.connectionId)
  useValue(host.state.profile)
  useGatewayActivationEpoch()
  return readScope()
}

function current(scope) {
  const now = readScope()
  return scope.valid && now.valid && scope.token === now.token
}

async function rest(ctx, scope, path, opts) {
  if (!current(scope)) throw new Error('The chat or gateway changed; try again.')
  const result = await ctx.rest(path, opts)
  if (!current(scope)) throw new Error('The chat or gateway changed; try again.')
  return result
}

function queryKey(scope, resource) {
  return ['dirtside', scope.connection, scope.profile, scope.epoch, scope.key, resource]
}

function useTarget(ctx, scope) {
  return useQuery({
    queryKey: queryKey(scope, 'target'),
    queryFn: () => rest(ctx, scope, `/sessions/${encodeURIComponent(scope.key)}/target`),
    enabled: Boolean(scope.key && scope.valid), refetchInterval: 2000, retry: false,
  })
}

const small = { color: 'var(--ui-text-secondary)', fontSize: '0.8rem' }
const card = { borderTop: '1px solid var(--ui-stroke-secondary)', padding: '10px 0' }
const button = { border: '1px solid var(--ui-stroke-secondary)', borderRadius: 4, padding: '2px 8px' }
const when = seconds => seconds == null ? 'never' : new Date(seconds * 1000).toLocaleString()

export function DirtsidePane({ ctx }) {
  const scope = useScope()
  const visible = useValue(host.paneVisibility('dirtside:pane'))
  const client = useQueryClient()
  const [notice, setNotice] = useState(null)
  const target = useTarget(ctx, scope)
  const devices = useQuery({
    queryKey: queryKey(scope, 'devices'), queryFn: () => rest(ctx, scope, '/devices'),
    enabled: visible && scope.valid, refetchInterval: visible ? 2000 : false, retry: false,
  })
  const requests = useQuery({
    queryKey: queryKey(scope, 'requests'),
    queryFn: () => rest(ctx, scope, '/requests' + (scope.key ? `?session_key=${encodeURIComponent(scope.key)}` : '')),
    enabled: visible && scope.valid, refetchInterval: visible ? 2000 : false, retry: false,
  })
  const state = notice?.scope === scope.token ? notice : null
  const rows = !scope.valid || devices.isError ? [] : devices.data ?? []
  const selected = !scope.valid || target.isError ? '' : target.data?.target ?? ''
  const devicesById = new Map(rows.map(device => [device.id, device.name]))

  async function act(path, options, message) {
    if (!current(scope)) return
    setNotice({ scope: scope.token, pending: true })
    try {
      await rest(ctx, scope, path, options)
      await client.invalidateQueries({ queryKey: queryKey(scope).slice(0, -1) })
      if (current(scope)) setNotice({ scope: scope.token, message })
    } catch (error) {
      if (current(scope)) setNotice({ scope: scope.token, error: String(error.message || error) })
    }
  }

  return jsxs('section', {
    'aria-label': 'Dirtside', style: { padding: 12, overflow: 'auto', height: '100%', fontSize: '0.875rem' },
    children: [
      jsx('h2', { children: 'Dirtside' }),
      !scope.valid && jsx('p', { role: 'status', children: "Switch to this chat's gateway and profile to use Dirtside." }),
      jsx('label', { htmlFor: 'dirtside-target', children: 'This conversation runs on' }),
      jsxs('select', {
        id: 'dirtside-target', value: selected,
        disabled: !scope.key || !scope.valid || Boolean(state?.pending),
        style: { ...button, display: 'block', width: '100%', margin: '6px 0' },
        onChange: event => act(`/sessions/${encodeURIComponent(scope.key)}/target`,
          { method: 'PUT', body: { target: event.target.value } },
          'The target changed for this conversation from the next command.'),
        children: [
          jsx('option', { value: '', disabled: true, children: target.isError ? 'Target unavailable' : 'Choose a target' }),
          jsx('option', { value: 'server', children: 'server' }),
          ...rows.map(device => jsx('option', {
            value: device.name, children: `${device.name} (${device.online ? 'online' : 'offline'})`,
          }, device.id)),
        ],
      }),
      !scope.key && jsx('p', { style: small, children: 'Open a saved conversation to choose its target.' }),
      jsx('p', { style: small, children: 'Changes apply from the next command; prompt facts refresh in a new session.' }),
      state?.message && jsx('p', { role: 'status', children: state.message }),
      state?.error && jsx('p', { role: 'alert', children: state.error }),
      ...[target, devices, requests].filter(query => query.isError).map((query, index) =>
        jsx('p', { role: 'alert', children: String(query.error?.message || 'Dirtside backend unavailable.') }, index)),
      jsx('h3', { children: 'Devices' }),
      devices.isPending && visible && jsx('p', { children: 'Loading devices.' }),
      devices.data?.length === 0 && !devices.isError && jsx('p', { children: 'No devices are paired.' }),
      ...rows.map(device => jsxs('article', { style: card, children: [
        jsxs('div', { children: [
          jsx(StatusDot, { tone: device.online ? 'good' : 'muted' }), ' ',
          jsx('strong', { children: device.name }), ` (${device.online ? 'online' : 'offline'})`,
        ] }),
        jsx('div', { style: small, children: device.os }),
        jsx('div', { style: { ...small, overflowWrap: 'anywhere' }, children: device.home }),
        jsx('div', { style: small, children: `Last seen: ${when(device.last_seen)}` }),
        jsx('button', {
          type: 'button', style: button, disabled: Boolean(state?.pending) || !scope.valid,
          'aria-label': `Revoke ${device.name}`,
          onClick: () => act(`/devices/${encodeURIComponent(device.name)}/revoke`, { method: 'POST' },
            `Revoked ${device.name} and cancelled its live requests.`),
          children: 'Revoke',
        }),
      ] }, device.id)),
      jsx('h3', { children: 'Recent requests' }),
      requests.isPending && visible && jsx('p', { children: 'Loading requests.' }),
      requests.data?.length === 0 && !requests.isError && jsx('p', { children: 'No recent requests.' }),
      ...(!scope.valid || requests.isError ? [] : requests.data ?? []).map(request => jsxs('article', { style: card, children: [
        jsx('div', { children: request.preview }),
        jsx('div', { style: small, children: `${devicesById.get(request.device_id) ?? 'unpaired device'}: ${request.state}` }),
        jsx('div', { style: small, children: `Started: ${when(request.created_at)}; exit: ${request.exit_code ?? 'pending'}` }),
        request.reason && jsx('div', { style: small, children: request.reason }),
        request.tail && jsx('pre', {
          'aria-label': 'Live output tail',
          style: { whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', fontSize: '0.75rem' }, children: request.tail,
        }),
      ] }, request.id)),
    ],
  })
}

export function TargetChip({ ctx }) {
  const scope = useScope()
  const target = useTarget(ctx, scope)
  const name = !scope.key ? 'no conversation' : !scope.valid ? 'other gateway'
    : target.isError ? 'target unavailable' : target.data?.target ?? 'loading'
  return jsx('span', { style: small, title: 'Dirtside conversation target', children: `Dirtside: ${name}` })
}

export default {
  id: 'dirtside', name: 'Dirtside', defaultEnabled: false,
  register(ctx) {
    ctx.register({
      id: 'pane', area: PANES_AREA, title: 'Dirtside',
      data: { placement: 'right', width: '320px' }, render: () => jsx(DirtsidePane, { ctx }),
    })
    ctx.register({
      id: 'chip', area: STATUSBAR_AREAS.right, order: 125, render: () => jsx(TargetChip, { ctx }),
    })
  },
}
