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

function setup(recover, resetAll = async () => response({ok: true, count: 6,
  device_ids: ['sensor-01', 'sensor-02', 'sensor-03', 'sensor-04', 'sensor-05', 'sensor-06']}),
  maintenance = async () => response({records: [{id: 'history-1', device_id: 'sensor-02', status: 'needs_visit', summary: '현장 점검 필요'}]})) {
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
      if (url === '/api/maintenance') return maintenance(url, options);
      if (url === '/api/scenario/reset-all') return resetAll(url, options);
      if (url === '/api/scenario/reset') return response({ok: true});
      if (url === '/api/recover') return recover(url, options);
      throw new Error('Unexpected URL: ' + url);
    },
    EventSource: FakeEventSource, URL, AbortController, setTimeout, clearTimeout,
  });
  function inspect(recovery = offer, reply = 'sensor-99라는 문장이 있어도 구조화된 대상을 사용합니다.', sources = []) {
    state.input.value = 'sensor-02 점검';
    state.onSubmit();
    streams.at(-1).emit({type: 'FinalAnswer', reply, recovery, sources});
    streams.at(-1).emit('[DONE]');
    return state.log.value.filter(item => item.kind === 'agent').at(-1);
  }
  return {state, calls, inspect, streams};
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


test('structured log results appear for the correct device without recovery controls', () => {
  const ui = setup(async () => response(successful));
  ui.state.input.value = 'sensor-03 로그 보여줘';
  ui.state.onSubmit();
  const deviceLogs = {ok: true, device_id: 'sensor-03', simulated: true,
    logs: [{id: 'entry-1', code: 'DEVICE_UNREACHABLE', level: 'ERROR', message: '통신 불가'}]};
  ui.streams.at(-1).emit({type: 'FinalAnswer', reply: '장치 로그', metadata: {route: 'logs'}, device_logs: deviceLogs});
  ui.streams.at(-1).emit('[DONE]');
  // 선택 목록이 아직 비동기로 도착하지 않았더라도 서버 대상과 일치하는 장치만 표시한다.
  ui.state.chooseDevice('sensor-03');
  assert.equal(ui.state.activeResult.value.deviceLogs.logs[0].code, 'DEVICE_UNREACHABLE');
  assert.equal(ui.state.activeResult.value.recovery, undefined);
  assert.equal(posts(ui).length, 0);
  ui.state.chooseDevice('sensor-02');
  assert.equal(ui.state.activeResult.value, null);
});


test('bulk reset is one request, blocks overlapping operations, and invalidates all offers', async () => {
  let finish;
  const ui = setup(async () => response(successful), () => new Promise(resolve => { finish = resolve; }));
  await ui.state.refreshAll();
  const first = ui.inspect();
  const other = ui.inspect({...offer, device_id: 'sensor-05'});
  const history = ui.state.maintenanceRecords.value;
  const pending = ui.state.resetAll();
  assert.equal(ui.state.recovering.value, '__all__');
  assert.equal(first.recoveryStatus, 'superseded');
  assert.equal(other.recoveryStatus, 'superseded');
  await ui.state.resetAll();
  await ui.state.resetSelected();
  await ui.state.onRecover(first);
  const count = ui.state.log.value.length;
  ui.state.input.value = 'sensor-01 점검해줘';
  ui.state.onSubmit();
  assert.equal(ui.state.log.value.length, count);
  assert.equal(posts(ui).length, 0);
  assert.equal(ui.calls.filter(call => call.url === '/api/scenario/reset-all').length, 1);
  assert.equal(ui.calls.filter(call => call.url === '/api/scenario/reset').length, 0);
  finish(response({ok: true, device_ids: ['sensor-01', 'sensor-02', 'sensor-03', 'sensor-04', 'sensor-05', 'sensor-06']}));
  await pending;
  assert.equal(ui.state.recovering.value, null);
  assert.match(ui.state.toolbarMessage.value, /6개.*전체 초기화/);
  assert.deepEqual(ui.state.maintenanceRecords.value, history);
  for (const id of ['sensor-01', 'sensor-02', 'sensor-05', 'sensor-06']) {
    assert.equal(ui.state.deviceState(id), '재점검 필요');
  }
  assert.equal(ui.state.activeResult.value, null);
});

test('a lost bulk reset response leaves old results invalid and never automatically retries', async () => {
  const ui = setup(async () => response(successful), async () => { throw new Error('connection lost'); });
  const item = ui.inspect();
  await ui.state.resetAll();
  assert.equal(ui.state.recovering.value, null);
  assert.equal(item.recoveryStatus, 'superseded');
  assert.equal(ui.state.activeResult.value, null);
  assert.match(ui.state.toolbarMessage.value, /결과를 확인하지 못했습니다/);
  await ui.state.onRecover(item);
  assert.equal(posts(ui).length, 0);
  assert.equal(ui.calls.filter(call => call.url === '/api/scenario/reset-all').length, 1);
});

