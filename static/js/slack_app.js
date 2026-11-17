/**
 * Authentic Slack Web Controller
 * Handles mentions, formatting, reactions, modal shortcuts, and channel switching
 */
document.addEventListener('DOMContentLoaded', () => {
  initModals();
  initMentionAutocomplete();
  initToasts();
  initUserSwitcher();
  initFilters();
  initKeyboardShortcuts();
  initReactions();
  initChatEnterKey();
  initHuddleSystem();
});

function initChatEnterKey() {
  const chatTextarea = document.getElementById('chat-composer-textarea');
  if (chatTextarea) {
    chatTextarea.addEventListener('keydown', (e) => {
      if (mentionPopup && mentionPopup.classList.contains('visible')) return;
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        const form = chatTextarea.closest('form');
        if (chatTextarea.value.trim() && form) {
          form.submit();
        }
      }
    });
  }
}

// 1. Modals management
function initModals() {
  const modalTriggers = document.querySelectorAll('[data-open-modal]');
  const modalClosers = document.querySelectorAll('[data-close-modal]');
  const overlays = document.querySelectorAll('.modal-overlay');

  modalTriggers.forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.preventDefault();
      const modalId = btn.getAttribute('data-open-modal');
      const target = document.getElementById(modalId);
      if (target) {
        target.classList.add('open');
        const firstInput = target.querySelector('input:not([type=hidden]), textarea');
        if (firstInput) setTimeout(() => firstInput.focus(), 100);
      }
    });
  });

  modalClosers.forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.preventDefault();
      const modal = btn.closest('.modal-overlay');
      if (modal) modal.classList.remove('open');
    });
  });

  overlays.forEach(overlay => {
    overlay.addEventListener('click', (e) => {
      if (e.target === overlay) overlay.classList.remove('open');
    });
  });
}

// Helper to open the Add Task modal with a pre‑selected status
function openAddTaskModal(status) {
  const modal = document.getElementById('add-task-modal');
  if (!modal) return;
  // Set the status dropdown
  const statusSelect = document.getElementById('task-modal-status');
  if (statusSelect) statusSelect.value = status;
  // Reset the form (clears previous inputs) but keep the status
  const form = document.getElementById('add-task-form');
  if (form) form.reset();
  // Re‑apply the status after reset
  if (statusSelect) statusSelect.value = status;
  // Show the modal
  modal.classList.add('open');
  // Focus the title field for quick entry
  const titleInput = document.getElementById('task-modal-title');
  if (titleInput) setTimeout(() => titleInput.focus(), 100);
}


// 2. Keyboard shortcuts (Ctrl+K for search, Esc to close)
function initKeyboardShortcuts() {
  document.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
      e.preventDefault();
      const searchModal = document.getElementById('quick-search-modal');
      if (searchModal) {
        searchModal.classList.add('open');
        const input = document.getElementById('quick-jump-input');
        if (input) setTimeout(() => input.focus(), 100);
      }
    } else if (e.key === 'Escape') {
      document.querySelectorAll('.modal-overlay').forEach(m => m.classList.remove('open'));
      hideMentionPopup();
    }
  });

  const jumpInput = document.getElementById('quick-jump-input');
  if (jumpInput) {
    jumpInput.addEventListener('input', (e) => {
      const q = e.target.value.toLowerCase();
      const channels = document.querySelectorAll('#quick-search-modal .channel-item');
      channels.forEach(ch => {
        const text = ch.textContent.toLowerCase();
        ch.style.display = text.includes(q) ? 'flex' : 'none';
      });
    });
  }
}

// 3. Autocomplete for @mentions
let activeTextarea = null;
let mentionPopup = null;
let mentionUsers = [];

function initMentionAutocomplete() {
  const usersScript = document.getElementById('workspace-users-json');
  if (usersScript) {
    try {
      mentionUsers = JSON.parse(usersScript.textContent);
    } catch (err) {
      console.error("Failed to parse workspace users:", err);
    }
  }

  mentionPopup = document.createElement('div');
  mentionPopup.className = 'mention-popup';
  document.body.appendChild(mentionPopup);

  const mentionInputs = document.querySelectorAll('.mention-input');
  mentionInputs.forEach(input => {
    input.addEventListener('keyup', handleMentionInput);
    input.addEventListener('keydown', handleMentionKeydown);
    input.addEventListener('focus', () => { activeTextarea = input; });
  });

  document.addEventListener('click', (e) => {
    if (mentionPopup && !mentionPopup.contains(e.target) && e.target !== activeTextarea) {
      hideMentionPopup();
    }
  });
}

function handleMentionInput(e) {
  const textarea = e.target;
  activeTextarea = textarea;
  const cursor = textarea.selectionStart;
  const text = textarea.value.substring(0, cursor);

  const lastAt = text.lastIndexOf('@');
  if (lastAt !== -1 && (lastAt === 0 || /\s/.test(text[lastAt - 1]))) {
    const query = text.substring(lastAt + 1).toLowerCase();
    if (!query.includes(' ') && !query.includes('\n')) {
      showMentionMatches(query, textarea, lastAt);
      return;
    }
  }
  hideMentionPopup();
}

