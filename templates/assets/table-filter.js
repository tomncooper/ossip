/**
 * TableFilter - A reusable table filtering library for OSSIP project pages
 *
 * Provides client-side filtering functionality for improvement proposal tables.
 * Filters are applied via dropdowns that show/hide table rows based on data
 * attributes, plus an optional free-text search box.
 */

const TableFilter = (function() {
    'use strict';

    const SEARCH_DEBOUNCE_MS = 150;

    let config = {};
    let filterState = {};

    // Free-text search state (kept separate from filterState so it can never
    // collide with a column id)
    let searchTerm = '';

    // Search index: one lowercase haystack string per row, built once at init
    // so keystrokes never re-read/re-lowercase the DOM
    const searchIndex = new Map();

    // Cached list of table body rows (static site; rows never change)
    let rowList = [];

    /**
     * Initialize the table filter with configuration
     * @param {Object} options - Configuration options
     * @param {string} options.tableSelector - CSS selector for the table element
     * @param {string} options.filterContainerId - ID for the filter controls container
     * @param {Array} options.columns - Array of column configurations
     * @param {string} options.columns[].id - Unique ID for the filter
     * @param {string} options.columns[].label - Display label for the filter
     * @param {string} options.columns[].dataAttr - Data attribute name on table rows
     * @param {boolean} options.columns[].multi - Optional: true when the attribute
     *     holds a JSON array of values; the dropdown lists individual values and
     *     rows match on partial membership
     * @param {Object} [options.search] - Optional free-text search configuration
     * @param {Array<number>} options.search.columns - Indices of the table cells
     *     to search (e.g. [0, 1] for ID + description/title)
     * @param {string} [options.search.placeholder] - Placeholder text for the input
     */
    function init(options) {
        config = options;

        // Initialize filter state (all filters set to 'all')
        config.columns.forEach(col => {
            filterState[col.id] = 'all';
        });
        searchTerm = '';

        // Cache the rows and build the search index up front
        cacheRows();
        buildSearchIndex();

        // Build the filter UI
        buildFilterUI();

        // Populate dropdowns with unique values from table
        populateFilters();

        // Attach event listeners
        attachEventListeners();

        // Initial row count display
        updateRowCount();
    }

    /**
     * Cache the tbody rows once so filtering passes avoid repeated
     * querySelectorAll calls on large tables.
     */
    function cacheRows() {
        const table = document.querySelector(config.tableSelector);
        if (!table) {
            console.error(`Table with selector '${config.tableSelector}' not found`);
            rowList = [];
            return;
        }
        rowList = Array.from(table.querySelectorAll('tbody tr'));
    }

    /**
     * Build the search index: for every row, concatenate the textContent of
     * the configured search cells (lowercased, space-separated) into a single
     * haystack string. Done once at init; each keystroke afterwards is just a
     * cached string lookup.
     */
    function buildSearchIndex() {
        searchIndex.clear();
        if (!config.search || !Array.isArray(config.search.columns)) return;

        rowList.forEach(row => {
            const haystack = config.search.columns
                .map(idx => {
                    const cell = row.cells[idx];
                    return cell ? cell.textContent.trim().toLowerCase() : '';
                })
                .filter(text => text !== '')
                .join(' ');
            searchIndex.set(row, haystack);
        });
    }

    /**
     * Build the filter UI HTML and inject into the page
     */
    function buildFilterUI() {
        const container = document.getElementById(config.filterContainerId);
        if (!container) {
            console.error(`Filter container with ID '${config.filterContainerId}' not found`);
            return;
        }

        let html = '<div class="filter-controls">';

        // Optional free-text search input (placed first: primary interaction)
        if (config.search) {
            const placeholder = config.search.placeholder || 'Search...';
            html += `
                <div class="filter-group">
                    <label for="search-input">Search:</label>
                    <input type="text" id="search-input" class="filter-search" placeholder="${placeholder}" autocomplete="off" />
                </div>
            `;
        }

        // Create a dropdown for each configured column
        config.columns.forEach(col => {
            html += `
                <div class="filter-group">
                    <label for="${col.id}-filter">${col.label}:</label>
                    <select id="${col.id}-filter" class="filter-dropdown">
                        <option value="all">All</option>
                    </select>
                </div>
            `;
        });

        // Add clear filters button and row counter
        html += `
            <div class="filter-group">
                <button id="clear-filters" class="clear-filters-btn">Clear Filters</button>
            </div>
            <div class="filter-group row-counter">
                <span id="row-count"></span>
            </div>
        `;

        html += '</div>';

        container.innerHTML = html;
    }

    /**
     * Get the filterable values for a row/column pair.
     *
     * For multi-value columns (e.g. authors, where a row holds a JSON array of
     * names in its data attribute) returns every individual value; for
     * single-value columns returns a one-element array. Legacy non-JSON values
     * on multi columns are tolerated and treated as a single value.
     */
    function getRowValues(row, col) {
        const raw = row.getAttribute(col.dataAttr);
        if (!raw || raw.trim() === '') return [];
        if (col.multi) {
            try {
                return JSON.parse(raw);
            } catch (e) {
                // Tolerate legacy non-JSON values: treat as single value
                return [raw];
            }
        }
        return [raw];
    }

    /**
     * Populate filter dropdowns with unique values from the table
     */
    function populateFilters() {
        config.columns.forEach(col => {
            const uniqueValues = new Set();

            rowList.forEach(row => {
                // Multi-value columns contribute each individual value to the
                // dropdown; single-value columns contribute the whole string
                getRowValues(row, col).forEach(value => {
                    if (value && value.trim() !== '') {
                        uniqueValues.add(value);
                    }
                });
            });

            // Sort values alphabetically
            const sortedValues = Array.from(uniqueValues).sort((a, b) =>
                a.localeCompare(b, undefined, { sensitivity: 'base' })
            );

            // Populate the dropdown
            const dropdown = document.getElementById(`${col.id}-filter`);
            if (dropdown) {
                sortedValues.forEach(value => {
                    const option = document.createElement('option');
                    option.value = value;
                    option.textContent = value;
                    dropdown.appendChild(option);
                });
            }
        });
    }

    /**
     * Attach event listeners to filter controls
     */
    function attachEventListeners() {
        // Attach change listeners to each dropdown
        config.columns.forEach(col => {
            const dropdown = document.getElementById(`${col.id}-filter`);
            if (dropdown) {
                dropdown.addEventListener('change', (e) => {
                    filterState[col.id] = e.target.value;
                    applyFilters();
                });
            }
        });

        // Attach debounced input listener to the search box
        const searchInput = document.getElementById('search-input');
        if (searchInput) {
            let debounceTimer = null;
            searchInput.addEventListener('input', (e) => {
                clearTimeout(debounceTimer);
                debounceTimer = setTimeout(() => {
                    searchTerm = e.target.value.toLowerCase().trim();
                    applyFilters();
                }, SEARCH_DEBOUNCE_MS);
            });
            // Escape clears the search
            searchInput.addEventListener('keydown', (e) => {
                if (e.key === 'Escape' && e.target.value !== '') {
                    e.target.value = '';
                    searchTerm = '';
                    applyFilters();
                }
            });
        }

        // Attach click listener to clear button
        const clearBtn = document.getElementById('clear-filters');
        if (clearBtn) {
            clearBtn.addEventListener('click', clearFilters);
        }
    }

    /**
     * Apply filters to the table based on current filter state.
     * Dropdown filters and the search term are combined with AND logic;
     * a row is visible only when it matches every active filter.
     */
    function applyFilters() {
        let visibleCount = 0;

        rowList.forEach(row => {
            // Check if row matches all active dropdown filters
            const matchesFilters = config.columns.every(col => {
                const filterValue = filterState[col.id];
                if (filterValue === 'all') return true;

                // Multi-value columns match on partial membership: a row
                // matches when the selected value is one of its values
                return getRowValues(row, col).includes(filterValue);
            });

            // Check the free-text search against the prebuilt index
            const matchesSearch = !searchTerm ||
                (searchIndex.get(row) || '').includes(searchTerm);

            const visible = matchesFilters && matchesSearch;
            row.classList.toggle('filtered-out', !visible);
            if (visible) visibleCount++;
        });

        updateRowCount(visibleCount, rowList.length);
    }

    /**
     * Clear all filters (dropdowns + search) and show all rows
     */
    function clearFilters() {
        // Reset all dropdowns to 'all'
        config.columns.forEach(col => {
            const dropdown = document.getElementById(`${col.id}-filter`);
            if (dropdown) {
                dropdown.value = 'all';
            }
            filterState[col.id] = 'all';
        });

        // Reset the search box
        const searchInput = document.getElementById('search-input');
        if (searchInput) searchInput.value = '';
        searchTerm = '';

        // Route through the shared filtering path so row count and
        // visibility stay single-sourced
        applyFilters();
    }

    /**
     * Update the row count display
     * @param {number} visible - Number of visible rows (optional, will count if not provided)
     * @param {number} total - Total number of rows (optional, will count if not provided)
     */
    function updateRowCount(visible, total) {
        const totalCount = total !== undefined ? total : rowList.length;
        const visibleCount = visible !== undefined ? visible :
            rowList.filter(row => !row.classList.contains('filtered-out')).length;

        const counterEl = document.getElementById('row-count');
        if (counterEl) {
            if (visibleCount === totalCount) {
                counterEl.textContent = `Showing all ${totalCount} proposals`;
            } else {
                counterEl.textContent = `Showing ${visibleCount} of ${totalCount} proposals`;
            }
        }
    }

    // Public API
    return {
        init: init
    };
})();
