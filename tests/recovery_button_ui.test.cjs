// 외부 패키지 없이 실제 화면 스크립트의 상태 전이·중복 실행 방지를 검증한다.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { resolve } = require('node:path');
const { runInNewContext } = require('node:vm');
const html = readFileSync(resolve(__dirname, '../web_chat.html'), 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
const offer = {device_id: 'sensor-02', device_name: '실습실 온습도 센서', action: 'restart_collection', simulated: true};
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
      ref: value => ({value}), reactive: value => value, nextTick: async () => {},
    },
    fetch: async (url, options) => {
      calls.push({url, options});
      if (url === '/health') return response({llm_backend: 'fake'});
      if (url === '/api/recover') return recover(url, options);
      throw new Error('Unexpected URL: ' + url);
    },
    EventSource: FakeEventSource, AbortController, setTimeout, clearTimeout,
  });
  function inspect(recovery = offer, reply = 'sensor-99라는 문장이 있어도 구조화된 대상을 사용합니다.') {
    state.input.value = 'sensor-02 점검';
    state.onSubmit();
    streams.at(-1).emit({type: 'FinalAnswer', reply, recovery});
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
  assert.equal(JSON.parse(posts(ui)[0].options.body).device_id, 'sensor-02');
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