test('fresh logs after reset do not revive pre-reset observations or historical recovery offers', async () => {
  const ui = setup(async () => response(successful));
  await ui.state.refreshAll();
  ui.state.maintenanceRecords.value = [{device_id: 'sensor-02', kind: 'inspection', status: 'open',
    evidence: {data: {telemetry_age_seconds: 600}}}];
  const old = ui.inspect();
  await ui.state.resetAll();
  ui.state.input.value = 'sensor-02 로그 보여줘';
  ui.state.onSubmit();
  ui.streams.at(-1).emit({type: 'FinalAnswer', reply: '새 로그', metadata: {route: 'logs'},
    device_logs: {ok: true, logs: [{id: 'new-event'}]}});
  ui.streams.at(-1).emit('[DONE]');
  assert.equal(ui.state.activeResult.value.deviceLogs.logs[0].id, 'new-event');
  assert.equal(ui.state.snapshot.value, null);
  ui.state.viewResult(old);
  assert.equal(ui.state.activeResult.value, null);
  assert.equal(old.recoveryStatus, 'superseded');
});


test('name-based answers select the server-resolved device even when no ID was typed', async () => {
  const ui = setup(async () => response(successful));
  await ui.state.refreshAll();
  ui.state.deviceList.value.push({device_id: 'sensor-03', name: '복도 온습도 센서'});
  ui.state.input.value = '복도를 관리하는 센서가 뭐가 있더라';
  ui.state.onSubmit();
  ui.streams.at(-1).emit({type: 'FinalAnswer', device_id: 'sensor-03', reply: '복도 온습도 센서', metadata: {route: 'device_info'}});
  ui.streams.at(-1).emit('[DONE]');
  assert.equal(ui.state.selectedDevice.value, 'sensor-03');
  assert.equal(ui.state.log.value.at(-1).deviceId, 'sensor-03');
  assert.equal(posts(ui).length, 0);
});


test('failed refresh preserves records, distinguishes stale data, and clears on recovery', async () => {
  let fail = false;
  const record = {id: 'saved-1', device_id: 'sensor-02', status: 'open'};
  const ui = setup(async () => response(successful), undefined,
    async () => fail ? response({detail: 'offline'}, 503) : response({records: [record]}));
  await ui.state.loadMaintenance();
  const time = ui.state.historyUpdatedAt.value;
  assert.equal(ui.state.historyMessage.value, '');
  fail = true;
  await ui.state.loadMaintenance();
  assert.equal(ui.state.maintenanceRecords.value[0].id, 'saved-1');
  assert.equal(ui.state.historyUpdatedAt.value, time);
  assert.match(ui.state.historyMessage.value, /최신 기록.*갱신하지 못했습니다/);
  assert.match(ui.state.historyMessage.value, /마지막으로 불러온 기록/);
  assert.equal(ui.state.historyLoading.value, false);
  fail = false;
  await ui.state.loadMaintenance();
  assert.equal(ui.state.historyMessage.value, '');
  assert.equal(ui.state.historyLoaded.value, true);
});

test('an older failed request cannot overwrite a newer successful history refresh', async () => {
  const pending = [];
  const ui = setup(async () => response(successful), undefined,
    () => new Promise(resolve => pending.push(resolve)));
  const latest = ui.state.loadMaintenance();
  pending[1](response({records: [{id: 'newest'}]}));
  await latest;
  pending[0](response({detail: 'old failure'}, 503));
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(ui.state.maintenanceRecords.value[0].id, 'newest');
  assert.equal(ui.state.historyMessage.value, '');
  assert.equal(ui.state.historyLoading.value, false);
});

test('an older successful response cannot resurrect history after a newer empty result', async () => {
  const pending = [];
  const ui = setup(async () => response(successful), undefined,
    () => new Promise(resolve => pending.push(resolve)));
  const latest = ui.state.loadMaintenance();
  pending[1](response({records: []}));
  await latest;
  pending[0](response({records: [{id: 'old'}]}));
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(ui.state.maintenanceRecords.value.length, 0);
  assert.equal(ui.state.historyLoaded.value, true);
  assert.equal(ui.state.historyMessage.value, '');
  assert.equal(ui.state.historyEmptyText.value, '아직 점검 기록이 없습니다.');
});

test('first-load errors stay visible with the selected-device filter and differ from empty results', async () => {
  let fail = true;
  const ui = setup(async () => response(successful), undefined,
    async () => fail ? response({detail: 'offline'}, 503) : response({records: []}));
  ui.state.historyFilter.value = 'selected';
  await ui.state.loadMaintenance();
  assert.equal(ui.state.historyLoaded.value, false);
  assert.match(ui.state.historyEmptyText.value, /불러오지 못했습니다/);
  fail = false;
  await ui.state.loadMaintenance();
  assert.equal(ui.state.historyEmptyText.value, '선택한 장치의 기록이 없습니다.');
  assert.equal(ui.state.historyMessage.value, '');
});

test('manual source links allow only verified official HTTPS hosts', () => {
  const ui = setup(async () => response(successful));
  assert.equal(ui.state.safeManualUrl('https://kb.shelly.cloud/knowledge-base/shelly-h-t-gen3'),
    'https://kb.shelly.cloud/knowledge-base/shelly-h-t-gen3');
  assert.equal(ui.state.safeManualUrl('https://shelly-api-docs.shelly.cloud/gen2/ComponentsAndServices/WiFi/'),
    'https://shelly-api-docs.shelly.cloud/gen2/ComponentsAndServices/WiFi/');
  for (const value of [null, '', 'javascript:alert(1)', 'http://kb.shelly.cloud/a',
    'https://kb.shelly.cloud.evil.example/a', 'https://evil.example/', 'https://user:pass@kb.shelly.cloud/']) {
    assert.equal(ui.state.safeManualUrl(value), '');
  }
});
