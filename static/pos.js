/* ===== Helpers ===== */

function byId(id) { return document.getElementById(id); }
function q(sel, root=document) { return root.querySelector(sel); }
function qa(sel, root=document) { return Array.from(root.querySelectorAll(sel)); }

function focusLastProduct() {
  const rows = qa('#items-table tbody tr');
  if (!rows.length) return;
  const input = q('.product-input', rows[rows.length - 1]);
  if (input) input.focus();
}

/** Find product <option> by any of:
 *  - exact datalist value (the visible text)
 *  - barcode match (data-barcode)
 *  - code exact or prefix (data-code == typed || option.value starts with "CODE -")
 */
function findOption(valRaw) {
  if (!valRaw) return null;
  const val = String(valRaw).trim();
  const V = val.toUpperCase();
  const opts = qa('#products option');

  // exact visible value
  let opt = opts.find(o => o.value === val);
  if (opt) return opt;

  // barcode match
  opt = opts.find(o => (o.dataset.barcode || '') === val);
  if (opt) return opt;

  // code exact in data-code
  opt = opts.find(o => (o.dataset.code || '').toUpperCase() === V);
  if (opt) return opt;

  // value starts with "CODE - "
  opt = opts.find(o => o.value.toUpperCase().startsWith(V + ' - '));
  if (opt) return opt;

  return null;
}

/** Create a new blank line row */
function addItemRow(kind) {
  const tbody = q('#items-table tbody');
  const tr = document.createElement('tr');
  tr.innerHTML = `
    <td><input list="products" class="form-control form-control-sm product-input" placeholder="Code / Name / Barcode" autocomplete="off"></td>
    <td><input type="number" min="1" value="1" class="form-control form-control-sm qty-input"></td>
    <td><input type="number" step="0.01" min="0" value="0" class="form-control form-control-sm price-input"></td>
    <td class="line-total text-end">0.00</td>
    <td style="width:52px"><button type="button" class="btn btn-sm btn-outline-danger" title="Remove" aria-label="Remove row">&times;</button></td>
  `;
  tbody.appendChild(tr);

  const productInput = q('.product-input', tr);
  const priceInput   = q('.price-input', tr);
  const qtyInput     = q('.qty-input', tr);
  const removeBtn    = q('button', tr);

  const applyOption = (opt) => {
    if (!opt) return;
    // lock the visible value to the canonical displayed option so later matching is exact
    productInput.value = opt.value;
    const defaultPrice = parseFloat(opt.dataset.price || '0') || 0;
    priceInput.value = defaultPrice.toFixed(2);
    if (!qtyInput.value || qtyInput.value === '0') qtyInput.value = '1';
    recalcTotals();
  };

  productInput.addEventListener('change', () => applyOption(findOption(productInput.value)));
  productInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      const opt = findOption(productInput.value);
      if (opt) {
        e.preventDefault();
        applyOption(opt);
        qtyInput.focus();
      }
    }
  });

  qtyInput.addEventListener('input', recalcTotals);
  priceInput.addEventListener('input', recalcTotals);
  removeBtn.addEventListener('click', () => { tr.remove(); recalcTotals(); });

  focusLastProduct();
}

/* ===== Totals, stock guard, & JSON ===== */

function recalcTotals() {
  const rows = qa('#items-table tbody tr');
  let subtotal = 0;
  let taxTotal = 0;

  const opts = qa('#products option');
  const isReturn = byId('id_is_return')?.checked;

  let stockProblem = false;
  const stockErrors = [];

  rows.forEach(r => {
    const qty   = parseFloat(q('.qty-input', r)?.value || '0');
    const price = parseFloat(q('.price-input', r)?.value || '0');
    const val   = q('.product-input', r)?.value || '';

    let taxPercent = 0;
    const matched = findOption(val);

    if (matched) {
      taxPercent = parseFloat(matched.dataset.tax || '0') || 0;

      // stock guard only for normal sales
      if (!isReturn) {
        const ds = matched.dataset.stock;
        const avail = (ds !== undefined && ds !== null && ds !== '') ? parseInt(ds, 10) : null;
        if (avail !== null && qty > avail) {
          r.classList.add('table-danger');
          stockProblem = true;
          const label = matched.value || 'Selected product';
          stockErrors.push(`${label}: requested ${qty}, in stock ${avail}`);
        } else {
          r.classList.remove('table-danger');
        }
      } else {
        r.classList.remove('table-danger');
      }
    } else {
      // unmatched product: keep row but highlight to user
      r.classList.add('table-danger');
    }

    const lt = qty * price;
    subtotal += lt;
    taxTotal += (lt * taxPercent / 100.0);
    const cell = q('.line-total', r);
    if (cell) cell.innerText = lt.toFixed(2);
  });

  const discount = parseFloat(byId('id_discount')?.value || '0');
  let grand = subtotal - discount + taxTotal;

  if (isReturn) {
    subtotal = -subtotal;
    taxTotal = -taxTotal;
    grand = -grand;
  }

  const put = (sel, v) => { const n = q(sel); if (n) n.innerText = (Number.isFinite(v) ? v : 0).toFixed(2); };
  put('#subtotal', subtotal);
  put('#discount', discount);
  put('#tax', taxTotal);
  put('#grand_total', grand);

  buildItemsJSON();

  // banner + disable Complete when overselling
  const alertBox = byId('pos_error');
  const btn = byId('btnComplete');
  if (!isReturn && stockProblem) {
    if (alertBox) {
      alertBox.innerHTML = 'Not enough stock for:<br>' + stockErrors.join('<br>');
      alertBox.classList.remove('d-none');
    }
    if (btn) btn.disabled = true;
  } else {
    if (alertBox) alertBox.classList.add('d-none');
    if (btn) btn.disabled = false;
  }

  // optional: live credit alert if your file defines updateCreditAlert()
  if (typeof updateCreditAlert === 'function') updateCreditAlert();
}

