const supportedBrands = [
  "Apple",
  "Samsung",
  "Garmin",
  "Huawei",
  "Amazfit",
  "Xiaomi",
  "Redmi",
  "Google",
  "OnePlus",
  "Oppo",
  "Motorola",
];

// Common misspellings and shorthand names that users type during quick checks.
const brandAliases = {
  apple: "Apple",
  applt: "Apple",
  aplle: "Apple",
  iphone: "Apple",
  samsung: "Samsung",
  samsng: "Samsung",
  garmin: "Garmin",
  huawei: "Huawei",
  amazfit: "Amazfit",
  xiaomi: "Xiaomi",
  redmi: "Redmi",
  google: "Google",
  pixel: "Google",
  oneplus: "OnePlus",
  "one plus": "OnePlus",
  oppo: "Oppo",
  motorola: "Motorola",
  moto: "Motorola",
};

// Example chips double as a small manual test set for the demo UI.
const examples = [
  "Apple Watch Series 9",
  "apple watch ultra 2",
  "Applt watch ultra",
  "Samsung Galaxy Watch7",
  "Garmin Fenix 7 Pro",
  "Garmin Forerunner 165",
  "Huawei Watch GT 4",
  "Amazfit GTR 4",
  "Xiaomi Watch 2 Pro",
  "Google Pixel Watch 2",
  "OnePlus Watch 2",
  "Motorola Moto 360",
];

const searchInput = document.querySelector("#watchSearch");
const searchButton = document.querySelector("#searchButton");
const debugToggle = document.querySelector("#debugToggle");
const statusText = document.querySelector("#statusText");
const cardMount = document.querySelector("#cardMount");
const suggestionsBox = document.querySelector("#suggestions");
const examplesBox = document.querySelector("#examples");

let currentCard = null;
let activeRequestId = 0;

