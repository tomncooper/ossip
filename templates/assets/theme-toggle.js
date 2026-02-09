(function () {
    var STORAGE_KEY = 'ossip-theme';
    var LIGHT = 'light';

    function getPreferred() {
        return localStorage.getItem(STORAGE_KEY);
    }

    function isLight() {
        return document.documentElement.getAttribute('data-theme') === LIGHT;
    }

    function setTheme(light) {
        if (light) {
            document.documentElement.setAttribute('data-theme', LIGHT);
        } else {
            document.documentElement.removeAttribute('data-theme');
        }
        localStorage.setItem(STORAGE_KEY, light ? LIGHT : 'dark');
        updateButton();
    }

    var btn;

    function updateButton() {
        if (!btn) return;
        if (isLight()) {
            btn.textContent = '\u{1F319} Dark';
            btn.setAttribute('aria-label', 'Switch to dark theme');
        } else {
            btn.textContent = '\u{2600}\u{FE0F} Light';
            btn.setAttribute('aria-label', 'Switch to light theme');
        }
    }

    function init() {
        btn = document.createElement('button');
        btn.className = 'theme-toggle';
        btn.type = 'button';
        updateButton();

        btn.addEventListener('click', function () {
            setTheme(!isLight());
        });

        document.body.appendChild(btn);

        // Enable transitions after initial paint to avoid FOUC
        requestAnimationFrame(function () {
            requestAnimationFrame(function () {
                document.documentElement.classList.add('transitions-enabled');
            });
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
