(function () {
    function initTomSelects(root) {
      if (!window.TomSelect) return;
      (root || document).querySelectorAll('select.js-enhance-select').forEach(function (el) {
        if (el._tsInit) return; // idempotent
        el._tsInit = true;
  
        const isMulti     = el.multiple === true || el.hasAttribute('multiple');
        const placeholder = el.getAttribute('data-placeholder') || (isMulti ? 'Select one or more…' : 'Select…');
        const allowClear  = el.hasAttribute('data-allow-clear') && !isMulti; // clear_button only makes sense on single
        const maxItemsAttr = el.getAttribute('data-max-items');
        const maxItems    = isMulti ? (maxItemsAttr ? parseInt(maxItemsAttr, 10) : null) : 1;
  
        const plugins = ['dropdown_input'];
        // nice remove “x” on tokens
        if (isMulti) plugins.push('remove_button');
        if (allowClear) plugins.push('clear_button');
  
        new TomSelect(el, {
          plugins,
          maxItems,                // null = unlimited for multi
          create: false,
          selectOnTab: true,
          persist: false,
          closeAfterSelect: !isMulti,  // keep open while choosing multiple
          copyClassesToDropdown: true,
          placeholder,
          maxOptions: 2000,
          render: {
            no_results: (data, escape) =>
              `<div class="no-results p-2">No results for “<b>${escape(data.input)}</b>”</div>`
          },
          sortField: { field:'text', direction:'asc' },
        });
      });
    }
  
    // Init on DOM ready
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', function(){ initTomSelects(document); });
    } else {
      initTomSelects(document);
    }
  
    // Re-init helper if you inject forms dynamically
    window.initTomSelects = initTomSelects;
  })();
  