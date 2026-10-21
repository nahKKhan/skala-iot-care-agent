// 외부 패키지 없이 실제 화면 스크립트의 상태 전이·중복 실행 방지를 검증한다.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { resolve } = require('node:path');
const { runInNewContext } = require('node:vm');
const html = readFileSync(resolve(__dirname, '../web_chat.html'), 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
const offer = {scenario_revision: 'revision-1', expected_sequence: 0, device_id: 'sensor-02', device_name: '실습실 온습도 센서', action: 'restart_collection', simulated: true};
const successful = {device_id: 'sensor-02', recovery_verified: true,
  before: {telemetry_age_seconds: 600, telemetry_sequence: 0},
  after: {telemetry_age_seconds: 0, telemetry_sequence: 1}};
const response = (payload, status = 200) => ({ok: status >= 200 && status < 300, status, json: async () => payload});

function setup(recover) {
  let state;
  const calls = [];
  const streams = [];
  class FakeEventSource {
    constructor(url) { this.url = url; streams.push(this); }
    close() { this.closed = true; }
    emit(payload) { this.onmessage({data: typeof payload === 'string' ? payload : JSON.stringify(payload)}); }
  }
  runInNewContext(script, {
    Vue: {
      createApp: options => ({mount: () => { state = options.setup(); }}),
      ref: value => ({value}), reactive: value => value, nextTick: async callback => { if (callback) callback(); },
      computed: getter => ({get value() { return getter(); }}),
    },
    fetch: async (url, options) => {
      calls.push({url, options});
      if (url === '/health') return response({llm_backend: 'fake'});
      if (url === '/api/devices') return response({devices: [{device_id: 'sensor-02', name: '실습실 온습도 센서'}]});
      if (url === '/api/maintenance') return response({records: [{id: 'history-1', device_id: 'sensor-02', status: 'needs_visit', summary: '현장 점검 필요'}]});
      if (url === '/api/scenario/reset') return response({ok: true});
      if (url === '/api/recover') return recover(url, options);
      throw new Error('Unexpected URL: ' + url);
    },
    EventSource: FakeEventSource, AbortController, setTimeout, clearTimeout,
  });
  function inspect(recovery = offer, reply = 'sensor-99라는 문장이 있어도 구조화된 대상을 사용합니다.', sources = []) {
    state.input.value = 'sensor-02 점검';
    state.onSubmit();
    streams.at(-1).emit({type: 'FinalAnswer', reply, recovery, sources});
    streams.at(-1).emit('[DONE]');
    return state.log.value.filter(item => item.kind === 'agent').at(-1);
  }
  return {state, calls, inspect};
}

const posts = instance => instance.calls.filter(call => call.url === '/api/recover');

test('uses the server-provided target and displays verified recovery', async () => {
  const ui = setup(async () => response(successful));
  const item = ui.inspect();
  await ui.state.onRecover(item);
  const payload = JSON.parse(posts(ui)[0].options.body);
  assert.equal(payload.device_id, 'sensor-02');
  assert.equal(payload.scenario_revision, 'revision-1');
  assert.equal(payload.expected_sequence, 0);
  assert.equal(typeof payload.request_id, 'string');
  assert.equal(item.recoveryStatus, 'done');
  assert.equal(item.recoveryResult.after.telemetry_sequence, 1);
  assert.equal(ui.state.recovering.value, null);
  assert.equal(ui.state.recoveryButtonLabel(item), '가상 복구 완료');
});

test('blocks double clicks and chat submissions while a recovery is running', async () => {
  let finish;
  const ui = setup(() => new Promise(resolve => { finish = resolve; }));
  const item = ui.inspect();
  const pending = ui.state.onRecover(item);
  assert.equal(item.recoveryStatus, 'running');
  await ui.state.onRecover(item);
  const count = ui.state.log.value.length;
  ui.state.input.value = 'sensor-03 점검';
  ui.state.onSubmit();
  assert.equal(ui.state.log.value.length, count);
  assert.equal(posts(ui).length, 1);
  finish(response(successful));
  await pending;
  await ui.state.onRecover(item);
  assert.equal(posts(ui).length, 1);
  assert.equal(ui.state.recovering.value, null);
});

test('keeps failed, unverified, and rejected recovery outcomes distinct', async () => {
  for (const [payload, status, expected] of [
    [{device_id: 'sensor-02', recovery_verified: false}, 200, 'failed'],
    [{device_id: 'sensor-02', recovery_verified: null, message: '확인 불가'}, 200, 'unknown'],
    [{detail: '현재 수신 지연이 없습니다.'}, 409, 'blocked'],
    [{detail: '응답 시간 초과'}, 504, 'unknown'],
  ]) {
    const ui = setup(async () => response(payload, status));
    const item = ui.inspect();
    await ui.state.onRecover(item);
    assert.equal(item.recoveryStatus, expected);
    assert.equal(ui.state.recovering.value, null);
    assert.notEqual(ui.state.recoveryButtonLabel(item), '가상 복구 완료');
  }
});

test('a lost response never automatically resends the mutation', async () => {
  const ui = setup(async () => { throw new Error('connection lost'); });
  const item = ui.inspect();
  await ui.state.onRecover(item);
  assert.equal(item.recoveryStatus, 'unknown');
  await ui.state.onRecover(item);
  assert.equal(posts(ui).length, 1);
  assert.equal(ui.state.recovering.value, null);
});

test('invalidates older offers for the same device', async () => {
  const ui = setup(async () => response(successful));
  const previous = ui.inspect();
  const current = ui.inspect();
  await ui.state.onRecover(current);
  assert.equal(previous.recoveryStatus, 'superseded');
  await ui.state.onRecover(previous);
  assert.equal(posts(ui).length, 1);
});

test('does not expose recovery controls for a report without an offer', async () => {
  const ui = setup(async () => response(successful));
  const item = ui.inspect(null, '정상 장치');
  assert.equal(item.recovery, undefined);
  await ui.state.onRecover(item);
  assert.equal(posts(ui).length, 0);
});


test('keeps retrieved source excerpts on the answer and loads maintenance history', async () => {
  const ui = setup(async () => response(successful));
  const sources = [{source_id: 'telemetry_delayed#1', title: '수신 지연', text: '근거 문단'}];
  const item = ui.inspect(offer, '점검 결과', sources);
  assert.equal(item.sources[0].source_id, 'telemetry_delayed#1');
  await ui.state.loadMaintenance();
  assert.equal(ui.state.maintenanceRecords.value[0].status, 'needs_visit');
});

test('scenario reset invalidates old offers without deleting maintenance history', async () => {
  const ui = setup(async () => response(successful));
  const item = ui.inspect();
  await ui.state.resetSelected();
  assert.equal(item.recoveryStatus, 'superseded');
  assert.equal(ui.calls.filter(call => call.url === '/api/scenario/reset').length, 1);
  await ui.state.onRecover(item);
  assert.equal(posts(ui).length, 0);
  await ui.state.loadMaintenance();
  assert.equal(ui.state.maintenanceRecords.value.length, 1);
});


test('dashboard keeps missing observations unknown and preserves zero and offline values', async () => {
  const ui = setup(async () => response(successful));
  await ui.state.loadMaintenance();
  assert.equal(ui.state.snapshot.value.data, null);
  ui.state.maintenanceRecords.value = [{device_id: 'sensor-02', kind: 'inspection', status: 'open',
    evidence: {data: {battery_pct: 0, connected: false, telemetry_age_seconds: 0}}}];
  assert.equal(ui.state.snapshot.value.data.battery_pct, 0);
  assert.equal(ui.state.snapshot.value.data.connected, false);
  assert.equal(ui.state.snapshot.value.data.telemetry_age_seconds, 0);
  ui.state.chooseDevice('sensor-03');
  assert.equal(ui.state.snapshot.value, null);
  assert.equal(ui.state.deviceState('sensor-03'), '점검 전');
});

test('dashboard filters history and counts recorded recovery outcomes only', () => {
  const ui = setup(async () => response(successful));
  ui.state.maintenanceRecords.value = [
    {device_id: 'sensor-02', kind: 'recovery', status: 'resolved'},
    {device_id: 'sensor-03', kind: 'inspection', status: 'needs_visit'},
    {device_id: 'sensor-02', kind: 'recovery', status: 'verification_pending'},
    {device_id: 'sensor-01', kind: 'inspection', status: 'normal'},
  ];
  assert.equal(ui.state.confirmedRecoveries.value, 1);
  assert.equal(ui.state.followupRecords.value, 2);
  assert.equal(ui.state.filteredHistory.value.length, 4);
  ui.state.historyFilter.value = 'selected';
  assert.equal(ui.state.filteredHistory.value.length, 2);
  ui.state.chooseDevice('sensor-03');
  assert.equal(ui.state.filteredHistory.value.length, 1);
  assert.equal(ui.state.filteredHistory.value[0].device_id, 'sensor-03');
});

test('candidate cards use only final answer candidates with retrieved source metadata', () => {
  const ui = setup(async () => response(successful));
  const source = {source_id: 'delay#1', title: '수신 지연', text: '점검 절차', causes: [
    {id: 'collection', title: '수집 모듈 일시 정지', check: '수신 로그 확인'},
    {id: 'network', title: '네트워크 지연', check: '게이트웨이 로그 확인'},
  ]};
  ui.inspect(offer, '원인 후보:\n- 수집 모듈 일시 정지 [delay#1]\n- 미등록 후보 [unknown#1]', [source]);
  assert.equal(ui.state.candidateList.value.length, 1);
  assert.equal(ui.state.candidateList.value[0].id, 'collection');
  assert.equal(ui.state.candidateList.value[0].sourceId, 'delay#1');
  ui.state.chooseDevice('sensor-03');
  assert.equal(ui.state.candidateList.value.length, 0);
  assert.equal(ui.state.manualSources.value.length, 0);
});

test('recovery observations replace pre-recovery values and yield to a newer inspection', async () => {
  const ui = setup(async () => response(successful));
  const item = ui.inspect();
  await ui.state.onRecover(item);
  assert.equal(ui.state.snapshot.value.data.telemetry_age_seconds, 0);
  assert.equal(ui.state.snapshot.value.status, 'resolved');
  ui.state.maintenanceRecords.value = [{device_id: 'sensor-02', kind: 'inspection', status: 'open',
    updated_at: new Date(Date.parse(item.recoveredAt) + 60000).toISOString(),
    evidence: {data: {telemetry_age_seconds: 600}}}];
  assert.equal(ui.state.snapshot.value.data.telemetry_age_seconds, 600);
  assert.equal(ui.state.snapshot.value.status, 'open');
});

test('unknown recovery and reset do not show old observations as current', async () => {
  const ui = setup(async () => response({...successful, after: null, recovery_verified: null}));
  const item = ui.inspect();
  await ui.state.onRecover(item);
  assert.equal(ui.state.snapshot.value.data, null);
  assert.equal(ui.state.snapshot.value.status, 'verification_pending');
  await ui.state.resetSelected();
  assert.equal(ui.state.snapshot.value, null);
  assert.equal(ui.state.activeResult.value, null);
  assert.equal(ui.state.deviceState('sensor-02'), '재점검 필요');
});
