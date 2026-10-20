(function () {
  "use strict";

  const form = document.getElementById("loginForm");
  if (!form) return;
  const button = document.getElementById("loginButton");
  const errorBox = document.getElementById("loginError");
  const nextUrl = form.dataset.next || "/dashboard";

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    errorBox.classList.add("hidden");
    button.disabled = true;
    button.textContent = "登录中…";
    try {
      await App.api("/api/auth/login", {
        method: "POST",
        body: {
          username: form.username.value.trim(),
          password: form.password.value,
        },
      });
      window.location.href = nextUrl.startsWith("/") ? nextUrl : "/dashboard";
    } catch (error) {
      errorBox.textContent = error.message;
      errorBox.classList.remove("hidden");
    } finally {
      button.disabled = false;
      button.textContent = "登录";
    }
  });
})();
