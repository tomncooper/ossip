/**
 * TableSort - Click-to-sort column headings for OSSIP project pages
 *
 * Clicking a heading sorts the table by that column; clicking it again
 * reverses the order. A cell's sort key is its data-sort attribute when
 * present, otherwise its text. Integer keys sort before text keys, text keys
 * use natural ordering (so 1.9 < 1.10 and FLINK-9 < FLINK-10), and empty
 * keys always sort last. Headings marked data-nosort are left alone;
 * headings marked data-sort-reverse sort descending on the first click.
 */

const TableSort = (function() {
    'use strict';

    // Integers only: "1.10" is a version, not 1.1
    const INTEGER = /^-?\d+$/;

    function sortKey(row, index) {
        const cell = row.cells[index];
        if (!cell) return '';
        const key = cell.hasAttribute('data-sort')
            ? cell.getAttribute('data-sort')
            : cell.textContent;
        return key.trim();
    }

    function compareKeys(a, b) {
        if (a === '' || b === '') return (a === '') - (b === '');
        const aIsNum = INTEGER.test(a);
        const bIsNum = INTEGER.test(b);
        if (aIsNum && bIsNum) return Number(a) - Number(b);
        if (aIsNum !== bIsNum) return aIsNum ? -1 : 1;
        return a.localeCompare(b, undefined, { numeric: true, sensitivity: 'base' });
    }

    function sortBy(table, th, index) {
        const ascending = th.getAttribute('aria-sort') === 'none'
            ? !th.hasAttribute('data-sort-reverse')
            : th.getAttribute('aria-sort') !== 'ascending';

        table.querySelectorAll('thead th[aria-sort]').forEach(other => {
            other.setAttribute('aria-sort', 'none');
        });
        th.setAttribute('aria-sort', ascending ? 'ascending' : 'descending');

        const tbody = table.tBodies[0];
        const rows = Array.from(tbody.rows).map(row => ({ row, key: sortKey(row, index) }));
        rows.sort((x, y) => {
            const result = compareKeys(x.key, y.key);
            return ascending || x.key === '' || y.key === '' ? result : -result;
        });
        rows.forEach(({ row }) => tbody.appendChild(row));
    }

    function init(options) {
        const table = document.querySelector(options.tableSelector);
        if (!table) {
            console.error(`Table with selector '${options.tableSelector}' not found`);
            return;
        }

        table.querySelectorAll('thead th').forEach((th, index) => {
            if (th.hasAttribute('data-nosort')) return;
            th.classList.add('sortable');
            th.setAttribute('aria-sort', 'none');
            th.tabIndex = 0;
            th.addEventListener('click', () => sortBy(table, th, index));
            th.addEventListener('keydown', e => {
                if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    sortBy(table, th, index);
                }
            });
        });
    }

    return {
        init: init
    };
})();
