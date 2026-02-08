/**
 * TableFilter - A reusable table filtering library for OSSIP project pages
 * 
 * Provides client-side filtering functionality for improvement proposal tables.
 * Filters are applied via dropdowns that show/hide table rows based on data attributes.
 */

const TableFilter = (function() {
    'use strict';

    let config = {};
    let filterState = {};

    /**
     * Initialize the table filter with configuration
     * @param {Object} options - Configuration options
     * @param {string} options.tableSelector - CSS selector for the table element
     * @param {string} options.filterContainerId - ID for the filter controls container
     * @param {Array} options.columns - Array of column configurations
     * @param {string} options.columns[].id - Unique ID for the filter
     * @param {string} options.columns[].label - Display label for the filter
     * @param {string} options.columns[].dataAttr - Data attribute name on table rows
     */
    function init(options) {
        config = options;
        
        // Initialize filter state (all filters set to 'all')
        config.columns.forEach(col => {
            filterState[col.id] = 'all';
        });

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
     * Build the filter UI HTML and inject into the page
     */
    function buildFilterUI() {
        const container = document.getElementById(config.filterContainerId);
        if (!container) {
            console.error(`Filter container with ID '${config.filterContainerId}' not found`);
            return;
        }

        let html = '<div class="filter-controls">';
        
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
     * Populate filter dropdowns with unique values from the table
     */
    function populateFilters() {
        const table = document.querySelector(config.tableSelector);
        if (!table) {
            console.error(`Table with selector '${config.tableSelector}' not found`);
            return;
        }

        const rows = table.querySelectorAll('tbody tr');

        config.columns.forEach(col => {
            const uniqueValues = new Set();
            
            rows.forEach(row => {
                const value = row.getAttribute(col.dataAttr);
                if (value && value.trim() !== '') {
                    uniqueValues.add(value);
                }
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

        // Attach click listener to clear button
        const clearBtn = document.getElementById('clear-filters');
        if (clearBtn) {
            clearBtn.addEventListener('click', clearFilters);
        }
    }

    /**
     * Apply filters to the table based on current filter state
     */
    function applyFilters() {
        const table = document.querySelector(config.tableSelector);
        if (!table) return;

        const rows = table.querySelectorAll('tbody tr');
        let visibleCount = 0;

        rows.forEach(row => {
            // Check if row matches all active filters
            const matches = config.columns.every(col => {
                const filterValue = filterState[col.id];
                if (filterValue === 'all') return true;
                
                const rowValue = row.getAttribute(col.dataAttr);
                return rowValue === filterValue;
            });

            if (matches) {
                row.classList.remove('filtered-out');
                visibleCount++;
            } else {
                row.classList.add('filtered-out');
            }
        });

        updateRowCount(visibleCount, rows.length);
    }

    /**
     * Clear all filters and show all rows
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

        // Remove all filtered-out classes
        const table = document.querySelector(config.tableSelector);
        if (table) {
            const rows = table.querySelectorAll('tbody tr');
            rows.forEach(row => row.classList.remove('filtered-out'));
            updateRowCount(rows.length, rows.length);
        }
    }

    /**
     * Update the row count display
     * @param {number} visible - Number of visible rows (optional, will count if not provided)
     * @param {number} total - Total number of rows (optional, will count if not provided)
     */
    function updateRowCount(visible, total) {
        const table = document.querySelector(config.tableSelector);
        if (!table) return;

        const rows = table.querySelectorAll('tbody tr');
        const totalCount = total !== undefined ? total : rows.length;
        const visibleCount = visible !== undefined ? visible : 
            Array.from(rows).filter(row => !row.classList.contains('filtered-out')).length;

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
