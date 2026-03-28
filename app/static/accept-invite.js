const acceptForm = document.getElementById("acceptInviteForm");
const acceptStatus = document.getElementById("acceptStatus");
const params = new URLSearchParams(window.location.search);
const token = params.get("token");

if (!token) {
  acceptStatus.className = "auth-status auth-status-error";
  acceptStatus.textContent = "Invite token is missing.";
}

acceptForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!token) {
    return;
  }
  acceptStatus.className = "auth-status auth-status-pending";
  acceptStatus.textContent = "Activating invite...";
  try {
    const response = await fetch(`/auth/accept-invite?token=${encodeURIComponent(token)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        full_name: document.getElementById("acceptName").value || null,
        password: document.getElementById("acceptPassword").value,
      }),
    });
    if (!response.ok) {
      throw new Error(await response.text());
    }
    acceptStatus.className = "auth-status auth-status-success";
    acceptStatus.textContent = "Invite accepted. Redirecting to dashboard...";
    window.location.href = "/";
  } catch (error) {
    acceptStatus.className = "auth-status auth-status-error";
    acceptStatus.textContent = `Invite acceptance failed: ${error.message}`;
  }
});
