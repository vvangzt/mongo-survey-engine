(function () {
  "use strict";

  const form = document.getElementById("registerForm");
  if (!form) return;
  const button = document.getElementById("registerButton");
  const errorBox = document.getElementById("registerError");
  const nextUrl = form.dataset.next || "/dashboard";

  function showError(message) {
    errorBox.textContent = message;
    errorBox.classList.remove("hidden");
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    errorBox.classList.add("hidden");
    if (form.password.value !== form.confirm_password.value) {
      showError("两次输入的密码不一致");
      return;
    }
    if (!form.username.checkValidity()) {
      showError("用户名需为 3–32 位小写字母、数字或下划线");
      return;
    }
    button.disabled = true;
    button.textContent = "创建中…";
    try {
      await App.api("/api/auth/register", {
        method: "POST",
        body: {
          username: form.username.value.trim().toLowerCase(),
          email: form.email.value.trim().toLowerCase(),
          password: form.password.value,
          display_name: form.display_name.value.trim() || null,
        },
      });
      window.location.href = nextUrl.startsWith("/") ? nextUrl : "/dashboard";
    } catch (error) {
      showError(error.message);
    } finally {
      button.disabled = false;
      button.textContent = "创建并登录";
    }
  });
})();
