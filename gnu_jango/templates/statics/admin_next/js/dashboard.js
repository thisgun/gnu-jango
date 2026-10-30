(function () {
  function ready(callback) {
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', callback);
      return;
    }
    callback();
  }

  ready(function () {
    document.querySelectorAll('form[data-confirm]').forEach(function (form) {
      form.addEventListener('submit', function (event) {
        var message = form.getAttribute('data-confirm') || '';
        if (message && !window.confirm(message)) {
          event.preventDefault();
        }
      });
    });

    // A POST button inside another form (e.g. 배송조회 '지금 조회' on the order change form):
    // forms cannot nest, so post a small form of its own with the page's CSRF token.
    document.querySelectorAll('button[data-g5-post-url]').forEach(function (button) {
      button.addEventListener('click', function () {
        var token = document.querySelector('input[name="csrfmiddlewaretoken"]');
        var target;
        try {
          target = new URL(button.getAttribute('data-g5-post-url') || '', window.location.href);
        } catch (error) {
          return;
        }
        // same-origin admin paths only: never a javascript: or foreign URL from the markup
        if (!token || button.disabled || target.origin !== window.location.origin) {
          return;
        }
        button.disabled = true;
        var form = document.createElement('form');
        form.method = 'post';
        form.action = target.pathname + target.search;
        var input = document.createElement('input');
        input.type = 'hidden';
        input.name = 'csrfmiddlewaretoken';
        input.value = token.value;
        form.appendChild(input);
        document.body.appendChild(form);
        form.submit();
      });
    });

    var toggle = document.querySelector('[data-admin-menu-toggle]');
    if (toggle) {
      toggle.addEventListener('click', function () {
        document.body.classList.toggle('g5-admin-nav-open');
      });
    }

    var filter = document.querySelector('#changelist-filter');
    var hasNativeFilterTrigger = Array.prototype.some.call(
      document.querySelectorAll('a, button'),
      function (el) {
        if (el.hasAttribute('data-g5-admin-filter-toggle')) {
          return false;
        }
        var text = (el.textContent || '').replace(/\s+/g, ' ').trim();
        return text.indexOf('필터') !== -1 || text.indexOf('filter_list') !== -1;
      }
    );

    if (filter && !hasNativeFilterTrigger && !document.querySelector('[data-g5-admin-filter-toggle]')) {
      var filterToggle = document.createElement('button');
      filterToggle.type = 'button';
      filterToggle.className = 'g5-admin-filter-toggle';
      filterToggle.setAttribute('data-g5-admin-filter-toggle', '');
      filterToggle.setAttribute('aria-controls', filter.id || 'changelist-filter');
      filterToggle.setAttribute('aria-expanded', 'false');
      filterToggle.innerHTML = '<span class="material-symbols-outlined" aria-hidden="true">filter_alt</span><strong>&#54596;&#53552;</strong>';

      filter.parentNode.insertBefore(filterToggle, filter);
      filter.classList.add('g5-admin-filter-panel');

      filterToggle.addEventListener('click', function () {
        var isOpen = document.body.classList.toggle('g5-admin-filters-open');
        filterToggle.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
      });
    }

    var search = document.querySelector('#changelist-search, #toolbar form');
    if (search) {
      search.classList.add('g5-admin-mobile-search');
    }

    var actionBar = document.querySelector('.actions');
    if (actionBar) {
      actionBar.classList.add('g5-admin-mobile-actions');
    }

    document.querySelectorAll('.g5-admin-flow-list').forEach(function (list) {
      if (list.scrollWidth > list.clientWidth) {
        list.setAttribute('tabindex', '0');
        list.setAttribute('aria-label', list.getAttribute('aria-label') || 'Operations pipeline');
      }
    });
  });
})();