function buildItemsJSON() {
  const rows = qa('#items-table tbody tr');
  const items = [];

  rows.forEach(r => {
    const val = q('.product-input', r)?.value || '';
    const opt = findOption(val);
    const qty = parseInt(q('.qty-input', r)?.value || '0', 10);
    const price = parseFloat(q('.price-input', r)?.value || '0');

    if (opt && qty > 0) {
      const pid = parseInt(opt.dataset.id, 10);
      const p = Number.isFinite(price) ? price : parseFloat(opt.dataset.price || '0') || 0;
      if (pid) items.push({ product_id: pid, qty: qty, unit_price: p, price: p });
    }
  });

  const hidden = byId('items_json');
  if (hidden) hidden.value = JSON.stringify(items);
  return items;
}

/* ===== Quick scan (code/name/barcode) ===== */

function addOrBumpFromQuickScan(text) {
  const opt = findOption(text);
  if (!opt) return false;

  // If same product already in any row, bump qty instead of adding a new row
  const display = opt.value;
  const rows = qa('#items-table tbody tr');
  for (const r of rows) {
    const inp = q('.product-input', r);
    if (inp && inp.value === display) {
      const qtyEl = q('.qty-input', r);
      qtyEl.value = String((parseInt(qtyEl.value || '1', 10) || 1) + 1);
      recalcTotals();
      return true;
    }
  }

  // else add a row prefilled
  addItemRow('sale');
  const last = rows.length ? rows[rows.length - 1].nextElementSibling || q('#items-table tbody tr:last-child') : q('#items-table tbody tr:last-child');
  const prodInput = q('.product-input', last);
  const priceInput = q('.price-input', last);
  const qtyInput = q('.qty-input', last);

  if (prodInput) prodInput.value = display;
  const defaultPrice = parseFloat(opt.dataset.price || '0') || 0;
  if (priceInput) priceInput.value = defaultPrice.toFixed(2);
  if (qtyInput && (!qtyInput.value || qtyInput.value === '0')) qtyInput.value = '1';

  recalcTotals();
  return true;
}

/* ===== Restore on validation error ===== */

function restoreItemsFromJSON(jsonStr) {
  let arr = [];
  try { arr = JSON.parse(jsonStr || '[]'); } catch (_) { arr = []; }
  const tbody = q('#items-table tbody');
  if (!tbody || !arr.length) return false;

  tbody.innerHTML = '';
  arr.forEach(item => {
    addItemRow('sale');
    const tr = q('#items-table tbody tr:last-child');
    const opt = q(`#products option[data-id="${item.product_id}"]`);
    const displayValue = opt ? opt.value : '';
    const prodInput = q('.product-input', tr);
    const qtyInput  = q('.qty-input', tr);
    const prInput   = q('.price-input', tr);

    if (prodInput && displayValue) prodInput.value = displayValue;
    if (qtyInput)  qtyInput.value = parseInt(item.qty || 1, 10);
    const p = (item.unit_price ?? item.price ?? 0);
    if (prInput)   prInput.value = (typeof p === 'number') ? p.toFixed(2) : String(p);
  });

  recalcTotals();
  return true;
}

/* ===== Boot ===== */

document.addEventListener('DOMContentLoaded', function () {
  console.log("pos items");
  // restore rows after validation error
  let restored = false;
  const hidden = byId('items_json');
  console.log("pos items",hidden.value);
  if (hidden && hidden.value && hidden.value.trim().length > 2) {
    try { restored = restoreItemsFromJSON(hidden.value); } catch (_) { restored = false; }
  }
  if (!restored && !q('#items-table tbody tr')) addItemRow('sale');

  // quick scan
  const qs = byId('quick_scan');
  if (qs) {
    qs.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') {
        e.preventDefault();
        if (addOrBumpFromQuickScan(qs.value.trim())) {
          qs.value = '';
        } else {
          // gentle nudge if not found
          const box = byId('pos_error');
          if (box) { box.textContent = 'No matching product: try full code or scan barcode.'; box.classList.remove('d-none'); }
        }
      }
    });
    qs.focus();
  }

  // add/clear buttons
  const btnAdd = byId('btnAddRow');
  if (btnAdd) btnAdd.addEventListener('click', () => addItemRow('sale'));

  const btnClear = byId('btnClear');
  if (btnClear) btnClear.addEventListener('click', () => {
    const tbody = q('#items-table tbody');
    tbody.innerHTML = '';
    recalcTotals();
    if (qs) qs.focus();
  });

  // submit guard
  const form = byId('pos-form');
  if (form) {
    form.addEventListener('submit', function (ev) {
      const items = buildItemsJSON(); // ensure fresh JSON
      if (!items.length) {
        ev.preventDefault();
        const box = byId('pos_error');
        if (box) { box.textContent = 'Add at least one item before completing the sale.'; box.classList.remove('d-none'); }
        else alert('Add at least one item before completing the sale.');
      }
    });
  }

  // react to totals-affecting inputs
  ['#id_discount', '#id_is_return'].forEach(sel => {
    const el = q(sel);
    if (el) el.addEventListener('input', recalcTotals);
  });

  recalcTotals();
});