function showMentionMatches(query, textarea, atIndex) {
  const matches = mentionUsers.filter(u =>
    u.username.toLowerCase().includes(query) ||
    u.name.toLowerCase().includes(query)
  );

  if (matches.length === 0) {
    hideMentionPopup();
    return;
  }

  mentionPopup.innerHTML = '';
  matches.forEach((user, idx) => {
    const opt = document.createElement('div');
    opt.className = `mention-popup-item ${idx === 0 ? 'selected' : ''}`;
    opt.innerHTML = `
      <div class="slack-avatar-square" style="width:24px;height:24px;font-size:10px;background:${user.color};">${user.initials}</div>
      <div style="display:flex;flex-direction:column;line-height:1.2;">
        <span style="font-weight:700;font-size:13px;">${user.name}</span>
        <span style="font-size:11px;color:#888;">@${user.username} &bull; ${user.role}</span>
      </div>
    `;
    opt.addEventListener('mousedown', (e) => {
      e.preventDefault();
      insertMention(user, textarea, atIndex);
    });
    mentionPopup.appendChild(opt);
  });

  const rect = textarea.getBoundingClientRect();
  mentionPopup.style.left = `${rect.left + 10}px`;
  mentionPopup.style.top = `${rect.top - Math.min(220, matches.length * 48) - 10}px`;
  mentionPopup.classList.add('visible');
}

function handleMentionKeydown(e) {
  if (!mentionPopup || !mentionPopup.classList.contains('visible')) return;

  const options = mentionPopup.querySelectorAll('.mention-popup-item');
  let selectedIdx = Array.from(options).findIndex(o => o.classList.contains('selected'));

  if (e.key === 'ArrowDown') {
    e.preventDefault();
    if (selectedIdx < options.length - 1) {
      options[selectedIdx].classList.remove('selected');
      options[selectedIdx + 1].classList.add('selected');
      options[selectedIdx + 1].scrollIntoView({ block: 'nearest' });
    }
  } else if (e.key === 'ArrowUp') {
    e.preventDefault();
    if (selectedIdx > 0) {
      options[selectedIdx].classList.remove('selected');
      options[selectedIdx - 1].classList.add('selected');
      options[selectedIdx - 1].scrollIntoView({ block: 'nearest' });
    }
  } else if (e.key === 'Enter' || e.key === 'Tab') {
    if (selectedIdx !== -1) {
      e.preventDefault();
      options[selectedIdx].dispatchEvent(new MouseEvent('mousedown'));
    }
  }
}

function insertMention(user, textarea, atIndex) {
  const currentVal = textarea.value;
  const cursor = textarea.selectionStart;

  const before = currentVal.substring(0, atIndex);
  const after = currentVal.substring(cursor);
  const mentionText = `@${user.username} `;

  textarea.value = before + mentionText + after;
  const newCursor = atIndex + mentionText.length;
  textarea.selectionStart = textarea.selectionEnd = newCursor;
  textarea.focus();

  hideMentionPopup();

  // Also auto-select in tagged_users select if present
  const tagSelect = document.querySelector('.slack-tag-select');
  if (tagSelect) {
    for (let i = 0; i < tagSelect.options.length; i++) {
      if (tagSelect.options[i].value == user.id) {
        tagSelect.options[i].selected = true;
      }
    }
  }
}

function hideMentionPopup() {
  if (mentionPopup) {
    mentionPopup.classList.remove('visible');
  }
}

// 4. Formatting tools for message composer
window.applyFormat = function(symbol) {
  const textarea = activeTextarea || document.querySelector('.composer-input-grid textarea');
  if (!textarea) return;

  const start = textarea.selectionStart;
  const end = textarea.selectionEnd;
  const selectedText = textarea.value.substring(start, end);

  if (symbol === '• ') {
    textarea.value = textarea.value.substring(0, start) + '\n• ' + selectedText + textarea.value.substring(end);
  } else {
    textarea.value = textarea.value.substring(0, start) + symbol + (selectedText || 'text') + symbol + textarea.value.substring(end);
  }
  textarea.focus();
};

function getCookie(name) {
  let cookieValue = null;
  if (document.cookie && document.cookie !== '') {
    const cookies = document.cookie.split(';');
    for (let i = 0; i < cookies.length; i++) {
      const cookie = cookies[i].trim();
      if (cookie.substring(0, name.length + 1) === (name + '=')) {
        cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
        break;
      }
    }
  }
  return cookieValue;
}

window.manualToggleReaction = function(reportId, emoji) {
  const csrftoken = getCookie('csrftoken');
  const formData = new FormData();
  formData.append('emoji', emoji);

  fetch(`/reports/${reportId}/react/`, {
    method: 'POST',
    headers: {
      'X-CSRFToken': csrftoken,
    },
    body: formData
  })
  .then(res => res.json())
  .then(data => {
    if (data.status === 'ok') {
      updateReactionsBar(reportId, data.reactions);
    }
  })
  .catch(err => console.error("Error toggling reaction:", err));
};

