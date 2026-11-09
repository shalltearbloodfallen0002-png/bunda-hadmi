document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("[data-confirm]").forEach(el => {
    el.addEventListener("click", e => {
      if (!confirm(el.dataset.confirm || "Yakin ingin melanjutkan?")) e.preventDefault();
    });
  });
  document.querySelectorAll("[data-autosubmit]").forEach(el => {
    el.addEventListener("change", () => el.form.submit());
  });
});
