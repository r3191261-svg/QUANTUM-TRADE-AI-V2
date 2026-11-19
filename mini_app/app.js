(() => {
  const tg = window.Telegram?.WebApp;
  const initData = tg?.initData || "";
  const view = document.getElementById("view");
  const toastNode = document.getElementById("toast");
  const state = { screen: "home", signalFilter: "all", profile: null, news: [], newsEnabled: false, config: null, pair: "EUR/USD", interval: "5", market: "forex" };

  const pairOptions = {
    forex: ["EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF", "AUD/USD", "USD/CAD", "NZD/USD", "EUR/GBP", "EUR/JPY", "EUR/CHF", "EUR/AUD", "GBP/JPY", "GBP/CHF", "AUD/JPY", "GBP/AUD"],
    crypto: ["BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT", "XRP/USDT", "DOGE/USDT", "TON/USDT"],
    commodities: ["Gold", "Silver", "Brent", "WTI", "Natural Gas", "Copper"],
    indices: ["S&P 500", "NASDAQ", "Dow Jones", "DAX", "FTSE 100", "RTS", "MOEX"],
    stocks: ["AAPL", "TSLA", "NVDA", "MSFT", "AMZN", "GOOGL"]
  };
  const symbols = {
    "EUR/USD":"FX:EURUSD","GBP/USD":"FX:GBPUSD","USD/JPY":"FX:USDJPY","USD/CHF":"FX:USDCHF","AUD/USD":"FX:AUDUSD","USD/CAD":"FX:USDCAD","NZD/USD":"FX:NZDUSD","EUR/GBP":"FX:EURGBP","EUR/JPY":"FX:EURJPY","EUR/CHF":"FX:EURCHF","EUR/AUD":"FX:EURAUD","GBP/JPY":"FX:GBPJPY","GBP/CHF":"FX:GBPCHF","AUD/JPY":"FX:AUDJPY","GBP/AUD":"FX:GBPAUD",
    "BTC/USDT":"BINANCE:BTCUSDT","ETH/USDT":"BINANCE:ETHUSDT","BNB/USDT":"BINANCE:BNBUSDT","SOL/USDT":"BINANCE:SOLUSDT","XRP/USDT":"BINANCE:XRPUSDT","DOGE/USDT":"BINANCE:DOGEUSDT","TON/USDT":"BINANCE:TONUSDT",
    "Gold":"OANDA:XAUUSD","Silver":"OANDA:XAGUSD","Brent":"TVC:UKOIL","WTI":"TVC:USOIL","Natural Gas":"NYMEX:NG1!","Copper":"COMEX:HG1!",
    "S&P 500":"SP:SPX","NASDAQ":"NASDAQ:NDX","Dow Jones":"DJ:DJI","DAX":"XETR:DAX","FTSE 100":"TVC:UKX","RTS":"MOEX:RTSI","MOEX":"MOEX:IMOEX",
    "AAPL":"NASDAQ:AAPL","TSLA":"NASDAQ:TSLA","NVDA":"NASDAQ:NVDA","MSFT":"NASDAQ:MSFT","AMZN":"NASDAQ:AMZN","GOOGL":"NASDAQ:GOOGL"
  };

  const esc = value => String(value ?? "").replace(/[&<>"']/g, ch => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[ch]));
  const safeUrl = value => { try { const u = new URL(value); return u.protocol === "https:" ? u.href : ""; } catch { return ""; } };
  const dateTime = value => { if (!value) return ""; const d = new Date(value); return Number.isNaN(d.valueOf()) ? "" : new Intl.DateTimeFormat("ru-RU", {hour:"2-digit",minute:"2-digit",day:"2-digit",month:"2-digit"}).format(d); };
  const resultText = status => status === "win" ? "Профит" : status === "loss" ? "Лосс" : "В работе";
  const resultIcon = status => status === "win" ? "✓" : status === "loss" ? "×" : "◉";
  const directionText = direction => /вверх|up|buy|call|рост/i.test(direction || "") ? "UP" : /вниз|down|sell|put|падение/i.test(direction || "") ? "DOWN" : "—";
  const directionClass = direction => directionText(direction) === "UP" ? "up" : directionText(direction) === "DOWN" ? "down" : "";

  async function api(path, options = {}) {
    const response = await fetch(path, {
      ...options,
      headers: { "Authorization": `tma ${initData}`, ...(options.body ? {"Content-Type":"application/json"} : {}), ...(options.headers || {}) }
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || `Ошибка сервера ${response.status}`);
    return data;
  }

  function toast(message) {
    toastNode.textContent = message;
    toastNode.classList.add("show");
    clearTimeout(toast._timer);
    toast._timer = setTimeout(() => toastNode.classList.remove("show"), 2600);
  }

  function signalCard(signal) {
    const direction = directionText(signal.direction);
    const dirLabel = direction === "UP" ? "↑ UP" : direction === "DOWN" ? "↓ DOWN" : "—";
    return `<article class="signal-row fade-in">
      <div class="signal-main"><div class="pair">${esc(signal.pair || "Сигнал")}</div><div class="signal-meta">${esc((signal.timeframe || "").toUpperCase())} · ${esc(dateTime(signal.created_at))}</div></div>
      <span class="direction ${directionClass(signal.direction)}">${dirLabel}</span>
      <span class="result-pill ${esc(signal.status)}">${resultIcon(signal.status)} ${resultText(signal.status)}</span>
    </article>`;
  }

  function stat(value, label, color = "blue") {
    return `<div class="stat-card"><div class="stat-value ${color}">${esc(value)}</div><div class="stat-label">${esc(label)}</div></div>`;
  }

  function renderHome() {
    const profile = state.profile || {};
    const latest = profile.signals?.[0];
    return `<section class="hero fade-in"><div class="eyebrow">QUANTUM TRADE AI · Центр рынка</div><h1>Торговые данные<br>в одном приложении</h1><p>Сигналы из подключённого канала, история их результатов и графики рынка.</p><div class="hero-actions"><button class="button primary" data-go="signals">Открыть сигналы</button><button class="button ghost" data-go="charts">График</button></div></section>
      <div class="section-head"><h2>Сигналы за сегодня</h2><span class="sub">по публикациям, доставленным вам</span></div>
      <div class="stats-grid">${stat(profile.signals_today ?? 0,"Всего","blue")}${stat(profile.wins_today ?? 0,"Профит","green")}${stat(profile.losses_today ?? 0,"Лосс","red")}</div>
      <section class="card advisor"><div class="quote-row"><div class="card-title"><span class="blue">◈</span> AI-советник рынка</div><span class="advisor-status">По сохранённым сигналам</span></div>
        <p class="news-description" style="margin:10px 0 0">${latest ? `Последняя подтверждённая публикация: <b>${esc(latest.pair || "инструмент не распознан")}</b>, направление ${esc(latest.direction || "не указано")}, статус «${esc(resultText(latest.status))}».` : "Пока нет доставленных сигналов для анализа."}</p>
        <div class="notice">Автоматический расчёт RSI, MACD и уровней не подключён: в проекте пока нет источника свечных данных и AI API. Здесь не показывается вымышленный прогноз.</div></section>
      <div class="section-head"><h2>Последние сигналы</h2><button class="tab" data-go="signals">Вся история →</button></div>
      ${latest ? profile.signals.slice(0,4).map(signalCard).join("") : `<div class="card empty">Публикации появятся здесь после доставки сигнала ботом.</div>`}
      <section class="card"><div class="card-title">Автоматическая торговля</div><p class="news-description">Подключение и сделки не подтверждены API. Используйте форму поддержки для проверки условий.</p><div class="hero-actions"><a class="button primary" href="${safeUrl(state.config?.registration_url)}" target="_blank" rel="noopener">Регистрация</a><a class="button ghost" href="${safeUrl(state.config?.support_url)}" target="_blank" rel="noopener">Поддержка</a></div></section>`;
  }

  function renderSignalList() {
    let signals = state.profile?.signals || [];
    if (state.signalFilter === "open") signals = signals.filter(s => s.status === "pending");
    if (state.signalFilter === "history") signals = signals.filter(s => s.status !== "pending");
    return `<div class="eyebrow">ЛИЧНЫЙ ПОТОК</div><h1 style="font-size:23px;margin:7px 0">Центр сигналов</h1>
      <div class="stats-grid">${stat(state.profile?.wins_today ?? 0,"Профит","green")}${stat(state.profile?.losses_today ?? 0,"Лосс","red")}${stat((state.profile?.signals || []).filter(s=>s.status==="pending").length,"В работе","blue")}</div>
      <div class="tabs"><button class="tab ${state.signalFilter === "all" ? "active" : ""}" data-filter="all">Все сигналы</button><button class="tab ${state.signalFilter === "open" ? "active" : ""}" data-filter="open">Открытые</button><button class="tab ${state.signalFilter === "history" ? "active" : ""}" data-filter="history">История</button></div>
      ${signals.length ? signals.map(signalCard).join("") : `<div class="card empty">В выбранном разделе пока нет сохранённых сигналов.</div>`}`;
  }

  function renderChart() {
    const symbol = symbols[state.pair] || "FX:EURUSD";
    const interval = state.interval;
    const src = `https://www.tradingview.com/widgetembed/?symbol=${encodeURIComponent(symbol)}&interval=${encodeURIComponent(interval)}&theme=dark&style=1&timezone=Asia%2FTashkent&withdateranges=1&hideideas=1&studies=%5B%5D&hide_side_toolbar=1&allow_symbol_change=1&save_image=0`;
    const markets = [["forex","Forex"],["crypto","Крипто"],["commodities","Товары"],["indices","Индексы"],["stocks","Акции"]];
    return `<div class="eyebrow">ГРАФИКИ · ВИДЖЕТ TRADINGVIEW</div><h1 style="font-size:22px;margin:7px 0">Рынок</h1>
      <div class="tabs">${markets.map(([key,label])=>`<button class="tab ${state.market===key?"active":""}" data-market="${key}">${label}</button>`).join("")}</div>
      <div class="chart-controls"><select class="select chart-select" id="pair-select">${(pairOptions[state.market]||pairOptions.forex).map(p=>`<option ${p===state.pair?"selected":""}>${esc(p)}</option>`).join("")}</select></div>
      <div class="chart-controls">${[["1","1м"],["5","5м"],["15","15м"],["30","30м"],["60","1ч"],["240","4ч"],["D","1д"],["W","1н"]].map(([v,l])=>`<button class="time-chip ${state.interval===v?"active":""}" data-interval="${v}">${l}</button>`).join("")}</div>
      <iframe class="chart-frame" title="График ${esc(state.pair)}" src="${src}" loading="lazy" referrerpolicy="no-referrer" allowfullscreen></iframe>
      <p class="chart-note">График предоставляется TradingView. Котировки, доступность инструмента и задержка обновления зависят от поставщика данных. Сигналы и котировки не являются рекомендацией.</p>`;
  }

  function renderNews() {
    if (!state.newsEnabled) return `<div class="eyebrow">ЛЕНТА РЫНКА</div><h1 style="font-size:22px;margin:7px 0">Новости</h1><div class="card empty">Перепубликация новостей и изображений RSS отключена, пока не подтверждены права на распространение материалов. Здесь не подставляются фиктивные статьи или фотографии.</div>`;
    if (!state.news.length) return `<div class="eyebrow">ЛЕНТА РЫНКА</div><h1 style="font-size:22px;margin:7px 0">Новости</h1><div class="card empty">В общей базе пока нет новостей. Лента обновляется серверным RSS-процессом.</div>`;
    return `<div class="eyebrow">РЕАЛЬНЫЕ ПУБЛИКАЦИИ</div><h1 style="font-size:22px;margin:7px 0">Новости рынка</h1>${state.news.map(item=>{
      const image = safeUrl(item.image);
      const href = safeUrl(item.url);
      return `<article class="card news-card fade-in">${image ? `<img class="news-image" src="${image}" alt="" loading="lazy" referrerpolicy="no-referrer">` : `<div class="news-no-image">Изображение не предоставлено источником</div>`}<div class="news-content"><div class="news-category">РЫНОК</div><div class="news-title">${esc(item.title)}</div><div class="news-description">${esc(item.description)}</div><div class="news-footer"><span>${esc(dateTime(item.published_at))}</span>${href ? `<a class="button ghost" href="${href}" target="_blank" rel="noopener">Источник ↗</a>` : ""}</div></div></article>`;
    }).join("")}`;
  }

  function renderProfile() {
    const p = state.profile || {};
    return `<div class="eyebrow">АККАУНТ TELEGRAM</div><h1 style="font-size:22px;margin:7px 0 14px">Профиль</h1>
      <section class="card"><div class="profile-head"><div class="avatar">♙</div><div><div class="profile-name">${esc(p.name || p.username || "Пользователь")}</div><div class="profile-id">Telegram ID: ${esc(p.id || "—")}</div></div></div><div class="setting-row" style="margin-top:10px"><div><div class="setting-label">Статус</div><div class="setting-help">Доступ к основному боту</div></div><span class="result-pill ${p.status === "active" ? "win" : "loss"}">${p.status === "active" ? "Активен" : "Ограничен"}</span></div></section>
      <section class="card"><div class="card-title">Настройки аккаунта</div><div class="setting-row"><div><div class="setting-label">Уведомления о сигналах</div><div class="setting-help">Синхронизировано с Telegram-ботом</div></div><button id="notification-switch" class="switch ${p.notifications ? "on" : ""}" role="switch" aria-checked="${!!p.notifications}" aria-label="Уведомления"></button></div>
        <a class="setting-row" href="${safeUrl(state.config?.support_url)}" target="_blank" rel="noopener" style="text-decoration:none;color:inherit"><div><div class="setting-label">Поддержка</div><div class="setting-help">Открыть чат QUANTUM TRADE AI</div></div><span class="blue">›</span></a>
        <a class="setting-row" href="${safeUrl(state.config?.registration_url)}" target="_blank" rel="noopener" style="text-decoration:none;color:inherit"><div><div class="setting-label">Автоматическая торговля</div><div class="setting-help">Информация и регистрация</div></div><span class="blue">›</span></a></section>
      <section class="card"><div class="card-title">Данные приложения</div><div class="setting-help" style="line-height:1.5;margin-top:8px">Профиль подтверждён подписью Telegram WebApp. ID берётся из Telegram, а не из параметра страницы.</div></section>`;
  }

  function render() {
    document.querySelectorAll(".nav-item").forEach(item => item.classList.toggle("active", item.dataset.screen === state.screen));
    if (state.screen === "home") view.innerHTML = renderHome();
    if (state.screen === "signals") view.innerHTML = renderSignalList();
    if (state.screen === "charts") view.innerHTML = renderChart();
    if (state.screen === "news") view.innerHTML = renderNews();
    if (state.screen === "profile") view.innerHTML = renderProfile();
    if (state.screen === "charts") document.getElementById("pair-select")?.addEventListener("change", event => { state.pair = event.target.value; render(); });
    document.getElementById("notification-switch")?.addEventListener("click", async event => {
      const next = !state.profile.notifications;
      event.currentTarget.disabled = true;
      try {
        const result = await api("/api/notifications", {method:"POST",body:JSON.stringify({enabled:next})});
        state.profile.notifications = result.notifications;
        render();
        toast("Настройка уведомлений сохранена");
      } catch (error) { toast(error.message); event.currentTarget.disabled = false; }
    });
  }

  async function refresh() {
    if (!initData) {
      view.innerHTML = `<section class="card error-card"><img src="/logo.svg" class="brand-mark" alt=""><h2>Откройте приложение через Telegram</h2><p>Для защиты аккаунта Mini App принимает только подписанные Telegram данные. Запустите его кнопкой в чате с QUANTUM TRADE AI.</p></section>`;
      return;
    }
    if (tg) { tg.ready(); tg.expand(); }
    try {
      const [profile, config, news] = await Promise.all([api("/api/me"), api("/api/config"), api("/api/news")]);
      state.profile = profile;
      state.config = config;
      state.news = news.news || [];
      state.newsEnabled = !!news.enabled;
      render();
    } catch (error) {
      view.innerHTML = `<section class="card error-card"><h2>Не удалось загрузить приложение</h2><p>${esc(error.message)}<br>Попробуйте обновить экран или открыть Mini App заново из Telegram.</p><button class="button primary" id="retry-button">Повторить</button></section>`;
      document.getElementById("retry-button")?.addEventListener("click", refresh);
    }
  }

  document.querySelectorAll(".nav-item").forEach(button => button.addEventListener("click", () => { state.screen = button.dataset.screen; render(); window.scrollTo({top:0,behavior:"smooth"}); }));
  document.getElementById("refresh-button").addEventListener("click", async () => { await refresh(); toast("Данные обновлены"); });
  document.addEventListener("click", event => {
    const go = event.target.closest("[data-go]");
    if (go) { state.screen = go.dataset.go; render(); window.scrollTo({top:0,behavior:"smooth"}); return; }
    const filter = event.target.closest("[data-filter]");
    if (filter) { state.signalFilter = filter.dataset.filter; render(); return; }
    const market = event.target.closest("[data-market]");
    if (market) { state.market = market.dataset.market; const opts=pairOptions[state.market]||pairOptions.forex; if(!opts.includes(state.pair)) state.pair=opts[0]; render(); return; }
    const interval = event.target.closest("[data-interval]");
    if (interval) { state.interval = interval.dataset.interval; render(); }
  });

  refresh();
  setInterval(() => { if (initData && document.visibilityState === "visible") refresh().catch(() => {}); }, 30000);
})();
