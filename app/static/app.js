const categoryTabsEl = document.getElementById("categoryTabs");
const refreshBtn = document.getElementById("refreshBtn");
const searchInput = document.getElementById("searchInput");
const searchBtn = document.getElementById("searchBtn");
const sortSelect = document.getElementById("sortSelect");
const statusEl = document.getElementById("status");
const loadingSpinner = document.getElementById("loadingSpinner");
const seeMoreBtn = document.getElementById("seeMoreBtn");

const topStoryEl = document.getElementById("topStory");
const storyListEl = document.getElementById("storyList");
const sideStoriesEl = document.getElementById("sideStories");
const sourceHealthEl = document.getElementById("sourceHealth");
const sidePanelTitleEl = document.getElementById("sidePanelTitle");
const topPanelTitleEl = document.getElementById("topPanelTitle");
const briefingDateEl = document.getElementById("briefingDate");
const briefingTitleEl = document.getElementById("briefingTitle");

const totalTrendsEl = document.getElementById("totalTrends");
const lowRiskCountEl = document.getElementById("lowRiskCount");
const mediumRiskCountEl = document.getElementById("mediumRiskCount");
const avgRiskEl = document.getElementById("avgRisk");

const topStoryTemplate = document.getElementById("topStoryTemplate");
const storyItemTemplate = document.getElementById("storyItemTemplate");
const sideItemTemplate = document.getElementById("sideItemTemplate");

const FETCH_LIMIT = 20;
const PAGE_SIZE = 10;

const CATEGORIES = [
  { id: "all", label: "Home" },
  { id: "local", label: "Local" },
  { id: "india", label: "India" },
  { id: "world", label: "World" },
  { id: "entertainment", label: "Entertainment" },
  { id: "health", label: "Health" },
  { id: "trending", label: "Trending" },
  { id: "sports", label: "Sports" },
  { id: "esports", label: "Esports" },
  { id: "food", label: "Food" },
  { id: "events", label: "Events" },
];

const CATEGORY_LABELS = Object.fromEntries(CATEGORIES.map((category) => [category.id, category.label]));

let selectedCategory = "all";
let allResults = [];
let visibleCount = PAGE_SIZE;
let searchTerm = "";
let sortMode = "latest";
let isLoading = false;

function platformLabel(platform) {
  if (!platform) return "From Source";
  if (platform === "Hacker News") return "From Hacker News";
  if (platform === "Google News") return "From Google News";
  if (platform === "Reddit") return "From Reddit";
  return `From ${platform}`;
}

function setStatus(text, isError = false) {
  if (!statusEl) return;
  statusEl.textContent = text;
  statusEl.style.color = isError ? "#efb0a9" : "#85a5ce";
}

function setLoading(loading) {
  isLoading = loading;
  if (loadingSpinner) loadingSpinner.classList.toggle("hidden", !loading);

  if (refreshBtn) refreshBtn.disabled = loading;
  if (searchBtn) searchBtn.disabled = loading;
  if (searchInput) searchInput.disabled = loading;
  if (sortSelect) sortSelect.disabled = loading;
  if (seeMoreBtn) seeMoreBtn.disabled = loading;
  if (categoryTabsEl) {
    categoryTabsEl.querySelectorAll("button").forEach((button) => {
      button.disabled = loading;
    });
  }
}

