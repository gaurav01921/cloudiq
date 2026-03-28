const loginForm = document.getElementById("loginForm");
const loginStatus = document.getElementById("loginStatus");

async function login(email, password) {
  const response = await fetch("/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!response.ok) {
    const body = await response.text();
    throw new Error(body);
  }
  return response.json();
}

loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const email = document.getElementById("email").value;
  const password = document.getElementById("password").value;
  loginStatus.className = "auth-status auth-status-pending";
  loginStatus.textContent = "Signing in...";
  try {
    const user = await login(email, password);
    loginStatus.className = "auth-status auth-status-success";
    loginStatus.textContent = `Authenticated as ${user.full_name} (${user.role}). Redirecting...`;
    window.location.href = "/";
  } catch (error) {
    loginStatus.className = "auth-status auth-status-error";
    loginStatus.textContent = `Login failed: ${error.message}`;
  }
});
