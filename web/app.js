/* ==========================================================================
 * MCWConverter — 四步向导状态机 + pywebview 后端桥接
 *
 * 后端 API（window.pywebview.api，无后端时自动降级为 mock 演示数据）：
 *   select_folder()                 -> { path, world_name | null }
 *   select_archive()                -> { path, extracted_path }
 *   detect(path)                    -> { world_name, platform, version, dimensions }
 *   list_versions(platform?)        -> [{ label, data_version, recommended, lossy, ... }]
 *   convert(path, version)          -> 触发转换，完成时 resolve
 *   pick_output() / save_to()       -> 输出路径
 * 进度回推：后端调用 window.onProgress(json 字符串)
 *   -> { phase:'decrypt'|'convert', done:N, total:N, text:string }
 * ========================================================================== */
(function () {
  'use strict';

  var STEP_SELECT = 1;
  var STEP_EXPORT = 2;
  var STEP_CONVERT = 3;
  var STEP_SAVE = 4;

  var EDITION_LABEL = { bedrock: '基岩版', java: 'Java 版' };
  var PLATFORM_ICON = { bedrock: 'stone', java: 'grass' };

  // ---------- 状态 ----------
  var state = {
    step: STEP_SELECT,
    world: null,           // { path, extracted_path, world_name, platform, version, dimensions }
    bedrockVersions: [],
    javaVersions: [],
    selected: null,        // { platform, version }
    expanded: {},          // 每个分区是否展开全部
    converting: false,
    failed: false,
    errorMsg: '',
    loadError: '',
    progress: { phase: 'decrypt', done: 0, total: 1, text: '' },
    result: null,
    savedTo: null,
    outputName: '',
  };

  // ---------- DOM ----------
  function el(id) { return document.getElementById(id); }

  /** 与后端一致的文件夹名清洗：替换 Windows 非法字符、去首尾空格/点。 */
  function sanitizeName(s) {
    return String(s || '')
      .replace(/[\\/:*?"<>|\u0000-\u001f]/g, '_')
      .trim()
      .replace(/\.+$/, '')
      .slice(0, 120);
  }

  var titleEl = el('title');
  var subtitleEl = el('subtitle');
  var contentEl = el('content');
  var buttonBarEl = el('buttonBar');
  var overlayEl = el('overlay');
  var overlayTitleEl = el('overlayTitle');
  var overlayBodyEl = el('overlayBody');

  // ---------- pywebview API 桥接 ----------
  function getApi() {
    try {
      if (window.pywebview && window.pywebview.api) return window.pywebview.api;
    } catch (e) { /* ignore */ }
    return null;
  }

  // 后端进度回推入口（约定：window.onProgress(json 字符串)）
  window.onProgress = function (payload) {
    try {
      var obj = typeof payload === 'string' ? JSON.parse(payload) : payload;
      if (!obj || typeof obj !== 'object') return;

      if (obj.phase === 'done') {
        state.converting = false;
        state.result = obj.result || {};
        // 默认命名：原存档名 + 转换后的版本号，如「我的世界_Java_1.20.4」
        var wn = (state.world && (state.world.world_name || state.world.name)) ||
          (state.result && state.result.world_name) || 'world';
        var ver = (state.result && state.result.target_version_str) || '';
        state.outputName = sanitizeName(wn + (ver ? '_Java_' + ver : ''));
        state.step = STEP_SAVE;
        render();
        return;
      }
      if (obj.phase === 'error') {
        state.converting = false;
        state.failed = true;
        state.errorMsg = obj.error || '发生未知错误。';
        render();
        return;
      }

      state.progress = {
        phase: obj.phase || 'convert',
        done: Number(obj.done) || 0,
        total: Number(obj.total) || 1,
        text: obj.text || '',
      };
      if (state.step === STEP_CONVERT && state.converting) renderStep3();
    } catch (e) { /* ignore */ }
  };

  function apiCall(name) {
    var args = Array.prototype.slice.call(arguments, 1);
    var api = getApi();
    if (api && typeof api[name] === 'function') {
      try {
        return Promise.resolve(api[name].apply(api, args));
      } catch (e) {
        return Promise.reject(e);
      }
    }
    return mockCall(name, args);
  }

  // ---------- 无后端时的演示兜底（浏览器直接打开也能走通四步） ----------
  var MOCK_DELAY = 240;

  function mockBedrock() {
    return [
      { label: '1.21.40', data_version: 2231, recommended: false, lossy: false, beta: true },
      { label: '1.21.0', data_version: 2230, recommended: true, lossy: false },
      { label: '1.20.80', data_version: 2200, recommended: false, lossy: false },
      { label: '1.20.60', data_version: 2170, recommended: false, lossy: true },
      { label: '1.19.80', data_version: 2070, recommended: false, lossy: true },
      { label: '1.18.30', data_version: 1930, recommended: false, lossy: true },
    ];
  }

  function mockJava() {
    return [
      { label: '1.20.4', data_version: 3700, recommended: true, lossy: false },
      { label: '1.20.2', data_version: 3698, recommended: false, lossy: false },
      { label: '1.20.1', data_version: 3693, recommended: false, lossy: false },
      { label: '1.19.4', data_version: 3465, recommended: false, lossy: true },
      { label: '1.19.2', data_version: 3447, recommended: false, lossy: true },
      { label: '1.18.2', data_version: 3342, recommended: false, lossy: true },
    ];
  }

  function mockConvert() {
    return new Promise(function (resolve) {
      var i = 0;
      var decryptTotal = 8;
      var convertTotal = 12;
      var timer = setInterval(function () {
        i += 1;
        var phase, done, total, text;
        if (i <= decryptTotal) {
          phase = 'decrypt'; done = i; total = decryptTotal; text = '正在解密 LevelDB 文件...';
        } else {
          phase = 'convert'; done = i - decryptTotal; total = convertTotal; text = '正在转换区块...';
        }
        window.onProgress(JSON.stringify({ phase: phase, done: done, total: total, text: text }));
        if (i >= decryptTotal + convertTotal) {
          clearInterval(timer);
          var worldName = (state.world && state.world.world_name) || 'world';
          var res = { final_dir: '_java', world_name: worldName };
          window.onProgress(JSON.stringify({ phase: 'done', result: res }));
          resolve(res);
        }
      }, 120);
    });
  }

  function mockCall(name, args) {
    switch (name) {
      case 'select_folder':
        return new Promise(function (resolve) {
          setTimeout(function () {
            resolve({ path: 'C:\\Users\\demo\\worlds\\示例世界', world_name: '示例世界' });
          }, MOCK_DELAY);
        });
      case 'select_archive':
        return new Promise(function (resolve) {
          setTimeout(function () {
            resolve({ path: 'C:\\Users\\demo\\worlds\\示例世界.zip', extracted_path: 'C:\\Users\\demo\\worlds\\示例世界' });
          }, MOCK_DELAY);
        });
      case 'detect':
        return new Promise(function (resolve) {
          setTimeout(function () {
            resolve({
              world_name: '示例世界',
              platform: 'bedrock',
              version: '1.20.80',
              dimensions: { '主世界': 128, '下界': 40, '末地': 10 },
            });
          }, MOCK_DELAY);
        });
      case 'list_versions': {
        var platform = args[0];
        var list = platform === 'java' ? mockJava() : mockBedrock();
        return new Promise(function (resolve) {
          setTimeout(function () { resolve(list.map(function (v) { return Object.assign({}, v); })); }, MOCK_DELAY);
        });
      }
      case 'convert':
        return mockConvert();
      case 'pick_output':
        return new Promise(function (resolve) {
          setTimeout(function () { resolve('C:\\Users\\demo\\Documents\\output'); }, MOCK_DELAY);
        });
      case 'save_to':
        return new Promise(function (resolve) {
          var folderName = args[1] || 'world';
          setTimeout(function () {
            resolve({ ok: true, path: 'C:\\Users\\demo\\Documents\\output\\' + folderName });
          }, MOCK_DELAY);
        });
      case 'save_default':
        return new Promise(function (resolve) {
          var folderName = args[0] || 'world';
          setTimeout(function () {
            resolve({ ok: true, path: 'C:\\Users\\demo\\MCWConverter\\saved\\' + folderName });
          }, MOCK_DELAY);
        });
      default:
        return Promise.resolve(null);
    }
  }

  // ---------- 工具 ----------
  function escHtml(s) {
    return String(s === null || s === undefined ? '' : s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
  }

  function escAttr(s) {
    return escHtml(s).replace(/"/g, '&quot;');
  }

  function errMsg(e) {
    if (!e) return '未知错误';
    if (typeof e === 'string') return e;
    return e.message || String(e);
  }

  function normalize(list, platform) {
    if (!Array.isArray(list)) return [];
    return list.map(function (v) {
      var o;
      if (typeof v === 'string') {
        o = { label: v, data_version: null, recommended: false, lossy: false };
      } else if (v && typeof v === 'object') {
        o = Object.assign({}, v);
      } else {
        o = { label: String(v), data_version: null, recommended: false, lossy: false };
      }
      o._platform = platform;
      return o;
    });
  }

  function splitVersions(all) {
    var bedrock = [];
    var java = [];
    (all || []).forEach(function (v) {
      var platform = v && v.platform ? String(v.platform).toLowerCase() : null;
      var label = String(v && v.label ? v.label : '');
      if (platform === 'java') java.push(v);
      else if (platform === 'bedrock') bedrock.push(v);
      else if (/bedrock/i.test(label)) bedrock.push(v);
      else java.push(v);
    });
    state.bedrockVersions = normalize(bedrock, 'bedrock');
    state.javaVersions = normalize(java, 'java');
  }

  // ---------- 版本列表加载（兼容 有参/无参 两种后端签名） ----------
  function loadVersions() {
    var api = getApi();
    if (api && typeof api.list_versions === 'function') {
      return Promise.all([
        Promise.resolve(api.list_versions('bedrock')),
        Promise.resolve(api.list_versions('java')),
      ]).then(function (res) {
        state.bedrockVersions = normalize(res[0], 'bedrock');
        state.javaVersions = normalize(res[1], 'java');
      }).catch(function (e) {
        // 回退：无参 list_versions()，按 item.platform / label 分列
        return Promise.resolve(api.list_versions()).then(function (all) {
          splitVersions(all);
        }).catch(function (e2) {
          state.loadError = errMsg(e2 || e);
        });
      });
    }
    return apiCall('list_versions', 'bedrock').then(function (bedrock) {
      state.bedrockVersions = normalize(bedrock, 'bedrock');
      return apiCall('list_versions', 'java');
    }).then(function (java) {
      state.javaVersions = normalize(java, 'java');
    });
  }

  // ---------- 布局辅助 ----------
  function buildMeta(w) {
    if (!w) return '';
    var parts = [];
    if (w.platform) parts.push(EDITION_LABEL[w.platform] || w.platform);
    if (w.version) parts.push('v' + w.version);
    if (w.dimensions) {
      Object.keys(w.dimensions).forEach(function (d) {
        parts.push(d + ' ' + w.dimensions[d] + ' 区块');
      });
    }
    return parts.join(' · ');
  }

  function setHeader(title, subtitle) {
    titleEl.textContent = title;
    subtitleEl.textContent = subtitle;
  }

  function setStepper() {
    var active = state.step;
    for (var i = 1; i <= 4; i++) {
      var st = el('st' + i);
      if (st) st.classList.toggle('active', i <= active);
    }
    for (var j = 1; j <= 3; j++) {
      var cn = el('c' + j);
      if (cn) cn.classList.toggle('done', active > j);
    }
  }

  function setButtons(buttons) {
    buttonBarEl.innerHTML = '';
    buttons.forEach(function (b) {
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'btn ' + (b.variant || 'btn-primary');
      btn.textContent = b.label;
      btn.disabled = !b.enabled;
      if (b.enabled && b.onClick) btn.addEventListener('click', b.onClick);
      buttonBarEl.appendChild(btn);
    });
  }

  // ---------- 渲染入口 ----------
  function render() {
    setStepper();
    if (state.step === STEP_SELECT) renderStep1();
    else if (state.step === STEP_EXPORT) renderStep2();
    else if (state.step === STEP_CONVERT) renderStep3();
    else if (state.step === STEP_SAVE) renderStep4();
  }

  // ---------- 步骤 1：选择世界 ----------
  function renderStep1() {
    if (!state.world) {
      setHeader('选择世界', '请选择你的世界文件夹或存档压缩包。');
      contentEl.className = 'content';
      contentEl.innerHTML =
        '<div class="entry-row">' +
          '<button type="button" class="entry-card" id="cardFolder">' +
            '<span class="entry-title">选择世界文件夹</span>' +
            '<span class="entry-desc">选择世界文件夹，其余交给我们处理。</span>' +
          '</button>' +
          '<button type="button" class="entry-card" id="cardArchive">' +
            '<span class="entry-title">选择存档压缩包</span>' +
            '<span class="entry-desc">支持格式：.zip、.mcworld、.mctemplate、.tar 等。</span>' +
          '</button>' +
        '</div>';
      el('cardFolder').addEventListener('click', chooseFolder);
      el('cardArchive').addEventListener('click', chooseArchive);
      setButtons([{ label: '开始', variant: 'btn-primary', enabled: false }]);
      return;
    }
    renderStep1Selected();
  }

  function renderStep1Selected() {
    var w = state.world;
    var name = w.world_name || w.name || '未知世界';
    var meta = buildMeta(w);
    setHeader('选择世界', '世界已就绪，可以开始转换。');
    contentEl.className = 'content';
    contentEl.innerHTML =
      '<div class="status-block">' +
        '<div class="status-title">世界已选择</div>' +
        '<div class="status-desc">你的世界 <span class="em">' + escHtml(name) + '</span> 已就绪。</div>' +
        (meta ? '<div class="status-meta">' + escHtml(meta) + '</div>' : '') +
      '</div>';
    setButtons([
      { label: '取消', variant: 'btn-danger', enabled: true, onClick: cancelSelection },
      { label: '开始', variant: 'btn-primary', enabled: true, onClick: startExport },
    ]);
  }

  // ---------- 步骤 2：导出为 ----------
  function renderStep2() {
    setHeader('导出为', '请选择要导出到的 Minecraft 版本。');

    if (!state.bedrockVersions.length && !state.javaVersions.length) {
      contentEl.className = 'content';
      if (state.loadError) {
        contentEl.innerHTML =
          '<div class="status-block">' +
            '<div class="status-title error">版本列表加载失败</div>' +
            '<div class="status-desc">' + escHtml(state.loadError) + '</div>' +
          '</div>';
      } else {
        contentEl.innerHTML =
          '<div class="status-block"><div class="status-title">正在加载版本列表...</div></div>';
      }
      setButtons(step2Buttons());
      return;
    }

    contentEl.className = 'content scrollable';
    contentEl.innerHTML =
      buildSection('基岩版', 'bedrock', state.bedrockVersions) +
      buildSection('Java 版', 'java', state.javaVersions);
    bindVersionCards();
    setButtons(step2Buttons());
  }

  function buildSection(headerText, platform, versions) {
    var html = '<section class="section"><div class="section-title">' + escHtml(headerText) + '</div>';
    if (!versions.length) {
      html += '<div class="status-meta">暂无可选版本。</div></section>';
      return html;
    }
    var expanded = !!state.expanded[platform];
    var shown = expanded ? versions : versions.slice(0, 3);
    var icon = PLATFORM_ICON[platform];
    html += '<div class="card-grid">';
    shown.forEach(function (v) {
      var selected = state.selected && state.selected.platform === platform && state.selected.version === v;
      html += buildVersionCard(v, platform, icon, selected);
    });
    html += '</div>';
    html += '<div class="show-all-wrap">' +
      '<button type="button" class="btn btn-info" data-action="toggle" data-platform="' + escAttr(platform) + '">' +
        (expanded ? '收起' : '显示全部 (' + versions.length + ')') +
      '</button></div>';
    html += '</section>';
    return html;
  }

  function buildVersionCard(v, platform, icon, selected) {
    var isSource = state.world && platform === state.world.platform &&
      String(v.label) === String(state.world.version);
    var badges = '';
    if (v.beta) badges += '<span class="badge beta">测试版</span>';
    if (isSource) badges += '<span class="badge source">源版本</span>';
    var sub = String(v.label) + (v.lossy ? ' · 有损转换' : '');
    return '<button type="button" class="ver-card' + (selected ? ' selected' : '') + '" ' +
      'data-platform="' + escAttr(platform) + '" data-label="' + escAttr(String(v.label)) + '">' +
      '<span class="ver-icon"><img src="../assets/' + icon + '.svg" alt=""></span>' +
      '<span class="ver-text">' +
        '<span class="ver-name">' + escHtml(EDITION_LABEL[platform]) + '</span>' +
        '<span class="ver-ver">' + escHtml(sub) + '</span>' +
      '</span>' +
      badges +
      '</button>';
  }

  function bindVersionCards() {
    contentEl.querySelectorAll('.ver-card').forEach(function (card) {
      var platform = card.getAttribute('data-platform');
      var label = card.getAttribute('data-label');
      var list = platform === 'java' ? state.javaVersions : state.bedrockVersions;
      var version = null;
      for (var i = 0; i < list.length; i++) {
        if (String(list[i].label) === label) { version = list[i]; break; }
      }
      card.addEventListener('click', function () { selectVersion(platform, version); });
    });
    contentEl.querySelectorAll('.btn-info[data-action="toggle"]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var platform = btn.getAttribute('data-platform');
        state.expanded[platform] = !state.expanded[platform];
        render();
      });
    });
  }

  function step2Buttons() {
    var selected = !!(state.selected && state.selected.version);
    return [
      { label: '高级选项', variant: 'btn-secondary', enabled: selected, onClick: showAdvanced },
      { label: '重新开始', variant: 'btn-danger', enabled: true, onClick: restart },
      { label: '转换', variant: 'btn-primary', enabled: selected, onClick: startConvert },
    ];
  }

  function selectVersion(platform, version) {
    state.selected = { platform: platform, version: version };
    render();
  }

  // ---------- 步骤 3：转换中 ----------
  function renderStep3() {
    if (state.failed) {
      setHeader('转换失败', '转换过程中出现错误。');
      contentEl.className = 'content';
      contentEl.innerHTML =
        '<div class="status-block">' +
          '<div class="status-title error">转换失败</div>' +
          '<div class="status-desc">' + escHtml(state.errorMsg || '发生未知错误。') + '</div>' +
        '</div>';
      setButtons([{ label: '重新开始', variant: 'btn-danger', enabled: true, onClick: restart }]);
      return;
    }

    setHeader('转换中', '正在转换世界，请稍候。');
    contentEl.className = 'content';
    var p = state.progress;
    var total = Math.max(p.total, 1);
    var pct = Math.max(0, Math.min(100, Math.round((p.done / total) * 100)));
    var phaseLabel = p.phase === 'decrypt' ? '解密中' : '转换中';
    contentEl.innerHTML =
      '<div class="progress-block">' +
        '<div class="status-title">' + phaseLabel + '...</div>' +
        '<div class="progress-track"><div class="progress-fill" style="width:' + pct + '%"></div></div>' +
        '<div class="stage-text">' + escHtml(p.text || '处理中...') + '</div>' +
        '<div class="count-text">' + p.done + ' / ' + total + '</div>' +
      '</div>';
    setButtons([{ label: '重新开始', variant: 'btn-danger', enabled: false }]);
  }

  // ---------- 步骤 4：保存世界 ----------
  function renderStep4() {
    var edition = '';
    var versionLabel = '';
    var subtitle = '世界已就绪，可以保存。';
    if (state.selected && state.selected.version) {
      edition = EDITION_LABEL[state.selected.platform] || '';
      versionLabel = state.selected.version.label || '';
      subtitle = ('你的 ' + edition + ' ' + versionLabel + ' 世界已就绪，可以保存。').replace(/\s+/g, ' ').trim();
    }
    setHeader('保存世界', subtitle);
    contentEl.className = 'content';
    var savedNote = state.savedTo
      ? '<div class="status-meta">已保存到：' + escHtml(state.savedTo) + '</div>'
      : '';
    var inputDisabled = state.savedTo ? ' disabled' : '';
    contentEl.innerHTML =
      '<div class="status-block">' +
        '<div class="status-title">准备保存</div>' +
        '<div class="status-desc">世界已转换完成，现在可以保存到指定位置。</div>' +
        '<div class="form-row">' +
          '<label for="outputName">存档名称</label>' +
          '<input type="text" id="outputName" class="text-input" value="' +
            escAttr(state.outputName || '') + '" placeholder="输出存档文件夹名称"' + inputDisabled + '>' +
        '</div>' +
        savedNote +
      '</div>';
    setButtons([
      { label: '重新开始', variant: 'btn-danger', enabled: true, onClick: restart },
      { label: '保存到应用目录', variant: 'btn-secondary', enabled: !state.savedTo, onClick: saveDefault },
      { label: '保存', variant: 'btn-primary', enabled: !state.savedTo, onClick: saveWorld },
    ]);
  }

  // ---------- 动作 ----------
  function chooseFolder() {
    apiCall('select_folder').then(function (picked) {
      if (!picked || !picked.path) return;
      var info = { path: picked.path, world_name: picked.world_name || null };
      return apiCall('detect', picked.path).then(function (det) {
        if (det && typeof det === 'object') {
          info = Object.assign({ path: picked.path }, det);
        }
        return info;
      }).catch(function () { return info; });
    }).then(function (info) {
      if (!info) return;
      state.world = info;
      state.bedrockVersions = [];
      state.javaVersions = [];
      render();
    }).catch(function (e) {
      showOverlay('错误', '<p>' + escHtml('无法打开世界文件夹：' + errMsg(e)) + '</p>');
    });
  }

  function chooseArchive() {
    apiCall('select_archive').then(function (picked) {
      if (!picked || !picked.extracted_path) return;
      var info = { path: picked.path, extracted_path: picked.extracted_path, world_name: null };
      return apiCall('detect', picked.extracted_path).then(function (det) {
        if (det && typeof det === 'object') {
          info = Object.assign({ path: picked.path, extracted_path: picked.extracted_path }, det);
        }
        return info;
      }).catch(function () { return info; });
    }).then(function (info) {
      if (!info) return;
      state.world = info;
      state.bedrockVersions = [];
      state.javaVersions = [];
      render();
    }).catch(function (e) {
      showOverlay('错误', '<p>' + escHtml('无法导入压缩包：' + errMsg(e)) + '</p>');
    });
  }

  function cancelSelection() {
    state.world = null;
    render();
  }

  function startExport() {
    state.step = STEP_EXPORT;
    state.selected = null;
    state.loadError = '';
    render();
    loadVersions().then(function () {
      if (!state.loadError && !state.bedrockVersions.length && !state.javaVersions.length) {
        state.loadError = '没有可用的目标版本。';
      }
      if (state.step === STEP_EXPORT) render();
    }).catch(function (e) {
      state.loadError = errMsg(e);
      if (state.step === STEP_EXPORT) render();
    });
  }

  function startConvert() {
    state.step = STEP_CONVERT;
    state.converting = true;
    state.failed = false;
    state.result = null;
    state.progress = { phase: 'decrypt', done: 0, total: 1, text: '' };
    render();

    var sel = state.selected && state.selected.version;
    var versionLabel = sel ? (sel.label || sel.version || null) : null;
    var srcPath = state.world.extracted_path || state.world.path;

    apiCall('convert', srcPath, versionLabel).then(function (result) {
      // 真实后端为异步：完成由 window.onProgress 的 phase='done' 事件推进到 SAVE。
      // 此处仅在同步/显式返回结果时兜底推进（兼容 mock 等同步实现）。
      if (result && typeof result === 'object' && !result.status && (result.final_dir != null || result.out_path != null)) {
        state.converting = false;
        state.result = result || {};
        state.step = STEP_SAVE;
        render();
      }
    }).catch(function (e) {
      state.converting = false;
      state.failed = true;
      state.errorMsg = errMsg(e);
      render();
    });
  }

  function _readNameInput() {
    var nameInput = el('outputName');
    var name = nameInput ? nameInput.value.trim() : '';
    return sanitizeName(name);
  }

  function _handleSaveResult(out) {
    if (out && typeof out === 'object') {
      if (out.ok === false) {
        showOverlay('保存失败', '<p>' + escHtml(out.error || '未知错误') + '</p>');
        return;
      }
      out = out.path || out.result || null;
    }
    if (!out) return; // 用户取消目录选择等
    state.savedTo = String(out);
    render();
  }

  function saveWorld() {
    var api = getApi();
    var name = _readNameInput() || state.outputName || 'world';

    // 优先用 save_to（后端内部会弹目录选择并真正复制产物），返回 {ok,path} 或 {ok:false,error}。
    var useSaveTo = api && typeof api.save_to === 'function';
    var promise = useSaveTo
      ? apiCall('save_to', null, name)
      : apiCall('pick_output');
    promise.then(_handleSaveResult).catch(function (e) {
      showOverlay('保存失败', '<p>' + escHtml(errMsg(e)) + '</p>');
    });
  }

  /** 保存到应用工作目录（桌面等受保护目录被安全软件拦截时的可靠出路）。 */
  function saveDefault() {
    var name = _readNameInput() || state.outputName || 'world';
    apiCall('save_default', name).then(_handleSaveResult).catch(function (e) {
      showOverlay('保存失败', '<p>' + escHtml(errMsg(e)) + '</p>');
    });
  }

  function restart() {
    state.world = null;
    state.bedrockVersions = [];
    state.javaVersions = [];
    state.selected = null;
    state.expanded = {};
    state.converting = false;
    state.failed = false;
    state.errorMsg = '';
    state.loadError = '';
    state.progress = { phase: 'decrypt', done: 0, total: 1, text: '' };
    state.result = null;
    state.savedTo = null;
    state.outputName = '';
    state.step = STEP_SELECT;
    render();
  }

  // ---------- 覆盖层 ----------
  function showAdvanced() {
    showOverlay('高级选项',
      '<p>已知的转换限制（Amulet 引擎）：</p><ul>' +
      '<li>实体（生物 / 动物）不会被保留，它们会在游戏中重新生成。</li>' +
      '<li>跨平台转换时部分物品可能会丢失。</li>' +
      '<li>平台专属方块会被替换为最接近的原版方块。</li>' +
      '<li>出生点可能会略有偏移（默认 0, ~80, 0）。</li>' +
      '</ul>');
  }

  function showOverlay(title, bodyHtml) {
    overlayTitleEl.textContent = title;
    overlayBodyEl.innerHTML = bodyHtml;
    overlayEl.hidden = false;
  }

  function hideOverlay() {
    overlayEl.hidden = true;
  }

  // ---------- 初始化 ----------
  function init() {
    el('overlayClose').addEventListener('click', hideOverlay);
    overlayEl.addEventListener('click', function (e) {
      if (e.target === overlayEl) hideOverlay();
    });
    // pywebview 就绪事件：api 采用惰性读取，无需额外状态变更
    window.addEventListener('pywebviewready', function () { /* no-op */ });
    render();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
