(() => {
  // --- 视频页面功能开关配置 ---
  window.VIDEO_FEATURES = {
    enableIdentityCheck: true, // 是否强制要求输入岗位和姓名
    enableTopMarquee: true,    // 是否显示顶部滚动公告
    enableMainAd: true,        // 是否显示中间的主广告横幅
    enableSideAds: true,       // 是否显示左右两侧悬浮对联广告
    enableDownloadAd: false     // 是否在点击下载时弹出恶搞广告
  };

  const VERIFY_ENDPOINT = '/webui/api/verify';
  const VIDEO_WS_ENDPOINT = '/webui/api/video/ws';
  const PROMPT_MIN_HEIGHT = 52;
  const PROMPT_MAX_HEIGHT = 160;

  const promptInput = document.getElementById('promptInput');
  const sendBtn = document.getElementById('sendBtn');
  const feed = document.getElementById('videoFeed');
  const emptyState = document.getElementById('videoEmpty');
  const sizeSelect = document.getElementById('sizeSelect');
  const secondsSelect = document.getElementById('secondsSelect');
  const countSelect = document.getElementById('countSelect');
  const videoModelSelect = document.getElementById('videoModelSelect');
  const presetToggle = document.getElementById('presetToggle');
  const refImageInput = document.getElementById('refImageInput');
  const refImageBtn = document.getElementById('refImageBtn');
  const refImagePreview = document.getElementById('refImagePreview');

  let activeSocket = null;
  let sending = false;
  let referenceImages = [];  // Array of { base64, name }

  // Track active runs: run_id -> card
  let activeRuns = {};

  const HISTORY_KEY = 'grok2api_video_history';
  let videoHistory = [];

  function loadVideoHistory() {
    try {
      videoHistory = JSON.parse(localStorage.getItem(HISTORY_KEY)) || [];
      const toRender = [...videoHistory].reverse();
      toRender.forEach(item => {
        const card = createVideoCard(item.prompt, item.size, item.seconds, item.preset, null, item.userRole, item.userName);
        updateCardProgress(card, 100);
        markCardCompleted(card, item.url, item.thumbnailUrl, true);
      });
    } catch {
      videoHistory = [];
    }
  }

  function saveToVideoHistory(item) {
    if (!item || !item.url) return;
    videoHistory.unshift(item);
    if (videoHistory.length > 50) videoHistory.length = 50;
    try {
      localStorage.setItem(HISTORY_KEY, JSON.stringify(videoHistory));
    } catch { }
  }

  function text(key, fallback, params) {
    if (typeof window.t !== 'function') return fallback;
    const value = t(key, params);
    return value === key ? fallback : value;
  }

  function toast(message, type = 'info') {
    if (typeof showToast === 'function') showToast(message, type);
  }

  function buildWebSocketUrl(path, params = {}) {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const url = new URL(path, `${protocol}//${window.location.host}`);
    Object.entries(params).forEach(([key, value]) => {
      if (value === null || value === undefined || value === '') return;
      url.searchParams.set(key, String(value));
    });
    return url.toString();
  }

  function resizePromptInput() {
    if (!promptInput) return;
    promptInput.style.height = `${PROMPT_MIN_HEIGHT}px`;
    const nextHeight = Math.min(Math.max(promptInput.scrollHeight, PROMPT_MIN_HEIGHT), PROMPT_MAX_HEIGHT);
    promptInput.style.height = `${nextHeight}px`;
    promptInput.style.overflowY = promptInput.scrollHeight > PROMPT_MAX_HEIGHT ? 'auto' : 'hidden';
  }

  function setEmptyState() {
    if (!feed || !emptyState) return;
    const hasCard = feed.querySelector('.webui-video-card') !== null;
    emptyState.hidden = hasCard;
    emptyState.style.display = hasCard ? 'none' : '';
  }

  function renderSendButton(running) {
    if (!sendBtn) return;
    const label = running
      ? text('webui.video.stop', '停止')
      : text('webui.video.generate', '生成');
    const icon = running
      ? '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="6" y="6" width="12" height="12" rx="1"></rect></svg>'
      : '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14"></path><path d="m6 11 6-6 6 6"></path></svg>';
    sendBtn.innerHTML = icon;
    sendBtn.setAttribute('aria-label', label);
    sendBtn.setAttribute('title', label);
  }

  function setSending(next) {
    sending = next;
    if (promptInput) promptInput.disabled = next;
    if (sizeSelect) sizeSelect.disabled = next;
    if (secondsSelect) secondsSelect.disabled = next;
    if (countSelect) countSelect.disabled = next;
    if (videoModelSelect) videoModelSelect.disabled = next;
    presetToggle?.querySelectorAll('.webui-masonry-toggle-btn').forEach((button) => {
      button.disabled = next;
    });
    renderSendButton(next);
  }

  function checkBatchDone() {
    // If no active runs left, reset sending state
    if (Object.keys(activeRuns).length === 0 && sending) {
      setSending(false);
      promptInput?.focus();
      if (activeSocket) {
        try { activeSocket.close(1000, 'batch_done'); } catch { }
        activeSocket = null;
      }
    }
  }

  function readToggleValue(group, fallback) {
    const active = group?.querySelector('.webui-masonry-toggle-btn.is-active');
    return active?.dataset.value || fallback;
  }

  function setToggleValue(group, value) {
    group?.querySelectorAll('.webui-masonry-toggle-btn').forEach((button) => {
      const active = button.dataset.value === value;
      button.classList.toggle('is-active', active);
      button.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
  }

  function formatSizeLabel(size) {
    const map = { '720x1280': '9:16', '1280x720': '16:9', '1024x1024': '1:1' };
    return map[size] || size;
  }

  function formatPresetLabel(preset) {
    const map = {
      custom: text('webui.video.presetCustom', '自定义'),
      fun: text('webui.video.presetFun', '趣味'),
      normal: text('webui.video.presetNormal', '正常'),
      spicy: text('webui.video.presetSpicy', '大胆'),
    };
    return map[preset] || preset;
  }

  function generateRunId() {
    const bytes = new Uint8Array(16);
    crypto.getRandomValues(bytes);
    return Array.from(bytes, b => b.toString(16).padStart(2, '0')).join('');
  }

  function createVideoCard(prompt, size, seconds, preset, batchLabel, userRole = '', userName = '') {
    const wrap = document.createElement('article');
    wrap.className = 'webui-video-card';

    const head = document.createElement('header');
    head.className = 'webui-video-card-head';

    const promptEl = document.createElement('div');
    promptEl.className = 'webui-video-card-prompt';
    promptEl.textContent = prompt;

    head.appendChild(promptEl);

    // Show batch label if multi-generation (e.g. "#2 / 4")
    if (batchLabel) {
      const batchEl = document.createElement('span');
      batchEl.className = 'webui-video-card-batch';
      batchEl.textContent = batchLabel;
      head.appendChild(batchEl);
    }

    const body = document.createElement('div');
    body.className = 'webui-video-card-body';

    const progressWrap = document.createElement('div');
    progressWrap.className = 'webui-video-progress-wrap';

    const progressRing = document.createElement('div');
    progressRing.className = 'webui-video-progress-ring';

    const progressInner = document.createElement('div');
    progressInner.className = 'webui-video-progress-inner';

    const progressIcon = document.createElement('div');
    progressIcon.className = 'webui-video-progress-icon';
    progressIcon.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M23 7l-7 5 7 5V7z"/><rect x="1" y="5" width="15" height="14" rx="2" ry="2"/></svg>';

    const progressValue = document.createElement('div');
    progressValue.className = 'webui-video-progress-value';
    progressValue.textContent = '0%';

    progressInner.appendChild(progressIcon);
    progressInner.appendChild(progressValue);
    progressRing.appendChild(progressInner);
    progressWrap.appendChild(progressRing);
    body.appendChild(progressWrap);

    wrap.appendChild(head);
    wrap.appendChild(body);
    feed.prepend(wrap);
    setEmptyState();

    return {
      wrap,
      body,
      stateChip: null,
      progressRing,
      progressValue,
      progressWrap,
      completed: false,
      failed: false,
      userRole,
      userName
    };
  }

  function updateCardProgress(card, progress) {
    const clamped = Math.max(0, Math.min(100, progress));
    card.progressValue.textContent = `${clamped}%`;
    card.progressRing.style.setProperty('--video-progress', `${clamped * 3.6}deg`);
  }

  function markCardCompleted(card, url, thumbnailUrl, skipSave = false) {
    card.completed = true;

    if (card.stateChip) {
      card.stateChip.dataset.state = 'success';
      card.stateChip.textContent = text('webui.video.statusSuccess', '生成成功');
    }

    card.progressWrap.remove();

    const player = document.createElement('div');
    player.className = 'webui-video-player';

    const video = document.createElement('video');
    video.controls = false;  // no controls on thumbnail
    video.autoplay = true;
    video.loop = true;
    video.muted = true;
    video.playsInline = true;
    video.preload = 'metadata';
    video.src = url;
    if (thumbnailUrl) video.poster = thumbnailUrl;

    video.addEventListener('canplay', () => {
      video.play().catch(err => console.warn('Autoplay prevented:', err));
    }, { once: true });

    player.appendChild(video);
    card.body.appendChild(player);

    // Download button
    let fileName = `video_${Date.now()}.mp4`;
    if (card.userRole || card.userName) {
      fileName = `${card.userRole}_${card.userName}_${Date.now()}.mp4`;
    }

    const dlBtn = document.createElement('button');
    dlBtn.className = 'webui-video-download';
    dlBtn.type = 'button';
    dlBtn.title = text('webui.video.download', '下载');
    dlBtn.innerHTML = '<svg viewBox="0 0 24 24"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>';
    dlBtn.addEventListener('click', (e) => {
      e.stopPropagation(); // don't open lightbox
      const a = document.createElement('a');
      a.href = url;
      a.download = fileName;
      document.body.appendChild(a);
      a.click();
      a.remove();

      if (window.VIDEO_FEATURES.enableDownloadAd) {
        const overlay = document.getElementById('downloadAdOverlay');
        if (overlay) overlay.style.display = 'flex';
      }
    });
    card.body.appendChild(dlBtn);

    // Click card to open lightbox
    card.wrap.style.cursor = 'pointer';
    card.wrap.addEventListener('click', () => {
      openLightbox(url, thumbnailUrl, fileName);
    });

    if (!skipSave) {
      saveToVideoHistory({
        prompt: card.wrap.querySelector('.webui-video-card-prompt')?.textContent || '',
        size: '1:1',
        seconds: '16',
        preset: 'custom',
        url: url,
        thumbnailUrl: thumbnailUrl,
        timestamp: Date.now(),
        userRole: card.userRole,
        userName: card.userName
      });
    }
  }

  /* --- Lightbox --- */
  function openLightbox(videoUrl, posterUrl, fileName = '') {
    // Remove existing lightbox if any
    document.getElementById('videoLightbox')?.remove();

    const overlay = document.createElement('div');
    overlay.id = 'videoLightbox';
    overlay.className = 'webui-video-lightbox';

    const content = document.createElement('div');
    content.className = 'webui-video-lightbox-content';

    const video = document.createElement('video');
    video.controls = true;
    video.autoplay = true;
    video.loop = true;
    video.playsInline = true;
    video.src = videoUrl;
    if (posterUrl) video.poster = posterUrl;

    const closeBtn = document.createElement('button');
    closeBtn.className = 'webui-video-lightbox-close';
    closeBtn.innerHTML = '&times;';
    closeBtn.type = 'button';

    const dlBtn = document.createElement('a');
    dlBtn.className = 'webui-video-lightbox-download';
    dlBtn.href = videoUrl;
    dlBtn.download = fileName || `video_${Date.now()}.mp4`;
    dlBtn.title = text('webui.video.download', '下载');
    dlBtn.innerHTML = '<svg viewBox="0 0 24 24"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>';
    dlBtn.addEventListener('click', () => {
      if (window.VIDEO_FEATURES.enableDownloadAd) {
        const overlay = document.getElementById('downloadAdOverlay');
        if (overlay) overlay.style.display = 'flex';
      }
    });

    content.appendChild(video);
    content.appendChild(closeBtn);
    content.appendChild(dlBtn);
    overlay.appendChild(content);
    document.body.appendChild(overlay);

    // Close on backdrop click
    overlay.addEventListener('click', (e) => {
      if (e.target === overlay) closeLightbox();
    });
    closeBtn.addEventListener('click', closeLightbox);
    // Close on Escape
    const onKey = (e) => { if (e.key === 'Escape') closeLightbox(); };
    document.addEventListener('keydown', onKey);
    overlay._onKey = onKey;
  }

  function closeLightbox() {
    const el = document.getElementById('videoLightbox');
    if (!el) return;
    if (el._onKey) document.removeEventListener('keydown', el._onKey);
    // Pause video before removing
    const v = el.querySelector('video');
    if (v) { v.pause(); v.src = ''; }
    el.remove();
  }

  function markCardFailed(card, message) {
    card.failed = true;
    if (card.stateChip) {
      card.stateChip.dataset.state = 'failed';
      card.stateChip.textContent = text('webui.video.statusFailed', '生成失败');
    }

    card.progressWrap.remove();

    const errorEl = document.createElement('div');
    errorEl.className = 'webui-video-error';
    errorEl.textContent = message || text('webui.video.errors.requestFailed', '请求失败');
    card.body.appendChild(errorEl);
  }

  function markCardStopped(card) {
    if (!card || card.completed || card.failed) return;
    if (card.stateChip) {
      card.stateChip.dataset.state = 'failed';
      card.stateChip.textContent = text('webui.video.statusStopped', '已停止');
    }
    card.progressWrap.remove();
  }

  async function ensureAccess() {
    const stored = await webuiKey.get();
    if (stored && await verifyKey(VERIFY_ENDPOINT, stored)) return true;
    if (stored) webuiKey.clear();
    if (await verifyKey(VERIFY_ENDPOINT, '')) return true;
    location.href = '/webui/login';
    return false;
  }

  async function startGeneration() {
    if (sending) {
      stopGeneration({ silent: true });
      return;
    }

    let userRole = '';
    let userName = '';

    if (window.VIDEO_FEATURES.enableIdentityCheck) {
      const userRoleInput = document.getElementById('userRole');
      const userNameInput = document.getElementById('userName');
      userRole = String(userRoleInput?.value || '').trim();
      userName = String(userNameInput?.value || '').trim();

      if (!userRole || !userName) {
        toast('生成视频前请务必在下方输入您的岗位和姓名！', 'error');
        userRoleInput?.focus();
        return;
      }

      // 记住输入信息
      localStorage.setItem('video_userRole', userRole);
      localStorage.setItem('video_userName', userName);
    }

    const prompt = String(promptInput?.value || '').trim();
    if (!prompt) {
      toast(text('webui.video.errors.enterPrompt', '请输入提示词'), 'error');
      return;
    }

    const size = sizeSelect?.value || '720x1280';
    const seconds = parseInt(secondsSelect?.value || '6', 10);
    const preset = readToggleValue(presetToggle, 'custom');
    const model = videoModelSelect?.value || 'grok-imagine-video';
    const count = Math.max(1, Math.min(4, parseInt(countSelect?.value || '1', 10)));

    setSending(true);
    activeRuns = {};
    promptInput.value = '';
    resizePromptInput();

    // Create cards for each video in the batch
    const runIds = [];
    for (let i = 0; i < count; i++) {
      const runId = generateRunId();
      const batchLabel = count > 1 ? `#${i + 1} / ${count}` : null;
      const card = createVideoCard(prompt, size, seconds, preset, batchLabel, userRole, userName);
      activeRuns[runId] = card;
      runIds.push(runId);
    }

    const token = await webuiKey.get();
    const wsUrl = buildWebSocketUrl(VIDEO_WS_ENDPOINT, token ? { access_token: token } : {});
    const socket = new WebSocket(wsUrl);
    activeSocket = socket;

    // Heartbeat to keep WebSocket alive through proxies/gateways
    let pingInterval = null;
    const startPing = () => {
      pingInterval = setInterval(() => {
        if (socket.readyState === WebSocket.OPEN) {
          try { socket.send(JSON.stringify({ type: 'ping' })); } catch { }
        }
      }, 15000);
    };

    socket.addEventListener('open', () => {
      if (activeSocket !== socket) return;
      try {
        // Send a start message for each video
        for (const runId of runIds) {
          socket.send(JSON.stringify({
            type: 'start',
            run_id: runId,
            prompt,
            size,
            seconds,
            preset,
            model,
            ...(referenceImages.length ? { input_references: referenceImages.map(r => ({ image_url: r.base64 })) } : {}),
          }));
        }
        startPing();
      } catch {
        // Mark all cards failed
        for (const runId of Object.keys(activeRuns)) {
          markCardFailed(activeRuns[runId], text('webui.video.errors.requestFailed', '请求失败'));
        }
        activeRuns = {};
        setSending(false);
      }
    });

    socket.addEventListener('message', (event) => {
      let payload;
      try {
        payload = JSON.parse(String(event.data || '{}'));
      } catch {
        return;
      }
      if (!payload || typeof payload !== 'object') return;

      const runId = String(payload.run_id || '');
      const card = activeRuns[runId];

      if (payload.type === 'status') {
        if (payload.status === 'completed' && card) {
          // Remove from active runs; card already marked via 'video' message
          delete activeRuns[runId];
          checkBatchDone();
        } else if (payload.status === 'stopped' && card) {
          markCardStopped(card);
          delete activeRuns[runId];
          checkBatchDone();
        }
        return;
      }

      if (payload.type === 'progress' && card && !card.completed) {
        updateCardProgress(card, payload.progress || 0);
        return;
      }

      if (payload.type === 'video' && card && !card.completed) {
        updateCardProgress(card, 100);
        markCardCompleted(card, payload.url, payload.thumbnail_url);
        return;
      }

      if (payload.type === 'error') {
        if (card && !card.completed && !card.failed) {
          markCardFailed(card, payload.message);
          delete activeRuns[runId];
        } else if (!runId) {
          // Global error (e.g. too_many_tasks) — show as toast
          toast(payload.message || text('webui.video.errors.requestFailed', '请求失败'), 'error');
        }
        checkBatchDone();
      }
    });

    socket.addEventListener('error', () => {
      // Mark all remaining active cards as failed
      for (const [runId, card] of Object.entries(activeRuns)) {
        if (!card.completed && !card.failed) {
          markCardFailed(card, text('webui.video.errors.connectionFailed', '连接失败'));
        }
      }
      activeRuns = {};
      setSending(false);
    });

    socket.addEventListener('close', () => {
      if (pingInterval) clearInterval(pingInterval);
      if (activeSocket === socket) activeSocket = null;
      // Mark any remaining active cards as stopped
      for (const [runId, card] of Object.entries(activeRuns)) {
        if (!card.completed && !card.failed) {
          markCardStopped(card);
        }
      }
      activeRuns = {};
      setSending(false);
      promptInput?.focus();
    });
  }

  function stopGeneration({ silent = false } = {}) {
    const socket = activeSocket;
    activeSocket = null;
    if (socket) {
      // Send stop for all active runs
      try { socket.send(JSON.stringify({ type: 'stop' })); } catch { }
      try { socket.close(1000, 'stopped'); } catch { }
    }
    for (const card of Object.values(activeRuns)) {
      markCardStopped(card);
    }
    activeRuns = {};
    setSending(false);
    if (!silent) toast(text('webui.video.statusStopped', '已停止'), 'info');
  }

  async function boot() {
    await renderWebuiHeader?.();
    await renderSiteFooter?.();
    window.I18n?.apply?.(document);

    // 动态应用功能开关
    if (!window.VIDEO_FEATURES.enableTopMarquee) {
      const marquee = document.querySelector('.marquee-container');
      if (marquee) marquee.style.display = 'none';
    }
    if (!window.VIDEO_FEATURES.enableMainAd) {
      const mainAd = document.querySelector('.webui-video-ad-banner');
      if (mainAd) mainAd.style.display = 'none';
    }
    if (!window.VIDEO_FEATURES.enableSideAds) {
      const sideAds = document.querySelectorAll('.webui-side-ad');
      sideAds.forEach(ad => ad.style.display = 'none');
    }
    if (!window.VIDEO_FEATURES.enableIdentityCheck) {
      const userInfoBar = document.querySelector('.user-info-bar');
      if (userInfoBar) userInfoBar.style.display = 'none';
    }

    if (!await ensureAccess()) return;
    setToggleValue(presetToggle, 'custom');
    setSending(false);

    const roleInput = document.getElementById('userRole');
    const nameInput = document.getElementById('userName');
    if (roleInput) roleInput.value = localStorage.getItem('video_userRole') || '';
    if (nameInput) nameInput.value = localStorage.getItem('video_userName') || '';

    loadVideoHistory();
    setEmptyState();
    resizePromptInput();
    promptInput?.focus();
  }

  sendBtn?.addEventListener('click', () => {
    void startGeneration();
  });

  presetToggle?.addEventListener('click', (event) => {
    const button = event.target instanceof Element ? event.target.closest('.webui-masonry-toggle-btn') : null;
    if (!(button instanceof HTMLButtonElement) || button.disabled) return;
    setToggleValue(presetToggle, button.dataset.value || 'custom');
  });

  promptInput?.addEventListener('input', resizePromptInput);
  promptInput?.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      void startGeneration();
    }
  });

  /* --- Reference image upload (multi) --- */
  const MAX_REF_IMAGES = 5;
  const MAX_IMAGE_BYTES = 512 * 1024;  // Compress if > 512KB
  const MAX_IMAGE_DIM = 1920;          // Max width/height after resize

  function readFileAsBase64(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result);
      reader.onerror = reject;
      reader.readAsDataURL(file);
    });
  }

  function compressImage(dataUrl, maxDim = MAX_IMAGE_DIM, quality = 0.8) {
    return new Promise((resolve) => {
      const img = new Image();
      img.onload = () => {
        let { width, height } = img;
        if (width > maxDim || height > maxDim) {
          const scale = maxDim / Math.max(width, height);
          width = Math.round(width * scale);
          height = Math.round(height * scale);
        }
        const canvas = document.createElement('canvas');
        canvas.width = width;
        canvas.height = height;
        const ctx = canvas.getContext('2d');
        ctx.drawImage(img, 0, 0, width, height);
        resolve(canvas.toDataURL('image/jpeg', quality));
      };
      img.onerror = () => resolve(dataUrl);  // fallback to original
      img.src = dataUrl;
    });
  }

  function renderRefPreviews() {
    if (!refImagePreview) return;
    refImagePreview.innerHTML = '';
    if (referenceImages.length === 0) {
      refImagePreview.hidden = true;
      refImageBtn?.classList.remove('is-active');
      return;
    }
    refImagePreview.hidden = false;
    refImageBtn?.classList.add('is-active');
    referenceImages.forEach((img, idx) => {
      const wrap = document.createElement('div');
      wrap.className = 'webui-video-ref-item';
      const thumb = document.createElement('img');
      thumb.className = 'webui-video-ref-thumb';
      thumb.src = img.base64;
      thumb.alt = img.name || '';
      const removeBtn = document.createElement('button');
      removeBtn.type = 'button';
      removeBtn.className = 'webui-video-ref-remove';
      removeBtn.innerHTML = '&times;';
      removeBtn.addEventListener('click', () => {
        referenceImages.splice(idx, 1);
        renderRefPreviews();
      });
      wrap.appendChild(thumb);
      wrap.appendChild(removeBtn);
      refImagePreview.appendChild(wrap);
    });
  }

  function clearAllReferenceImages() {
    referenceImages = [];
    if (refImageInput) refImageInput.value = '';
    renderRefPreviews();
  }

  refImageBtn?.addEventListener('click', () => {
    if (sending) return;
    if (referenceImages.length >= MAX_REF_IMAGES) {
      toast(text('webui.video.errors.maxRefImages', `最多添加 ${MAX_REF_IMAGES} 张参考图`), 'error');
      return;
    }
    refImageInput?.click();
  });

  refImageInput?.addEventListener('change', async () => {
    const files = Array.from(refImageInput.files || []);
    if (!files.length) return;
    for (const file of files) {
      if (referenceImages.length >= MAX_REF_IMAGES) break;
      if (!file.type.startsWith('image/')) continue;
      if (file.size > 10 * 1024 * 1024) {
        toast(`${file.name}: image must be under 10 MB`, 'error');
        continue;
      }
      try {
        let base64 = await readFileAsBase64(file);
        // Compress large images to avoid Cloudflare blocking
        if (file.size > MAX_IMAGE_BYTES) {
          base64 = await compressImage(base64);
        }
        referenceImages.push({ base64, name: file.name });
      } catch {
        toast(`${file.name}: failed to read`, 'error');
      }
    }
    refImageInput.value = '';
    renderRefPreviews();
  });

  /* --- Drag-and-drop image upload --- */
  const composerEl = document.querySelector('.webui-video-composer');

  async function handleDroppedFiles(files) {
    for (const file of files) {
      if (referenceImages.length >= MAX_REF_IMAGES) break;
      if (!file.type.startsWith('image/')) continue;
      if (file.size > 10 * 1024 * 1024) {
        toast(`${file.name}: image must be under 10 MB`, 'error');
        continue;
      }
      try {
        let base64 = await readFileAsBase64(file);
        if (file.size > MAX_IMAGE_BYTES) {
          base64 = await compressImage(base64);
        }
        referenceImages.push({ base64, name: file.name });
      } catch {
        toast(`${file.name}: failed to read`, 'error');
      }
    }
    renderRefPreviews();
  }

  if (composerEl) {
    composerEl.addEventListener('dragenter', (e) => {
      e.preventDefault();
      e.stopPropagation();
      composerEl.classList.add('drag-over');
    });
    composerEl.addEventListener('dragover', (e) => {
      e.preventDefault();
      e.stopPropagation();
      composerEl.classList.add('drag-over');
    });
    composerEl.addEventListener('dragleave', (e) => {
      e.preventDefault();
      e.stopPropagation();
      composerEl.classList.remove('drag-over');
    });
    composerEl.addEventListener('drop', (e) => {
      e.preventDefault();
      e.stopPropagation();
      composerEl.classList.remove('drag-over');
      if (sending) return;
      const files = Array.from(e.dataTransfer?.files || []);
      if (files.length) handleDroppedFiles(files);
    });
  }

  /* --- Paste image upload --- */
  promptInput?.addEventListener('paste', (e) => {
    if (sending) return;
    const items = Array.from(e.clipboardData?.items || []);
    const imageFiles = items
      .filter((item) => item.kind === 'file' && item.type.startsWith('image/'))
      .map((item) => item.getAsFile())
      .filter(Boolean);
    if (imageFiles.length) {
      e.preventDefault();
      handleDroppedFiles(imageFiles);
    }
  });

  window.addEventListener('beforeunload', () => {
    if (!activeSocket) return;
    try { activeSocket.close(1000, 'unload'); } catch { }
    activeSocket = null;
  });

  boot().catch((error) => {
    console.error('webui video boot failed', error);
    toast(text('webui.video.errors.initFailed', '视频页面初始化失败'), 'error');
  });
})();