function updateReactionsBar(reportId, reactions) {
  const bar = document.getElementById(`reactions-bar-${reportId}`);
  if (!bar) return;

  if (!reactions || reactions.length === 0) {
    bar.innerHTML = '';
    bar.style.display = 'none';
    return;
  }

  bar.style.display = 'flex';
  bar.innerHTML = '';
  reactions.forEach(r => {
    const chip = document.createElement('div');
    chip.className = `reaction-chip ${r.user_reacted ? 'active' : ''}`;
    chip.title = (r.users || []).join(', ');
    chip.onclick = function() { manualToggleReaction(reportId, r.emoji); };
    chip.innerHTML = `<span>${r.emoji}</span> <span>${r.count}</span>`;
    bar.appendChild(chip);
  });
}

// 5. Reactions Controller (Manual Reactions Only)
function initReactions() {
  document.querySelectorAll('.js-manual-react').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.preventDefault();
      const reportId = btn.getAttribute('data-report-id');
      const emoji = btn.getAttribute('data-emoji') || '👍';
      if (reportId) {
        manualToggleReaction(reportId, emoji);
      }
    });
  });
}

// 6. User Switcher & Profile Popover
function initUserSwitcher() {
  const trigger = document.getElementById('user-profile-trigger');
  const railTrigger = document.getElementById('rail-profile-trigger');
  const popover = document.getElementById('user-popover-menu');
  const switcher = document.getElementById('user-switcher');

  const togglePopover = (e, srcElem) => {
    e.stopPropagation();
    if (!popover) return;
    const isOpen = popover.classList.contains('open');
    if (isOpen) {
      popover.classList.remove('open');
      if (trigger) trigger.classList.remove('popover-open');
    } else {
      // Position popover right above or beside the clicked trigger
      const rect = srcElem ? srcElem.getBoundingClientRect() : (trigger ? trigger.getBoundingClientRect() : null);
      if (rect) {
        if (srcElem === railTrigger) {
          popover.style.left = (rect.right + 10) + 'px';
          popover.style.bottom = Math.max(16, window.innerHeight - rect.bottom) + 'px';
        } else {
          popover.style.left = Math.max(10, rect.left) + 'px';
          popover.style.bottom = (window.innerHeight - rect.top + 8) + 'px';
        }
      }
      popover.classList.add('open');
      if (trigger) trigger.classList.add('popover-open');
    }
  };

  if (trigger && popover) {
    trigger.addEventListener('click', (e) => togglePopover(e, trigger));
  }
  if (railTrigger && popover) {
    railTrigger.addEventListener('click', (e) => togglePopover(e, railTrigger));
  }

  if (popover) {
    document.addEventListener('click', (e) => {
      const clickedTrigger = (trigger && trigger.contains(e.target)) || (railTrigger && railTrigger.contains(e.target));
      if (!popover.contains(e.target) && !clickedTrigger) {
        popover.classList.remove('open');
        if (trigger) trigger.classList.remove('popover-open');
      }
    });

    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && popover.classList.contains('open')) {
        popover.classList.remove('open');
        if (trigger) trigger.classList.remove('popover-open');
      }
    });
  }

  if (switcher) {
    switcher.addEventListener('change', (e) => {
      const userId = e.target.value;
      if (userId) {
        window.location.href = `/switch-user/${userId}/`;
      }
    });
  }
}

// 7. Auto-dismiss toasts
function initToasts() {
  const toasts = document.querySelectorAll('.toast-msg');
  toasts.forEach(t => {
    setTimeout(() => {
      t.style.opacity = '0';
      t.style.transform = 'translateY(-10px)';
      t.style.transition = 'all 0.3s ease';
      setTimeout(() => t.remove(), 300);
    }, 4000);
  });
}

// 8. Filters
function initFilters() {
  const datePicker = document.getElementById('feed-date-filter');
  if (datePicker) {
    datePicker.addEventListener('change', (e) => {
      const url = new URL(window.location.href);
      if (e.target.value) {
        url.searchParams.set('date', e.target.value);
      } else {
        url.searchParams.delete('date');
      }
      window.location.href = url.toString();
    });
  }
}

// ==============================================================================
// 9. SLACK HUDDLE REAL-TIME MEETING CONTROLLER
// ==============================================================================

let currentHuddleState = {
  active: false,
  projectSlug: null,
  huddleId: null,
  durationSeconds: 0,
  timerInterval: null,
  pollInterval: null,
  isMuted: false,
  isCameraOn: false,
  isScreenSharing: false,
  localMediaStream: null,
  screenStream: null,
};

