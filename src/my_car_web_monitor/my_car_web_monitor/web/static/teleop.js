/* Browser input gestures. Arbitration and ramps are authoritative on the server. */
(() => {
  "use strict";
  const byId = id => document.getElementById(id);
  const pad = byId("joystick"), knob = byId("joystick-knob");
  const error = byId("control-error"), modeButton = byId("toggle-pivot");
  const connect = byId("connect-control"), disconnect = byId("disconnect-control");
  const limits = ["linear", "steering", "angular"].map(name => byId(`limit-${name}`));
  const applyLimitsButton = byId("apply-limits"), limitsStatus = byId("limits-status");
  let desiredLimits = [2.0, 0.845, 5.0];
  let limitsPending = null, draftRevision = 0, initializeLimits = false, limitsReady = false;
  const physical = new Set(), accepted = new Set();
  const bindings = new Map([["KeyW", "forward"], ["ArrowUp", "forward"],
    ["KeyS", "backward"], ["ArrowDown", "backward"], ["KeyA", "left"],
    ["ArrowLeft", "left"], ["KeyD", "right"], ["ArrowRight", "right"]]);
  let socket = null, token = null, heartbeat = null, eventId = 0;
  let pivot = false, owner = null, neutral = true, estop = false, pointerId = null;
  let inputEpoch = null, switching = false, pointerHeld = false, steeringStep = 0;
  let mouseIgnored = false;
  let noticeUntil = 0;
  function notice(message) { error.textContent = message; noticeUntil = performance.now() + 2000; }

  function available() { return socket?.readyState === WebSocket.OPEN && token !== null; }
  function send(payload, event = true) {
    if (!available()) return false;
    if (socket.bufferedAmount > 2048) { closeControl("송신 지연 · 다시 연결하세요"); return false; }
    if (event) payload.event_id = ++eventId;
    socket.send(JSON.stringify({...payload, token, input_epoch:inputEpoch}));
    return true;
  }
  function resetInput() {
    accepted.clear();
    pointerId = null;
    mouseIgnored = false;
    owner = null;
    neutral = true;
    knob.style.left = "50%";
    knob.style.top = "50%";
  }
  function closeControl(reason = "제어 연결 해제") {
    const previous = socket;
    socket = null;
    token = null;
    if (heartbeat !== null) clearInterval(heartbeat);
    heartbeat = null;
    resetInput();
    previous?.close();
    byId("control-state").textContent = "미연결";
    if (previous && !["제어 연결 해제", "구동 해제", "미연결"].includes(reason)) notice(reason);
    limitsPending = null;
    limitsReady = false;
    inputEpoch = null;
    switching = false;
    steeringStep = 0;
    configureMode();
    limits.forEach(input => { input.disabled = false; });
    applyLimitsButton.disabled = false;
    connect.disabled = false;
    disconnect.disabled = true;
    byId("input-owner").textContent = "입력 대기";
    byId("local-command").textContent = "웹 목표: —";
  }
  function keyboardState(steerDelta = 0) {
    const commands = new Set([...accepted].map(key => bindings.get(key)));
    const x = Number(commands.has("left")) - Number(commands.has("right"));
    const y = pivot ? 0 : Number(commands.has("forward")) - Number(commands.has("backward"));
    send({type:"input", source:"keyboard", active:accepted.size > 0, x, y, steer_delta:steerDelta});
  }
  function editable(target) { return target?.closest("input,textarea,select,[contenteditable=true]"); }
  function toggleMode() {
    if (!available()) return;
    if (switching || physical.size || pointerHeld) {
      notice("눌린 키·드래그 또는 진행 중인 모드 전환이 우선합니다");
      return;
    }
    send({type:"mode", pivot:!pivot});
  }
  function writeLimits(values) {
    limits.forEach((input, index) => { input.value = String(values[index]); });
  }
  function applyLimits() {
    if (!neutral || owner !== null) {
      notice("중립에서만 최대값을 변경할 수 있습니다");
      return;
    }
    if (limits.some(input => input.value.trim() === "" || !input.checkValidity() || !Number.isFinite(input.valueAsNumber))) {
      limitsStatus.textContent = "입력 범위를 확인하세요";
      limits.find(input => !input.checkValidity() || !Number.isFinite(input.valueAsNumber))?.reportValidity();
      return;
    }
    desiredLimits = limits.map(input => input.valueAsNumber);
    if (available()) {
      if (send({type:"limits", linear:desiredLimits[0], steering:desiredLimits[1], angular:desiredLimits[2]})) {
        limitsPending = {id:eventId, revision:draftRevision};
        limitsStatus.textContent = "적용 중";
      }
    } else {
      limitsStatus.textContent = "저장됨 · 연결 시 적용";
    }
  }
  function configureMode() {
    modeButton.textContent = switching ? "정지 지령 확인 중" : pivot ? "PIVOT · P로 일반 전환" : "일반 주행 · P로 PIVOT 전환";
    byId("steering-step").textContent = pivot ? "PIVOT · 연속 각속도 입력" : `조향 단계: ${steeringStep > 0 ? "좌 " + steeringStep : steeringStep < 0 ? "우 " + -steeringStep : "중앙 0"} / 5`;
    pad.dataset.pivot = String(pivot);
    pad.querySelector(".joystick-label").textContent = pivot ? "← 좌회전 · 우회전 →" : "↑ 전진 · 좌우 조향 · ↓ 후진";
    pad.setAttribute("aria-label", pivot ? "PIVOT 1차원 조이스틱: 왼쪽 좌회전, 오른쪽 우회전" : "일반 2차원 조이스틱: 위 전진, 아래 후진, 좌우 조향");
  }
  connect.addEventListener("click", () => {
    if (socket) return;
    error.textContent = "";
    resetInput();
    eventId = 0;
    initializeLimits = true;
    inputEpoch = null;
    switching = false;
    steeringStep = 0;
    connect.disabled = true;
    const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws/control`);
    socket = ws;
    let serverError = false;
    byId("control-state").textContent = "연결 중";
    ws.addEventListener("message", event => {
      if (socket !== ws) return;
      let data;
      try { data = JSON.parse(event.data); } catch { closeControl("잘못된 서버 응답"); return; }
      if (data.type === "error") { serverError = true; notice(data.message); return; }
      if (data.type !== "control_state") return;
      token = data.token;
      if (heartbeat === null) {
        // This socket never reconnects/arms automatically.
        heartbeat = setInterval(() => {
          if (document.hidden) closeControl("탭 이탈 · 다시 연결하세요");
          else send({type:"heartbeat"}, false);
        }, 50);
      }
      byId("control-state").textContent = data.estop ? "비상정지" : data.switching ? "연결됨·정지 확인" : data.enabled ? "연결됨·제어" : "연결됨·대기";
      disconnect.disabled = false;
      if (performance.now() > noticeUntil) error.textContent = data.message || "";
      estop = data.estop;
      const epochChanged = data.input_epoch !== inputEpoch;
      if (epochChanged) {
        inputEpoch = data.input_epoch;
        resetInput();  // Physical keys are preserved: release/repress after a reset.
      }
      switching = data.switching;
      if (data.last_event >= eventId || epochChanged) {
        if (data.owner !== "keyboard") accepted.clear();
        if (data.owner !== "mouse") pointerId = null;
        owner = data.owner;
        neutral = data.neutral;
        pivot = data.pivot;
        steeringStep = data.steering_step;
        configureMode();
      }
      if (initializeLimits) {
        initializeLimits = false;
        // Reapply local settings on a new socket; never replace an in-progress draft.
        if (!limits.includes(document.activeElement)) applyLimits();
      }
      if (limitsPending && data.last_event >= limitsPending.id) {
        if (draftRevision === limitsPending.revision) {
          desiredLimits = [...data.limits];
          if (!limits.includes(document.activeElement)) writeLimits(desiredLimits);
          limitsStatus.textContent = data.message || "적용됨";
        }
        limitsPending = null;
        limitsReady = true;
      }
      limits.forEach(input => { input.disabled = !neutral || owner !== null; });
      applyLimitsButton.disabled = !neutral || owner !== null || limitsPending !== null;
      byId("input-owner").textContent = switching ? "정지 지령 확인 대기" : owner ? owner === "keyboard" ? "키보드 우선 · 조향 단계 유지" : "마우스 우선 · 중립 복귀까지 유지" : "입력 대기";
      byId("local-command").textContent = `웹 입력: v ${data.linear.toFixed(3)} m/s · θ ${data.steering.toFixed(3)} rad · ω ${data.angular.toFixed(3)} rad/s | 송신 ${data.enabled ? "enable" : "0 · disable"}`;
      const x = pivot ? data.angular / data.limits[2] : data.steering / data.limits[1];
      const y = pivot ? 0 : data.linear / data.limits[0];
      knob.style.left = `${50 - x * 44}%`;
      knob.style.top = `${50 - y * 40}%`;
    });
    ws.addEventListener("close", () => { if (socket === ws) closeControl(serverError ? "미연결" : "연결 종료 · 다시 연결하세요"); });
    ws.addEventListener("error", () => { if (socket === ws) error.textContent = "제어 연결 실패"; });
  });
  disconnect.addEventListener("click", () => closeControl());
  byId("disable-control").addEventListener("click", () => closeControl("구동 해제"));
  byId("normal-stop").addEventListener("click", () => {
    accepted.clear();
    pointerId = null;
    send({type:"stop"});
  });
  byId("emergency-stop").addEventListener("click", () => { resetInput(); send({type:"estop"}); });
  byId("clear-estop").addEventListener("click", () => {
    if (physical.size || pointerId !== null) { notice("모든 입력을 놓은 뒤 해제하세요"); return; }
    send({type:"clear_estop"});
  });
  modeButton.addEventListener("click", toggleMode);
  applyLimitsButton.addEventListener("click", applyLimits);
  limits.forEach(input => {
    input.addEventListener("input", () => {
      draftRevision += 1;
      limitsStatus.textContent = "편집 중 · 적용 버튼 또는 Enter";
    });
    input.addEventListener("keydown", event => {
      if (event.key === "Enter") { event.preventDefault(); applyLimits(); }
    });
  });
  window.addEventListener("keydown", event => {
    if (event.code === "KeyP" && !event.repeat && !event.ctrlKey && !event.altKey && !event.metaKey && !editable(event.target)) { event.preventDefault(); toggleMode(); return; }
    if (!bindings.has(event.code)) return;
    const wasDown = physical.has(event.code);
    physical.add(event.code);
    if (!available() || editable(event.target) || event.ctrlKey || event.altKey || event.metaKey) return;
    if (!limitsReady) { notice("최대값을 적용한 뒤 조작하세요"); return; }
    event.preventDefault();
    if (event.repeat || wasDown || estop || switching || (pivot && ["forward", "backward"].includes(bindings.get(event.code)))) return;
    if (owner !== null && owner !== "keyboard") {
      send({type:"input", source:"keyboard", active:true, x:0, y:0});
      return;
    }
    owner = "keyboard";
    neutral = false;
    accepted.add(event.code);
    const direction = bindings.get(event.code);
    keyboardState(!pivot && direction === "left" ? 1 : !pivot && direction === "right" ? -1 : 0);
  });
  window.addEventListener("keyup", event => {
    physical.delete(event.code);
    if (!bindings.has(event.code)) return;
    if (accepted.delete(event.code)) { event.preventDefault(); keyboardState(); }
    else if (available() && physical.size === 0) {
      send({type:"input", source:"keyboard", active:false, x:0, y:0});
    }
  });
  function mouseAxes(event) {
    const rect = pad.getBoundingClientRect();
    const deadband = value => Math.abs(value) < 0.05 ? 0 : Math.sign(value) * (Math.abs(value) - 0.05) / 0.95;
    const x = deadband(Math.max(-1, Math.min(1, 1 - 2 * (event.clientX - rect.left) / rect.width)));
    const y = pivot ? 0 : deadband(Math.max(-1, Math.min(1, 1 - 2 * (event.clientY - rect.top) / rect.height)));
    send({type:"input", source:"mouse", active:true, x, y});
  }
  pad.addEventListener("pointerdown", event => {
    if (event.button !== 0 || !available() || estop || pointerId !== null) return;
    pointerHeld = true;
    if (switching) return;
    if (!limitsReady) { notice("최대값을 적용한 뒤 조작하세요"); return; }
    event.preventDefault();
    if (owner !== null && owner !== "mouse") {
      mouseIgnored = true;
      send({type:"input", source:"mouse", active:true, x:0, y:0});
      return;
    }
    if (mouseIgnored) return;
    owner = "mouse";
    neutral = false;
    pointerId = event.pointerId;
    pad.focus({preventScroll:true});
    pad.setPointerCapture(pointerId);
    mouseAxes(event);
  });
  pad.addEventListener("pointermove", event => {
    if (event.pointerId === pointerId && available()) mouseAxes(event);
  });
  function releasePointer(event) {
    if (event.pointerId !== pointerId) return;
    pointerId = null;
    send({type:"input", source:"mouse", active:false, x:0, y:0});
  }
  pad.addEventListener("pointerup", releasePointer);
  pad.addEventListener("pointercancel", releasePointer);
  pad.addEventListener("lostpointercapture", releasePointer);
  function clearIgnoredPointer() {
    pointerHeld = false;
    if (mouseIgnored) send({type:"input", source:"mouse", active:false, x:0, y:0});
    mouseIgnored = false;
  }
  window.addEventListener("pointerup", clearIgnoredPointer);
  window.addEventListener("pointercancel", clearIgnoredPointer);
  window.addEventListener("blur", () => { physical.clear(); pointerHeld = false; closeControl("포커스 이탈 · 다시 연결하세요"); });
  document.addEventListener("visibilitychange", () => { if (document.hidden) closeControl("탭 이탈 · 다시 연결하세요"); });
  window.addEventListener("pagehide", () => closeControl());
  fetch("/control/config").then(response => response.json()).then(config => {
    byId("ramp-info").textContent = `AUTO에서 입력 적용 · 속도 증가/복귀 ${config.ramp_seconds}초 · 마우스 복귀 ${config.mouse_return_seconds}초`;
  }).catch(() => { error.textContent = "제어 설정을 불러오지 못했습니다"; });
  configureMode();
  disconnect.disabled = true;
})();
