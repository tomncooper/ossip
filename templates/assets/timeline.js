/*
 * OSSIP timeline page: fetches the proposal event log JSON
 * (api/v1/events/events.json), renders a vertical timeline with summary
 * cards, and supports infinite scroll through the full history
 * (newest-first). Vanilla JS, no build step.
 *
 * Deep-link contract (used by the project index pages):
 *   ?project=kafka            pre-select a single project
 *   ?hide=renumbered,vote_started  start with those event types hidden
 *   ?q=share+groups           initial search text
 */
(function () {
    'use strict';

    var EVENTS_URL = 'api/v1/events/events.json';
    var BATCH_SIZE = 50;
    var SEARCH_DEBOUNCE_MS = 200;

    // Event-type visual vocabulary (mirrors docs + social messages).
    var TYPE_META = {
        new: { label: 'New', icon: '🆕' },
        state_changed: { label: 'State change', icon: null }, // icon = state emoji
        renumbered: { label: 'Renumbered', icon: '♻️' },
        disappeared: { label: 'Removed', icon: '🚫' },
        first_approval: { label: 'First approval', icon: '👍' },
        changes_requested: { label: 'Changes requested', icon: '🛠️' },
        vote_started: { label: 'Vote started', icon: '🗳️' }
    };

    var STATE_ICONS = {
        accepted: '✅',
        completed: '✅',
        'under discussion': '💬',
        'not accepted': '❌',
        'in progress': '🛠️',
        unknown: '❓'
    };

    var PROJECTS = [
        { key: 'kafka', label: 'Kafka' },
        { key: 'flink', label: 'Flink' },
        { key: 'strimzi', label: 'Strimzi' },
        { key: 'streamshub', label: 'StreamsHub' },
        { key: 'kroxylicious', label: 'Kroxylicious' }
    ];

    var MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
        'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

    // State
    var allEvents = [];      // full ApiEvent list, newest-first, as fetched
    var filteredEvents = []; // after filters
    var renderedCount = 0;
    var rendering = false;

    // Filters (derived once from the URL, then mutated by the UI)
    var filters = {
        project: null,
        hiddenTypes: new Set(),
        search: ''
    };

    // ---- DOM helpers ------------------------------------------------------

    function $(id) {
        return document.getElementById(id);
    }

    function el(tag, className, text) {
        var node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined) node.textContent = text;
        return node;
    }

    function sameOriginPath(url) {
        // https://ossip.dev/kips/KIP-900.html -> kips/KIP-900.html when the
        // origin matches this deployment; the absolute URL otherwise (file://
        // testing, mirrors).
        try {
            var resolved = new URL(url, window.location.href);
            if (resolved.origin === window.location.origin &&
                resolved.protocol !== 'file:') {
                return resolved.pathname.replace(/^\//, '');
            }
            return resolved.href;
        } catch (err) {
            return url;
        }
    }

    function formatDate(iso) {
        if (!iso) return '';
        var date = new Date(iso);
        if (isNaN(date.getTime())) return iso; // fall back to the raw string
        return MONTHS[date.getUTCMonth()] + ' ' +
            date.getUTCDate() + ', ' + date.getUTCFullYear();
    }

    function formatUpdated(iso) {
        // generated_at (YYYY-MM-DDTHH:MM:SSZ) -> "21 Nov 2026"
        var date = new Date(iso);
        if (isNaN(date.getTime())) return iso;
        return date.getUTCDate() + ' ' + MONTHS[date.getUTCMonth()] + ' ' +
            date.getUTCFullYear();
    }

    function eventIcon(ev) {
        if (ev.event_type === 'state_changed') {
            return STATE_ICONS[(ev.state_after || 'unknown').toLowerCase()] || '•';
        }
        var meta = TYPE_META[ev.event_type];
        return meta && meta.icon ? meta.icon : '•';
    }

    // ---- Filters ----------------------------------------------------------

    function filtersFromUrl() {
        var params = new URLSearchParams(window.location.search);
        var project = params.get('project');
        if (project && PROJECTS.some(function (p) { return p.key === project; })) {
            filters.project = project;
        }
        var hide = params.get('hide');
        if (hide) {
            hide.split(',').forEach(function (type) {
                if (type) filters.hiddenTypes.add(type);
            });
        }
        var q = params.get('q');
        if (q) filters.search = q;
    }

    function scrollToTimelineStart() {
        // Bring the top of the (re-rendered) list into view just below
        // the sticky controls, so filter changes never strand the user
        // mid-page with the rebuilt list far above the viewport.
        var timeline = $('tl-timeline');
        var controls = $('tl-controls');
        var top = timeline.getBoundingClientRect().top + window.scrollY
            - controls.getBoundingClientRect().height - 12;
        window.scrollTo(0, Math.max(0, top));
    }

    function applyFilters(scrollToStart) {
        var search = filters.search.toLowerCase();
        filteredEvents = allEvents.filter(function (ev) {
            if (filters.project && ev.project !== filters.project) return false;
            if (filters.hiddenTypes.has(ev.event_type)) return false;
            if (search) {
                var haystack = [ev.title, ev.reference, ev.current_reference]
                    .filter(Boolean).join(' ').toLowerCase();
                if (haystack.indexOf(search) === -1) return false;
            }
            return true;
        });
        renderedCount = 0;
        var timeline = $('tl-timeline');
        while (timeline.firstChild) timeline.removeChild(timeline.firstChild);
        updateCount();
        setSentinel();
        renderBatch();
        if (scrollToStart) scrollToTimelineStart();
    }

    function updateCount() {
        $('tl-count').textContent =
            'Showing ' + filteredEvents.length + ' of ' + allEvents.length + ' events';
    }

    function setSentinel() {
        var sentinel = $('tl-sentinel');
        if (allEvents.length === 0) {
            sentinel.textContent = 'No events found.';
        } else if (filteredEvents.length === 0) {
            sentinel.textContent = 'No events match the current filters';
        } else if (renderedCount >= filteredEvents.length) {
            sentinel.textContent = 'End of timeline';
        } else {
            sentinel.textContent = 'Loading more…';
        }
    }

    // ---- Rendering --------------------------------------------------------

    function renderBatch() {
        if (rendering) return;
        var batch = filteredEvents.slice(renderedCount, renderedCount + BATCH_SIZE);
        if (batch.length === 0) {
            setSentinel();
            return;
        }
        rendering = true;
        var timeline = $('tl-timeline');
        batch.forEach(function (ev) {
            timeline.appendChild(eventCard(ev));
        });
        renderedCount += batch.length;
        rendering = false;
        setSentinel();
    }

    function eventCard(ev) {
        var li = el('li', 'tl-event');
        li.setAttribute('data-project', ev.project);
        li.setAttribute('data-type', ev.event_type);

        var node = el('span', 'tl-node', eventIcon(ev));
        node.setAttribute('aria-hidden', 'true');
        li.appendChild(node);

        var card = el('div', 'tl-card');

        var meta = el('div', 'tl-meta');
        meta.appendChild(el('span', 'tl-date', formatDate(ev.event_time)));

        var project = el('span', 'tl-project tl-project-' + ev.project);
        project.appendChild(el('span', 'tl-dot'));
        project.appendChild(document.createTextNode(projectLabel(ev.project)));
        meta.appendChild(project);

        var url = ev.current_detail_url || ev.detail_url;
        var reference = ev.current_reference || ev.reference;
        if (url && reference) {
            var link = el('a', 'tl-ref', reference);
            link.href = sameOriginPath(url);
            meta.appendChild(link);
        } else if (reference) {
            meta.appendChild(el('span', 'tl-ref', reference));
        }

        card.appendChild(meta);

        var headline = el('div', 'tl-headline');
        if (url) {
            var headlineLink = el('a', 'tl-headline-link', ev.title);
            headlineLink.href = sameOriginPath(url);
            headline.appendChild(headlineLink);
        } else {
            headline.textContent = ev.title;
        }
        card.appendChild(headline);

        card.appendChild(el('div', 'tl-summary', ev.summary));
        li.appendChild(card);
        return li;
    }

    function projectLabel(key) {
        for (var i = 0; i < PROJECTS.length; i++) {
            if (PROJECTS[i].key === key) return PROJECTS[i].label;
        }
        return key; // never break on unknown projects
    }

    // ---- Filter bar construction ------------------------------------------

    function buildProjectChips() {
        var row = $('tl-project-chips');
        var allChip = chipButton('All', !filters.project);
        allChip.addEventListener('click', function () {
            filters.project = null;
            refreshProjectChips();
            applyFilters(true);
        });
        row.appendChild(allChip);

        PROJECTS.forEach(function (project) {
            var chip = chipButton(project.label, filters.project === project.key);
            chip.classList.add('tl-project-chip');
            chip.classList.add('tl-project-' + project.key);
            chip.addEventListener('click', function () {
                filters.project = filters.project === project.key ? null : project.key;
                refreshProjectChips();
                applyFilters(true);
            });
            row.appendChild(chip);
        });
    }

    function refreshProjectChips() {
        var row = $('tl-project-chips');
        row.replaceChildren();
        buildProjectChips();
    }

    function knownTypesIn(events) {
        // Union of known types and types present in the data, so unknown
        // future types are still filterable and render with a generic badge.
        var present = new Set(Object.keys(TYPE_META));
        events.forEach(function (ev) { present.add(ev.event_type); });
        return Array.from(present);
    }

    function buildTypeChips() {
        var row = $('tl-type-chips');
        var types = knownTypesIn(allEvents);
        types.sort();
        types.forEach(function (type) {
            var meta = TYPE_META[type] || { label: type, icon: null };
            var active = !filters.hiddenTypes.has(type);
            var chip = chipButton(meta.label, active);
            if (meta.icon) chip.appendChild(document.createTextNode(' ' + meta.icon));
            chip.classList.add('tl-type-chip');
            chip.addEventListener('click', function () {
                if (filters.hiddenTypes.has(type)) {
                    filters.hiddenTypes.delete(type);
                } else {
                    filters.hiddenTypes.add(type);
                }
                var active = !filters.hiddenTypes.has(type);
                chip.classList.toggle('active', active);
                chip.setAttribute('aria-pressed', active ? 'true' : 'false');
                applyFilters(true);
            });
            row.appendChild(chip);
        });
    }

    function chipButton(label, active) {
        var chip = el('button', 'tl-chip' + (active ? ' active' : ''), label);
        chip.type = 'button';
        chip.setAttribute('aria-pressed', active ? 'true' : 'false');
        return chip;
    }

    // ---- Infinite scroll ---------------------------------------------------

    function setupInfiniteScroll() {
        var sentinel = $('tl-sentinel');
        if ('IntersectionObserver' in window) {
            var observer = new IntersectionObserver(function (entries) {
                entries.forEach(function (entry) {
                    if (entry.isIntersecting &&
                        renderedCount < filteredEvents.length) {
                        renderBatch();
                    }
                });
            }, { rootMargin: '600px' });
            observer.observe(sentinel);
        }
        // Belt-and-braces window-scroll listener: runs alongside the
        // observer on every browser. Harmless duplication — renderBatch
        // appends one batch per trigger and is a no-op once exhausted.
        window.addEventListener('scroll', function () {
            if (renderedCount >= filteredEvents.length) return;
            var rect = sentinel.getBoundingClientRect();
            if (rect.top < window.innerHeight + 600) renderBatch();
        }, { passive: true });
    }

    // ---- Data fetching -----------------------------------------------------

    function fetchEvents() {
        var sentinel = $('tl-sentinel');
        sentinel.textContent = 'Loading events…';
        fetch(EVENTS_URL)
            .then(function (response) {
                if (!response.ok) {
                    throw new Error('HTTP ' + response.status);
                }
                return response.json();
            })
            .then(function (data) {
                allEvents = data.events || [];
                if (data.generated_at) {
                    $('tl-updated').textContent = formatUpdated(data.generated_at);
                }
                buildTypeChips();
                applyFilters();
            })
            .catch(function () {
                sentinel.textContent = '';
                var message = el('p', 'tl-error', 'Could not load the event data.');
                sentinel.appendChild(message);
                var retry = el('button', 'tl-chip', 'Retry');
                retry.type = 'button';
                retry.addEventListener('click', function () {
                    while (sentinel.firstChild) {
                        sentinel.removeChild(sentinel.firstChild);
                    }
                    fetchEvents();
                });
                sentinel.appendChild(retry);
            });
    }

    // ---- Init ---------------------------------------------------------------

    function init() {
        filtersFromUrl();

        // Reflect the URL state in the controls before the first render.
        var search = $('tl-search');
        search.value = filters.search;
        var searchTimer = null;
        search.addEventListener('input', function () {
            window.clearTimeout(searchTimer);
            searchTimer = window.setTimeout(function () {
                filters.search = search.value.trim();
                applyFilters(true);
            }, SEARCH_DEBOUNCE_MS);
        });

        buildProjectChips();
        setupInfiniteScroll();
        fetchEvents();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
