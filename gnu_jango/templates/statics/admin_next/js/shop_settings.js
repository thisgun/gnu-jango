(() => {
  "use strict";

  const preview = document.querySelector("[data-shipping-preview]");
  if (!preview) return;

  const mode = document.getElementById("id_de_send_cost_case");
  const limits = document.getElementById("id_de_send_cost_limit");
  const costs = document.getElementById("id_de_send_cost_list");
  const rows = preview.querySelector("[data-preview-rows]");
  const error = preview.querySelector("[data-preview-error]");
  const examples = [10000, 30000, 50000, 100000];
  const money = new Intl.NumberFormat("ko-KR");
  const numberPattern = /^(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)$/;

  function parseList(value, allowZero) {
    const parts = String(value || "").split(";").map((part) => part.trim());
    if (!parts.length || parts.some((part) => !numberPattern.test(part))) return null;
    const parsed = parts.map((part) => Number(part.replaceAll(",", "")));
    if (parsed.some((number) => !Number.isSafeInteger(number) || number < (allowZero ? 0 : 1))) return null;
    return parsed;
  }

  function render() {
    const shippingMode = mode?.value || "";
    let tierLimits = [];
    let tierCosts = [];
    let invalid = false;

    if (shippingMode === "차등") {
      tierLimits = parseList(limits?.value, false) || [];
      tierCosts = parseList(costs?.value, true) || [];
      invalid = !tierLimits.length || !tierCosts.length || tierLimits.length !== tierCosts.length;
      invalid ||= tierLimits.some((value, index) => index > 0 && value <= tierLimits[index - 1]);
    }

    error.hidden = !invalid;
    if (invalid) return;

    const previewRows = examples.map((total) => {
      // youngcart get_sendcost: only 금액별 차등 charges the shared fee; other cases charge 0
      let charge = 0;
      if (shippingMode === "차등") {
        const index = tierLimits.findIndex((limit) => total < limit);
        charge = index >= 0 ? tierCosts[index] : 0;
      }
      return `<tr><td>${money.format(total)}원</td><td>${money.format(charge)}원</td></tr>`;
    });
    rows.innerHTML = previewRows.join("");
  }

  [mode, limits, costs].forEach((input) => input?.addEventListener("input", render));
  [mode, limits, costs].forEach((input) => input?.addEventListener("change", render));
  render();
})();