// Make free-form input stable enough for matching: casing, punctuation, and extra spaces are ignored.
function normalizeQuery(value) {
  return String(value || "")
    .toLowerCase()
    .replace(/[._-]+/g, " ")
    .replace(/[^\p{L}\p{N}\s+]/gu, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function compact(value) {
  return normalizeQuery(value).replace(/\s+/g, "");
}

// Tiny edit-distance helper. It is enough for typos like "Applt" without adding a dependency.
function levenshtein(a, b) {
  const left = compact(a);
  const right = compact(b);
  if (!left || !right) return Math.max(left.length, right.length);
  const dp = Array.from({ length: left.length + 1 }, (_, i) => [i]);
  for (let j = 1; j <= right.length; j += 1) dp[0][j] = j;
  for (let i = 1; i <= left.length; i += 1) {
    for (let j = 1; j <= right.length; j += 1) {
      const cost = left[i - 1] === right[j - 1] ? 0 : 1;
      dp[i][j] = Math.min(dp[i - 1][j] + 1, dp[i][j - 1] + 1, dp[i - 1][j - 1] + cost);
    }
  }
  return dp[left.length][right.length];
}

function detectBrand(query) {
  // Prefer explicit aliases, then fall back to a one-character typo check on the first word.
  const normalized = normalizeQuery(query);
  const words = normalized.split(" ").filter(Boolean);
  const firstTwo = words.slice(0, 2).join(" ");

  for (const candidate of [firstTwo, words[0], ...words]) {
    if (brandAliases[candidate]) return brandAliases[candidate];
  }

  for (const brand of supportedBrands) {
    const brandKey = normalizeQuery(brand);
    if (normalized.includes(brandKey)) return brand;
    if (levenshtein(words[0] || "", brandKey) <= 1) return brand;
  }

  return null;
}

function removeBrandWords(query, brand) {
  // Model lookup expects "watch ultra 2", not "apple watch ultra 2".
  let value = normalizeQuery(query);
  if (!brand) return value;
  const aliases = Object.entries(brandAliases)
    .filter(([, target]) => target === brand)
    .map(([alias]) => alias)
    .sort((a, b) => b.length - a.length);

  for (const alias of aliases) {
    value = value.replace(new RegExp(`(^|\\s)${escapeRegExp(alias)}(?=\\s|$)`, "g"), " ");
  }
  return normalizeQuery(value);
}

function escapeRegExp(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function extractModelName(query, brand) {
  let model = removeBrandWords(query, brand);

  // Brand-specific fixes cover common user wording that differs from normalized DB names.
  if (brand === "Samsung" && /^watch\s*\d/.test(model)) {
    model = model.replace(/^watch\s*(\d)/, "galaxy watch$1");
  }
  if (brand === "Samsung" && /^galaxy watch\s+(\d)/.test(model)) {
    model = model.replace(/^galaxy watch\s+(\d)/, "galaxy watch$1");
  }
  if (brand === "Google" && !model.startsWith("pixel")) {
    model = `pixel ${model}`;
  }
  if (brand === "Motorola" && model.startsWith("360")) {
    model = `moto ${model}`;
  }

  return normalizeModelName(model);
}

function normalizeModelName(value) {
  return normalizeQuery(value)
    .replace(/\bs(\d)\b/g, "series $1")
    .replace(/\bwatch\s+(\d)\b/g, "watch $1")
    .replace(/\bgalaxy watch\s+(\d)\b/g, "galaxy watch$1")
    .replace(/\s+/g, " ")
    .trim();
}

function buildEndpointParams(query) {
  // If brand detection fails, use model-family hints before giving up.
  const normalized = normalizeQuery(query);
  let brand = detectBrand(normalized);

  if (!brand && normalized.includes("watch ultra")) brand = "Apple";
  if (!brand && normalized.includes("watch series")) brand = "Apple";
  if (!brand && normalized.includes("pixel watch")) brand = "Google";
  if (!brand && normalized.includes("fenix")) brand = "Garmin";
  if (!brand && normalized.includes("forerunner")) brand = "Garmin";
  if (!brand && normalized.includes("gtr")) brand = "Amazfit";

  const normalizedName = extractModelName(normalized, brand);
  return { brand, normalized_name: normalizedName };
}

function endpointUrl(params) {
  const search = new URLSearchParams({
    brand: params.brand || "",
    normalized_name: params.normalized_name || "",
  });
  return `/api/watch-card/by-name?${search.toString()}`;
}

async function fetchJson(url) {
  const response = await fetch(url);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(body.detail || "Не удалось получить карточку");
    error.status = response.status;
    throw error;
  }
  return body;
}

async function getSuggestions(query, brand) {
  // Suggestions come from the backend search endpoint, then get a small client-side fuzzy sort.
  const normalized = normalizeQuery(query);
  const withoutBrand = removeBrandWords(normalized, brand);
  const q = withoutBrand || normalized;
  const search = new URLSearchParams({ q, limit: "8" });
  if (brand) search.set("brand", brand);

  const results = await fetchJson(`/api/watch-card/search?${search.toString()}`).catch(() => []);
  return results
    .map((item) => ({
      ...item,
      score: fuzzyScore(`${item.brand} ${item.model_name} ${item.normalized_name}`, query),
    }))
    .sort((a, b) => b.score - a.score)
    .slice(0, 5);
}

function fuzzyScore(candidate, query) {
  const c = compact(candidate);
  const q = compact(query);
  if (!q) return 0;
  if (c.includes(q)) return 100 + q.length;
  const distance = levenshtein(c.slice(0, Math.max(q.length, 1)), q);
  return Math.max(0, 80 - distance * 12);
}

async function runSearch(query) {
  // requestId prevents an older slow response from replacing a newer search result.
  const requestId = activeRequestId + 1;
  activeRequestId = requestId;
  const rawQuery = query || searchInput.value;
  const params = buildEndpointParams(rawQuery);
  currentCard = null;
  renderCard(null);
  renderSuggestions([]);

  if (!params.brand || !params.normalized_name) {
    setStatus("Не понял бренд или модель. Попробуйте ввести название полностью.", true);
    return;
  }

  setStatus("Загружаю карточку...");
  searchButton.disabled = true;

  try {
    const card = await fetchJson(endpointUrl(params));
    if (requestId !== activeRequestId) return;
    currentCard = card;
    setStatus(`Найдено: ${card.title}`);
    renderCard(card);
  } catch (error) {
    const suggestions = await getSuggestions(rawQuery, params.brand);
    if (requestId !== activeRequestId) return;
    if (suggestions.length) {
      setStatus("Точного совпадения нет. Возможно, подойдёт один из вариантов:", true);
      renderSuggestions(suggestions);
    } else {
      setStatus("Карточка не найдена. Проверьте название или попробуйте другое написание.", true);
    }
  } finally {
    if (requestId === activeRequestId) {
      searchButton.disabled = false;
    }
  }
}

function setStatus(message, isError = false) {
  statusText.textContent = message || "";
  statusText.classList.toggle("error", Boolean(isError));
}

function renderSuggestions(items) {
  // Suggestion clicks rerun the normal search path, keeping behavior identical to typed input.
  suggestionsBox.hidden = !items.length;
  suggestionsBox.innerHTML = "";
  for (const item of items) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = `${item.brand} ${item.model_name}`;
    button.addEventListener("click", () => {
      searchInput.value = `${item.brand} ${item.model_name}`;
      runSearch(searchInput.value);
    });
    suggestionsBox.append(button);
  }
}

function renderCard(card) {
  // The renderer accepts incomplete cards; missing rows are simply not printed.
  cardMount.classList.toggle("has-card", Boolean(card));
  if (!card) {
    cardMount.innerHTML = "";
    return;
  }

  const rows = buildSpecRows(card);
  cardMount.innerHTML = `
    <article class="watch-card">
      <header class="card-header">
        <div class="card-title">${escapeHtml(card.title)}</div>
        <button class="close-button" type="button" aria-label="Закрыть карточку"></button>
      </header>
      <div class="watch-hero">
        ${
          card.image?.url
            ? `<img src="${escapeAttribute(card.image.url)}" alt="${escapeAttribute(card.title)}" />`
            : `<div class="image-placeholder">Нет изображения</div>`
        }
      </div>
      ${card.incomplete ? `<div class="badge-row"><span class="badge">Характеристики дополняются</span></div>` : ""}
      <div class="spec-list">
        ${rows
          .map(
            (row) => `
              <div class="spec-row">
                <div class="spec-icon" aria-hidden="true">${row.icon}</div>
                <div class="spec-label">${escapeHtml(row.label)}</div>
                <div class="spec-value">${escapeHtml(row.value)}</div>
              </div>
            `,
          )
          .join("")}
      </div>
      ${debugToggle.checked ? renderDebug(card) : ""}
    </article>
  `;

  cardMount.querySelector(".close-button").addEventListener("click", () => {
    currentCard = null;
    renderCard(null);
    setStatus("");
  });
}

function buildSpecRows(card) {
  // Keep row order close to the desired product-card reading flow.
  const rows = [];
  addRow(rows, "📐", "Размер", sizeValue(card));
  addRow(rows, "🖥️", "Дисплей", displayValue(card));
  addRow(rows, "⚙️", "Материалы", materialsValue(card));
  addRow(rows, "🔋", "АКБ", batteryValue(card));
  addRow(rows, "💧", "Влагозащита", card.protection?.water_resistance);
  addRow(rows, "📍", "Навигация", navigationValue(card));
  addRow(rows, "❤️", "Здоровье", healthValue(card));
  addRow(rows, "📶", "Связь", connectivityValue(card));
  addRow(rows, "⌚", "ОС", card.model?.os);
  addRow(rows, "💰", "Цена при анонсе", card.raw_extra?.launch_price);
  addRow(rows, "🔁", "Варианты", variantsValue(card));
  return rows;
}

function addRow(rows, icon, label, value) {
  // Empty values are skipped so the card never shows "null" or blank technical rows.
  const cleanValue = Array.isArray(value) ? value.filter(Boolean).join(", ") : value;
  if (cleanValue === null || cleanValue === undefined || cleanValue === "") return;
  rows.push({ icon, label, value: String(cleanValue) });
}

function sizeValue(card) {
  const sizes = unique(
    (card.variants || [])
      .map((variant) => variant.case_size_mm)
      .filter(Boolean)
      .map((size) => trimNumber(size)),
  );
  if (sizes.length > 1) return `${sizes.join(" / ")} мм`;
  if (card.main_variant?.case_size_mm) return `${trimNumber(card.main_variant.case_size_mm)} мм`;
  return null;
}

function displayValue(card) {
  const parts = [formatToken(card.display?.type), card.display?.size_raw, card.display?.resolution].filter(Boolean);
  return parts.join(", ");
}

function materialsValue(card) {
  return [formatToken(card.materials?.case_material), formatToken(card.materials?.glass_type)].filter(Boolean).join(", ");
}

function batteryValue(card) {
  return [card.battery?.capacity_mah ? `${card.battery.capacity_mah} мАч` : null, formatBatteryLife(card.battery?.life)]
    .filter(Boolean)
    .join(", ");
}

function navigationValue(card) {
  const values = [];
  if (card.navigation?.gps) values.push("GPS");
  if (card.raw_extra?.glonass) values.push("GLONASS");
  if (card.raw_extra?.galileo) values.push("Galileo");
  if (card.raw_extra?.beidou) values.push("BDS");
  if (card.navigation?.compass) values.push("компас");
  if (card.navigation?.altimeter) values.push("альтиметр");
  if (card.navigation?.barometer) values.push("барометр");
  return values.join(", ");
}

function healthValue(card) {
  const values = [];
  if (card.health?.heart_rate) values.push("пульс");
  if (card.health?.spo2) values.push("SpO₂");
  if (card.health?.ecg) values.push("ЭКГ");
  if (card.health?.skin_temperature) values.push("темп. тела");
  if (isYes(card.raw_extra?.sleep_tracking)) values.push("сон");
  return values.join(", ");
}

function connectivityValue(card) {
  const values = [];
  if (card.connectivity?.type) values.push(formatConnectivity(card.connectivity.type));
  if (card.connectivity?.bluetooth && !values.some((value) => value.includes("Bluetooth"))) values.push("Bluetooth");
  if (card.connectivity?.wifi) values.push("Wi‑Fi");
  if (card.connectivity?.nfc) values.push("NFC");
  if (card.connectivity?.lte) values.push("LTE");
  if (card.connectivity?.esim) values.push("eSIM");
  return unique(values).join(", ");
}

function variantsValue(card) {
  if (!card.variants || card.variants.length <= 1) return null;
  const sizes = unique(
    card.variants
      .map((variant) => variant.case_size_mm)
      .filter(Boolean)
      .map((size) => trimNumber(size)),
  );
  if (sizes.length > 1) return `${sizes.join(" / ")} мм`;
  const names = unique(card.variants.map((variant) => variant.variant_name).filter(Boolean));
  return names.length ? names.join(" / ") : null;
}

function renderDebug(card) {
  // Debug exposes the raw response for QA without changing the normal card layout.
  return `
    <section class="debug-panel">
      <h2>Debug</h2>
      <dl>
        <dt>source_host</dt><dd>${escapeHtml(card.source?.host || "—")}</dd>
        <dt>source_url</dt><dd>${escapeHtml(card.source?.url || "—")}</dd>
        <dt>quality</dt><dd>${escapeHtml(card.main_variant?.quality_score ?? "—")}</dd>
        <dt>incomplete</dt><dd>${escapeHtml(String(Boolean(card.incomplete)))}</dd>
        <dt>warnings</dt><dd>${escapeHtml((card.warnings || []).join(", ") || "—")}</dd>
      </dl>
      <pre>${escapeHtml(JSON.stringify(card, null, 2))}</pre>
    </section>
  `;
}

function formatToken(value) {
  // Database keys are stable; display labels can stay friendly and localized here.
  if (!value) return null;
  const dictionary = {
    oled_amoled: "OLED / AMOLED",
    gorilla_glass_5: "Gorilla Glass 5",
    gorilla_glass_3: "Gorilla Glass 3",
    stainless_steel: "нержавеющая сталь",
    aluminum: "алюминий",
    sapphire: "Sapphire",
  };
  const key = String(value).toLowerCase();
  return dictionary[key] || String(value).replace(/_/g, " ");
}

function formatConnectivity(value) {
  const dictionary = {
    "gps+lte": "GPS + LTE",
    "gps+bluetooth": "GPS + Bluetooth",
    gps: "GPS",
    bluetooth: "Bluetooth",
    lte: "LTE",
  };
  return dictionary[value] || value;
}

function formatBatteryLife(value) {
  // Convert backend "days" values into compact Russian card copy.
  if (!value) return null;
  const match = String(value).match(/([\d.]+)\s*days?/i);
  if (!match) return value;
  const days = Number(match[1]);
  if (!Number.isFinite(days)) return value;
  if (days < 1) return `до ${Math.round(days * 24)} ч.`;
  if (days === 1) return "до 1 дня";
  if (days === 1.5) return "до 36 ч.";
  return `до ${trimNumber(days)} ${days < 5 ? "дня" : "дней"}`;
}

function trimNumber(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return value;
  return Number.isInteger(number) ? String(number) : String(number).replace(/0+$/, "").replace(/\.$/, "");
}

function isYes(value) {
  return String(value || "").toLowerCase() === "y" || value === true;
}

function unique(values) {
  return [...new Set(values.filter(Boolean))];
}

function escapeHtml(value) {
  // The card is rendered with template strings, so every API value must be escaped.
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function escapeAttribute(value) {
  return escapeHtml(value);
}

function renderExamples() {
  // Show only a few chips so the search panel stays compact.
  for (const example of examples.slice(0, 6)) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = example;
    button.addEventListener("click", () => {
      searchInput.value = example;
      runSearch(example);
    });
    examplesBox.append(button);
  }
}

searchButton.addEventListener("click", () => runSearch());
searchInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") runSearch();
});
debugToggle.addEventListener("change", () => renderCard(currentCard));

renderExamples();
searchInput.value = "Amazfit GTR 4";
runSearch(searchInput.value);