function initHuddleSystem() {
  // Bind Dock / Floating Bar Buttons
  const btnMic = document.getElementById('huddle-btn-mic');
  const btnCam = document.getElementById('huddle-btn-camera');
  const btnScreen = document.getElementById('huddle-btn-screen');
  const btnExpand = document.getElementById('huddle-btn-expand');
  const btnLeave = document.getElementById('huddle-btn-leave');

  // Bind Stage Window Buttons
  const stageBtnMic = document.getElementById('stage-btn-mic');
  const stageBtnCam = document.getElementById('stage-btn-cam');
  const stageBtnScreen = document.getElementById('stage-btn-screen');
  const stageBtnLeave = document.getElementById('stage-btn-leave');
  const stageBtnMinimize = document.getElementById('huddle-btn-minimize');
  const stageHeaderLeave = document.getElementById('huddle-btn-stage-leave');

  if (btnMic) btnMic.addEventListener('click', toggleHuddleMic);
  if (stageBtnMic) stageBtnMic.addEventListener('click', toggleHuddleMic);

  if (btnCam) btnCam.addEventListener('click', toggleHuddleCamera);
  if (stageBtnCam) stageBtnCam.addEventListener('click', toggleHuddleCamera);

  if (btnScreen) btnScreen.addEventListener('click', toggleHuddleScreenShare);
  if (stageBtnScreen) stageBtnScreen.addEventListener('click', toggleHuddleScreenShare);

  if (btnExpand) btnExpand.addEventListener('click', openHuddleStage);
  if (stageBtnMinimize) stageBtnMinimize.addEventListener('click', closeHuddleStage);

  if (btnLeave) btnLeave.addEventListener('click', leaveCurrentHuddle);
  if (stageBtnLeave) stageBtnLeave.addEventListener('click', leaveCurrentHuddle);
  if (stageHeaderLeave) stageHeaderLeave.addEventListener('click', leaveCurrentHuddle);

  // Check if current page is in a project channel and check status
  checkPageChannelHuddle();
}

function getCsrfToken() {
  const token = document.querySelector('[name=csrfmiddlewaretoken]');
  if (token) return token.value;
  const match = document.cookie.match(/csrftoken=([^;]+)/);
  return match ? match[1] : '';
}