function formatRelativeTime(createdUtc) {
  if (!createdUtc) return "recently";
  const seconds = Math.max(1, Math.floor(Date.now() / 1000 - createdUtc));
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

function placeholderImage() {
  return (
    "data:image/svg+xml;utf8," +
    encodeURIComponent(
      "<svg xmlns='http://www.w3.org/2000/svg' width='800' height='450'><defs><linearGradient id='g' x1='0' x2='1' y1='0' y2='1'><stop stop-color='#263244' offset='0'/><stop stop-color='#1f2735' offset='1'/></linearGradient></defs><rect width='100%' height='100%' fill='url(#g)'/></svg>"
    )
  );
}

function verdictClass(verdict) {
  if (verdict === "Low Risk") return "real";
  if (verdict === "High Risk") return "misleading";
  return "verify";
}

function displaySummary(item) {
  const summary = (item.trend.summary || "").trim();
  if (summary) return summary;
  if (item.reasons?.length) return item.reasons[0];
  return "Open the official article for full context.";
}

function makeEvidenceLink(article) {
  const anchor = document.createElement("a");
  anchor.href = article.article_url;
  anchor.target = "_blank";
  anchor.rel = "noreferrer";
  anchor.textContent = article.source || "Source";
  return anchor;
}

function populateEvidenceDetails(root, item) {
  root.querySelector(".evidence-summary").textContent =
    `Corroboration: ${item.evidence.credible_hits}/${item.evidence.total_hits} | Trusted sources: ${item.evidence.source_diversity}`;

  const reasonList = root.querySelector(".reason-list");
  item.reasons.forEach((reason) => {
    const li = document.createElement("li");
    li.textContent = reason;
    reasonList.appendChild(li);
  });

  const evidenceLinks = root.querySelector(".evidence-links");
  (item.evidence.articles || []).slice(0, 4).forEach((article) => {
    evidenceLinks.appendChild(makeEvidenceLink(article));
  });
}

function normalizeText(value) {
  return String(value || "").toLowerCase();
}

function matchesSearch(item, query) {
  if (!query) return true;
  const haystack = [
    item.trend.title,
    item.trend.summary,
    item.trend.source_name,
    item.trend.author,
    item.trend.category,
    item.verdict,
  ]
    .map(normalizeText)
    .join(" ");
  return haystack.includes(query);
}

function sortResults(items) {
  const copy = [...items];
  if (sortMode === "spread") {
    copy.sort((a, b) => b.spread_index - a.spread_index);
    return copy;
  }
  if (sortMode === "credible") {
    copy.sort((a, b) => b.credibility_score - a.credibility_score);
    return copy;
  }
  copy.sort((a, b) => (b.trend.created_utc || 0) - (a.trend.created_utc || 0));
  return copy;
}

function filteredResults() {
  const query = searchTerm.trim().toLowerCase();
  if (!query) return sortResults(allResults);
  const localFiltered = allResults.filter((item) => matchesSearch(item, query));
  // Backend already returns query-specific stories; fall back to full set if strict local filter over-prunes.
  if (!localFiltered.length) return sortResults(allResults);
  return sortResults(localFiltered);
}

function fillStoryCommon(container, item) {
  container.querySelectorAll(".source-name").forEach((el) => {
    el.textContent =
      item.trend.source_name || item.trend.author || item.trend.metrics?.source || item.trend.platform;
  });
  container.querySelectorAll(".story-time").forEach((el) => {
    el.textContent = formatRelativeTime(item.trend.created_utc);
  });
  container.querySelectorAll(".story-title").forEach((el) => {
    el.textContent = item.trend.title;
  });
  container.querySelectorAll(".story-summary").forEach((el) => {
    el.textContent = displaySummary(item);
  });
  container.querySelectorAll(".via-platform").forEach((el) => {
    el.textContent = platformLabel(item.trend.platform);
  });
}

function screenshotTarget(articleUrl, sourceUrl) {
  if (!articleUrl) return sourceUrl || "";
  if (articleUrl.includes("news.google.com/rss/articles/") && sourceUrl) return sourceUrl;
  return sourceUrl || articleUrl;
}

function applyImage(imageEl, imageUrl, articleUrl, sourceUrl) {
  const target = screenshotTarget(articleUrl, sourceUrl);
  const mshots = target ? `https://s.wordpress.com/mshots/v1/${encodeURIComponent(target)}?w=900` : "";
  const thum = target ? `https://image.thum.io/get/width/900/noanimate/${encodeURIComponent(target)}` : "";
  const normalizedImage = (imageUrl || "").replaceAll("&amp;", "&");
  const queue = [normalizedImage, mshots, thum, placeholderImage()].filter(Boolean);
  const dedupedQueue = [...new Set(queue)];
  let index = 0;

  const tryNext = () => {
    if (index >= dedupedQueue.length) return;
    imageEl.src = dedupedQueue[index];
    index += 1;
  };

  imageEl.onerror = () => {
    tryNext();
  };

  // Some hosts return tiny placeholders/logos. Move to backup in that case.
  imageEl.onload = () => {
    if (index >= queue.length) return;
    if (imageEl.naturalWidth < 160 || imageEl.naturalHeight < 90) {
      tryNext();
    }
  };

  tryNext();
}

function buildTopStory(item) {
  const node = topStoryTemplate.content.cloneNode(true);
  const root = node.querySelector(".top-story-card");
  fillStoryCommon(root, item);

  root.querySelector(".category-pill").textContent = CATEGORY_LABELS[item.trend.category] || item.trend.category;

  root.querySelector(".fake-chip").textContent = `Risk ${item.fake_probability.toFixed(0)}%`;
  root.querySelector(".credibility-chip").textContent = `Credibility ${item.credibility_score.toFixed(0)}%`;
  root.querySelector(".spread-chip").textContent = `Spread ${item.spread_index.toFixed(0)}`;

  const verdictChip = root.querySelector(".verdict-chip");
  verdictChip.textContent = item.verdict;
  verdictChip.classList.add(verdictClass(item.verdict));

  const image = root.querySelector(".top-image");
  applyImage(image, item.trend.image_url, item.trend.url, item.trend.source_url);

  const mediaLink = root.querySelector(".top-media-link");
  mediaLink.href = item.trend.url;

  const readLink = root.querySelector(".read-link");
  readLink.href = item.trend.url;

  const insight = root.querySelector(".insight-block");
  populateEvidenceDetails(root, item);
  root.querySelector(".insight-btn").addEventListener("click", () => {
    insight.classList.toggle("hidden");
  });

  return node;
}

function buildStoryRow(item) {
  const node = storyItemTemplate.content.cloneNode(true);
  const root = node.querySelector(".story-row");
  fillStoryCommon(root, item);

  const verdictChip = root.querySelector(".verdict-chip");
  verdictChip.textContent = item.verdict;
  verdictChip.classList.add(verdictClass(item.verdict));
  root.querySelector(".credibility-chip").textContent = `Credibility ${item.credibility_score.toFixed(0)}%`;

  const image = root.querySelector(".row-image");
  applyImage(image, item.trend.image_url, item.trend.url, item.trend.source_url);

  const mediaLink = root.querySelector(".row-media-link");
  mediaLink.href = item.trend.url;
  root.querySelector(".read-link").href = item.trend.url;

  const insight = root.querySelector(".insight-block");
  populateEvidenceDetails(root, item);
  root.querySelector(".insight-btn").addEventListener("click", () => {
    insight.classList.toggle("hidden");
  });

  return node;
}

function buildSideItem(item) {
  const node = sideItemTemplate.content.cloneNode(true);
  const root = node.querySelector(".side-item");
  root.querySelector(".source-name").textContent =
    item.trend.source_name || item.trend.author || item.trend.platform;
  root.querySelector(".via-platform").textContent = platformLabel(item.trend.platform);
  root.querySelector(".story-time").textContent = formatRelativeTime(item.trend.created_utc);

  const link = root.querySelector(".side-title");
  link.textContent = item.trend.title;
  link.href = item.trend.url;

  const image = root.querySelector(".side-image");
  applyImage(image, item.trend.image_url, item.trend.url, item.trend.source_url);
  root.querySelector(".side-image-link").href = item.trend.url;
  return node;
}

function renderSourceHealth(sourceHealth) {
  sourceHealthEl.innerHTML = "";
  Object.entries(sourceHealth || {}).forEach(([source, state]) => {
    const pill = document.createElement("span");
    const ok = String(state).startsWith("ok") || String(state) === "api_ok" || String(state) === "fallback_rss";
    pill.className = `source-pill ${ok ? "ok" : "warn"}`;
    pill.textContent = `${source.replace("_", " ")}: ${state}`;
    sourceHealthEl.appendChild(pill);
  });
}

function renderStats(items) {
  const total = items.length;
  const lowRisk = items.filter((x) => x.verdict === "Low Risk").length;
  const mediumRisk = items.filter((x) => x.verdict === "Medium Risk").length;
  const avgRisk = total ? items.reduce((sum, x) => sum + x.fake_probability, 0) / total : 0;

  if (totalTrendsEl) totalTrendsEl.textContent = String(total);
  if (lowRiskCountEl) lowRiskCountEl.textContent = String(lowRisk);
  if (mediumRiskCountEl) mediumRiskCountEl.textContent = String(mediumRisk);
  if (avgRiskEl) avgRiskEl.textContent = `${avgRisk.toFixed(1)}%`;
}

function pickSideStories(allVisible, allFiltered) {
  if (selectedCategory === "all") {
    const localStories = allFiltered.filter((item) => item.trend.category === "local");
    if (localStories.length) return localStories.slice(0, 5);
  }
  return allVisible.slice(1, 6);
}

function render() {
  const filtered = filteredResults();
  const visible = filtered.slice(0, visibleCount);
  renderStats(filtered);

  topStoryEl.innerHTML = "";
  storyListEl.innerHTML = "";
  sideStoriesEl.innerHTML = "";

  if (!visible.length) {
    setStatus("No stories match your filter.", true);
    seeMoreBtn.style.display = "none";
    return;
  }

  setStatus(`Showing ${visible.length} of ${filtered.length} stories`);
  topStoryEl.appendChild(buildTopStory(visible[0]));
  visible.slice(1).forEach((item) => {
    storyListEl.appendChild(buildStoryRow(item));
  });

  const sideItems = pickSideStories(visible, filtered);
  sideItems.forEach((item) => {
    sideStoriesEl.appendChild(buildSideItem(item));
  });

  if (selectedCategory === "all") {
    sidePanelTitleEl.textContent = "Local News";
    topPanelTitleEl.textContent = "Top Stories";
    briefingTitleEl.textContent = "Your Briefing";
  } else {
    const label = CATEGORY_LABELS[selectedCategory] || selectedCategory;
    sidePanelTitleEl.textContent = "Related Stories";
    topPanelTitleEl.textContent = `${label} Highlights`;
    briefingTitleEl.textContent = `${label} Briefing`;
  }

  if (filtered.length > visibleCount) {
    seeMoreBtn.style.display = "inline-flex";
  } else {
    seeMoreBtn.style.display = "none";
  }
}

function renderCategoryTabs() {
  categoryTabsEl.innerHTML = "";
  CATEGORIES.forEach((category) => {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = category.label;
    button.classList.toggle("active", category.id === selectedCategory);
    button.addEventListener("click", () => {
      if (isLoading) return;
      selectedCategory = category.id;
      searchTerm = "";
      if (searchInput) searchInput.value = "";
      visibleCount = PAGE_SIZE;
      renderCategoryTabs();
      runAnalysis(true);
    });
    categoryTabsEl.appendChild(button);
  });
}

async function runAnalysis(forceRefresh = false) {
  const query = (searchTerm || "").trim();
  setStatus(query ? `Searching for "${query}"...` : "Refreshing live signals...");
  setLoading(true);
  const refreshParam = forceRefresh ? "&refresh=true" : "";
  const queryParam = query ? `&query=${encodeURIComponent(query)}` : "";
  const url =
    `/api/analyze?limit=${FETCH_LIMIT}&category=${encodeURIComponent(selectedCategory)}` +
    `${queryParam}${refreshParam}`;

  try {
    const response = await fetch(url);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    allResults = data.results || [];
    renderSourceHealth(data.source_health || {});
    render();
  } catch (error) {
    setStatus(`Failed to load feed: ${error.message}`, true);
  } finally {
    setLoading(false);
  }
}

refreshBtn.addEventListener("click", () => runAnalysis(true));
seeMoreBtn.addEventListener("click", () => {
  visibleCount += PAGE_SIZE;
  render();
});
searchBtn.addEventListener("click", () => {
  if (isLoading) return;
  searchTerm = searchInput.value || "";
  visibleCount = PAGE_SIZE;
  runAnalysis(true);
});
searchInput.addEventListener("keydown", (event) => {
  if (event.key !== "Enter") return;
  if (isLoading) return;
  searchTerm = searchInput.value || "";
  visibleCount = PAGE_SIZE;
  runAnalysis(true);
});
searchInput.addEventListener("input", () => {
  if (!searchInput.value.trim()) {
    searchTerm = "";
  }
});
sortSelect.addEventListener("change", () => {
  sortMode = sortSelect.value || "latest";
  if (!allResults.length) return;
  visibleCount = PAGE_SIZE;
  render();
});

renderCategoryTabs();
briefingDateEl.textContent = new Date().toLocaleDateString(undefined, {
  weekday: "long",
  day: "numeric",
  month: "long",
  year: "numeric",
});
runAnalysis(false);
