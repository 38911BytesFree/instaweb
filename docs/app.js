(() => {
  "use strict";

  const IMAGE_STORY_DURATION_MS = 5000;

  // State
  let archiveData = { profile: { username: "yukipanvel" }, stories: [], posts: [] };
  let activeTab = "posts";
  let activeMonthKey = "all";
  let searchQuery = "";
  const collapsedMonths = new Set();

  // Story Player State
  let storyGroups = [];
  let currentGroupIndex = 0;
  let currentStoryIndex = 0;
  let storyPaused = false;
  let storyMuted = false;
  let storyTimerId = null;
  let storyStartTimestamp = 0;
  let storyElapsedMs = 0;

  // Post Carousel State
  let activePost = null;
  let activeSlideIndex = 0;

  // DOM Elements
  const els = {
    lastSyncedBadge: document.getElementById("last-synced-badge"),
    avatarRing: document.getElementById("profile-avatar-ring"),
    avatarFallback: document.getElementById("profile-avatar-fallback"),
    avatarImg: document.getElementById("profile-avatar-img"),
    username: document.getElementById("profile-username"),
    igLink: document.getElementById("profile-ig-link"),
    statPosts: document.getElementById("stat-posts"),
    statStories: document.getElementById("stat-stories"),
    statActiveStories: document.getElementById("stat-active-stories"),
    fullName: document.getElementById("profile-fullname"),
    biography: document.getElementById("profile-biography"),
    storiesSection: document.getElementById("stories-section"),
    storiesTray: document.getElementById("stories-tray"),
    tabButtons: document.querySelectorAll(".tab-btn"),
    searchInput: document.getElementById("search-input"),
    monthNav: document.getElementById("month-nav"),
    mediaSections: document.getElementById("media-sections"),
    emptyState: document.getElementById("empty-state"),

    // Story Modal
    storyModal: document.getElementById("story-modal"),
    storyProgressContainer: document.getElementById("story-progress-container"),
    storyGroupTitle: document.getElementById("story-modal-group-title"),
    storyTimestamp: document.getElementById("story-modal-timestamp"),
    storyPauseBtn: document.getElementById("story-pause-btn"),
    storyMuteBtn: document.getElementById("story-mute-btn"),
    storyCloseBtn: document.getElementById("story-close-btn"),
    storyPrevZone: document.getElementById("story-prev-zone"),
    storyNextZone: document.getElementById("story-next-zone"),
    storyMediaWrapper: document.getElementById("story-media-wrapper"),
    storyCaption: document.getElementById("story-caption"),
    storyPermalink: document.getElementById("story-permalink"),

    // Post Modal
    postModal: document.getElementById("post-modal"),
    postBackdrop: document.getElementById("post-modal-backdrop"),
    postCloseBtn: document.getElementById("post-close-btn"),
    carouselPrevBtn: document.getElementById("carousel-prev-btn"),
    carouselNextBtn: document.getElementById("carousel-next-btn"),
    carouselDots: document.getElementById("carousel-dots"),
    postStage: document.getElementById("post-modal-stage"),
    postUsername: document.getElementById("post-modal-username"),
    postDate: document.getElementById("post-modal-date"),
    postCaption: document.getElementById("post-modal-caption"),
    postLikes: document.getElementById("post-modal-likes"),
    postComments: document.getElementById("post-modal-comments"),
    postLink: document.getElementById("post-modal-link"),
  };

  function formatDateTime(isoStr) {
    if (!isoStr) return "";
    const d = new Date(isoStr);
    if (Number.isNaN(d.getTime())) return isoStr;
    return d.toLocaleString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  }

  function formatDateKey(isoStr) {
    if (!isoStr) return "Unknown Date";
    return isoStr.slice(0, 10);
  }

  function formatMonthKey(isoStr) {
    if (!isoStr || isoStr.length < 7) return "Unknown";
    return isoStr.slice(0, 7); // YYYY-MM
  }

  function formatMonthLabel(monthKey, short = false) {
    if (!monthKey || monthKey === "Unknown" || !/^\d{4}-\d{2}$/.test(monthKey)) {
      return "Unknown Month";
    }
    const [year, month] = monthKey.split("-").map(Number);
    const date = new Date(Date.UTC(year, month - 1, 1));
    return date.toLocaleString(undefined, {
      month: short ? "short" : "long",
      year: "numeric",
      timeZone: "UTC",
    });
  }

  function isStoryActive(story) {
    const now = Date.now();
    if (story.expiresAt) {
      const exp = new Date(story.expiresAt).getTime();
      if (!Number.isNaN(exp)) return exp > now;
    }
    if (story.takenAt) {
      const taken = new Date(story.takenAt).getTime();
      if (!Number.isNaN(taken)) return now - taken < 24 * 3600 * 1000;
    }
    return false;
  }

  function buildStoryGroups(stories) {
    const groups = [];
    const activeStories = stories
      .filter((s) => isStoryActive(s))
      .sort((a, b) => new Date(a.takenAt) - new Date(b.takenAt));

    if (activeStories.length > 0) {
      groups.push({
        id: "active-24h",
        title: "Active (24h)",
        isActive: true,
        coverUrl: activeStories[activeStories.length - 1].thumbnailPath || activeStories[0].localPath,
        stories: activeStories,
      });
    }

    const byDate = new Map();
    for (const story of stories) {
      const dateKey = formatDateKey(story.takenAt);
      if (!byDate.has(dateKey)) {
        byDate.set(dateKey, []);
      }
      byDate.get(dateKey).push(story);
    }

    const sortedDates = Array.from(byDate.keys()).sort((a, b) => b.localeCompare(a));
    for (const dateKey of sortedDates) {
      const items = byDate
        .get(dateKey)
        .slice()
        .sort((a, b) => new Date(a.takenAt) - new Date(b.takenAt));
      groups.push({
        id: `date-${dateKey}`,
        title: dateKey,
        isActive: false,
        coverUrl: items[items.length - 1].thumbnailPath || items[0].localPath,
        stories: items,
      });
    }

    return groups;
  }

  function renderProfile(data) {
    const profile = data.profile || {};
    const username = profile.username || "yukipanvel";
    els.username.textContent = `@${username}`;
    els.igLink.href = `https://www.instagram.com/${username}/`;
    const fullNameText = profile.fullName && profile.fullName !== username ? profile.fullName : "";
    els.fullName.textContent = fullNameText;
    els.fullName.hidden = !fullNameText;
    els.biography.textContent = profile.biography || "";
    els.biography.hidden = !profile.biography;

    const initials = username.slice(0, 2).toUpperCase();
    els.avatarFallback.textContent = initials;

    if (profile.avatarLocalPath) {
      els.avatarImg.src = profile.avatarLocalPath;
      els.avatarImg.hidden = false;
      els.avatarFallback.hidden = true;
    } else {
      els.avatarImg.hidden = true;
      els.avatarFallback.hidden = false;
    }

    const stories = data.stories || [];
    const posts = data.posts || [];
    const activeCount = stories.filter((s) => isStoryActive(s)).length;

    els.statPosts.textContent = String(posts.length);
    els.statStories.textContent = String(stories.length);
    els.statActiveStories.textContent = String(activeCount);

    if (activeCount > 0 || stories.length > 0) {
      els.avatarRing.classList.toggle("has-active-stories", activeCount > 0);
    } else {
      els.avatarRing.classList.remove("has-active-stories");
    }

    if (profile.lastUpdatedUtc) {
      els.lastSyncedBadge.textContent = `Last synced: ${formatDateTime(profile.lastUpdatedUtc)}`;
    } else {
      els.lastSyncedBadge.textContent = "Waiting for first sync";
    }
  }

  function renderStoriesTray() {
    els.storiesTray.innerHTML = "";
    if (storyGroups.length === 0) {
      if (els.storiesSection) {
        els.storiesSection.hidden = true;
      }
      return;
    }
    if (els.storiesSection) {
      els.storiesSection.hidden = false;
    }

    storyGroups.forEach((group, idx) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = `story-ring-item${group.isActive ? " is-active" : ""}`;
      btn.innerHTML = `
        <div class="story-ring-circle">
          <img class="story-ring-thumb" src="${group.coverUrl}" alt="${group.title}" loading="lazy" />
        </div>
        <span class="story-ring-label">${group.title}</span>
        <span class="story-ring-count">${group.stories.length} ${group.stories.length === 1 ? "story" : "stories"}</span>
      `;
      btn.addEventListener("click", () => openStoryModal(idx, 0));
      els.storiesTray.appendChild(btn);
    });
  }

  function createMediaCard(kind, item) {
    const card = document.createElement("article");
    card.className = `grid-card${kind === "story" ? " story-aspect" : ""}`;

    if (kind === "post") {
      const firstMedia = (item.media && item.media[0]) || {};
      const badgeText =
        item.mediaType === "carousel"
          ? `❐ ${item.media.length}`
          : item.mediaType === "video"
          ? "▶ Video"
          : "";

      if (firstMedia.type === "video") {
        card.innerHTML = `
          <video src="${firstMedia.localPath}" ${firstMedia.posterPath ? `poster="${firstMedia.posterPath}"` : ""} muted playsinline preload="metadata"></video>
          ${badgeText ? `<span class="card-badge">${badgeText}</span>` : ""}
          <div class="card-overlay">
            <span class="card-overlay-date">${formatDateKey(item.takenAt)}</span>
            <p class="card-overlay-caption">${escapeHtml(item.caption || "")}</p>
          </div>
        `;
      } else {
        card.innerHTML = `
          <img src="${firstMedia.localPath || ""}" alt="${escapeHtml(item.caption || "Instagram post")}" loading="lazy" />
          ${badgeText ? `<span class="card-badge">${badgeText}</span>` : ""}
          <div class="card-overlay">
            <span class="card-overlay-date">${formatDateKey(item.takenAt)}</span>
            <p class="card-overlay-caption">${escapeHtml(item.caption || "")}</p>
          </div>
        `;
      }
      card.addEventListener("click", () => openPostModal(item));
    } else {
      const isActive = isStoryActive(item);
      const badgeText = isActive ? "● Live 24h" : formatDateKey(item.takenAt);
      if (item.mediaType === "video") {
        card.innerHTML = `
          <video src="${item.localPath}" ${item.thumbnailPath ? `poster="${item.thumbnailPath}"` : ""} muted playsinline preload="metadata"></video>
          <span class="card-badge">${badgeText}</span>
        `;
      } else {
        card.innerHTML = `
          <img src="${item.localPath}" alt="Archived story" loading="lazy" />
          <span class="card-badge">${badgeText}</span>
        `;
      }
      card.addEventListener("click", () => openSingleStoryInPlayer(item));
    }

    return card;
  }

  function renderMonthNav(sortedMonths, byMonth, totalCount) {
    els.monthNav.innerHTML = "";
    if (sortedMonths.length <= 1) {
      els.monthNav.hidden = true;
      return;
    }
    els.monthNav.hidden = false;

    const allBtn = document.createElement("button");
    allBtn.type = "button";
    allBtn.className = `month-pill${activeMonthKey === "all" ? " active" : ""}`;
    allBtn.textContent = `All Months (${totalCount})`;
    allBtn.addEventListener("click", () => {
      activeMonthKey = "all";
      renderGrid(archiveData);
    });
    els.monthNav.appendChild(allBtn);

    sortedMonths.forEach((monthKey) => {
      const count = byMonth.get(monthKey).length;
      const pill = document.createElement("button");
      pill.type = "button";
      pill.className = `month-pill${activeMonthKey === monthKey ? " active" : ""}`;
      pill.textContent = `${formatMonthLabel(monthKey, true)} (${count})`;
      pill.addEventListener("click", () => {
        activeMonthKey = monthKey;
        collapsedMonths.delete(monthKey);
        renderGrid(archiveData);
      });
      els.monthNav.appendChild(pill);
    });
  }

  function renderGrid(data) {
    els.mediaSections.innerHTML = "";
    const q = searchQuery.trim().toLowerCase();

    let items = [];
    if (activeTab === "posts") {
      items = (data.posts || []).map((p) => ({ kind: "post", item: p }));
    } else if (activeTab === "stories") {
      items = (data.stories || []).map((s) => ({ kind: "story", item: s }));
    } else if (activeTab === "videos") {
      const videoPosts = (data.posts || [])
        .filter((p) => p.mediaType === "video" || (p.media || []).some((m) => m.type === "video"))
        .map((p) => ({ kind: "post", item: p }));
      const videoStories = (data.stories || [])
        .filter((s) => s.mediaType === "video")
        .map((s) => ({ kind: "story", item: s }));
      items = [...videoPosts, ...videoStories];
    }

    if (q) {
      items = items.filter(({ item }) => {
        const caption = (item.caption || "").toLowerCase();
        const dateStr = (item.takenAt || "").toLowerCase();
        return caption.includes(q) || dateStr.includes(q);
      });
    }

    if (items.length === 0) {
      els.monthNav.hidden = true;
      els.emptyState.hidden = false;
      return;
    }
    els.emptyState.hidden = true;

    // Group items by YYYY-MM
    const byMonth = new Map();
    for (const entry of items) {
      const monthKey = formatMonthKey(entry.item.takenAt);
      if (!byMonth.has(monthKey)) {
        byMonth.set(monthKey, []);
      }
      byMonth.get(monthKey).push(entry);
    }

    const sortedMonths = Array.from(byMonth.keys()).sort((a, b) => b.localeCompare(a));
    if (activeMonthKey !== "all" && !byMonth.has(activeMonthKey)) {
      activeMonthKey = "all";
    }

    renderMonthNav(sortedMonths, byMonth, items.length);

    const visibleMonths =
      activeMonthKey === "all" ? sortedMonths : sortedMonths.filter((m) => m === activeMonthKey);

    visibleMonths.forEach((monthKey) => {
      const monthEntries = byMonth
        .get(monthKey)
        .slice()
        .sort((a, b) => new Date(b.item.takenAt) - new Date(a.item.takenAt));

      const isCollapsed = collapsedMonths.has(monthKey);
      const section = document.createElement("section");
      section.className = `month-group${isCollapsed ? " collapsed" : ""}`;
      section.id = `month-${monthKey}`;

      const header = document.createElement("div");
      header.className = "month-header";
      const itemLabel = monthEntries.length === 1 ? "1 item" : `${monthEntries.length} items`;
      header.innerHTML = `
        <div class="month-title-wrap">
          <h3 class="month-title">${formatMonthLabel(monthKey, false)}</h3>
          <span class="month-count-badge">${itemLabel}</span>
        </div>
        <button class="month-toggle-btn" type="button" aria-expanded="${!isCollapsed}">
          ${isCollapsed ? "Show ▾" : "Hide ▴"}
        </button>
      `;

      header.addEventListener("click", () => {
        if (collapsedMonths.has(monthKey)) {
          collapsedMonths.delete(monthKey);
        } else {
          collapsedMonths.add(monthKey);
        }
        renderGrid(archiveData);
      });

      const grid = document.createElement("div");
      grid.className = "media-grid";
      monthEntries.forEach(({ kind, item }) => {
        grid.appendChild(createMediaCard(kind, item));
      });

      section.appendChild(header);
      section.appendChild(grid);
      els.mediaSections.appendChild(section);
    });
  }

  function escapeHtml(str) {
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  // Story Player Logic
  function openSingleStoryInPlayer(story) {
    const dateKey = formatDateKey(story.takenAt);
    const groupIdx = storyGroups.findIndex((g) => g.id === `date-${dateKey}`);
    if (groupIdx !== -1) {
      const storyIdx = storyGroups[groupIdx].stories.findIndex((s) => s.id === story.id);
      openStoryModal(groupIdx, Math.max(0, storyIdx));
    }
  }

  function openStoryModal(groupIdx, storyIdx) {
    if (!storyGroups[groupIdx]) return;
    currentGroupIndex = groupIdx;
    currentStoryIndex = storyIdx;
    storyPaused = false;
    els.storyModal.hidden = false;
    document.body.style.overflow = "hidden";
    renderCurrentStory();
  }

  function closeStoryModal() {
    clearStoryTimer();
    els.storyMediaWrapper.innerHTML = "";
    els.storyModal.hidden = true;
    document.body.style.overflow = "";
  }

  function clearStoryTimer() {
    if (storyTimerId) {
      cancelAnimationFrame(storyTimerId);
      storyTimerId = null;
    }
  }

  function renderCurrentStory() {
    clearStoryTimer();
    const group = storyGroups[currentGroupIndex];
    if (!group) {
      closeStoryModal();
      return;
    }
    const story = group.stories[currentStoryIndex];
    if (!story) {
      closeStoryModal();
      return;
    }

    // Build segmented progress bars
    els.storyProgressContainer.innerHTML = "";
    group.stories.forEach((_, idx) => {
      const seg = document.createElement("div");
      seg.className = "story-progress-segment";
      const fill = document.createElement("div");
      fill.className = "story-progress-fill";
      fill.style.width = idx < currentStoryIndex ? "100%" : "0%";
      seg.appendChild(fill);
      els.storyProgressContainer.appendChild(seg);
    });

    els.storyGroupTitle.textContent = group.title;
    els.storyTimestamp.textContent = formatDateTime(story.takenAt);
    els.storyCaption.textContent = story.caption || "";
    els.storyPermalink.href = story.originalPermalink || "#";
    els.storyPauseBtn.textContent = storyPaused ? "▶" : "⏸";

    els.storyMediaWrapper.innerHTML = "";
    const activeFill =
      els.storyProgressContainer.children[currentStoryIndex]?.querySelector(".story-progress-fill");

    if (story.mediaType === "video") {
      els.storyMuteBtn.hidden = false;
      els.storyMuteBtn.textContent = storyMuted ? "🔇" : "🔊";

      const video = document.createElement("video");
      video.src = story.localPath;
      video.playsInline = true;
      video.muted = storyMuted;
      video.autoplay = !storyPaused;

      video.addEventListener("timeupdate", () => {
        if (video.duration && activeFill) {
          const pct = Math.min(100, (video.currentTime / video.duration) * 100);
          activeFill.style.width = `${pct}%`;
        }
      });
      video.addEventListener("ended", () => nextStory());
      els.storyMediaWrapper.appendChild(video);
    } else {
      els.storyMuteBtn.hidden = true;
      const img = document.createElement("img");
      img.src = story.localPath;
      img.alt = story.caption || "Instagram Story";
      els.storyMediaWrapper.appendChild(img);

      storyElapsedMs = 0;
      storyStartTimestamp = performance.now();
      const tick = (now) => {
        if (!storyPaused) {
          storyElapsedMs += now - storyStartTimestamp;
        }
        storyStartTimestamp = now;
        const pct = Math.min(100, (storyElapsedMs / IMAGE_STORY_DURATION_MS) * 100);
        if (activeFill) {
          activeFill.style.width = `${pct}%`;
        }
        if (storyElapsedMs >= IMAGE_STORY_DURATION_MS) {
          nextStory();
        } else {
          storyTimerId = requestAnimationFrame(tick);
        }
      };
      storyTimerId = requestAnimationFrame(tick);
    }
  }

  function nextStory() {
    const group = storyGroups[currentGroupIndex];
    if (!group) return closeStoryModal();
    if (currentStoryIndex + 1 < group.stories.length) {
      currentStoryIndex += 1;
      renderCurrentStory();
    } else if (currentGroupIndex + 1 < storyGroups.length) {
      currentGroupIndex += 1;
      currentStoryIndex = 0;
      renderCurrentStory();
    } else {
      closeStoryModal();
    }
  }

  function prevStory() {
    if (currentStoryIndex > 0) {
      currentStoryIndex -= 1;
      renderCurrentStory();
    } else if (currentGroupIndex > 0) {
      currentGroupIndex -= 1;
      const prevGroup = storyGroups[currentGroupIndex];
      currentStoryIndex = Math.max(0, prevGroup.stories.length - 1);
      renderCurrentStory();
    } else {
      currentStoryIndex = 0;
      renderCurrentStory();
    }
  }

  function togglePauseStory() {
    storyPaused = !storyPaused;
    els.storyPauseBtn.textContent = storyPaused ? "▶" : "⏸";
    const video = els.storyMediaWrapper.querySelector("video");
    if (video) {
      if (storyPaused) video.pause();
      else video.play();
    }
  }

  function toggleMuteStory() {
    storyMuted = !storyMuted;
    els.storyMuteBtn.textContent = storyMuted ? "🔇" : "🔊";
    const video = els.storyMediaWrapper.querySelector("video");
    if (video) {
      video.muted = storyMuted;
    }
  }

  // Post Lightbox Modal Logic
  function openPostModal(post) {
    activePost = post;
    activeSlideIndex = 0;
    els.postModal.hidden = false;
    document.body.style.overflow = "hidden";

    const username = (archiveData.profile && archiveData.profile.username) || "yukipanvel";
    els.postUsername.textContent = `@${username}`;
    els.postDate.textContent = formatDateTime(post.takenAt);
    els.postCaption.textContent = post.caption || "";
    els.postLikes.textContent = `♥ ${post.likesCount || 0}`;
    els.postComments.textContent = `💬 ${post.commentsCount || 0}`;
    els.postLink.href = post.permalink || "#";

    renderPostSlide();
  }

  function closePostModal() {
    els.postStage.innerHTML = "";
    els.postModal.hidden = true;
    document.body.style.overflow = "";
    activePost = null;
  }

  function renderPostSlide() {
    if (!activePost) return;
    const slides = activePost.media || [];
    const slide = slides[activeSlideIndex] || {};
    els.postStage.innerHTML = "";

    if (slide.type === "video") {
      const video = document.createElement("video");
      video.src = slide.localPath;
      if (slide.posterPath) video.poster = slide.posterPath;
      video.controls = true;
      video.autoplay = true;
      video.playsInline = true;
      els.postStage.appendChild(video);
    } else if (slide.localPath) {
      const img = document.createElement("img");
      img.src = slide.localPath;
      img.alt = activePost.caption || "Instagram post slide";
      els.postStage.appendChild(img);
    }

    const hasMultiple = slides.length > 1;
    els.carouselPrevBtn.hidden = !hasMultiple || activeSlideIndex === 0;
    els.carouselNextBtn.hidden = !hasMultiple || activeSlideIndex === slides.length - 1;

    els.carouselDots.innerHTML = "";
    if (hasMultiple) {
      slides.forEach((_, idx) => {
        const dot = document.createElement("span");
        dot.className = `carousel-dot${idx === activeSlideIndex ? " active" : ""}`;
        els.carouselDots.appendChild(dot);
      });
    }
  }

  function renderAll() {
    storyGroups = buildStoryGroups(archiveData.stories || []);
    renderProfile(archiveData);
    renderStoriesTray();
    renderGrid(archiveData);
  }

  async function init() {
    try {
      const resp = await fetch("data/archive.json", { cache: "no-store" });
      if (resp.ok) {
        archiveData = await resp.json();
      }
    } catch (err) {
      console.warn("Could not load data/archive.json:", err);
    }

    renderAll();

    els.avatarRing.addEventListener("click", () => {
      if (storyGroups.length > 0) openStoryModal(0, 0);
    });

    els.tabButtons.forEach((btn) => {
      btn.addEventListener("click", () => {
        els.tabButtons.forEach((b) => {
          b.classList.remove("active");
          b.setAttribute("aria-selected", "false");
        });
        btn.classList.add("active");
        btn.setAttribute("aria-selected", "true");
        activeTab = btn.dataset.tab || "posts";
        renderGrid(archiveData);
      });
    });

    els.searchInput.addEventListener("input", (e) => {
      searchQuery = e.target.value || "";
      renderGrid(archiveData);
    });

    // Story Modal Controls
    els.storyCloseBtn.addEventListener("click", closeStoryModal);
    els.storyPauseBtn.addEventListener("click", togglePauseStory);
    els.storyMuteBtn.addEventListener("click", toggleMuteStory);
    els.storyPrevZone.addEventListener("click", prevStory);
    els.storyNextZone.addEventListener("click", nextStory);

    // Post Modal Controls
    els.postCloseBtn.addEventListener("click", closePostModal);
    els.postBackdrop.addEventListener("click", closePostModal);
    els.carouselPrevBtn.addEventListener("click", () => {
      if (activeSlideIndex > 0) {
        activeSlideIndex -= 1;
        renderPostSlide();
      }
    });
    els.carouselNextBtn.addEventListener("click", () => {
      if (activePost && activeSlideIndex + 1 < (activePost.media || []).length) {
        activeSlideIndex += 1;
        renderPostSlide();
      }
    });

    // Keyboard shortcuts
    window.addEventListener("keydown", (e) => {
      if (!els.storyModal.hidden) {
        if (e.key === "Escape") closeStoryModal();
        else if (e.key === "ArrowRight") nextStory();
        else if (e.key === "ArrowLeft") prevStory();
        else if (e.key === " ") {
          e.preventDefault();
          togglePauseStory();
        }
      } else if (!els.postModal.hidden) {
        if (e.key === "Escape") closePostModal();
        else if (e.key === "ArrowRight") els.carouselNextBtn.click();
        else if (e.key === "ArrowLeft") els.carouselPrevBtn.click();
      }
    });
  }

  init();
})();