function getChannelSlugFromUrl() {
  const match = window.location.pathname.match(/\/project\/([a-zA-Z0-9_\-]+)\//);
  return match ? match[1] : null;
}

function checkPageChannelHuddle() {
  const slug = getChannelSlugFromUrl();
  if (!slug) return;

  fetch(`/project/${slug}/huddle/status/`)
    .then(r => r.json())
    .then(data => {
      updateHuddleHeaderBtn(slug, data.is_active);
      if (data.is_active && data.current_in_huddle) {
        // User was already in this huddle; restore meeting UI
        connectHuddleUI(slug, data);
      }
    })
    .catch(err => console.error('Error fetching huddle status:', err));
}

function updateHuddleHeaderBtn(slug, isActive) {
  const btn = document.getElementById('channel-header-huddle-btn');
  const label = document.getElementById('channel-header-huddle-label');
  if (!btn || !label) return;

  if (isActive) {
    btn.classList.add('huddle-active');
    label.textContent = currentHuddleState.active ? 'In Huddle' : 'Join Huddle';
  } else {
    btn.classList.remove('huddle-active');
    label.textContent = 'Huddle';
  }
}

window.toggleChannelHuddle = function(slug) {
  if (currentHuddleState.active && currentHuddleState.projectSlug === slug) {
    // If currently in this huddle, clicking the header button toggles stage view
    const stage = document.getElementById('huddle-stage-modal');
    if (stage && stage.style.display !== 'none') {
      closeHuddleStage();
    } else {
      openHuddleStage();
    }
    return;
  }

  // Join or start huddle
  const formData = new FormData();
  formData.append('topic', `#${slug} Meeting`);

  fetch(`/project/${slug}/huddle/join/`, {
    method: 'POST',
    headers: { 'X-CSRFToken': getCsrfToken() },
    body: formData,
  })
    .then(r => r.json())
    .then(res => {
      fetch(`/project/${slug}/huddle/status/`)
        .then(r => r.json())
        .then(data => {
          connectHuddleUI(slug, data);
          openHuddleStage();
          playHuddleChime(true);
        });
    })
    .catch(err => alert('Could not start huddle: ' + err));
};

function connectHuddleUI(slug, data) {
  currentHuddleState.active = true;
  currentHuddleState.projectSlug = slug;
  currentHuddleState.huddleId = data.huddle_id;
  currentHuddleState.durationSeconds = data.duration_seconds || 0;

  // Show floating bar
  const floatingBar = document.getElementById('huddle-floating-bar');
  if (floatingBar) floatingBar.style.display = 'block';

  const barTitle = document.getElementById('huddle-bar-title');
  if (barTitle) barTitle.textContent = `Huddle • #${data.project_name || slug}`;

  const stageTitle = document.getElementById('huddle-stage-channel-name');
  if (stageTitle) stageTitle.textContent = `#${data.project_name || slug} Meeting`;

  updateHuddleHeaderBtn(slug, true);
  renderHuddleParticipants(data.participants || []);

  // Start timer
  if (currentHuddleState.timerInterval) clearInterval(currentHuddleState.timerInterval);
  currentHuddleState.timerInterval = setInterval(() => {
    currentHuddleState.durationSeconds++;
    const formatted = formatHuddleTime(currentHuddleState.durationSeconds);
    const timerElem = document.getElementById('huddle-timer');
    const stageTimer = document.getElementById('huddle-stage-timer');
    if (timerElem) timerElem.textContent = formatted;
    if (stageTimer) stageTimer.textContent = formatted;
  }, 1000);

  // Start background poll & ping interval (every 4 seconds)
  if (currentHuddleState.pollInterval) clearInterval(currentHuddleState.pollInterval);
  currentHuddleState.pollInterval = setInterval(pollHuddleState, 4000);
}

function pollHuddleState() {
  if (!currentHuddleState.active || !currentHuddleState.projectSlug) return;

  // Send ping update
  const formData = new FormData();
  formData.append('is_muted', currentHuddleState.isMuted);
  formData.append('is_camera_on', currentHuddleState.isCameraOn);
  formData.append('is_screen_sharing', currentHuddleState.isScreenSharing);

  fetch(`/project/${currentHuddleState.projectSlug}/huddle/update/`, {
    method: 'POST',
    headers: { 'X-CSRFToken': getCsrfToken() },
    body: formData,
  })
    .then(r => r.json())
    .catch(e => {});

  // Fetch latest participants
  fetch(`/project/${currentHuddleState.projectSlug}/huddle/status/`)
    .then(r => r.json())
    .then(data => {
      if (!data.is_active) {
        // Huddle ended
        handleHuddleEnded();
      } else {
        renderHuddleParticipants(data.participants || []);
      }
    })
    .catch(e => {});
}

function formatHuddleTime(totalSeconds) {
  const mins = Math.floor(totalSeconds / 60);
  const secs = totalSeconds % 60;
  return `${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
}

function renderHuddleParticipants(participants) {
  const countElem = document.getElementById('huddle-participant-count');
  if (countElem) {
    countElem.textContent = `${participants.length} ${participants.length === 1 ? 'person' : 'people'}`;
  }

  // Mini avatar cluster on dock bar
  const cluster = document.getElementById('huddle-avatar-cluster');
  if (cluster) {
    cluster.innerHTML = participants.map(p => `
      <div class="mini-huddle-avatar" style="background:${p.avatar_color};" title="${p.name} (@${p.username})">
        ${p.initials}
      </div>
    `).join('');
  }

  // Dynamically update huddle 🎧 icons next to users in sidebar Direct Messages
  const allUserIndicators = document.querySelectorAll('.user-huddle-indicator');
  allUserIndicators.forEach(el => el.style.display = 'none');
  participants.forEach(p => {
    const indicator = document.querySelector(`.user-huddle-user-${p.user_id}`);
    if (indicator) indicator.style.display = 'inline-flex';
  });

  const footerBadge = document.getElementById('footer-user-huddle-badge');
  if (footerBadge) {
    const selfInHuddle = participants.some(p => p.is_me);
    footerBadge.style.display = selfInHuddle ? 'inline-flex' : 'none';
  }

  // Update video grid in stage
  const grid = document.getElementById('huddle-video-grid');
  if (!grid) return;

  // Keep self card, update or append other participants
  const selfCard = document.getElementById('huddle-self-card');
  grid.innerHTML = '';
  if (selfCard) grid.appendChild(selfCard);

  participants.forEach(p => {
    if (p.is_me) return; // Self is already shown

    const card = document.createElement('div');
    card.className = 'huddle-video-card';
    card.innerHTML = `
      <div class="huddle-video-viewfinder">
        <div class="huddle-video-placeholder">
          <div class="slack-avatar-square" style="width:72px;height:72px;font-size:26px;background:${p.avatar_color};">
            ${p.initials}
          </div>
        </div>
        <div class="huddle-card-badges">
          <span class="huddle-status-pill-badge">${p.is_muted ? '🔇 Muted' : '🎙️ Active'}</span>
          ${p.is_screen_sharing ? '<span class="huddle-status-pill-badge" style="background:#0052CC;">🖥️ Sharing</span>' : ''}
        </div>
      </div>
      <div class="huddle-card-footer">
        <span class="huddle-card-username">${p.name}</span>
      </div>
    `;
    grid.appendChild(card);
  });
}

function toggleHuddleMic() {
  currentHuddleState.isMuted = !currentHuddleState.isMuted;
  
  if (currentHuddleState.localMediaStream) {
    currentHuddleState.localMediaStream.getAudioTracks().forEach(track => {
      track.enabled = !currentHuddleState.isMuted;
    });
  }

  const micBadge = document.getElementById('huddle-self-mic-badge');
  if (micBadge) {
    micBadge.textContent = currentHuddleState.isMuted ? '🔇 Muted' : '🎙️ Active';
    micBadge.style.background = currentHuddleState.isMuted ? 'rgba(224, 30, 90, 0.8)' : 'rgba(0, 0, 0, 0.65)';
  }

  const btnMic = document.getElementById('huddle-btn-mic');
  const stageBtnMic = document.getElementById('stage-btn-mic');
  [btnMic, stageBtnMic].forEach(btn => {
    if (!btn) return;
    if (currentHuddleState.isMuted) {
      btn.classList.add('muted');
      btn.querySelector('.ctrl-label, .huddle-ctrl-text').textContent = 'Unmute';
      btn.querySelector('.ctrl-icon, .huddle-ctrl-icon').textContent = '🔇';
    } else {
      btn.classList.remove('muted');
      btn.querySelector('.ctrl-label, .huddle-ctrl-text').textContent = 'Mute';
      btn.querySelector('.ctrl-icon, .huddle-ctrl-icon').textContent = '🎙️';
    }
  });

  pollHuddleState();
}

function toggleHuddleCamera() {
  currentHuddleState.isCameraOn = !currentHuddleState.isCameraOn;
  const videoElem = document.getElementById('huddle-local-video');
  const placeholderElem = document.getElementById('huddle-local-placeholder');
  const btnCam = document.getElementById('huddle-btn-camera');
  const stageBtnCam = document.getElementById('stage-btn-cam');

  if (currentHuddleState.isCameraOn) {
    navigator.mediaDevices.getUserMedia({ video: true, audio: true })
      .then(stream => {
        currentHuddleState.localMediaStream = stream;
        if (videoElem) {
          videoElem.srcObject = stream;
          videoElem.style.display = 'block';
        }
        if (placeholderElem) placeholderElem.style.display = 'none';

        [btnCam, stageBtnCam].forEach(btn => {
          if (!btn) return;
          btn.classList.add('active');
          btn.querySelector('.ctrl-label, .huddle-ctrl-text').textContent = 'Video Off';
        });
        pollHuddleState();
      })
      .catch(err => {
        console.warn('Camera permission denied or camera not found:', err);
        currentHuddleState.isCameraOn = false;
        alert('Could not access camera/mic: ' + err.message);
      });
  } else {
    if (currentHuddleState.localMediaStream) {
      currentHuddleState.localMediaStream.getVideoTracks().forEach(t => t.stop());
    }
    if (videoElem) {
      videoElem.srcObject = null;
      videoElem.style.display = 'none';
    }
    if (placeholderElem) placeholderElem.style.display = 'flex';

    [btnCam, stageBtnCam].forEach(btn => {
      if (!btn) return;
      btn.classList.remove('active');
      btn.querySelector('.ctrl-label, .huddle-ctrl-text').textContent = 'Video';
    });
    pollHuddleState();
  }
}

function toggleHuddleScreenShare() {
  currentHuddleState.isScreenSharing = !currentHuddleState.isScreenSharing;
  const btnScreen = document.getElementById('huddle-btn-screen');
  const stageBtnScreen = document.getElementById('stage-btn-screen');
  const videoElem = document.getElementById('huddle-local-video');
  const placeholderElem = document.getElementById('huddle-local-placeholder');

  if (currentHuddleState.isScreenSharing) {
    navigator.mediaDevices.getDisplayMedia({ video: true })
      .then(stream => {
        currentHuddleState.screenStream = stream;
        if (videoElem) {
          videoElem.srcObject = stream;
          videoElem.style.display = 'block';
          videoElem.style.transform = 'none'; // do not mirror screen
        }
        if (placeholderElem) placeholderElem.style.display = 'none';

        stream.getVideoTracks()[0].onended = () => {
          toggleHuddleScreenShare(); // auto revert when user stops sharing
        };

        [btnScreen, stageBtnScreen].forEach(btn => {
          if (!btn) return;
          btn.classList.add('active');
          btn.querySelector('.ctrl-label, .huddle-ctrl-text').textContent = 'Stop Sharing';
        });
        pollHuddleState();
      })
      .catch(err => {
        currentHuddleState.isScreenSharing = false;
        console.warn('Screen share cancelled:', err);
      });
  } else {
    if (currentHuddleState.screenStream) {
      currentHuddleState.screenStream.getTracks().forEach(t => t.stop());
    }
    if (videoElem) {
      if (currentHuddleState.isCameraOn && currentHuddleState.localMediaStream) {
        videoElem.srcObject = currentHuddleState.localMediaStream;
        videoElem.style.transform = 'scaleX(-1)';
      } else {
        videoElem.style.display = 'none';
        if (placeholderElem) placeholderElem.style.display = 'flex';
      }
    }

    [btnScreen, stageBtnScreen].forEach(btn => {
      if (!btn) return;
      btn.classList.remove('active');
      btn.querySelector('.ctrl-label, .huddle-ctrl-text').textContent = 'Share Screen';
    });
    pollHuddleState();
  }
}

function openHuddleStage() {
  const modal = document.getElementById('huddle-stage-modal');
  if (modal) modal.style.display = 'flex';
}

function closeHuddleStage() {
  const modal = document.getElementById('huddle-stage-modal');
  if (modal) modal.style.display = 'none';
}

function leaveCurrentHuddle() {
  if (!currentHuddleState.active || !currentHuddleState.projectSlug) return;
  const slug = currentHuddleState.projectSlug;

  fetch(`/project/${slug}/huddle/leave/`, {
    method: 'POST',
    headers: { 'X-CSRFToken': getCsrfToken() },
  })
    .finally(() => {
      handleHuddleEnded();
      playHuddleChime(false);
    });
}

function handleHuddleEnded() {
  // Stop media tracks
  if (currentHuddleState.localMediaStream) {
    currentHuddleState.localMediaStream.getTracks().forEach(t => t.stop());
  }
  if (currentHuddleState.screenStream) {
    currentHuddleState.screenStream.getTracks().forEach(t => t.stop());
  }

  // Clear timers
  if (currentHuddleState.timerInterval) clearInterval(currentHuddleState.timerInterval);
  if (currentHuddleState.pollInterval) clearInterval(currentHuddleState.pollInterval);

  const slug = currentHuddleState.projectSlug;

  currentHuddleState.active = false;
  currentHuddleState.projectSlug = null;
  currentHuddleState.huddleId = null;
  currentHuddleState.isMuted = false;
  currentHuddleState.isCameraOn = false;
  currentHuddleState.isScreenSharing = false;

  // Hide UI
  const floatingBar = document.getElementById('huddle-floating-bar');
  if (floatingBar) floatingBar.style.display = 'none';
  closeHuddleStage();

  // Clear sidebar indicators
  const allUserIndicators = document.querySelectorAll('.user-huddle-indicator');
  allUserIndicators.forEach(el => el.style.display = 'none');
  const footerBadge = document.getElementById('footer-user-huddle-badge');
  if (footerBadge) footerBadge.style.display = 'none';

  if (slug) updateHuddleHeaderBtn(slug, false);
}

// Pleasant WebAudio Slack chime for huddle join / leave
function playHuddleChime(isJoin) {
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.connect(gain);
    gain.connect(ctx.destination);

    const now = ctx.currentTime;
    if (isJoin) {
      // Ascending two-tone chime (Slack huddle join)
      osc.frequency.setValueAtTime(440, now);
      osc.frequency.setValueAtTime(587.33, now + 0.12);
      gain.gain.setValueAtTime(0.18, now);
      gain.gain.exponentialRampToValueAtTime(0.001, now + 0.35);
      osc.start(now);
      osc.stop(now + 0.35);
    } else {
      // Descending two-tone chime (Slack huddle leave)
      osc.frequency.setValueAtTime(587.33, now);
      osc.frequency.setValueAtTime(440, now + 0.12);
      gain.gain.setValueAtTime(0.18, now);
      gain.gain.exponentialRampToValueAtTime(0.001, now + 0.35);
      osc.start(now);
      osc.stop(now + 0.35);
    }
  } catch (e) {}
}

// ==============================================================================
// 10. MESSAGE & COMMENT EDIT / DELETE CONTROLLER
// ==============================================================================

window.openEditMessage = function(reportId) {
  const displayElem = document.getElementById(`msg-display-text-${reportId}`);
  const editBox = document.getElementById(`msg-edit-box-${reportId}`);
  const textarea = document.getElementById(`msg-edit-textarea-${reportId}`);

  if (displayElem && editBox) {
    displayElem.style.display = 'none';
    editBox.style.display = 'block';
    if (textarea) {
      textarea.focus();
      textarea.setSelectionRange(textarea.value.length, textarea.value.length);
    }
  }
};

window.cancelEditMessage = function(reportId) {
  const displayElem = document.getElementById(`msg-display-text-${reportId}`);
  const editBox = document.getElementById(`msg-edit-box-${reportId}`);
  if (displayElem && editBox) {
    displayElem.style.display = 'block';
    editBox.style.display = 'none';
  }
};

window.saveEditMessage = function(reportId) {
  const textarea = document.getElementById(`msg-edit-textarea-${reportId}`);
  if (!textarea) return;

  const content = textarea.value.trim();
  if (!content) {
    alert('Message content cannot be blank.');
    return;
  }

  const formData = new FormData();
  formData.append('content', content);

  fetch(`/reports/${reportId}/edit/`, {
    method: 'POST',
    headers: {
      'X-CSRFToken': getCsrfToken(),
      'X-Requested-With': 'XMLHttpRequest'
    },
    body: formData,
  })
    .then(r => r.json())
    .then(data => {
      if (data.status === 'ok') {
        const displayElem = document.getElementById(`msg-display-text-${reportId}`);
        const editBox = document.getElementById(`msg-edit-box-${reportId}`);
        const editedTag = document.getElementById(`msg-edited-tag-${reportId}`);

        if (displayElem) {
          displayElem.innerHTML = data.message_html;
          displayElem.style.display = 'block';
        }
        if (editBox) editBox.style.display = 'none';
        if (editedTag) editedTag.style.display = 'inline';
      } else {
        alert(data.error || 'Failed to update message.');
      }
    })
    .catch(err => alert('Error saving message: ' + err));
};

window.deleteMessage = function(reportId) {
  if (!confirm('Are you sure you want to delete this message? This cannot be undone.')) {
    return;
  }

  fetch(`/reports/${reportId}/delete/`, {
    method: 'POST',
    headers: {
      'X-CSRFToken': getCsrfToken(),
      'X-Requested-With': 'XMLHttpRequest'
    },
  })
    .then(r => r.json())
    .then(data => {
      if (data.status === 'ok') {
        const msgWrapper = document.getElementById(`msg-content-wrapper-${reportId}`);
        const msgRow = msgWrapper ? msgWrapper.closest('.slack-msg-row') : null;
        if (msgRow) {
          msgRow.style.opacity = '0';
          msgRow.style.transform = 'scale(0.95)';
          msgRow.style.transition = 'all 0.25s ease';
          setTimeout(() => msgRow.remove(), 260);
        }
      } else {
        alert(data.error || 'Failed to delete message.');
      }
    })
    .catch(err => alert('Error deleting message: ' + err));
};

window.openEditComment = function(commentId) {
  const textElem = document.getElementById(`comment-text-${commentId}`);
  const editBox = document.getElementById(`comment-edit-box-${commentId}`);
  const input = document.getElementById(`comment-input-${commentId}`);

  if (textElem && editBox) {
    textElem.style.display = 'none';
    editBox.style.display = 'block';
    if (input) input.focus();
  }
};

window.cancelEditComment = function(commentId) {
  const textElem = document.getElementById(`comment-text-${commentId}`);
  const editBox = document.getElementById(`comment-edit-box-${commentId}`);
  if (textElem && editBox) {
    textElem.style.display = 'block';
    editBox.style.display = 'none';
  }
};

window.saveEditComment = function(commentId) {
  const input = document.getElementById(`comment-input-${commentId}`);
  if (!input) return;

  const msg = input.value.trim();
  if (!msg) {
    alert('Reply cannot be blank.');
    return;
  }

  const formData = new FormData();
  formData.append('message', msg);

  fetch(`/comments/${commentId}/edit/`, {
    method: 'POST',
    headers: {
      'X-CSRFToken': getCsrfToken(),
      'X-Requested-With': 'XMLHttpRequest'
    },
    body: formData,
  })
    .then(r => r.json())
    .then(data => {
      if (data.status === 'ok') {
        const textElem = document.getElementById(`comment-text-${commentId}`);
        const editBox = document.getElementById(`comment-edit-box-${commentId}`);
        if (textElem) {
          textElem.textContent = data.message;
          textElem.style.display = 'block';
        }
        if (editBox) editBox.style.display = 'none';
      } else {
        alert(data.error || 'Failed to update reply.');
      }
    })
    .catch(err => alert('Error updating reply: ' + err));
};

window.deleteComment = function(commentId) {
  if (!confirm('Are you sure you want to delete this reply?')) {
    return;
  }

  fetch(`/comments/${commentId}/delete/`, {
    method: 'POST',
    headers: {
      'X-CSRFToken': getCsrfToken(),
      'X-Requested-With': 'XMLHttpRequest'
    },
  })
    .then(r => r.json())
    .then(data => {
      if (data.status === 'ok') {
        const item = document.getElementById(`comment-item-${commentId}`);
        if (item) {
          item.style.opacity = '0';
          item.style.transition = 'all 0.2s ease';
          setTimeout(() => item.remove(), 200);
        }
      } else {
        alert(data.error || 'Failed to delete reply.');
      }
    })
    .catch(err => alert('Error deleting reply: ' + err));
};

// 11. Confluence Table of Contents Smooth Scroller
window.smoothScrollToConfluenceDay = function(e, targetId) {
  if (e) e.preventDefault();
  const targetElem = document.getElementById(targetId);
  const container = document.getElementById('view-panel-confluence');

  if (targetElem) {
    if (container) {
      const offsetTop = targetElem.offsetTop - container.offsetTop - 16;
      container.scrollTo({
        top: offsetTop,
        behavior: 'smooth'
      });
    } else {
      targetElem.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    targetElem.style.transition = 'box-shadow 0.3s ease, background 0.3s ease';
    const oldBg = targetElem.style.background;
    targetElem.style.background = '#F0F7FA';
    targetElem.style.boxShadow = '0 0 0 3px #0052CC';
    setTimeout(() => {
      targetElem.style.background = oldBg || '';
      targetElem.style.boxShadow = '';
    }, 1200);
  }
};

// 12. Forward Message Controller

window.openForwardModal = function(rawContent) {
  const modal = document.getElementById('forward-message-modal');
  const preview = document.getElementById('forward-preview-box');
  const input = document.getElementById('forward-input-content');
  if (modal && preview && input) {
    input.value = rawContent;
    preview.textContent = rawContent;
    modal.style.display = 'flex';
  }
};

window.closeForwardModal = function() {
  const modal = document.getElementById('forward-message-modal');
  if (modal) modal.style.display = 'none';
};

window.toggleForwardDest = function(val) {
  const channelGroup = document.getElementById('forward-channel-group');
  const dmGroup = document.getElementById('forward-dm-group');
  const channelSelect = document.getElementById('forward-channel-select');
  const dmSelect = document.getElementById('forward-dm-select');

  if (val === 'dm') {
    channelGroup.style.display = 'none';
    channelSelect.disabled = true;
    channelSelect.name = 'dest_id_channel';

    dmGroup.style.display = 'block';
    dmSelect.disabled = false;
    dmSelect.name = 'dest_id';
  } else {
    dmGroup.style.display = 'none';
    dmSelect.disabled = true;
    dmSelect.name = 'dest_id_dm';

    channelGroup.style.display = 'block';
    channelSelect.disabled = false;
    channelSelect.name = 'dest_id';
  }
};

// Default Clean Theme: Light mode only
(function() {
  try {
    localStorage.removeItem('statuspulse_theme');
    document.body.classList.remove('dark-mode');
  } catch (e) {}
})();





